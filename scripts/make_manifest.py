#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 白模渲染器 · OPT-05/06  工件清单 + QA 报告
=================================================
扫描产物目录，生成两个东西：
    outputs/artifact_manifest.json   可复现档案：文件 / SHA-256 / 尺寸 / 参数 / 来源
    outputs/QA报告.md                逐张的检查表 + 自动判定 + 待人工确认项

用法：
    python scripts/make_manifest.py                 # 扫 outputs/
    python scripts/make_manifest.py --where outputs/试跑-2026-09-24
    python scripts/make_manifest.py --where assets/passes   # 也支持扫 pass

设计依据：优化总纲 §三.5「可复现」与 §四「自动 QA + 人工复核」；
         红线见 ADR-002（丝印/刻度/量程/认证标识不得由 AI 生成）。
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import sqlite3
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(ROOT, "config", "tasks.db")
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".exr", ".tif", ".tiff"}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def img_size(path):
    """只读文件头取宽高，不加载整张图。"""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return w, h, "PNG"
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    b = f.read(1)
                    if not b:
                        return None
                    if b != b"\xff":
                        continue
                    marker = f.read(1)
                    while marker == b"\xff":
                        marker = f.read(1)
                    if marker and 0xC0 <= marker[0] <= 0xCF and marker[0] not in (0xC4, 0xC8, 0xCC):
                        f.read(3)
                        h_, w_ = struct.unpack(">HH", f.read(4))
                        return w_, h_, "JPEG"
                    seg = f.read(2)
                    if len(seg) < 2:
                        return None
                    f.seek(struct.unpack(">H", seg)[0] - 2, 1)
            if head[:4] == b"II*\x00" or head[:4] == b"MM\x00*":
                return None, None, "TIFF"
            if head[:4] == b"v/1\x01":
                return None, None, "EXR"
    except Exception:
        return None
    return None


def load_tasks():
    """读任务库，按 output 路径建索引，用于把产物关联回参数与 seed。"""
    idx = {}
    if not os.path.isfile(DB_FILE):
        return idx
    try:
        con = sqlite3.connect(DB_FILE)
        con.row_factory = sqlite3.Row
        for r in con.execute("SELECT id, sku, view, variant, payload, status, output, created_at "
                             "FROM tasks WHERE output IS NOT NULL AND output <> ''"):
            for p in (r["output"] or "").split(","):
                p = p.strip().replace("/", os.sep)
                if p:
                    idx[os.path.normcase(os.path.join(ROOT, p))] = dict(r)
        con.close()
    except Exception:
        pass
    return idx


def collect(where):
    items = []
    for dirpath, _dirs, files in os.walk(where):
        if os.sep + "_raw" in dirpath:
            continue
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in IMG_EXT:
                continue
            full = os.path.join(dirpath, fn)
            w, h, kind = img_size(full)
            items.append({
                "path": os.path.relpath(full, ROOT).replace("\\", "/"),
                "name": fn,
                "ext": ext.lstrip("."),
                "format": kind,
                "width": w, "height": h,
                "bytes": os.path.getsize(full),
                "sha256": sha256(full),
                "mtime": _dt.datetime.fromtimestamp(os.path.getmtime(full))
                          .strftime("%Y-%m-%d %H:%M:%S"),
                "_abs": os.path.normcase(os.path.abspath(full)),
            })
    return items


def qa_rows(items, tasks):
    rows = []
    for it in items:
        t = tasks.get(it["_abs"])
        sku = (t or {}).get("sku") or "-"
        view = (t or {}).get("view") or "-"
        seed = "-"
        mode = "-"
        if t:
            try:
                p = json.loads(t.get("payload") or "{}")
                seed = p.get("seed", "-")
                mode = "ControlNet" if p.get("depth_img") else "文生图"
            except Exception:
                pass

        # 自动判定
        big_enough = bool(it["width"] and it["height"] and it["width"] >= 768)
        has_record = bool(t)
        checks = {
            "分辨率达标(≥768)": "✅" if big_enough else ("⚠️" if it["width"] else "—"),
            "可追溯任务": "✅" if has_record else "⚠️ 无任务记录",
            "尺寸数字": "—",
            "形状是否守住": "待人工",
            "文字是否臆造": "待人工",
            "透明/镜面是否翻车": "待人工",
        }
        rows.append({
            "file": it["path"], "sku": sku, "view": view, "seed": seed,
            "mode": mode, "size": f'{it["width"]}×{it["height"]}' if it["width"] else "—",
            "sha8": it["sha256"][:12], "checks": checks,
        })
    return rows


def write_reports(items, rows, where):
    outdir = os.path.join(ROOT, "outputs")
    os.makedirs(outdir, exist_ok=True)

    manifest = {
        "_comment": "AI 白模渲染器 · 工件清单（可复现档案）",
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_dir": os.path.relpath(where, ROOT).replace("\\", "/"),
        "count": len(items),
        "artifacts": [{k: v for k, v in it.items() if not k.startswith("_")} for it in items],
    }
    mpath = os.path.join(outdir, "artifact_manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    lines = []
    lines.append("# QA 报告（自动生成）\n")
    lines.append(f"> 生成时间：{manifest['generated_at']}　｜　扫描：`{manifest['scanned_dir']}`　｜　共 **{len(items)}** 个文件\n")
    lines.append("## 硬规矩（ADR-002）\n")
    lines.append("- ⛔ **丝印 / LOGO / 刻度 / 量程 / 认证标识 / 透明件** 一律**不得由 AI 生成**，必须引擎真渲染 + 图层回贴。")
    lines.append("- ⛔ 自动检查**不能**代替人工看图；任何「待人工」项未确认前，**不得**当作可交付物。\n")
    lines.append("## 逐张检查表\n")
    lines.append("| # | 文件 | SKU | 机位 | 模式 | 尺寸 | seed | 形状 | 文字 | 透明/镜面 | 分辨率 | 可追溯 | SHA-256 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        c = r["checks"]
        lines.append("| {} | `{}` | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | `{}` |".format(
            i, r["file"], r["sku"], r["view"], r["mode"], r["size"], r["seed"],
            c["形状是否守住"], c["文字是否臆造"], c["透明/镜面是否翻车"],
            c["分辨率达标(≥768)"], c["可追溯任务"], r["sha8"]))
    lines.append("")
    lines.append("## 待人工确认清单\n")
    pend = [r for r in rows if any(v == "待人工" for v in r["checks"].values())]
    if pend:
        for r in pend:
            lines.append(f"- [ ] `{r['file']}`　→ 与 `{r['sku']}/{r['view']}` 的结构 pass 逐项对照；"
                         f"重点看**文字/丝印有没有被 AI 臆造**")
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("## 不合格时怎么办\n")
    lines.append("1. 结构没守住 → 换/补结构 pass（`scripts\\出pass.bat`），或提高 ControlNet 强度后重跑。")
    lines.append("2. 文字被臆造 → **这是必然的**（ADR-002），走图层回贴；不要试图用提示词修。")
    lines.append("3. 透明件 / 镜面翻车 → 走「真渲染合成」兜底通道，不交给 AI。")

    qpath = os.path.join(outdir, "QA报告.md")
    with open(qpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return mpath, qpath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--where", default=None, help="要扫描的目录（默认 outputs/）")
    args = ap.parse_args()

    where = args.where or os.path.join(ROOT, "outputs")
    if not os.path.isabs(where):
        where = os.path.join(ROOT, where)
    if not os.path.isdir(where):
        print("目录不存在：%s" % where)
        return 1

    items = collect(where)
    tasks = load_tasks()
    rows = qa_rows(items, tasks)
    mpath, qpath = write_reports(items, rows, where)

    print("=" * 62)
    print(" 工件清单 + QA 报告")
    print("=" * 62)
    print("  扫描目录 : %s" % os.path.relpath(where, ROOT))
    print("  文件数   : %d" % len(items))
    for it in items:
        print("    %-58s %s" % (it["path"], f'{it["width"]}×{it["height"]}' if it["width"] else ""))
    print("-" * 62)
    print("  ✅ %s" % os.path.relpath(mpath, ROOT))
    print("  ✅ %s" % os.path.relpath(qpath, ROOT))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
