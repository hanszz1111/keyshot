# -*- coding: utf-8 -*-
"""端到端验收（修正版）：走真实 /api/tasks（嵌套 payload）→ /api/comfy/submit。

⚠️ 上一版脚本踩的坑：/api/tasks 的 insert_tasks 读的是 t["payload"]（嵌套对象），
   而脚本把 source_img/denoise 放在任务对象顶层 → payload 存成 {} → image_mode=False
   → 走了 txt2img 工作流，产出一张人像。本版按前端 app.js 的真实格式提交。

   E1  denoise 0.50 —— 预期"基本没渲染"（复现用户报的问题）
   E2  denoise 0.85 + Canny CN —— 预期"材质彻底改变且形状保留"
"""
import json, time, urllib.request, os

WEB = "http://127.0.0.1:8765"
ROOT = r"F:/AI-Renderer/packs/ComfyUI_windows_portable/ComfyUI"
OUTDIR = os.path.join(ROOT, "output")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

POS = ("Professional studio product photograph of a handheld laser rangefinder device. "
       "The input is an unpainted clay/grey 3D model screenshot on a dark background. "
       "Convert it into a finished, fully materialised product: apply real surface materials, "
       "colour and finish to every surface. Matte dark charcoal plastic body, brushed aluminium "
       "trim ring, large softbox key light from front-left, gentle fill light, soft contact shadow, "
       "clean dark grey seamless studio background, premium commercial product photography, "
       "realistic material response, accurate camera perspective, crisp silhouette")
NEG = ("blurry, low quality, warped geometry, extra parts, distorted product shape, "
       "inaccurate markings, invented text, fake logo, cluttered background, cartoon, illustration, "
       "white unpainted plastic, bare grey model, clay render, untextured surface, "
       "flat unlit shading, raw 3D viewport screenshot, no material")


def post(path, payload):
    req = urllib.request.Request(WEB + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=120) as r:
        return json.loads(r.read().decode())


def get(path, timeout=30):
    with _OPENER.open(WEB + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def submit(denoise):
    """按前端格式：任务对象里带 payload 嵌套。"""
    inner = {
        "positive": POS, "negative": NEG, "seed": 20260927,
        "width": 1024, "height": 656,
        "source_img": "source/stl_2/686fe7beb8755065f052ccab297d137b.png",
        "denoise": denoise,
        "_meta": {"sku": "stl_2", "view": "photo", "variant": 0, "mode": "image",
                  "ui_version": "2.0", "style": "studio",
                  "description": "白模转成品", "input_kind": "clay"},
    }
    task = {"sku": "stl_2", "view": "photo", "variant": 0,
            "positive": POS, "negative": NEG, "payload": inner}
    post("/api/tasks", {"tasks": [task]})
    d = get("/api/tasks")
    tid = None
    for t in (d.get("tasks") or []):
        if t.get("status") == "pending" and t.get("view") == "photo":
            tid = t.get("id"); break
    if not tid:
        return None, None
    sub = post("/api/comfy/submit", {"id": tid})
    return sub, tid


def poll_until(tid, timeout_s=240):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            s = get("/api/comfy/poll?id=%s" % tid)
        except Exception:
            s = {}
        st = s.get("state")
        if st in ("done", "error", "empty"):
            return s, time.time() - t0
        time.sleep(3)
    return {"state": "timeout"}, time.time() - t0


def main():
    print("=" * 86)
    print("  端到端验收（修正版）· /api/tasks(payload嵌套) → /api/comfy/submit → poll")
    print("=" * 86)
    report = {}
    for denoise, tag in [(0.50, "E1"), (0.85, "E2")]:
        sub, tid = submit(denoise)
        print("\n[%s] denoise=%.2f  提交 -> %s (id=%s)" % (
            tag, denoise, json.dumps(sub, ensure_ascii=False)[:220], tid))
        if not tid:
            report[tag] = {"error": "no task"}
            continue
        s, dur = poll_until(tid)
        print("      轮询 %.1fs -> %s" % (dur, json.dumps(s, ensure_ascii=False)[:400]))
        report[tag] = {"tid": tid, "denoise": denoise, "poll": s, "seconds": round(dur, 1)}
    with open("bug2_e2e_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n已写 bug2_e2e_result.json")


if __name__ == "__main__":
    main()
