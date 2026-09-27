# -*- coding: utf-8 -*-
"""E2E 结果量化：ai_render_00026_.png（新版链路，CN0.75 + denoise0.85）vs 源图。"""
import os, json
import numpy as np
from PIL import Image, ImageFilter

ROOT = r"F:/AI-Renderer/packs/ComfyUI_windows_portable/ComfyUI"
SRC = os.path.join(ROOT, "input", "bug2_src.png")
OUT = os.path.join(ROOT, "output", "ai_render_00026_.png")
LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bug2_lab")


def load(p, size=None):
    im = Image.open(p).convert("RGB")
    if size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im).astype(np.float32)


def sil(a):
    g = a.mean(axis=2)
    thr = max(24.0, float(np.median(g)) + (float(np.percentile(g, 99)) - float(np.median(g))) * 0.28)
    return g > thr


def edges(a):
    im = Image.fromarray(a.astype(np.uint8)).convert("L")
    return np.asarray(im.filter(ImageFilter.FIND_EDGES)).astype(np.float32) > 40


def iou(m1, m2):
    u = np.logical_or(m1, m2).sum()
    return float(np.logical_and(m1, m2).sum()) / float(u) if u else 0.0


src = load(SRC); H, W = src.shape[:2]
img = load(OUT, (W, H))
mae = float(np.abs(img - src).mean())
print("E2E 新链路结果：%s" % os.path.basename(OUT))
print("  MAE(与源图)   = %.2f  /255" % mae)
print("  剪影 IoU      = %.3f" % iou(sil(src), sil(img)))
print("  边缘 IoU      = %.3f" % iou(edges(src), edges(img)))
print("  输出均值/标准差 = %.1f / %.1f   （源图 %.1f / %.1f）" % (
    img.mean(), img.std(), src.mean(), src.std()))

# 导出到实验目录
os.makedirs(LAB, exist_ok=True)
o = os.path.join(LAB, "E2E_new_pipeline_CN075_d085.png")
Image.open(OUT).convert("RGB").save(o)
print("已导出", o)
