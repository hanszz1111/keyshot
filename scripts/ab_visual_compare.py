#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B 目视对比图：把两臂并排 + **放大差异并标出改动位置**。

为什么需要这个：本项目多数 A/B 的臂间 MAE 只有 2–4（种子噪声 11+），
肉眼看两张并排图几乎一模一样，凭肉眼判不出「改了哪里」。
所以第三列直接把差异放大 / 用红色标出改动像素 —— 让人一眼看到
「差异集中在背景还是在产品结构上」。

用法（★ 需带 numpy/Pillow，用 ComfyUI 的 python_embeded）：

    python_embeded\\python.exe scripts/ab_visual_compare.py ^
        --dir outputs/_AB实验/clip --a W4A8-A --b INT8-A ^
        --out "outputs/_AB实验/clip/对比图-W4A8-A_vs_INT8-A.png"

    :: 多组对比（同一目录下多对臂）
    python_embeded\\python.exe scripts/ab_visual_compare.py --dir outputs/_AB实验/clip ^
        --pair W4A8-A:INT8-A --pair W4A8-B0:INT8-B0 --out .../对比图.png
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIFF_T = 12          # 与实验脚本一致的「差异像素」阈值（灰阶）
GAIN = 6.0           # 差异放大倍数


def load(path):
    return np.asarray(Image.open(path).convert("RGB"))


def font(size):
    for name in ("msyh.ttc", "simhei.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def pair_block(a_img, b_img, width):
    """返回 (并排图, 差异标注图, MAE)。"""
    assert a_img.shape == b_img.shape, "两图尺寸不同：%s vs %s" % (a_img.shape, b_img.shape)
    d = np.abs(a_img.astype(np.int16) - b_img.astype(np.int16)).mean(axis=2)
    mae = float(d.mean())

    # 差异放大图：改动像素染红叠加在 B 上，未改动处保留灰度底
    gray = (b_img.astype(np.float32) * 0.35).astype(np.uint8)
    mask = d > DIFF_T
    marked = gray.copy()
    marked[mask] = [255, 40, 40]
    # 再叠一层「放大后的差异灰度」，让细微差异也可见
    amp = np.clip(d * GAIN, 0, 255).astype(np.uint8)
    amp_rgb = np.stack([amp] * 3, axis=2)
    blend = ((marked.astype(np.float32) + amp_rgb.astype(np.float32)) / 2).astype(np.uint8)

    def fit(im):
        h = int(im.shape[0] * width / im.shape[1])
        return Image.fromarray(im).resize((width, h), Image.LANCZOS)

    return fit(a_img), fit(b_img), fit(blend), mae, float(mask.mean() * 100)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ab_visual_compare.py", description="A/B 目视对比图")
    ap.add_argument("--dir", required=True, help="实验输出目录（含各臂子目录）")
    ap.add_argument("--pair", action="append", required=True,
                    help="形如 A臂:B臂，可重复")
    ap.add_argument("--out", required=True, help="输出 PNG（Windows 路径）")
    ap.add_argument("--cell-width", type=int, default=420)
    args = ap.parse_args(argv)

    pairs = []
    for spec in args.pair:
        if ":" not in spec:
            raise SystemExit("--pair 需要写成 A臂:B臂，收到：%s" % spec)
        a, b = spec.split(":", 1)
        pairs.append((a.strip(), b.strip()))

    base = os.path.join(ROOT, args.dir.replace("/", os.sep))
    if not os.path.isdir(base):
        raise SystemExit("目录不存在：%s" % base)

    # 收集所有 (机位, 种子)
    cells = set()
    for arm in {x for p in pairs for x in p}:
        ad = os.path.join(base, arm)
        if not os.path.isdir(ad):
            raise SystemExit("臂目录不存在：%s" % ad)
        for f in os.listdir(ad):
            if f.endswith(".png") and "_s" in f:
                view, seed = f[:-4].rsplit("_s", 1)
                cells.add((view, seed))
    cells = sorted(cells)
    if not cells:
        raise SystemExit("没找到任何图")

    f_title, f_head, f_small = font(20), font(15), font(13)
    pad, gap, head_h, label_h = 14, 8, 34, 24
    total_w = pad + len(pairs) * 3 * (args.cell_width + gap) + pad
    cell_h = None
    blocks = []
    for pair in pairs:
        for view, seed in cells:
            pa = os.path.join(base, pair[0], "%s_s%s.png" % (view, seed))
            pb = os.path.join(base, pair[1], "%s_s%s.png" % (view, seed))
            if not (os.path.isfile(pa) and os.path.isfile(pb)):
                continue
            a, b, diff, mae, ratio = pair_block(load(pa), load(pb), args.cell_width)
            cell_h = cell_h or a.height
            blocks.append((pair, view, seed, a, b, diff, mae, ratio))
    if not blocks:
        raise SystemExit("没有可对比的图（检查臂名与文件名）")

    n_rows = len(blocks)
    row_h = label_h + cell_h + pad
    sheet = Image.new("RGB", (total_w, head_h + n_rows * row_h), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 7), "A/B 目视对比（第 3 列 = 差异放大 %g× + 红色标出改动像素，阈值 %d）"
           % (GAIN, DIFF_T), fill=(20, 45, 65), font=f_title)

    y = head_h
    last_pair = None
    for pair, view, seed, a, b, diff, mae, ratio in blocks:
        if pair != last_pair:
            d.rectangle([0, y, total_w, y + label_h - 4], fill=(232, 240, 246))
            d.text((pad, y + 4), "对比：%s  →  %s" % pair, fill=(20, 60, 95), font=f_head)
            y += label_h
            last_pair = pair
        d.text((pad, y), "%s / 种子 %s   MAE %.2f   改动像素 %.1f%%" % (view, seed, mae, ratio),
               fill=(40, 60, 75), font=f_small)
        y += label_h
        for i, im in enumerate((a, b, diff)):
            x = pad + (i % 3) * (args.cell_width + gap)
            sheet.paste(im, (x, y))
        y += cell_h + pad

    out = os.path.join(ROOT, args.out.replace("/", os.sep))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)
    print("已生成：%s" % args.out)
    print("  尺寸 %dx%d，%d 行" % (sheet.width, sheet.height, n_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
