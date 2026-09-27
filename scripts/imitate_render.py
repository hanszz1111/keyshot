#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 白模渲染器 · 仿图 Runner
================================
用投放区里的结构 pass（clay/depth/normal）出图，走【控制台 API】——与网页界面完全是同一条链路：
    入队任务 → /api/comfy/submit → 轮询 /api/comfy/poll → 结果落 outputs/<SKU>/<机位>/

★ 提示词纪律：默认模板【不写形状词】。形状只能来自结构 pass（否则测的就不是锁形能力了，见 P0 协议）。

用法：
    # 用材质预设（推荐）
    python scripts/imitate_render.py --sku GF --view side --preset white_black_rubber
    # 直接给提示词
    python scripts/imitate_render.py --sku GF --view side --prompt "..."
    # 多 seed 出一组
    python scripts/imitate_render.py --sku GF --view side --preset white_black_rubber --n 4
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSOLE = os.environ.get("RENDERER_CONSOLE", "http://127.0.0.1:8765")

# 通用摄影底座（刻意不含形状词）
PHOTO_BASE = ("professional e-commerce product photography, seamless light-grey studio "
              "background, large softbox key light with soft contact shadow, 85mm lens, "
              "sharp focus, ultra detailed, clean catalog shot")

NEGATIVE = ("text, letters, watermark, logo, brand name, numbers, screen display, blurry, "
            "low quality, distorted, deformed, extra objects, cluttered background, "
            "oversaturated, cartoon, cgi plastic look")

# 材质预设：只描述材质/配色/光照，绝不描述形状
PRESETS = {
    "white_black_rubber": (
        "matte white injection-molded plastic housing with subtle glossy sheen, "
        "black rubber over-mold trim along the edges and a textured grip pad, "
        "dark grey ribbed metal ring on the protruding cylinder"),
    "black_matte": (
        "matte black soft-touch plastic housing, dark grey metal accents, "
        "subtle anodized brushed details, low-sheen finish"),
    "silver_black": (
        "brushed silver aluminum housing with fine sandblast finish, "
        "matte black rubber grip areas, crisp metallic highlights"),
    "two_tone_olive": (
        "olive-drab green matte housing with black rubber over-mold accents, "
        "muted low-contrast palette"),
}


def call(path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(CONSOLE + path, data=data,
                                 method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    # 直连本机控制台，绕开环境代理
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if body else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", required=True)
    ap.add_argument("--view", default="front")
    ap.add_argument("--preset", default=None, choices=sorted(PRESETS.keys()))
    ap.add_argument("--prompt", default=None, help="完全自定义正提示词（覆盖 preset）")
    ap.add_argument("--negative", default=NEGATIVE)
    ap.add_argument("--size", default="1232x752")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--n", type=int, default=1, help="出一组（每个变体 seed+1）")
    ap.add_argument("--depth-w", type=float, default=0.65)
    ap.add_argument("--normal-w", type=float, default=0.45)
    ap.add_argument("--steps", type=int, default=None, help="覆盖默认步数（Lightning 建议 6-12）")
    ap.add_argument("--cfg", type=float, default=None, help="覆盖默认 cfg（Lightning 建议 1.5-3）")
    ap.add_argument("--rank", type=float, default=None,
                    help="直接指定提示词权重（等价于总强度），传了就覆盖 depth-w/normal-w")
    ap.add_argument("--timeout", type=int, default=180, help="单张等待上限（秒）")
    args = ap.parse_args()

    if args.prompt:
        positive = args.prompt
        prompt_src = "自定义"
    else:
        preset = args.preset or "white_black_rubber"
        positive = PRESETS[preset] + ", " + PHOTO_BASE
        prompt_src = "预设 " + preset

    try:
        w, h = (int(x) for x in args.size.lower().split("x"))
    except Exception:
        print("--size 应为 1232x752")
        return 2

    seed0 = args.seed if args.seed is not None else 20260926

    print("=" * 64)
    print(" 仿图 · SKU=%s 机位=%s" % (args.sku, args.view))
    print("=" * 64)
    st = call("/api/comfy/status")
    print("  ComfyUI：%s  %s" % ("在线" if st.get("online") else "离线", st.get("version") or st.get("error")))
    if not st.get("online"):
        print("  ⛔ 请先双击 启动全部.bat")
        return 3

    assets = call("/api/assets")
    ready = None
    for it in assets.get("items", []):
        if it["sku"] == args.sku:
            for v in it["views"]:
                if v["view"] == args.view:
                    ready = v
    if ready is None:
        print("  ⛔ 投放区里找不到 %s/%s" % (args.sku, args.view))
        return 4
    print("  结构 pass：%s" % json.dumps(ready["files"], ensure_ascii=False))
    print("           缺 %s" % (ready["missing"] or "无"))
    print("  提示词来源：%s" % prompt_src)

    tasks = []
    for i in range(args.n):
        payload = {
            "positive": positive, "negative": args.negative,
            "seed": seed0 + i, "width": w, "height": h,
            "depth_img": "%s/%s/depth.png" % (args.sku, args.view),
            "normal_img": "%s/%s/normal.png" % (args.sku, args.view),
            "depth_w": args.depth_w, "normal_w": args.normal_w,
        }
        if args.steps is not None:
            payload["steps"] = args.steps
        if args.cfg is not None:
            payload["cfg"] = args.cfg
        tasks.append({
            "sku": args.sku, "view": args.view, "variant": i,
            "positive": positive, "negative": args.negative,
            "payload": payload,
        })
    ins = call("/api/tasks", {"tasks": tasks})
    print("  入队：%s" % ins)

    allt = call("/api/tasks")["tasks"]
    myids = sorted([t["id"] for t in allt if t["sku"] == args.sku and t["view"] == args.view],
                   reverse=True)[:args.n]
    myids = sorted(myids)
    print("  本次任务：%s" % myids)

    results = []
    for tid in myids:
        t0 = time.time()
        try:
            sub = call("/api/comfy/submit", {"id": tid})
        except urllib.error.HTTPError as e:
            print("  ❌ #%s 提交失败：%s" % (tid, e.read().decode("utf-8", "ignore")[:300]))
            continue
        print("  ▶ #%s %s%s" % (tid, sub["mode"],
                                "（depth+normal）" if sub.get("with_normal") else
                                ("（depth）" if sub["mode"] == "controlnet" else "")))
        while time.time() - t0 < args.timeout:
            r = call("/api/comfy/poll?id=%s" % tid)
            if r["state"] == "done":
                el = time.time() - t0
                print("    ✅ %.1fs  %s" % (el, "、".join(r["saved"])))
                results.append((tid, el, r["saved"]))
                break
            if r["state"] in ("error", "empty"):
                print("    ❌ %s" % json.dumps(r, ensure_ascii=False)[:300])
                break
            time.sleep(2)
        else:
            print("    ⚠️ #%s 超时" % tid)

    print("-" * 64)
    if results:
        avg = sum(r[1] for r in results) / len(results)
        print("  完成 %d 张，平均 %.1fs" % (len(results), avg))
        for tid, el, saved in results:
            for s in saved:
                print("    %s" % s)
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
