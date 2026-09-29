#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROI 局部重绘准备 —— 把底图 / 掩膜 / 深度 / 法线裁到**同一 ROI**并可放大。

为什么（大纲 §2 P1）：
    整幅重绘时，模型要在一个 1232×752 的画面上改一个几百像素的部件，
    有效分辨率极低，且非目标区域容易被连带改动。裁到部件外接框 + 按尺度留边后，
    模型只需要处理一小块局部，细节密度大幅提高；生成完再缩回原位、
    由 composite_masked.py 做确定性合成，边外像素一个不动。

留边与放大都**按部件尺度**算，不用固定像素：
    pad = max(pad_min, 部件长边 × pad_ratio)
    放大倍数默认 1.0（ROI 本身就比整幅大得多，通常不必再放大）。

依赖 numpy + PIL（与 objectid_mask.py 一致，以子进程方式调用）。

用法：
    python roi_crop.py --base b.png --mask m.png --depth d.png --normal n.png \
        --bbox 120 480 300 700 --out-dir <dir> [--scale 1.5] [--json]
输出：
    <dir>/base.png  mask.png  depth.png  normal.png  roi.json
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image


def align_down(v, m):
    return int(v) // m * m


def align_up(v, m):
    return -(-int(v) // m) * m


def main(argv=None):
    ap = argparse.ArgumentParser(prog="roi_crop.py", description="ROI 局部重绘准备")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "X1", "Y0", "Y1"),
                    help="部件掩膜的外接框（闭区间，来自 part_mask 的 bbox）")
    ap.add_argument("--auto-bbox", action="store_true",
                    help="不给 --bbox 时，从 --mask 自动算外接框")
    ap.add_argument("--base", required=True)
    ap.add_argument("--mask", required=True)
    ap.add_argument("--depth")
    ap.add_argument("--normal")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--pad-ratio", type=float, default=0.12, help="留边 = 部件长边 × 该比例")
    ap.add_argument("--pad-min", type=int, default=8, help="留边下限（像素）")
    ap.add_argument("--pad-max", type=int, default=96, help="留边上限（像素）")
    ap.add_argument("--scale", type=float, default=1.0, help="ROI 放大倍数")
    ap.add_argument("--multiple", type=int, default=8, help="输出尺寸对齐到该倍数（默认 8）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    src = {}
    for role, path in (("base", args.base), ("mask", args.mask),
                       ("depth", args.depth), ("normal", args.normal)):
        if not path:
            continue
        if not os.path.isfile(path):
            raise SystemExit("找不到 %s：%s" % (role, path))
        src[role] = Image.open(path)

    W, H = src["base"].size
    # ★ 尺寸适配（2026-09-29）：底图可能是**已完成的候选图**，它的尺寸不一定等于结构图
    #   —— 实测结构图 1232×752，而 SDXL 产物 1536×1024、Qwen 产物 992×608，全都不一样。
    #   这里**以底图为基准**把掩膜/深度/法线缩放过去：底图是最终画面，要保住它的原始像素；
    #   掩膜是二值图（用 NEAREST，形状不会被糊掉），深度/法线是约束图，缩放可以接受。
    rescaled = []
    for role in ("mask", "depth", "normal"):
        img = src.get(role)
        if img is None or img.size == (W, H):
            continue
        src[role] = img.resize((W, H), Image.NEAREST if role == "mask" else Image.LANCZOS)
        rescaled.append("%s %dx%d→%dx%d" % (role, img.size[0], img.size[1], W, H))
    if rescaled:
        print("尺寸适配（以底图 %dx%d 为基准）：%s" % (W, H, "、".join(rescaled)))
    if args.bbox:
        x0, x1, y0, y1 = args.bbox
    elif args.auto_bbox:
        m = np.asarray(src["mask"].convert("L"))
        ys, xs = np.nonzero(m > 127)
        if not xs.size:
            raise SystemExit("掩膜里没有前景像素，无法自动取外接框")
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    else:
        raise SystemExit("必须给 --bbox，或加 --auto-bbox 让脚本自己算")
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    pad = int(round(max(bw, bh) * args.pad_ratio))
    pad = max(args.pad_min, min(args.pad_max, pad))

    rx0 = max(0, x0 - pad)
    ry0 = max(0, y0 - pad)
    rx1 = min(W - 1, x1 + pad)
    ry1 = min(H - 1, y1 + pad)
    # 让裁剪框再向外扩到 8 的倍数边界，保证宽高是 8 的倍数（采样器要求）
    rx0 = align_down(rx0, args.multiple)
    ry0 = align_down(ry0, args.multiple)
    rx1 = min(W, align_up(rx1 + 1, args.multiple))
    ry1 = min(H, align_up(ry1 + 1, args.multiple))
    rw, rh = rx1 - rx0, ry1 - ry0

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    tw = max(args.multiple, align_up(round(rw * args.scale), args.multiple))
    th = max(args.multiple, align_up(round(rh * args.scale), args.multiple))

    written = {}
    for role, img in src.items():
        crop = img.crop((rx0, ry0, rx1, ry1))
        resample = Image.NEAREST if role == "mask" else Image.LANCZOS
        if (crop.size) != (tw, th):
            crop = crop.resize((tw, th), resample)
        dest = os.path.join(out_dir, role + ".png")
        crop.save(dest)
        written[role] = dest

    info = {
        "ok": True,
        "source_size": [W, H],
        "rescaled": rescaled,
        "bbox": [x0, x1, y0, y1],
        "part_size": [bw, bh],
        "pad": pad,
        "roi": [rx0, rx1 - 1, ry0, ry1 - 1],   # 闭区间，与 composite_masked.py --bbox 同一口径
        "roi_size": [rw, rh],
        "out_size": [tw, th],
        "scale": args.scale,
        "files": written,
    }
    print("ROI 裁剪完成：部件 %dx%d，留边 %d → ROI %dx%d（原图 %dx%d），输出 %dx%d"
          % (bw, bh, pad, rw, rh, W, H, tw, th))
    print("  roi=%s" % (info["roi"],))
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
