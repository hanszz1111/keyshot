# -*- coding: utf-8 -*-
"""清理任务库中的测试任务（只删测试用 SKU，保留真实产品任务）。
用法：
    python clean_tasks.py plan
    python clean_tasks.py apply
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DB = os.path.join(ROOT, "config", "tasks.db")

# 只清这些测试 SKU（下划线前缀 + 明确的测试名）。
# 真实产品（GF / LS-360G / AI渲染1）一律不动。
TEST_SKUS = ["_P2TEST", "_NOTEXIST", "_UI验收", "_对比", "_参考图", "_passtest"]
KEEP_DONE_KEEP_ALIVE = ["GF"]  # 真实产品的成功任务保留，便于复查


def rows():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("select id, sku, view, status, created_at from tasks order by id")
    data = cur.fetchall()
    con.close()
    return data


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "plan").lower()
    all_rows = rows()
    targets = [r for r in all_rows if r[1] in TEST_SKUS]

    print("=== 任务库: %s (%d bytes) ===" % (DB, os.path.getsize(DB)))
    print("总任务 %d 条" % len(all_rows))
    print()

    if mode == "plan":
        print("将删除的测试任务（%d 条）:" % len(targets))
        for r in targets:
            print("  #%s  %-12s %-10s %-8s %s" % r)
        keep = [r for r in all_rows if r[1] not in TEST_SKUS]
        print()
        print("将保留（%d 条）:" % len(keep))
        from collections import Counter
        cnt = Counter((r[1], r[3]) for r in keep)
        for (sku, st), n in sorted(cnt.items()):
            print("  %-12s %-8s x%d" % (sku, st, n))
        print("\n这是计划，未改动。执行: python clean_tasks.py apply")
        return 0

    if mode != "apply":
        print("未知模式:", mode)
        return 2

    if not targets:
        print("没有需要清理的测试任务。")
        return 0

    # 备份
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(ROOT, "_隔离区", "20260927", "config")
    os.makedirs(backup_dir, exist_ok=True)
    backup = os.path.join(backup_dir, "tasks-before-clean-%s.db" % stamp)
    shutil.copy2(DB, backup)
    print("已备份任务库:", os.path.relpath(backup, ROOT))

    con = sqlite3.connect(DB)
    cur = con.cursor()
    ids = [r[0] for r in targets]
    placeholders = ",".join("?" * len(ids))
    cur.execute("delete from tasks where id in (%s)" % placeholders, ids)
    deleted = cur.rowcount
    con.commit()
    con.close()
    print("已删除 %d 条测试任务" % deleted)

    after = rows()
    from collections import Counter
    cnt = Counter((r[1], r[3]) for r in after)
    print("\n清理后剩余 %d 条:" % len(after))
    for (sku, st), n in sorted(cnt.items()):
        print("  %-12s %-8s x%d" % (sku, st, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
