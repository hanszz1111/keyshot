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
import tempfile
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

    # v3.4：新增功能必须有无 GPU 的契约测试，旧 18 项不能证明机位/CMF/深度图有效。
    st, body = req("GET", "/api/views")
    views = json.loads(body).get("presets", [])
    keys = [v["key"] for v in views]
    check("机位表包含双 3/4 与六视图且 ID 唯一",
          st == 200 and len(keys) == len(set(keys)) and
          all(v in keys for v in ("3q4_left", "3q4_right", "side", "side_left")) and
          len([v for v in views if v.get("group") == "six"]) == 6)
    st, body = req("GET", "/api/cmf")
    presets = json.loads(body).get("presets", [])
    legacy = {alias for p in presets for alias in p.get("legacy_ids", [])}
    check("CMF 统一库含纹理、工艺与旧 12 类映射",
          st == 200 and len(presets) >= 14 and len(legacy) >= 12 and
          all(p.get("texture") and p.get("process") for p in presets) and
          all(not p["ai_editable"] for p in presets if p["id"] in ("glass_clear", "chrome_mirror")))
    with tempfile.TemporaryDirectory() as tmp:
        manifest = os.path.join(tmp, "pass_manifest.json")
        sample = {"pass_format_version": S.PASS_FORMAT_VERSION,
                  "depth_encoding": {"encoding": "near_white_far_dark_bg_black_v2",
                                     "background": 0.0, "foreground_pixels": 10, "pixels": 100}}
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(sample, f)
        check("新版深度清单可用", S._pass_manifest_issue(tmp) == "")
        sample["pass_format_version"] = 1
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(sample, f)
        check("旧版深度清单提示重生成", "旧版" in S._pass_manifest_issue(tmp))
        for role in ("clay", "depth", "normal"):
            path = os.path.join(tmp, role + ".png")
            with open(path, "wb") as f:
                f.write(b"manual-pass-test")
            S._record_manual_pass(tmp, role, path)
            if role == "clay":
                check("只替换一个通道仍禁止混用旧图", "混有旧自动结构图" in S._pass_manifest_issue(tmp))
        check("三个通道都手动替换后可覆盖旧清单", S._pass_manifest_issue(tmp) == "")
        sample["pass_format_version"] = S.PASS_FORMAT_VERSION
        sample["depth_encoding"]["foreground_pixels"] = 0
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(sample, f)
        check("自动重生成后旧手工记录失效", "无有效结构" in S._pass_manifest_issue(tmp))

    # ---- v3.5：出图引擎注册表 + engine_id 兼容性契约（不需要 GPU / 实验实例）----
    st, body = req("GET", "/api/renderers")
    rd = json.loads(body)
    engines = {e["id"]: e for e in rd.get("items", [])}
    check("GET /api/renderers 返回引擎注册表",
          st == 200 and rd.get("default") == "sdxl_controlled" and
          {"sdxl_controlled", "qwen21_edit_local"} <= set(engines),
          f"引擎 {list(engines)}")
    check("稳定模式始终可用且允许批量",
          engines.get("sdxl_controlled", {}).get("available") is True and
          engines["sdxl_controlled"].get("batch_allowed") is True and
          engines["sdxl_controlled"].get("experimental") is False)
    qwen = engines.get("qwen21_edit_local", {})
    check("实验引擎结构契约（experimental / 仅图片精修 / 禁批量 / 有原因字段）",
          qwen.get("experimental") is True and qwen.get("supports") == ["image_edit"] and
          qwen.get("batch_allowed") is False and "reason" in qwen and "note" in qwen and
          bool(qwen.get("disabled_reason")),
          f"available={qwen.get('available')}")
    check("实验引擎指向独立实例（8190）且带中文标签与说明",
          qwen.get("host", "").endswith("8190") and qwen.get("label", "").startswith("实验模式") and
          len(qwen.get("note", "")) > 20)

    # 旧任务没有 engine_id 字段 → 必须按稳定模式处理，不能因新增字段而失效
    check("旧任务缺 engine_id 时回落到稳定模式",
          S.task_engine_id({"payload": json.dumps({"_meta": {"mode": "controlled"}})}) == "sdxl_controlled"
          and S.task_engine_id({"payload": "{}"}) == "sdxl_controlled"
          and S.task_engine_id({"payload": "坏 JSON"}) == "sdxl_controlled"
          and S.task_engine_id({"payload": json.dumps({"_meta": {"engine_id": "qwen21_edit_local"}})}) == "qwen21_edit_local")
    _eid, _cfg, engine_err = S.engine_cfg("不存在的引擎")
    check("未知引擎返回中文错误而不是静默回退", bool(engine_err) and "未知" in engine_err, engine_err)
    check("两个引擎指向各自的 ComfyUI 实例",
          S.engine_host("sdxl_controlled").endswith("8188") and
          S.engine_host("qwen21_edit_local").endswith("8190"))

    # Qwen 工作流的 API 格式契约：这几处写错都会「不报错但不出效果」
    qwf = S.load_qwen_workflow()
    check("Qwen 工作流可加载（8 节点，_ 开头的注释键已剥离）",
          sorted(qwf.keys()) == [str(i) for i in range(1, 9)] and
          qwf["1"]["class_type"] == "UNETLoader" and
          qwf["5"]["class_type"] == "TextEncodeQwenImage21" and
          qwf["8"]["class_type"] == "SaveImage")
    check("Qwen 参考图用扁平点号键 images.image_1",
          qwf["5"]["inputs"].get("images.image_1") == ["4", 0],
          "写成嵌套 dict 会被 ComfyUI 静默忽略")
    check("Qwen 编辑取 TextEncodeQwenImage21 的第 3 路 latent",
          qwf["6"]["inputs"].get("latent_image") == ["5", 2],
          "改用 EmptyLatentImage 会因尺寸不一致产生偏移")
    check("Qwen CLIPLoader.type = qwen_image（没有 qwen_image21 这个选项）",
          qwf["2"]["inputs"].get("type") == "qwen_image")
    check("Qwen 工作流不含任何 SDXL/ControlNet 字段",
          "ckpt_name" not in json.dumps(qwf) and "control_net_name" not in json.dumps(qwf) and
          "canny" not in json.dumps(qwf).lower() and
          qwf["6"]["inputs"].get("cfg") == 1.0)
    _qwf2 = S.load_qwen_workflow()
    _qwf2["4"]["inputs"]["image"] = "x.png"
    _qwf2["5"]["inputs"]["images.image_1"] = ["4", 0]
    _qapplied, _qskipped = S.fill_qwen_workflow(
        _qwf2, {"positive": "p", "negative": "n", "seed": 7, "resolution": 832},
        S.qwen_edit_cfg(), {})
    check("Qwen 填充器把载荷写进正确节点（提示词 / 种子 / 分辨率）",
          _qwf2["5"]["inputs"]["prompt"] == "p" and _qwf2["6"]["inputs"]["seed"] == 7 and
          _qwf2["5"]["inputs"]["resolution"] == 832 and
          {"positive", "seed", "resolution"} <= set(_qapplied))

    # 实验引擎不可用时的阻断：**必须报错，不能静默降级成 SDXL 出图**。
    # 这里强制把 enabled 置 false，保证结果不受用户当前配置影响（可用于离线自检）。
    _real_engines = S.render_engines
    S.render_engines = lambda: {k: {**v, **({"enabled": False} if k == "qwen21_edit_local" else {})}
                                for k, v in _real_engines().items()}
    qid = None
    try:
        st, body = req("POST", "/api/tasks", {"tasks": [{
            "sku": TEST_SKU, "view": "front", "variant": 9,
            "positive": "qwen probe", "negative": "n",
            "payload": {"positive": "qwen probe", "negative": "n",
                        "source_img": "source/%s/a.png" % TEST_SKU,
                        "_meta": {"mode": "image", "engine_id": "qwen21_edit_local"}}}]})
        qid = json.loads(body)["ids"][0]
        _blocked, _reason = False, ""
        try:
            S.guarded_submit(qid)
        except RuntimeError as exc:
            _blocked, _reason = True, str(exc)
        except Exception as exc:                       # pragma: no cover - 兜底
            _blocked, _reason = False, "非 RuntimeError：%s" % exc
        check("实验引擎不可用时准确阻断（不静默降级为 SDXL）",
              _blocked and len(_reason) > 6, f"原因：{_reason[:52]}")
        st, body = req("POST", "/api/ui/comfy/submit", {"id": qid})
        check("HTTP 层同样阻断并返回中文原因（400）",
              st == 400 and "实验引擎" in json.loads(body).get("error", ""),
              f"HTTP {st}")
    finally:
        S.render_engines = _real_engines
        # 探针任务用完即删：否则会污染后面「任务可查询」的计数断言
        if qid is not None:
            try:
                _con = sqlite3.connect(S.DB_FILE)
                try:
                    _con.execute("DELETE FROM tasks WHERE id=?", (qid,))
                    _con.commit()
                finally:
                    _con.close()
            except Exception as e:
                print(f"  [警告] 清理引擎探针任务失败：{e}")

    with open(os.path.join(os.path.dirname(__file__), "app.js"), encoding="utf-8") as f:
        app_js = f.read()
    check("补齐所选视角会检查整组三通道而非仅深度",
          'filter(view=>!item.views?.find(row=>row.view===view)?.ok)' in app_js)

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

    # ---- 清理测试任务并验证 ----
    # 清理动作在此显式执行一次以验证有效性；外层 run() 的 finally 会再执行一次，
    # 保证进程被中断（管道 SIGPIPE / Ctrl+C / 超时）时也不会留下 _selftest 残留。
    _cleanup_selftest()
    check("测试任务已清理", _count_selftest_tasks() == 0)

    httpd.shutdown()

    print("-" * 62)
    print(f"  通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("  失败项：" + "、".join(FAIL))
    print("=" * 62)
    return 0 if not FAIL else 1


def _count_selftest_tasks():
    """统计遗留的 _selftest 任务条数。"""
    con = sqlite3.connect(S.DB_FILE)
    try:
        return con.execute("SELECT COUNT(*) FROM tasks WHERE sku=?", (TEST_SKU,)).fetchone()[0]
    finally:
        con.close()


def _cleanup_selftest():
    """删除本次自检写入的 _selftest 任务与参数卡。

    设计为幂等且不抛异常：即使自检中途失败也要执行，
    避免残留的 4 条测试任务让下一次运行断言失败（造成“越跑越坏”的假故障）。
    """
    try:
        con = sqlite3.connect(S.DB_FILE)
        try:
            con.execute("DELETE FROM tasks WHERE sku=?", (TEST_SKU,))
            con.commit()
        finally:
            con.close()
    except Exception as e:
        print(f"  [警告] 清理自检任务失败：{e}")
    try:
        p = S.card_path(TEST_SKU)
        if os.path.isfile(p):
            os.remove(p)
    except Exception as e:
        print(f"  [警告] 清理自检参数卡失败：{e}")


def run():
    """包裹 main()，确保无论成功、失败还是被中断都执行清理。"""
    try:
        return main()
    finally:
        _cleanup_selftest()


if __name__ == "__main__":
    # 入口先清一次历史残留，再跑；结束时（含被中断）再清一次。
    _cleanup_selftest()
    sys.exit(run())
