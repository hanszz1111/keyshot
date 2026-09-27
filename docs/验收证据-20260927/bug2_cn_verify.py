# -*- coding: utf-8 -*-
"""对照实验：img2img 裸跑 vs img2img + Canny ControlNet 锁形状。

目的：证明「只提 denoise 会臆造别的产品」，而「Canny 锁形 + 高 denoise」能同时
      做到「材质彻底改变」且「形状还是原来那台设备」。
"""
import json, time, urllib.request, os

COMFY = "http://127.0.0.1:8188"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SRC = "bug2_src.png"
CKPT = "RealVisXL_V5.0_Lightning_fp16.safetensors"
CN = "controlnet-union-sdxl-1.0-promax.safetensors"

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
    req = urllib.request.Request(COMFY + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=90) as r:
        return json.loads(r.read().decode())


def get(path, timeout=30):
    with _OPENER.open(COMFY + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def base_nodes(w, h):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "15": {"class_type": "LoadImage", "inputs": {"image": SRC}},
        "5": {"class_type": "ImageScale", "inputs": {"image": ["15", 0], "upscale_method": "lanczos",
                                                     "width": w, "height": h, "crop": "disabled"}},
        "16": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["1", 2]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": POS, "clip": ["1", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}},
        "4": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "bug2_cn"}},
    }


def wf_nocn(steps, denoise, cfg):
    n = base_nodes(1024, 656)
    n["3"] = {"class_type": "KSampler", "inputs": {
        "seed": 20260927, "steps": steps, "cfg": cfg, "sampler_name": "dpmpp_sde",
        "scheduler": "karras", "denoise": denoise, "model": ["1", 0],
        "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["16", 0]}}
    return n


def wf_cn(steps, denoise, cfg, cn_w, lo, hi, endp):
    n = base_nodes(1024, 656)
    n["2"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CN}}
    n["22"] = {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["2", 0], "type": "canny/lineart/anime_lineart/mlsd"}}
    n["30"] = {"class_type": "Canny", "inputs": {"image": ["5", 0], "low_threshold": lo, "high_threshold": hi}}
    n["20"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
        "positive": ["6", 0], "negative": ["7", 0], "control_net": ["22", 0],
        "image": ["30", 0], "strength": cn_w, "start_percent": 0.0, "end_percent": endp}}
    n["3"] = {"class_type": "KSampler", "inputs": {
        "seed": 20260927, "steps": steps, "cfg": cfg, "sampler_name": "dpmpp_sde",
        "scheduler": "karras", "denoise": denoise, "model": ["1", 0],
        "positive": ["20", 0], "negative": ["20", 1], "latent_image": ["16", 0]}}
    return n


CASES = [
    ("N1_无CN_12步_denoise0.85", wf_nocn(12, 0.85, 3.0)),
    ("C1_CN0.75_12步_denoise0.85",
     wf_cn(12, 0.85, 3.0, 0.75, 0.06, 0.18, 0.85)),
    ("C2_CN1.00_12步_denoise0.85",
     wf_cn(12, 0.85, 3.0, 1.00, 0.06, 0.18, 0.85)),
    ("C3_CN0.75_12步_denoise0.70",
     wf_cn(12, 0.70, 3.0, 0.75, 0.04, 0.14, 0.90)),
]


def run_case(label, wf):
    t0 = time.time()
    try:
        res = post("/prompt", {"prompt": wf, "client_id": "bug2-cnlab"})
    except Exception as e:
        print(f"{label}: SUBMIT_FAIL {e}")
        return None
    if res.get("node_errors"):
        print(f"{label}: NODE_ERROR {json.dumps(res['node_errors'], ensure_ascii=False)[:400]}")
        return None
    pid = res["prompt_id"]
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            h = get(f"/history/{pid}")
        except Exception:
            time.sleep(1); continue
        if pid in h:
            outs = h[pid].get("outputs") or {}
            for _, o in outs.items():
                for im in (o.get("images") or []):
                    print(f"{label:34} -> {im['filename']}  ({time.time()-t0:.1f}s)")
                    return im["filename"]
            break
        time.sleep(1)
    print(f"{label}: TIMEOUT")
    return None


def main():
    print("=" * 78)
    print("  img2img 裸跑 vs + Canny ControlNet 锁形状")
    print("=" * 78)
    out = {}
    for label, wf in CASES:
        f = run_case(label, wf)
        if f:
            out[label] = f
    with open("bug2_cn_result.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\n完成。对照图：", list(out.values()))


if __name__ == "__main__":
    main()
