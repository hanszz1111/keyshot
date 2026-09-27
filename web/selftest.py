#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
控制台自检脚本（不依赖第三方库）

用途：改完 server.py 后跑一次，确认 API、SQLite、参数卡落盘、变更记录解析都正常。
    python selftest.py

测试产生的数据会在结束时清理，不影响正式数据。
"""

import json
import os
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as S  # noqa: E402

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
TEST_SKU = "_selftest"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    mark = "  OK  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   {extra}" if extra else ""))


def req(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main():
    print("=" * 62)
    print("  控制台自检")
    print("=" * 62)

    S.init_db()
    httpd = HTTPServer(("127.0.0.1", PORT), S.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # ---- 静态页（v1.9「形照」界面：品牌 + 两份新静态资源都要在）----
    st, html = req("GET", "/")
    check("首页「形照」可访问", st == 200 and "形照" in html and "/app.js" in html and "/styles.css" in html,
          f"HTTP {st}, {len(html)} 字节")
    for asset in ("/styles.css", "/app.js"):
        st, body = req("GET", asset)
        check(f"静态资源 {asset} 可访问", st == 200 and len(body) > 500, f"HTTP {st}, {len(body)} 字节")

    # ---- health ----
    st, body = req("GET", "/api/health")
    d = json.loads(body)
    check("GET /api/health", st == 200 and d.get("ok") is True,
          f"文档={'有' if d.get('doc') else '无'}")

    # ---- state ----
    st, body = req("GET", "/api/state")
    d = json.loads(body)
    check("GET /api/state 三块数据齐全",
          st == 200 and "board" in d and "cards" in d and "doc" in d,
          f"阶段 {len(d.get('board',{}).get('phases',[]))} / 风险 {len(d.get('board',{}).get('risks',[]))} / "
          f"待办 {len(d.get('board',{}).get('todos',[]))}")

    # ---- 参数卡落盘 ----
    card = {
        "asset": {"model": "D:/x.ksp", "category": "自检类目", "sku": TEST_SKU, "views": ["front", "top"]},
        "material": {"body": {"type": "ABS", "finish": "fine_sandblast", "color": "#2B2F33",
                              "roughness": 0.75, "metallic": 0.0}},
        "lighting": {"scheme": "studio_softbox_3point", "key": {"dir": "front_left_45", "temp": 5600}},
        "output": {"resolution": [1024, 1024], "count": 2, "upscale": 2, "lang": "CN"},
        "_seed_base": 100000,
    }
    st, body = req("POST", "/api/card", card)
    check("POST /api/card 保存参数卡", st == 200 and json.loads(body).get("ok"),
          f"sku={json.loads(body).get('sku')}")

    st, body = req("GET", "/api/state")
    skus = [c["sku"] for c in json.loads(body)["cards"]]
    check("参数卡出现在列表中", TEST_SKU in skus, f"共 {len(skus)} 张")

    st, body = req("GET", f"/api/card?sku={TEST_SKU}")
    check("GET /api/card 单张读取", st == 200 and json.loads(body)["asset"]["sku"] == TEST_SKU)

    # ---- 任务队列 ----
    items = []
    for v in ["front", "top"]:
        for i in range(2):
            items.append({"sku": TEST_SKU, "view": v, "variant": i,
                          "positive": f"positive for {v} v{i}", "negative": "neg",
                          "payload": {"seed": 100000 + i, "depth_img": "x.png"}})
    st, body = req("POST", "/api/tasks", {"tasks": items})
    check("POST /api/tasks 批量插入", json.loads(body).get("inserted") == 4,
          f"插入 {json.loads(body).get('inserted')} 条")

    st, body = req("GET", "/api/tasks")
    d = json.loads(body)
    mine = [t for t in d["tasks"] if t["sku"] == TEST_SKU]
    check("任务可查询且状态为 pending",
          len(mine) == 4 and all(t["status"] == "pending" for t in mine),
          f"stats={d['stats']}")

    tid = mine[0]["id"]
    st, body = req("POST", "/api/task/status", {"id": tid, "status": "done"})
    check("POST /api/task/status 更新状态", json.loads(body).get("updated") == 1)

    st, body = req("GET", "/api/tasks")
    row = [t for t in json.loads(body)["tasks"] if t["id"] == tid][0]
    check("状态已落库为 done", row["status"] == "done")

    # ---- 断点续跑 ----
    req("POST", "/api/task/status", {"id": tid, "status": "running"})
    n = S.reset_running()
    con = sqlite3.connect(S.DB_FILE)
    st_run = con.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]
    con.close()
    check("断点续跑：残留 running 被重置", n >= 1 and st_run == 0, f"重置 {n} 条")

    # ---- 看板持久化 ----
    st, _ = req("POST", "/api/board", S.DEFAULT_BOARD)
    check("POST /api/board 看板落盘", st == 200 and os.path.isfile(S.BOARD_FILE))

    # ---- 变更记录解析 ----
    st, body = req("GET", "/api/changelog")
    rows = json.loads(body)["rows"]
    check("从过程文档解析变更记录", len(rows) >= 1,
          f"{len(rows)} 条" + (f"，最新 {rows[0]['version']} {rows[0]['type']}" if rows else ""))

    # ---- 参数卡删除 ----
    st, body = req("DELETE", f"/api/card?sku={TEST_SKU}")
    check("DELETE /api/card", json.loads(body).get("ok") is True)
    check("参数卡文件已移除", not os.path.isfile(S.card_path(TEST_SKU)))

    # ---- 清理测试任务 ----
    con = sqlite3.connect(S.DB_FILE)
    con.execute("DELETE FROM tasks WHERE sku=?", (TEST_SKU,))
    con.commit()
    con.close()
    con = sqlite3.connect(S.DB_FILE)
    left = con.execute("SELECT COUNT(*) FROM tasks WHERE sku=?", (TEST_SKU,)).fetchone()[0]
    con.close()
    check("测试任务已清理", left == 0)

    httpd.shutdown()

    print("-" * 62)
    print(f"  通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("  失败项：" + "、".join(FAIL))
    print("=" * 62)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
