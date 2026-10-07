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
import shutil
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
CMF_TEST_SKU = "selftestcmf"
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
    angles = {v["key"]: v["elevation"] for v in views}
    check("俯视和仰视为精确正交方向", angles.get("top") == 90.0 and
          angles.get("bottom") == -90.0)
    st, body = req("GET", "/api/cmf")
    presets = json.loads(body).get("presets", [])
    legacy = {alias for p in presets for alias in p.get("legacy_ids", [])}
    check("CMF 统一库含纹理、工艺与旧 12 类映射",
          st == 200 and len(presets) >= 14 and len(legacy) >= 12 and
          all(p.get("texture") and p.get("process") for p in presets) and
          all(not p["ai_editable"] for p in presets if p["id"] in ("glass_clear", "chrome_mirror")))
    # 跨视角整机 CMF：测试数据只写 _selftest 专属目录，结束时统一清理。
    model_dir = os.path.join(S.MODELS_DIR, CMF_TEST_SKU)
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, "part.obj")
    with open(model_path, "w", encoding="utf-8") as f:
        f.write("o selftest\nv 0 0 0\n")
    for view, front_id, grip_id in (("front", "1", "2"), ("side", "7", "3")):
        folder = os.path.join(S.PASSES_DIR, CMF_TEST_SKU, view)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "pass_manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"pass_format_version": S.PASS_FORMAT_VERSION,
                       "depth_encoding": {"encoding": "near_white_far_dark_bg_black_v2",
                                          "background": 0.0, "foreground_pixels": 4, "pixels": 16},
                       "objectid_map": {front_id: "FrontShell", grip_id: "Grip"}}, f)
        with open(os.path.join(folder, "objectid.png"), "wb") as f:
            f.write(b"selftest-placeholder; guide image decoding is tested separately")
    st, body = req("GET", "/api/cmf/scheme?sku=" + CMF_TEST_SKU)
    empty_scheme = json.loads(body)
    check("新产品 CMF 方案为空且绑定源模型", st == 200 and empty_scheme["version"] == 0 and
          len(empty_scheme["fingerprint"]) == 64 and not empty_scheme["assignments"])
    st, body = req("POST", "/api/cmf/scheme", {"sku": CMF_TEST_SKU, "view": "front", "part": 2,
        "cmf": "rubber_matte", "label": "握持区", "color": "#252729"})
    scheme = json.loads(body)
    check("保存握持区胶皮到跨机位方案", st == 200 and scheme.get("version") == 1 and
          scheme.get("assignments", {}).get("Grip", {}).get("color") == "#252729")
    st, body = req("POST", "/api/cmf/scheme", {"sku": CMF_TEST_SKU, "view": "front",
        "action": "assign_many", "parts": [{"part": 1, "label": "前壳"}, {"part": 2, "label": "握持区"}],
        "cmf": "plastic_fine_matte", "color": "#6A7880"})
    batch = json.loads(body)
    check("批量材质一次写入且两个部件同色", st == 200 and batch.get("version") == 2 and
          all(batch.get("assignments", {}).get(name, {}).get("color") == "#6A7880"
              for name in ("FrontShell", "Grip")))
    st, body = req("POST", "/api/cmf/scheme", {"sku": CMF_TEST_SKU, "view": "front",
        "action": "assign_many", "parts": [{"part": 1}, {"part": 999}],
        "cmf": "plastic_fine_matte", "color": "#000000"})
    check("批量选区含无效部件时整体拒绝", st == 400 and
          S.load_cmf_scheme(CMF_TEST_SKU)["version"] == 2)
    st, body = req("POST", "/api/cmf/scheme", {"sku": CMF_TEST_SKU, "view": "front", "part": 2,
        "cmf": "rubber_matte", "label": "握持区", "color": "#252729"})
    scheme = json.loads(body)
    st, body = req("POST", "/api/cmf/scheme/check", {"sku": CMF_TEST_SKU,
        "views": ["front", "side"], "version": scheme.get("version"),
        "fingerprint": scheme.get("fingerprint")})
    check("不同机位部件号不同但同名部件仍可复用", st == 200 and json.loads(body).get("ok"))
    st, body = req("POST", "/api/cmf/scheme/check", {"sku": CMF_TEST_SKU,
        "views": ["3q4_left"], "version": scheme.get("version"),
        "fingerprint": scheme.get("fingerprint")})
    check("缺少机位部件映射时先阻断整批任务", st == 400 and
          "部件映射" in json.loads(body).get("error", ""))
    old_payload = {"positive": "product", "_meta": {"cmf_scheme":
                   {"version": scheme["version"], "fingerprint": scheme["fingerprint"]}}}
    S.validate_cmf_task({"sku": CMF_TEST_SKU, "view": "side"}, old_payload)
    check("任务提示词包含已核对的部位和材质", "握持区" in old_payload["positive"] and
          "matte rubber" in old_payload["positive"])
    st, body = req("POST", "/api/cmf/scheme", {"sku": CMF_TEST_SKU, "view": "front", "part": 1,
        "cmf": "plastic_fine_matte", "label": "前壳", "color": "#373D42"})
    check("方案更新后版本递增", st == 200 and json.loads(body).get("version") == scheme["version"] + 1)
    st, body = req("POST", "/api/cmf/scheme", {"sku": CMF_TEST_SKU, "view": "front", "part": 1,
        "action": "remove"})
    removed = json.loads(body)
    check("恢复主体材质只移除选中部件", st == 200 and removed.get("version") == scheme["version"] + 2 and
          "FrontShell" not in removed.get("assignments", {}) and "Grip" in removed.get("assignments", {}))
    st, body = req("POST", "/api/cmf/scheme/check", {"sku": CMF_TEST_SKU,
        "views": ["side"], "version": 1, "fingerprint": scheme["fingerprint"]})
    check("旧任务版本被阻断", st == 400 and "已改变" in json.loads(body).get("error", ""))
    with open(model_path, "a", encoding="utf-8") as f:
        f.write("v 1 0 0\n")
    st, body = req("GET", "/api/cmf/scheme?sku=" + CMF_TEST_SKU)
    check("源模型变化后方案标记失效", st == 200 and json.loads(body).get("stale") is True)
    st, body = req("POST", "/api/cmf/scheme", {"sku": CMF_TEST_SKU, "action": "reset"})
    check("确认重建方案后旧版本备份且新方案为空", st == 200 and
          json.loads(body).get("version") == scheme["version"] + 3 and not json.loads(body).get("assignments"))
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

    # ---- 大纲 §2 P1：候选底图版本链（v3.10）----
    _cands = S.list_candidates("AI渲染1", "front")
    check("list_candidates 能列出该机位的成图（版本链数据源）",
          isinstance(_cands, list) and
          all(c.get("rel", "").startswith("outputs/") and c.get("name") for c in _cands),
          "front 机位 %d 张" % len(_cands))
    check("候选列表不含 *_raw.png（那是 AI 原样对照件，不作底图候选）",
          all(not c["name"].endswith("_raw.png") for c in _cands))
    check("候选列表按时间倒序（最新的可作默认底图）",
          all(_cands[i]["ts"] >= _cands[i + 1]["ts"] for i in range(len(_cands) - 1)))
    check("不存在的 SKU / 机位返回空列表而不是抛异常",
          S.list_candidates("no_such_sku_xyz", "front") == [] and S.list_candidates("", "") == [])
    os.makedirs(S.PASSES_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="_selftest_pass_", dir=S.PASSES_DIR) as sample_dir:
        sample_path = os.path.join(sample_dir, "clay.png")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"selftest-clay-sample")
        sample_rel = os.path.relpath(sample_path, S.PASSES_DIR).replace("\\", "/")
        _staged, _serr = S.stage_base_image(TEST_SKU, "front", sample_rel)
        check("stage_base_image 把底图复制进部件工作区（供 comfy_upload 使用）",
              bool(_staged) and _staged.startswith("_部件/") and S._asset_path(_staged),
              _staged or (_serr or ""))
    _bad, _berr = S.stage_base_image(TEST_SKU, "front", "outputs/no/such/file.png")
    check("stage_base_image 对不存在的底图报中文错误而不是静默继续",
          _bad is None and "找不到" in (_berr or ""), _berr or "")

    # ---- 大纲 §3 P1：按部件 CMF 持久化（v3.10）----
    check("初始状态：该 SKU 还没有部件 CMF 分配", S.load_part_cmf(TEST_SKU) == {})
    _t1 = S.save_part_cmf(TEST_SKU, "front", 1234, "plastic_fine_matte", "#343b42")
    check("save_part_cmf 写入后按机位归档（含颜色覆盖）",
          (_t1.get("front") or {}).get("1234", {}).get("cmf") == "plastic_fine_matte" and
          (S.load_part_cmf(TEST_SKU).get("front") or {}).get("1234", {}).get("color") == "#343b42")
    S.save_part_cmf(TEST_SKU, "side", 1234, "plastic_fine_matte")
    _t2 = S.load_part_cmf(TEST_SKU)
    check("同一部件号在不同机位各存一份（切机位不串位 —— 大纲 GATE）",
          (_t2.get("front") or {}).get("1234", {}).get("color") == "#343b42" and
          "color" not in ((_t2.get("side") or {}).get("1234") or {}))
    S.save_part_cmf(TEST_SKU, "front", 1234, "")
    check("cmf 传空 = 删除该条分配（恢复默认）",
          "1234" not in (S.load_part_cmf(TEST_SKU).get("front") or {}))
    _raised = False
    try:
        S.save_part_cmf("", "front", 1, "x")
    except ValueError:
        _raised = True
    check("缺 sku / view / partId 时报错，而不是写坏参数卡", _raised)

    # ---- 大纲 §4：设计语言 / 布光预设（v3.8）----
    st, body = req("GET", "/api/designs")
    dd = json.loads(body)
    dp = dd.get("presets") or []
    check("GET /api/designs 返回设计/布光预设",
          st == 200 and len(dp) >= 4 and
          all(p.get("id") and p.get("name") and p.get("prompt") and p.get("lighting") for p in dp),
          "预设 %d 套 / 共用负面约束 %d 条" % (len(dp), len(dd.get("negative_common") or [])))
    _ids = [p["id"] for p in dp]
    check("设计预设 ID 唯一且都带背景与阴影定义",
          len(_ids) == len(set(_ids)) and all(p.get("background") and p.get("shadow") for p in dp))
    check("设计预设有稳定签名和对应保形背景",
          all(len(p.get("signature", "")) == 16 and
              p.get("render_style") in ("studio", "white", "dark") and
              p.get("render_light") in ("soft", "top", "dramatic", "natural") for p in dp))
    _pd = {"positive": "BASE", "negative": "blurry", "_meta": {"design": _ids[0]}}
    _dn, _de = S.apply_design(_pd)
    check("apply_design 把预设提示词并进正/负面（后端合并，前端只传 id）",
          _de is None and bool(_dn) and _pd["positive"].startswith("BASE")
          and len(_pd["positive"]) > len("BASE") and "invented" in _pd["negative"])
    _pd2 = {"positive": "X", "negative": "Y", "_meta": {}}
    check("未选设计预设时载荷原样不变（向后兼容）",
          S.apply_design(_pd2) == (None, None) and _pd2["positive"] == "X" and _pd2["negative"] == "Y")
    _pd3 = {"positive": "X", "negative": "Y", "_meta": {"design": "no_such_id"}}
    check("未知设计预设报中文错误而不是静默忽略",
          "未知" in (S.apply_design(_pd3)[1] or ""))
    _pd4 = {"positive": "X", "negative": "Y",
            "_meta": {"design": _ids[0], "design_signature": "outdated"}}
    check("八面任务不混用修改前后的设计语言",
          "已修改" in (S.apply_design(_pd4)[1] or "") and _pd4["positive"] == "X")

    # ---- v3.5：出图引擎注册表 + engine_id 兼容性契约（不需要 GPU / 实验实例）----
    st, body = req("GET", "/api/renderers")
    rd = json.loads(body)
    engines = {e["id"]: e for e in rd.get("items", [])}
    expected_default = "qwen21_edit_local" if engines.get("qwen21_edit_local", {}).get("available") else "sdxl_controlled"
    check("GET /api/renderers 返回引擎注册表",
          st == 200 and rd.get("default") == expected_default and
          {"sdxl_controlled", "qwen21_edit_local"} <= set(engines),
          f"引擎 {list(engines)}")
    _real_ready = S.engine_ready
    try:
        S.engine_ready = lambda eid: (True, "", {"host": S.engine_host(eid)})
        check("千问就绪时成为默认入口", S.renderers_report()["default"] == "qwen21_edit_local")
    finally:
        S.engine_ready = _real_ready
    check("稳定模式始终可用且允许批量",
          engines.get("sdxl_controlled", {}).get("available") is True and
          engines["sdxl_controlled"].get("batch_allowed") is True and
          engines["sdxl_controlled"].get("experimental") is False)
    qwen = engines.get("qwen21_edit_local", {})
    check("千问结构契约（多参考 / 多候选 / 质量尺寸可选）",
          qwen.get("experimental") is True and
          {"image_edit", "multi_view_sequential", "multi_image_reference",
           "per_view_candidates", "quality_steps", "resolution_budget"} <= set(qwen.get("supports") or []) and
          qwen.get("batch_allowed") is True and "reason" in qwen and "note" in qwen and
          bool(qwen.get("disabled_reason")),
          f"available={qwen.get('available')}")
    check("千问指向独立实例（8190）且标记首选",
          qwen.get("host", "").endswith("8190") and qwen.get("label", "").startswith("首选") and
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
        _qwf2, {"positive": "p", "negative": "n", "seed": 7, "resolution": 832, "steps": 35},
        S.qwen_edit_cfg(), {})
    check("Qwen 填充器把提示词、种子、尺寸和质量写进正确节点",
          _qwf2["5"]["inputs"]["prompt"] == "p" and _qwf2["6"]["inputs"]["seed"] == 7 and
          _qwf2["5"]["inputs"]["resolution"] == 832 and _qwf2["6"]["inputs"]["steps"] == 35 and
          {"positive", "seed", "resolution", "steps"} <= set(_qapplied))

    # ★ 2026-09-29 回归钉：实验引擎输入图的**路径口径**。
    #   项目约定 pass 图路径相对 assets/passes，形如 `<SKU>/<机位>/clay.png`，**不带 passes/ 前缀**
    #   （与 payload 的 depth_img 一致，见 _asset_path 注释）。
    #   曾经错写成要求 `passes/` 开头 → 界面上传的正确路径 100% 被判「缺少输入图片」，
    #   用户看到的就是「千问渲染必定失败」（24 条 failed）。这条断言防止再犯。
    check("实验引擎输入图路径口径与 depth_img 一致（不带 passes/ 前缀必须通过）",
          S.qwen_input_ok("AI渲染1/front/clay.png") is True and      # ← 曾被误判 False 的就是这个
          S.qwen_input_ok("stl_5/side/clay.png") is True and
          S.qwen_input_ok("source/stl_2/a.png") is True and
          S.qwen_input_ok("_部件/stl_5/side/guides/0123456789abcdef_cmf_guide.png") is True and
          S.qwen_input_ok("_部件/stl_5/front/guides/not-a-hash_cmf_guide.png") is False and
          S.qwen_input_ok("AI渲染1/front/depth.png") is False and    # 只收 clay 截图与产品图
          S.qwen_input_ok("") is False and
          S.qwen_input_ok(None) is False,
          "带 passes/ 与否都能过，但绝不能反过来要求必须带")

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
        check("千问拒绝把其他机位白模当作本机位输入",
              "机位不一致" in S.qwen_clay_input_issue(qid, "%s/side/clay.png" % TEST_SKU))
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
    with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
        app_html = f.read()
    st, body = req("POST", "/api/ui/product/batch", {"sku": TEST_SKU, "views": []})
    check("真材质底图批处理入口拒绝空机位", st == 400 and "机位" in json.loads(body).get("error", ""))
    check("千问真材质底图为可选项且逐机位引用",
          'id="qwenBaseSelect"' in app_html and
          'await ensureProductBases(sku,views,selectedMaterial,selectedColor,selectedStyle,' in app_js and
          'input_kind:state.sourceType==="image"?"photo":productBases?"product_base":"clay"' in app_js)
    check("千问固定种子可用于同条件步数对照且非法值被阻断",
          'id="qwenSeed"' in app_html and
          'function fixedQwenSeed()' in app_js and
          'seed_base:fixedQwenSeed()??Math.floor(Date.now()/1000)' in app_js and
          'try{const seed=fixedQwenSeed()' in app_js)
    check("补齐所选视角会检查整组三通道而非仅深度",
          'filter(view=>!item.views?.find(row=>row.view===view)?.ok)' in app_js)
    check("自动出图前会补齐白模、深度和法线整组",
          '["clay","depth","normal"].every(role=>viewHasPass(item,view,role))' in app_js)

    # 千问仍须按目标机位取白模；候选系列按主视图先行，再接第二参考。
    # 曾经用「预览机位」取图 → 出现「任务标记 3q4_left、输入图却是 side_left」的张冠李戴。
    check("千问按目标机位取白模，候选数可选且主视图先行",
          "find(r=>r.view===view)?.files?.clay" in app_js and
          'const perView=Number($("countSelect").value)' in app_js and
          "anchor_view:views.includes(\"front\")?\"front\":views[0]" in app_js and
          "return selectedViews();" in app_js,
          "按 view 取图 / 候选数可选 / 每组主视图先行")
    check("千问多机位使用目标白模与主视图双参考",
          '"images.image_2"] = ["9", 0]' in open(S.__file__, encoding="utf-8").read() and
          "<image1> is the target camera and geometry" in app_js and
          "<image2> is the same product" in app_js)
    check("两套引擎共用缺图补齐与八常用视角",
          'const COMMON_VIEWS = [...SIX_VIEWS,"3q4_left","3q4_right"]' in app_js and
          "async function ensureRequiredPasses(" in app_js and
          'await post("/api/ui/pass/batch"' in app_js and
          'await ensureRequiredPasses(sku,views,mode,experimental,' in app_js and
          '$("viewPickCommon").addEventListener' in app_js)
    check("千问预检不受稳定引擎离线误阻断",
          'if(!experimental&&!state.comfy.online)' in app_js)

    # 同系列只认同 SKU / 机位 / 候选编号 / series id 的已完成主视图。
    sid = "series-selftest-123"
    anchor_rel = f"outputs/{TEST_SKU}/front/qwen_test.png"
    anchor_id = S.insert_tasks([{
        "sku": TEST_SKU, "view": "front", "variant": 0,
        "payload": {"_meta": {"engine_id": "qwen21_edit_local",
                              "series": {"id": sid, "anchor_view": "front"}}}
    }])[0]
    S.update_task(anchor_id, status="done", output=anchor_rel)
    _real_output_path = S._output_path
    try:
        S._output_path = lambda rel: "/synthetic/qwen_test.png" if rel == anchor_rel else None
        found = S.qwen_series_anchor(
            {"sku": TEST_SKU, "view": "3q4_left", "variant": 0},
            {"series": {"id": sid, "anchor_view": "front"}})
        check("同系列侧面找到正确主视图结果", found["task_id"] == anchor_id and found["output"] == anchor_rel)
        try:
            S.qwen_series_anchor({"sku": TEST_SKU, "view": "3q4_right", "variant": 0},
                                 {"series": {"id": "series-other-123", "anchor_view": "front"}})
            rejected = False
        except RuntimeError as exc:
            rejected = "主视图尚未完成" in str(exc)
        check("不同系列不能串用旧主视图", rejected)
        S.update_task(anchor_id, status="failed", err="引导图依赖无法加载")
        try:
            S.qwen_series_anchor({"sku": TEST_SKU, "view": "3q4_left", "variant": 0},
                                 {"series": {"id": sid, "anchor_view": "front"}})
            explained = False
        except RuntimeError as exc:
            explained = "引导图依赖无法加载" in str(exc) and "主视图 #" in str(exc)
        check("关联机位显示同组主视图的原始失败原因", explained)
    finally:
        S._output_path = _real_output_path
        with S.DB_LOCK, S.db() as con:
            con.execute("DELETE FROM tasks WHERE id=?", (anchor_id,))
            con.commit()

    # 不调用真实显卡，只拦截 /prompt，检查主视图确实成为第二图像输入。
    submit_id = S.insert_tasks([{
        "sku": TEST_SKU, "view": "3q4_left", "variant": 0,
        "payload": {"_meta": {"engine_id": "qwen21_edit_local"}}
    }])[0]
    _saved = {name: getattr(S, name) for name in
              ("engine_ready", "comfy_upload", "_pass_exists", "qwen_clay_input_issue",
               "qwen_series_anchor", "stage_base_image", "http_json")}
    captured = {}
    try:
        S.engine_ready = lambda eid: (True, "", {"host": "http://127.0.0.1:8190"})
        S.comfy_upload = lambda rel, host=None: "uploaded_" + os.path.basename(rel)
        S._pass_exists = lambda rel: True
        S.qwen_clay_input_issue = lambda tid, rel: ""
        S.qwen_series_anchor = lambda task, meta: {"task_id": 77, "output": anchor_rel}
        S.stage_base_image = lambda sku, view, rel: ("_view_ref/qwen_anchor.png", None)
        def fake_http(url, data=None, timeout=None):
            captured["workflow"] = data["prompt"]
            return {"prompt_id": "selftest-qwen"}
        S.http_json = fake_http
        result = S._submit_qwen(submit_id, {
            "positive": "<image1> geometry; <image2> CMF", "negative": "",
            "source_img": "%s/3q4_left/clay.png" % TEST_SKU,
            "resolution": 896, "steps": 35,
            "_meta": {"mode": "image", "engine_id": "qwen21_edit_local",
                      "series": {"id": sid, "anchor_view": "front"}}
        }, "qwen21_edit_local")
        wf = captured["workflow"]
        check("千问第二参考图真正接入工作流且质量尺寸生效",
              result.get("appearance_ref_task") == 77 and
              wf["5"]["inputs"].get("images.image_2") == ["9", 0] and
              wf["9"]["class_type"] == "LoadImage" and
              wf["6"]["inputs"]["steps"] == 35 and
              wf["5"]["inputs"]["resolution"] == 896)
    finally:
        for name, value in _saved.items():
            setattr(S, name, value)
        with S.DB_LOCK, S.db() as con:
            con.execute("DELETE FROM tasks WHERE id=?", (submit_id,))
            con.commit()

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
    """删除本次自检写入的 _selftest 任务、参数卡与部件工作区。

    设计为幂等且不抛异常：即使自检中途失败也要执行，
    避免残留的测试数据让下一次运行断言失败（造成“越跑越坏”的假故障）。
    v3.10 起还要清 assets/_部件/_selftest —— 候选底图测试会往那里复制底图。
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
    try:
        part_ws = os.path.join(S.ASSETS, "_部件", TEST_SKU)
        if os.path.isdir(part_ws):
            shutil.rmtree(part_ws, ignore_errors=True)
    except Exception as e:
        print(f"  [警告] 清理自检部件工作区失败：{e}")
    try:
        for root in (S.MODELS_DIR, S.PASSES_DIR):
            target = os.path.join(root, CMF_TEST_SKU)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
        if os.path.isdir(S.CMF_SCHEME_DIR):
            for name in os.listdir(S.CMF_SCHEME_DIR):
                if name == CMF_TEST_SKU + ".json" or name.startswith(CMF_TEST_SKU + ".json.backup-"):
                    os.remove(os.path.join(S.CMF_SCHEME_DIR, name))
    except Exception as e:
        print(f"  [警告] 清理自检 CMF 样本失败：{e}")


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
