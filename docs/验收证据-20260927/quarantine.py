# -*- coding: utf-8 -*-
"""测试残留隔离：只移动、不删除，全量记账，可回滚。
用法：
    python quarantine.py plan     # 只打印计划，不动任何文件
    python quarantine.py apply    # 执行移动 + 落盘 manifest
"""
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
QUAR = os.path.join(ROOT, "_隔离区")
STAMP = "20260927"

# 判定为「本轮测试残留」的目录（相对项目根）
DIRS = [
    "assets/source/_P2TEST",   # P2 图片改图负例/正向测试源图
    "outputs/_P2TEST",         # P2 测试出图
    "outputs/_验收P2",         # P2 验收落盘
    "_ui_verify",              # 本轮 UI 验证脚本与截图（先移走，报告与截图已另存）
]
# 单独的文件
FILES = []


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
            if limit and fh.tell() > limit:
                break
    return h.hexdigest()


def build_plan():
    plan = []
    for rel in DIRS:
        src = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isdir(src):
            plan.append({"rel": rel, "kind": "dir", "status": "missing"})
            continue
        entries = []
        for base, _dirs, files in os.walk(src):
            for fn in files:
                fp = os.path.join(base, fn)
                entries.append({
                    "rel": os.path.relpath(fp, ROOT).replace("\\", "/"),
                    "size": os.path.getsize(fp),
                    "sha256": sha256(fp),
                })
        plan.append({
            "rel": rel, "kind": "dir", "status": "present",
            "dest": "_隔离区/%s/%s" % (STAMP, rel.replace("/", os.sep)),
            "file_count": len(entries),
            "total_size": sum(e["size"] for e in entries),
            "files": entries,
        })
    for rel in FILES:
        src = os.path.join(ROOT, rel.replace("/", os.sep))
        if os.path.isfile(src):
            plan.append({"rel": rel, "kind": "file", "status": "present",
                         "dest": "_隔离区/%s/%s" % (STAMP, rel.replace("/", os.sep)),
                         "size": os.path.getsize(src), "sha256": sha256(src)})
        else:
            plan.append({"rel": rel, "kind": "file", "status": "missing"})
    return plan


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "plan").lower()
    plan = build_plan()

    if mode == "plan":
        print("=== 隔离计划（只读，未改动任何文件） ===")
        print("项目根:", ROOT)
        print("隔离区: _隔离区/%s/" % STAMP)
        print()
        nf = 0
        nb = 0
        for it in plan:
            if it["status"] == "missing":
                print("  [缺失] %s" % it["rel"])
                continue
            if it["kind"] == "dir":
                print("  [目录] %-28s %2d 个文件 / %8d B" % (it["rel"], it["file_count"], it["total_size"]))
                nf += it["file_count"]
                nb += it["total_size"]
            else:
                print("  [文件] %-28s %8d B" % (it["rel"], it["size"]))
                nf += 1
                nb += it["size"]
        print()
        print("合计: %d 个文件 / %d B (%.2f MB)" % (nf, nb, nb / 1048576))
        print("\n这是计划，未执行。确认后运行: python quarantine.py apply")
        return 0

    if mode != "apply":
        print("未知模式:", mode)
        return 2

    # 安全检查：隔离区必须在项目内，且不能是项目根
    quar_root = os.path.join(ROOT, "_隔离区")
    assert os.path.commonpath([ROOT, quar_root]) == ROOT, "隔离区越界"
    assert quar_root != ROOT, "隔离区不能等于项目根"

    moved = []
    skipped = []
    for it in plan:
        if it["status"] == "missing":
            skipped.append(it["rel"])
            continue
        src = os.path.join(ROOT, it["rel"].replace("/", os.sep))
        dst = os.path.join(quar_root, STAMP, it["rel"].replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            print("目标已存在，跳过:", dst)
            skipped.append(it["rel"])
            continue
        shutil.move(src, dst)
        moved.append({"rel": it["rel"], "dest": os.path.relpath(dst, ROOT).replace("\\", "/")})
        print("已隔离:", it["rel"], "->", os.path.relpath(dst, ROOT))

    manifest = {
        "created": "2026-09-27",
        "reason": "清理本轮 P2/P3 验收残留与 UI 验证脚本；只移动不删除，可原样回滚。",
        "project_root": ROOT,
        "quarantine_root": os.path.relpath(quar_root, ROOT).replace("\\", "/"),
        "stamp": STAMP,
        "moved": moved,
        "skipped": skipped,
        "plan": plan,
    }
    mp = os.path.join(quar_root, "MANIFEST-%s.json" % STAMP)
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print()
    print("已隔离 %d 项，跳过 %d 项" % (len(moved), len(skipped)))
    print("清单:", os.path.relpath(mp, ROOT))
    print("回滚方式：按清单把每项从 _隔离区/%s/<原相对路径> 移回项目根即可。" % STAMP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
