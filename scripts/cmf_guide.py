#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由同机位白模与 16 位 object ID 输出确定性 CMF 配色引导图。

这只固定部件色块和基础明暗，不模拟微纹理、透明/金属反射，也不保证 AI 后续不漂移。
依赖 numpy/Pillow，与 objectid_mask.py 使用同一运行环境。
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

# ★★ 必须显式把脚本目录加进 sys.path（2026-09-30 修，对应 v3.20）★★
# 本服务在 Windows 上用 ComfyUI 的**嵌入式 Python** 跑子进程；嵌入式发行版带
# `python3xx._pth`，而 **_pth 模式下 Python 不会把脚本所在目录放进 sys.path**
# （实测 sys.path[0] 是 ComfyUI 工作目录）。于是 `from objectid_mask import read_ids`
# 直接 ModuleNotFoundError → 界面报「多材质配色参考生成失败」，同系列后续机位
# 又因「主视图失败」被连带阻断，一次坏掉一整组。
# 托管 Python 不带 _pth，所以本机自检与 Mac 端都测不出来 —— 只有真跑生产才暴露。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from objectid_mask import read_ids  # noqa: E402  （必须在上面那句之后）


def hex_rgb(value):
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ValueError("颜色须为 #RRGGBB")
    return np.array([int(value[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def make_guide(clay_path, objectid_path, manifest_path, scheme_path, default_color, out_path,
               background_color="#F3F5F6"):
    with open(manifest_path, "r", encoding="utf-8") as f:
        mapping = json.load(f).get("objectid_map") or {}
    if os.path.isfile(scheme_path):
        with open(scheme_path, "r", encoding="utf-8") as f:
            assignments = json.load(f).get("assignments") or {}
    else:
        assignments = {}
    clay = np.asarray(Image.open(clay_path).convert("RGBA"), dtype=np.uint8)
    width, height, ids = read_ids(objectid_path)
    if clay.shape[:2] != (height, width):
        raise ValueError("白模与对象 ID 图尺寸不一致，请重新生成同机位结构图")
    base = clay[..., :3].astype(np.float32)
    luma = base[..., 0] * .2126 + base[..., 1] * .7152 + base[..., 2] * .0722
    # 保留白模原有影棚明暗；平色分区由整数对象 ID 决定，不用 AI 猜。
    shade = np.clip(luma / 225.0, .18, 1.12)
    output = clay.copy()
    foreground = ids != 0
    # Qwen 的第一参考必须是稳定影棚底色；透明/黑色白模背景会被模型当成纹理继续生成。
    output[..., :3][~foreground] = hex_rgb(background_color).astype(np.uint8)
    output[..., 3] = 255
    output[..., :3][foreground] = np.clip(hex_rgb(default_color) * shade[foreground, None], 0, 255).astype(np.uint8)
    found = set()
    for key, name in mapping.items():
        item = assignments.get(name)
        if not item:
            continue
        found.add(name)
        mask = ids == int(key)
        if mask.any():
            output[..., :3][mask] = np.clip(hex_rgb(item["color"]) * shade[mask, None], 0, 255).astype(np.uint8)
    missing = set(assignments) - found
    if missing:
        raise ValueError("有 %d 个部位不在当前机位的对象 ID 清单中" % len(missing))
    # 轮廓/部件分界为硬约束线；同一网格上的明显暗缝再从白模亮度中提取。
    # 无几何或可见明暗依据的隐藏分模线无法凭空识别，须由 CAD 分件或人工补线。
    edges = np.zeros((height, width), dtype=bool)
    edges[:, 1:] |= (ids[:, 1:] != ids[:, :-1]) & foreground[:, 1:]
    edges[1:, :] |= (ids[1:, :] != ids[:-1, :]) & foreground[1:, :]
    detail = np.zeros_like(edges)
    detail[:, 1:] |= (np.abs(luma[:, 1:] - luma[:, :-1]) > 46) & foreground[:, 1:] & foreground[:, :-1]
    detail[1:, :] |= (np.abs(luma[1:, :] - luma[:-1, :]) > 46) & foreground[1:, :] & foreground[:-1, :]
    output[..., :3][edges] = np.minimum(output[..., :3][edges], 65)
    output[..., :3][detail & ~edges] = np.minimum(output[..., :3][detail & ~edges], 98)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    Image.fromarray(output, "RGBA").save(out_path)
    return {"parts": len(found), "width": width, "height": height}


def main():
    parser = argparse.ArgumentParser()
    for key in ("clay", "objectid", "manifest", "scheme", "default_color", "out"):
        parser.add_argument("--" + key.replace("_", "-"), required=True)
    parser.add_argument("--background-color", default="#F3F5F6")
    args = parser.parse_args()
    result = make_guide(args.clay, args.objectid, args.manifest, args.scheme,
                        args.default_color, args.out, args.background_color)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
