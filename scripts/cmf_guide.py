#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由同机位白模与 16 位 object ID 输出确定性 CMF 配色引导图。

这只固定部件色块和基础明暗，不模拟微纹理、透明/金属反射，也不保证 AI 后续不漂移。
依赖 numpy/Pillow，与 objectid_mask.py 使用同一运行环境。
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

from objectid_mask import read_ids


def hex_rgb(value):
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ValueError("颜色须为 #RRGGBB")
    return np.array([int(value[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def make_guide(clay_path, objectid_path, manifest_path, scheme_path, default_color, out_path):
    with open(manifest_path, "r", encoding="utf-8") as f:
        mapping = json.load(f).get("objectid_map") or {}
    with open(scheme_path, "r", encoding="utf-8") as f:
        assignments = json.load(f).get("assignments") or {}
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
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    Image.fromarray(output, "RGBA").save(out_path)
    return {"parts": len(found), "width": width, "height": height}


def main():
    parser = argparse.ArgumentParser()
    for key in ("clay", "objectid", "manifest", "scheme", "default_color", "out"):
        parser.add_argument("--" + key.replace("_", "-"), required=True)
    args = parser.parse_args()
    result = make_guide(args.clay, args.objectid, args.manifest, args.scheme,
                        args.default_color, args.out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
