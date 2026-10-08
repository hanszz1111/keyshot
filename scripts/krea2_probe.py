#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Krea-2 参考图编辑探针（实验性）。

用途：验证 `config/comfy_workflow_krea2_edit.json` 这条「按参考图编辑」链路在本机
8190 实例上是否真的跑得通，以及耗时如何。
**它不写任务库、不碰生产引擎列表**，只在隔离实例上提交一次并把结果落到 outputs/。

背景：Krea-2 官方只发 t2i 与 style-reference 两个模板，看起来「不能编辑」。
但核对 style-reference 模板的接线后发现，它走的是
`TextEncodeQwenImageEditPlus` → `FluxKontextMultiReferenceLatentMethod(index_timestep_zero)`
—— 即 **ref_latents 参考图通路，与 Qwen-Image-Edit 同源**，
而 `comfy/model_base.py` 的 `Krea2.extra_conds` 明确把 `ref_latents` 转发给模型。
本探针就是把这条通路单独跑一遍。

用法（需带 numpy/Pillow 的 ComfyUI python_embeded）：

    python_embeded\\python.exe scripts\\krea2_probe.py ^
        --ref assets/_部件/AI渲染1/front/guides/4fa332e145a58b03_cmf_guide.png ^
        --seed 43 --out outputs/_Krea2探针/front_s43.png
"""

import argparse
import json
import os
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import server as S                      # noqa: E402
import qwen_ab_experiment as AB         # noqa: E402  （复用它的 upload_file）

HOST = "http://127.0.0.1:8190"
WORKFLOW = "config/comfy_workflow_krea2_edit.json"
NEEDED_NODES = ("UNETLoader", "CLIPLoader", "VAELoader", "LoadImage",
                "TextEncodeQwenImageEditPlus", "FluxKontextMultiReferenceLatentMethod",
                "ConditioningZeroOut", "EmptyLatentImage", "KSampler",
                "VAEDecode", "SaveImage")
LOADER_OF = {"1": ("UNETLoader", "unet_name"),
             "2": ("CLIPLoader", "clip_name"),
             "3": ("VAELoader", "vae_name")}


def abs_of(rel):
    return os.path.join(ROOT, rel.replace("/", os.sep))


def preflight():
    """★ 先查权重与节点再提交。缺东西就早报错，别提交完才发现失败。"""
    problems = []
    for cls in NEEDED_NODES:
        try:
            info = S.http_json("%s/object_info/%s" % (HOST, cls), timeout=10)
        except Exception as exc:
            problems.append("节点 %s 查询失败（%s）" % (cls, exc))
            continue
        if not info or cls not in info:
            problems.append("节点 %s 不存在" % cls)

    wf = json.load(open(abs_of(WORKFLOW), encoding="utf-8"))
    for nid, (cls, field) in LOADER_OF.items():
        name = wf.get(nid, {}).get("inputs", {}).get(field)
        try:
            info = S.http_json("%s/object_info/%s" % (HOST, cls), timeout=15)
            values = info[cls]["input"]["required"][field][0]
        except Exception as exc:
            problems.append("%s 的 %s 下拉读取失败（%s）" % (cls, field, exc))
            continue
        if name not in values:
            problems.append("权重缺失：%s（%s 下拉里没有）" % (name, cls))

    if problems:
        print("前置检查未通过：", file=sys.stderr)
        for p in problems:
            print("   ✗ " + p, file=sys.stderr)
        raise SystemExit(2)
    print("前置检查通过：%d 个节点 + 3 个权重均就位" % len(NEEDED_NODES))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="krea2_probe.py", description="Krea-2 参考图编辑探针")
    ap.add_argument("--ref", required=True, help="参考图（项目内相对路径）")
    ap.add_argument("--prompt", default="", help="留空则用工作流里的默认指令")
    ap.add_argument("--seed", type=int, default=43)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", required=True, help="输出 PNG（项目内相对路径）")
    args = ap.parse_args(argv)

    preflight()

    wf = json.load(open(abs_of(WORKFLOW), encoding="utf-8"))
    ref_abs = abs_of(args.ref)
    if not os.path.isfile(ref_abs):
        raise SystemExit("参考图不存在：%s" % args.ref)
    wf["4"]["inputs"]["image"] = AB.upload_file(ref_abs, HOST)
    if args.prompt:
        wf["5"]["inputs"]["prompt"] = args.prompt
    wf["8"]["inputs"]["width"] = args.width
    wf["8"]["inputs"]["height"] = args.height
    wf["9"]["inputs"]["seed"] = args.seed
    wf["9"]["inputs"]["steps"] = args.steps

    print("提交：参考图 %s → ComfyUI 里的 %s" % (args.ref, wf["4"]["inputs"]["image"]))
    print("      %d×%d ｜ %d 步 ｜ 种子 %d" % (args.width, args.height, args.steps, args.seed))
    t0 = time.time()
    try:
        resp = S.http_json(HOST + "/prompt",
                           {"prompt": wf, "client_id": "krea2-probe"}, timeout=180)
    except Exception as exc:
        print("提交失败：%s" % exc, file=sys.stderr)
        return 1
    if resp.get("node_errors"):
        print("提交被拒（节点校验没过）：\n%s"
              % json.dumps(resp["node_errors"], ensure_ascii=False)[:900], file=sys.stderr)
        return 1
    pid = resp.get("prompt_id")
    print("prompt_id = %s，等待出图…" % pid)

    deadline = time.time() + args.timeout
    imgs, err = [], None
    while time.time() < deadline:
        try:
            hist = S.http_json("%s/history/%s" % (HOST, pid), timeout=20)
        except Exception as exc:
            err = "轮询失败：%s" % exc
            break
        if pid in hist:
            info = hist[pid]
            status = info.get("status") or {}
            if status.get("status_str") == "error":
                err = json.dumps(status.get("messages", []), ensure_ascii=False)[:900]
                break
            for out in (info.get("outputs") or {}).values():
                imgs.extend(out.get("images") or [])
            if imgs:
                break
        time.sleep(2.0)

    elapsed = round(time.time() - t0, 1)
    if err:
        print("生成出错：%s" % err, file=sys.stderr)
        return 1
    if not imgs:
        print("超时（%ss）仍无产物" % args.timeout, file=sys.stderr)
        return 1

    im = imgs[0]
    q = urllib.parse.urlencode({"filename": im.get("filename", ""),
                                "subfolder": im.get("subfolder", "") or "",
                                "type": im.get("type", "output")})
    dst = abs_of(args.out)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with S._urlopen("%s/view?%s" % (HOST, q), timeout=90) as r:
        blob = r.read()
    with open(dst, "wb") as f:
        f.write(blob)
    print("已保存 %s ｜ %.2f MiB ｜ 用时 %.1fs" % (args.out, len(blob) / 1024**2, elapsed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
