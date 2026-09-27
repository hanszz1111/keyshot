#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 白模渲染器 · ComfyUI 冒烟测试（端到端出图验证）
--------------------------------------------------
用途：不依赖任何第三方库，直接调 ComfyUI 的 HTTP API 出一张图，
      验证「本机 + 这张显卡 + 这套模型」的生成链路是否真的通，
      并记录实测耗时（供过程文档 15.4 的 8GB 稳定性/耗时回填）。

用法：
    python scripts/comfy_smoke_test.py            # 默认用 RealVisXL Lightning
    python scripts/comfy_smoke_test.py --base     # 换成官方 SDXL base 1.0
    python scripts/comfy_smoke_test.py --steps 8 --size 1024x1024

前提：ComfyUI 已在 127.0.0.1:8188 运行。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

HOST = "http://127.0.0.1:8188"

PROMPT_POS = (
    "professional product photography of a matte dark-grey handheld measuring "
    "instrument on a clean seamless light-grey background, studio softbox lighting, "
    "sharp focus, high detail, commercial catalog shot, 85mm lens"
)
PROMPT_NEG = (
    "text, watermark, logo, blurry, low quality, distorted, deformed, "
    "extra objects, cluttered background, oversaturated"
)

# ControlNet 锁形模式专用：★故意不写任何形状词★（P0 协议要求）
# 形状只能来自控制图；若写成"水平仪/方形/圆形"之类，测的就不是锁形能力了。
PROMPT_CN_POS = (
    "professional commercial product photography, realistic matte plastic and "
    "slightly glossy injection-molded housing, subtle brushed metal accents, "
    "clean seamless light-grey studio background, softbox lighting, soft contact "
    "shadow, 85mm lens, sharp focus, ultra detailed, catalog shot"
)


def api(path, payload=None, method=None, timeout=60):
    url = HOST + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode("utf-8")) if body else None


def build_workflow(ckpt, steps, cfg, w, h, seed, sampler, scheduler, prefix):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": PROMPT_POS, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": PROMPT_NEG, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0], "seed": seed,
                         "steps": steps, "cfg": cfg,
                         "sampler_name": sampler, "scheduler": scheduler,
                         "denoise": 1.0}},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": prefix}},
    }


def build_cn_workflow(ckpt, cn_name, cn_type, cn_strength, img, steps, cfg,
                      w, h, seed, sampler, scheduler, prefix, pos, neg):
    """ControlNet 锁形工作流：clay/pass 图 → ControlNet Union → 生成。
    pos 故意不写形状词（P0 协议要求），让形状只能来自控制图。"""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": pos, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": neg, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "LoadImage", "inputs": {"image": img}},
        "9": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": cn_name}},
        "10": {"class_type": "SetUnionControlNetType",
               "inputs": {"control_net": ["9", 0], "type": cn_type}},
        "11": {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["2", 0], "negative": ["3", 0],
                          "control_net": ["10", 0], "image": ["8", 0],
                          "strength": cn_strength,
                          "start_percent": 0.0, "end_percent": 1.0}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["11", 0], "negative": ["11", 1],
                         "latent_image": ["4", 0], "seed": seed,
                         "steps": steps, "cfg": cfg,
                         "sampler_name": sampler, "scheduler": scheduler,
                         "denoise": 1.0}},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": prefix}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", action="store_true", help="用官方 sd_xl_base_1.0 而不是 RealVisXL Lightning")
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--cfg", type=float, default=None)
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--timeout", type=int, default=900, help="等待出图的最长秒数")
    ap.add_argument("--cn", action="store_true", help="ControlNet 锁形模式（用 clay/pass 图当控制图）")
    ap.add_argument("--clay", default=r"D:\Dsektop\AI渲染\assets\passes\LS-360G\front\clay.png",
                    help="控制图路径（clay 或其他 pass）")
    ap.add_argument("--cn-type", default="tile",
                    help="Union ControlNet 类型：tile / canny / lineart / depth / normalbae / scribble …")
    ap.add_argument("--cn-strength", type=float, default=0.65)
    args = ap.parse_args()

    if args.base:
        ckpt = "sd_xl_base_1.0.safetensors"
        steps = args.steps or 25
        cfg = args.cfg if args.cfg is not None else 7.0
        sampler, scheduler = "dpmpp_2m", "karras"
    else:
        ckpt = "RealVisXL_V5.0_Lightning_fp16.safetensors"
        steps = args.steps or 8
        cfg = args.cfg if args.cfg is not None else 2.0
        sampler, scheduler = "dpmpp_sde", "karras"

    try:
        w, h = (int(x) for x in args.size.lower().split("x"))
    except Exception:
        print("--size 格式应为 1024x1024")
        return 2

    print("=" * 64)
    print(" ComfyUI 冒烟测试")
    print("=" * 64)
    print(f"  服务地址 : {HOST}")

    try:
        st = api("/system_stats")
    except Exception as e:
        print(f"  ❌ 连不上 ComfyUI：{e}")
        print("     请先启动 F:\\AI-Renderer\\packs\\ComfyUI_windows_portable\\run_nvidia_gpu.bat")
        return 3
    dev = (st.get("devices") or [{}])[0]
    print(f"  ComfyUI  : {st['system']['comfyui_version']}")
    print(f"  GPU      : {dev.get('name')}  显存 {dev.get('vram_total',0)/2**30:.1f} GB"
          f"（空闲 {dev.get('vram_free',0)/2**30:.1f} GB）")
    print(f"  底模     : {ckpt}")
    print(f"  参数     : {w}x{h}  steps={steps}  cfg={cfg}  {sampler}/{scheduler}  seed={args.seed}")
    print("-" * 64)

    if args.cn:
        # ---- ControlNet 锁形模式 ----
        import shutil
        src = args.clay
        if not os.path.isfile(src):
            print(f"  ❌ 找不到控制图：{src}")
            return 8
        in_dir = r"F:\AI-Renderer\packs\ComfyUI_windows_portable\ComfyUI\input"
        os.makedirs(in_dir, exist_ok=True)
        img_name = "cn_" + os.path.basename(src)
        shutil.copyfile(src, os.path.join(in_dir, img_name))
        cn_name = "controlnet-union-sdxl-1.0-promax.safetensors"
        print(f"  控制图   : {src}")
        print(f"  ControlNet: {cn_name}  type={args.cn_type}  strength={args.cn_strength}")
        print(f"  提示词   : 不写形状词（形状只能来自控制图）")
        print("-" * 64)
        prefix = f"smoke_cn_{args.cn_type}"
        wf = build_cn_workflow(ckpt, cn_name, args.cn_type, args.cn_strength, img_name,
                               steps, cfg, w, h, args.seed, sampler, scheduler,
                               prefix, PROMPT_CN_POS, PROMPT_NEG)
    else:
        prefix = "smoke_" + ("base" if args.base else "lightning")
        wf = build_workflow(ckpt, steps, cfg, w, h, args.seed, sampler, scheduler, prefix)

    t0 = time.time()
    try:
        res = api("/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())})
    except urllib.error.HTTPError as e:
        print("  ❌ 提交失败：", e.read().decode("utf-8", "ignore")[:800])
        return 4
    if res.get("node_errors"):
        print("  ❌ 节点报错：", json.dumps(res["node_errors"], ensure_ascii=False)[:800])
        return 4
    pid = res["prompt_id"]
    print(f"  已提交任务 : {pid}")

    hist = None
    while time.time() - t0 < args.timeout:
        try:
            h = api(f"/history/{pid}")
        except Exception:
            h = None
        if h and pid in h:
            hist = h[pid]
            break
        time.sleep(2)
    elapsed = time.time() - t0

    if hist is None:
        print(f"  ⚠️ 超时 {args.timeout}s 仍未返回，请去界面看队列状态")
        return 5

    status = (hist.get("status") or {})
    print(f"  状态      : {status.get('status_str')}  completed={status.get('completed')}")
    if status.get("status_str") == "error":
        for m in status.get("messages", []):
            print("     ", json.dumps(m, ensure_ascii=False)[:400])
        return 6

    imgs = []
    for node_out in (hist.get("outputs") or {}).values():
        imgs.extend(node_out.get("images") or [])
    if not imgs:
        print("  ❌ 没有产出图片")
        return 7

    print("-" * 64)
    print(f"  ✅ 出图成功：{len(imgs)} 张，耗时 {elapsed:.1f} 秒"
          f"（{elapsed/max(len(imgs),1):.1f} s/张）")
    for im in imgs:
        fn = im.get("filename")
        sub = im.get("subfolder") or ""
        local = os.path.join(
            r"F:\AI-Renderer\packs\ComfyUI_windows_portable\ComfyUI\output", sub, fn)
        url = f"{HOST}/view?filename={fn}&subfolder={sub}&type={im.get('type','output')}"
        print(f"     文件 : {local}")
        print(f"     预览 : {url}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
