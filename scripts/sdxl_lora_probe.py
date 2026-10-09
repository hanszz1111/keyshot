#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SDXL LoRA 探针（实验性）。

用途：验证 `industrial-design-extreme-material-r64`（及任意 SDXL LoRA）在
**正式实例 8188** 那条 SDXL 链路上是否真的生效、以及对画面做了什么。

★ 为什么不用 AI 生成式猜测「生效了没」：本轮刚在千问上踩过
  「LoRA 不报错但一个权重键都没命中、画面完全不变」的坑（跨代 LoRA）。
  SDXL 这边同样不能只看文件名。

走的是生产链路里的**无参考图分支**（`web/server.py:2121` 附近：
无 ref 时移除 12/13/14，KSampler 直接取 checkpoint）——
这样 LoRA 的效应不被 IPAdapter 混合，信号最干净。

用法（任意 Python，只需标准库）：

    python scripts\\sdxl_lora_probe.py --lora "" --seed 43 --out outputs/_SDXL探针/base_s43.png
    python scripts\\sdxl_lora_probe.py --lora industrial-design-extreme-material-r64.safetensors ^
        --strength 1.0 --seed 43 --out outputs/_SDXL探针/lora_s43.png
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
import qwen_ab_experiment as AB          # noqa: E402  （复用 upload_file）

HOST = "http://127.0.0.1:8188"
WF_T2I = "config/comfy_workflow_sdxl.json"
WF_CN = "config/comfy_workflow_sdxl_cn.json"

PROMPT = ("studio product photograph of a modern handheld electronic measuring device, "
          "injection-molded ABS housing with fine matte grain, anodized aluminium trim ring, "
          "precision-machined details, soft gradient studio background, large softbox lighting")


def abs_of(rel):
    return os.path.join(ROOT, rel.replace("/", os.sep))


def _strip_comments(wf):
    """★ 必须剥掉所有 `_` 前缀键（`_comment` / `_slots` / `_when` / `_notes`）。

    生产链路在 `web/server.py:1486-1496` 就是这么做的。带着它们送 `/prompt`
    会被 ComfyUI 当成节点，直接 **HTTP 500「Server got itself in trouble」**，
    且**不给任何有用报错**。（2026-10-08 在自建 Krea-2 工作流上踩过同一个坑。）
    """
    return {k: ({ik: iv for ik, iv in v.items() if not str(ik).startswith("_")}
                if isinstance(v, dict) else v)
            for k, v in wf.items() if not str(k).startswith("_")}


def build(lora, strength, cn=False, depth_rel="", normal_rel=""):
    wf = _strip_comments(json.load(open(abs_of(WF_CN if cn else WF_T2I), encoding="utf-8")))

    # 无参考图分支（与生产 `web/server.py:2121` 一致）：移除 IPAdapter 三节点，
    # KSampler 直接取 checkpoint。这样 LoRA 的效应不被 IPAdapter 混合，信号最干净。
    for nid in ("12", "13", "14"):
        wf.pop(nid, None)
    wf["3"]["inputs"]["model"] = ["1", 0]

    if cn:
        if not (depth_rel and normal_rel):
            raise SystemExit("--cn 需要同时给 --depth 与 --normal")
        for nid, rel in (("10", depth_rel), ("11", normal_rel)):
            p = abs_of(rel)
            if not os.path.isfile(p):
                raise SystemExit("找不到结构图：%s" % rel)
            wf[nid]["inputs"]["image"] = AB.upload_file(p, HOST)

    applied = []
    if lora:
        wf["900"] = {"class_type": "LoraLoaderModelOnly",
                     "inputs": {"model": ["1", 0], "lora_name": lora,
                                "strength_model": float(strength)}}
        wf["3"]["inputs"]["model"] = ["900", 0]
        applied.append({"node": "900", "lora_name": lora, "strength_model": strength})
    return wf, applied


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sdxl_lora_probe.py", description="SDXL LoRA 探针")
    ap.add_argument("--lora", default="", help="LoRA 文件名；留空 = 基线")
    ap.add_argument("--cn", action="store_true", help="走 ControlNet 工作流（白模 depth+normal）")
    ap.add_argument("--depth", default="", help="depth 图（项目内相对路径）")
    ap.add_argument("--normal", default="", help="normal 图（项目内相对路径）")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--seed", type=int, default=43)
    ap.add_argument("--steps", type=int, default=0, help="0 = 用工作流里的值（Lightning 8 步）")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.lora:
        opts = S.http_json("%s/object_info/LoraLoaderModelOnly" % HOST, timeout=15)
        names = opts["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
        if args.lora not in names:
            raise SystemExit("8188 上没有这个 LoRA：%s\n  可用：%s" % (args.lora, names))

    wf, applied = build(args.lora, args.strength, cn=args.cn,
                        depth_rel=args.depth, normal_rel=args.normal)
    wf["6"]["inputs"]["text"] = args.prompt
    wf["3"]["inputs"]["seed"] = args.seed
    if args.steps:
        wf["3"]["inputs"]["steps"] = args.steps

    print("提交到 8188：%s ｜ LoRA=%s ｜ 步数=%s ｜ cfg=%s ｜ 采样=%s/%s ｜ 种子=%d"
          % ("ControlNet 路径" if args.cn else "文生图路径", args.lora or "（无，基线）", wf["3"]["inputs"]["steps"], wf["3"]["inputs"]["cfg"],
             wf["3"]["inputs"]["sampler_name"], wf["3"]["inputs"]["scheduler"], args.seed))
    t0 = time.time()
    resp = S.http_json(HOST + "/prompt", {"prompt": wf, "client_id": "sdxl-lora-probe"}, timeout=120)
    if resp.get("node_errors"):
        print("节点校验失败：\n%s" % json.dumps(resp["node_errors"], ensure_ascii=False)[:800],
              file=sys.stderr)
        return 1
    pid = resp["prompt_id"]

    deadline = time.time() + args.timeout
    imgs = []
    while time.time() < deadline:
        hist = S.http_json("%s/history/%s" % (HOST, pid), timeout=20)
        if pid in hist:
            st = (hist[pid].get("status") or {})
            if st.get("status_str") == "error":
                print("执行出错：%s" % json.dumps(st.get("messages", []), ensure_ascii=False)[:600],
                      file=sys.stderr)
                return 1
            for out in (hist[pid].get("outputs") or {}).values():
                imgs.extend(out.get("images") or [])
            if imgs:
                break
        time.sleep(1.5)

    if not imgs:
        print("超时无产物", file=sys.stderr)
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
    print("已保存 %s ｜ %.2f MiB ｜ 用时 %.1fs" % (args.out, len(blob) / 1024**2, time.time() - t0))
    if applied:
        print("插入记录：%s" % json.dumps(applied, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
