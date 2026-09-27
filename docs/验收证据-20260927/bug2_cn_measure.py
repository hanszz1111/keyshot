# -*- coding: utf-8 -*-
"""量化对照：裸 img2img vs Canny ControlNet 锁形状。

指标：
  MAE      —— 与源图逐像素平均绝对差（0–255）。越大 = 材质/光照改动越彻底。
  IoU      —— 与源图前景剪影交并比。越接近 1 = 形状保留越好。
  edgeIoU  —— 与源图 Canny 边缘图的重合度。衡量"结构是否被保留"。
"""
import os, sys, json
import numpy as np
from PIL import Image, ImageFilter

COMFY_ROOT = r"F:/AI-Renderer/packs/ComfyUI_windows_portable/ComfyUI"
COMFY_OUT = os.path.join(COMFY_ROOT, "output")
SRC = os.path.join(COMFY_ROOT, "input", "bug2_src.png")
CASES = [
    ("N1_无CN_12步_denoise0.85", "bug2_cn_00001_.png"),
    ("C1_CN0.75_12步_denoise0.85", "bug2_cn_00002_.png"),
    ("C2_CN1.00_12步_denoise0.85", "bug2_cn_00003_.png"),
    ("C3_CN0.75_12步_denoise0.70", "bug2_cn_00004_.png"),
]


def load(p, size=None):
    im = Image.open(p).convert("RGB")
    if size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im).astype(np.float32)


def silhouette(a):
    """前景掩膜：白模背景近黑，取灰度 > 阈值 为物体。"""
    g = a.mean(axis=2)
    # 用 Otsu 式自适应：取中位数与最大值的中点
    thr = max(24.0, float(np.median(g)) + (float(np.percentile(g, 99)) - float(np.median(g))) * 0.28)
    return g > thr


def edge_map(a):
    im = Image.fromarray(a.astype(np.uint8)).convert("L")
    return np.asarray(im.filter(ImageFilter.FIND_EDGES)).astype(np.float32) > 40


def iou(m1, m2):
    inter = np.logical_and(m1, m2).sum()
    union = np.logical_or(m1, m2).sum()
    return float(inter) / float(union) if union else 0.0


def main():
    src = load(SRC)
    H, W = src.shape[:2]
    src_mask = silhouette(src)
    src_edge = edge_map(src)
    print("源图 %dx%d  前景占比 %.1f%%  边缘像素 %d" % (
        W, H, 100.0 * src_mask.mean(), src_edge.sum()))
    print("=" * 88)
    print("%-30s %8s %8s %8s" % ("配置", "MAE", "剪影IoU", "边缘IoU"))
    print("-" * 88)
    rows = []
    for label, fn in CASES:
        p = os.path.join(COMFY_OUT, fn)
        if not os.path.exists(p):
            print("%-30s 缺失" % label); continue
        img = load(p, (W, H))
        mae = float(np.abs(img - src).mean())
        m = silhouette(img)
        e = edge_map(img)
        r = dict(label=label, file=fn, mae=round(mae, 2),
                 sil_iou=round(iou(src_mask, m), 4),
                 edge_iou=round(iou(src_edge, e), 4))
        rows.append(r)
        print("%-30s %8.2f %8.3f %8.3f" % (label, r["mae"], r["sil_iou"], r["edge_iou"]))
    print("=" * 88)
    with open("bug2_cn_metrics.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("已写 bug2_cn_metrics.json")


if __name__ == "__main__":
    main()
