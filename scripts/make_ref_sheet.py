#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 白模渲染器 · 参考资料索引（只读源目录，产物写项目内）
============================================================
用途：设计/渲染源目录里的图往往单个几十 MB 打不开。本脚本
      ① 只读扫描源目录，统计图片数量/尺寸/体积
      ② 生成小尺寸缩略图到项目内，方便快速过图挑参考
      ③ 产出索引 JSON + Markdown 清单

★ 只读源目录：不移动、不改名、不覆盖任何源文件。

用法：
    python scripts/make_ref_sheet.py --src "F:\\ID设计-杨\\GF望远镜改款\\渲染图" --tag GF
    python scripts/make_ref_sheet.py --src "路径A" --src "路径B" --tag GF --max 900
"""
import argparse
import datetime as _dt
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    print("需要 Pillow：pip install pillow")
    raise SystemExit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_PREFIX = ("._", "._")


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024.0
    return "%.1f TB" % n


def scan(srcs):
    found = []
    for src in srcs:
        src = os.path.abspath(src)
        if not os.path.isdir(src):
            print("  ⚠️ 跳过（不存在）：%s" % src)
            continue
        for dirpath, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("._")]
            for fn in sorted(files):
                if fn.startswith(SKIP_PREFIX):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext not in IMG_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                found.append({
                    "path": full,
                    "rel": os.path.relpath(full, src).replace("\\", "/"),
                    "src_root": src,
                    "name": fn,
                    "ext": ext.lstrip("."),
                    "bytes": st.st_size,
                    "mtime": _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
    return found


def is_clown(name):
    n = name.lower()
    return "clown" in n or "_id." in n or "materialid" in n


def make_thumbs(items, outdir, max_edge, quality):
    os.makedirs(outdir, exist_ok=True)
    ok, fail = 0, 0
    for it in items:
        dst = os.path.join(outdir, os.path.splitext(it["name"])[0] + ".jpg")
        it["thumb"] = os.path.relpath(dst, ROOT).replace("\\", "/")
        try:
            with Image.open(it["path"]) as im:
                it["width"], it["height"] = im.size
                it["mode"] = im.mode
                if max(im.size) > max_edge:
                    im.thumbnail((max_edge, max_edge), Image.LANCZOS)
                im.convert("RGB").save(dst, "JPEG", quality=quality, optimize=True)
            it["thumb_bytes"] = os.path.getsize(dst)
            ok += 1
        except Exception as e:
            it["error"] = str(e)
            fail += 1
    return ok, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", action="append", required=True, help="源目录，可重复")
    ap.add_argument("--tag", default="refs", help="输出子目录名（建议用 SKU/项目名）")
    ap.add_argument("--max", type=int, default=900, help="缩略图最长边像素")
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--out", default=None, help="输出根目录（默认 outputs/_参考图）")
    ap.add_argument("--no-thumb", action="store_true", help="只统计不生成缩略图")
    args = ap.parse_args()

    outroot = args.out or os.path.join(ROOT, "outputs", "_参考图")
    outdir = os.path.join(outroot, args.tag)

    print("=" * 64)
    print(" 参考资料索引（★ 只读源目录）")
    print("=" * 64)
    items = scan(args.src)
    print("  命中图片：%d 张" % len(items))
    if not items:
        return 1

    n_clown = sum(1 for i in items if is_clown(i["name"]))
    total = sum(i["bytes"] for i in items)
    print("  其中通道图(_clown/_id)：%d 张；源图总体积 %s" % (n_clown, human(total)))

    if not args.no_thumb:
        ok, fail = make_thumbs(items, outdir, args.max, args.quality)
        print("  缩略图：成功 %d，失败 %d → %s" % (ok, fail, os.path.relpath(outdir, ROOT)))

    idx = {
        "_comment": "AI 白模渲染器 · 参考资料索引（源文件只读，未做任何修改）",
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tag": args.tag,
        "sources": [os.path.abspath(s) for s in args.src],
        "count": len(items),
        "clown_count": n_clown,
        "items": [{k: v for k, v in it.items() if k != "path"} for it in items],
    }
    os.makedirs(outdir, exist_ok=True)
    ipath = os.path.join(outdir, "ref_index.json")
    with open(ipath, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    lines = ["# 参考资料清单 · %s\n" % args.tag,
             "> 生成 %s ｜ 共 %d 张（其中通道图 %d 张）｜ 源目录只读，未修改\n"
             % (idx["generated_at"], len(items), n_clown),
             "| # | 文件 | 尺寸 | 体积 | 类型 | 缩略图 |",
             "|---|---|---|---|---|---|"]
    for i, it in enumerate(items, 1):
        wh = "%s×%s" % (it.get("width", "?"), it.get("height", "?"))
        kind = "通道/ID" if is_clown(it["name"]) else "成图"
        lines.append("| %d | `%s` | %s | %s | %s | `%s` |" % (
            i, it["rel"], wh, human(it["bytes"]), kind, it.get("thumb", "")))
    mpath = os.path.join(outdir, "清单.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("-" * 64)
    print("  ✅ %s" % os.path.relpath(ipath, ROOT))
    print("  ✅ %s" % os.path.relpath(mpath, ROOT))
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
