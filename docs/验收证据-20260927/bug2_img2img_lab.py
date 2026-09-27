# -*- coding: utf-8 -*-
"""img2img 参数对照实验：验证「基本没渲染」的根因是否为有效步数不足。

对同一张白模截图，用不同 (steps, denoise, sampler, cfg) 组合各出一张图，
统计「与原图的像素差」，差异越大说明渲染越明显。
"""
import json, time, urllib.request, os, sys

COMFY = "http://127.0.0.1:8188"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(COMFY + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path, timeout=30):
    with _OPENER.open(COMFY + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


CKPT = "RealVisXL_V5.0_Lightning_fp16.safetensors"
SRC = "bug2_src.png"

POS = ("Professional studio product photograph of a handheld laser rangefinder device. "
       "Matte dark charcoal plastic body with subtle satin sheen, brushed aluminum trim ring, "
       "large softbox key light from front-left, gentle fill, soft contact shadow, "
       "clean dark grey seamless studio background, premium commercial product photography, "
       "realistic material response, accurate camera perspective, crisp silhouette")
NEG = ("blurry, low quality, warped geometry, extra parts, distorted product shape, "
       "inaccurate markings, invented text, fake logo, cluttered background, cartoon, illustration, "
       "white unpainted plastic, clay render, grey model, untextured")


def build(steps, denoise, sampler, scheduler, cfg):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "15": {"class_type": "LoadImage", "inputs": {"image": SRC}},
        "5": {"class_type": "ImageScale", "inputs": {"image": ["15", 0], "upscale_method": "lanczos",
                                                     "width": 1024, "height": 656, "crop": "disabled"}},
        "16": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["1", 2]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": POS, "clip": ["1", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 20260927, "steps": steps, "cfg": cfg,
                                                   "sampler_name": sampler, "scheduler": scheduler,
                                                   "denoise": denoise, "model": ["1", 0],
                                                   "positive": ["6", 0], "negative": ["7", 0],
                                                   "latent_image": ["16", 0]}},
        "4": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "bug2_test"}},
    }


CONFIGS = [
    # label,               steps, denoise, sampler,      scheduler, cfg
    ("A_现状_8步_0.50_dpmppSDE_karras", 8,  0.50, "dpmpp_sde",     "karras", 2.0),
    ("B_8步_0.75_dpmppSDE_karras",      8,  0.75, "dpmpp_sde",     "karras", 2.0),
    ("C_20步_0.60_dpmpp_2m_karras",     20, 0.60, "dpmpp_2m",      "karras", 4.0),
    ("D_30步_0.70_dpmpp_2m_karras",     30, 0.70, "dpmpp_2m",      "karras", 5.0),
    ("E_12步_0.65_dpmpp_sde_normal",    12, 0.65, "dpmpp_sde",     "normal", 2.5),
]


def main():
    print("=" * 78)
    print("  img2img 参数对照实验")
    print("=" * 78)
    results = []
    for label, steps, denoise, sampler, sched, cfg in CONFIGS:
        eff = max(1, round(steps * denoise))
        wf = build(steps, denoise, sampler, sched, cfg)
        t0 = time.time()
        try:
            res = post("/prompt", {"prompt": wf, "client_id": "bug2-lab"})
            if res.get("node_errors"):
                print(f"{label}: NODE_ERROR {json.dumps(res['node_errors'], ensure_ascii=False)[:200]}")
                continue
            pid = res["prompt_id"]
        except Exception as e:
            print(f"{label}: SUBMIT_FAIL {e}")
            continue

        # 轮询
        img = None
        deadline = time.time() + 300
        while time.time() < deadline:
            try:
                h = get(f"/history/{pid}")
            except Exception:
                time.sleep(1)
                continue
            if pid in h:
                outs = h[pid].get("outputs") or {}
                for nid, o in outs.items():
                    imgs = o.get("images") or []
                    if imgs:
                        img = imgs[-1]
                        break
                break
            time.sleep(1)
        dt = time.time() - t0
        if not img:
            print(f"{label}: TIMEOUT/NO_IMAGE")
            continue
        results.append((label, steps, denoise, eff, sampler, sched, cfg, img["filename"], dt))
        print(f"{label:36} steps={steps:>3} denoise={denoise} 有效={eff:>2}步 "
              f"cfg={cfg} → {img['filename']}  ({dt:.1f}s)")

    print()
    print("产出文件在 ComfyUI output 目录：")
    for r in results:
        print("  ", r[7])
    with open("bug2_lab_result.json", "w", encoding="utf-8") as f:
        json.dump([{"label": r[0], "steps": r[1], "denoise": r[2], "effective": r[3],
                    "sampler": r[4], "scheduler": r[5], "cfg": r[6], "file": r[7],
                    "seconds": round(r[8], 1)} for r in results], f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
