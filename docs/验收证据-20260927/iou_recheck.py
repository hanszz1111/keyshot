# -*- coding: utf-8 -*-
"""独立复核 GF 四机位：白模 alpha 剪影 vs 成图背景扣除剪影 的 IoU。"""
import os
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ROOT)  # _ui_verify -> 项目根

VIEWS = ["front", "3q4_left", "3q4_right", "side"]
W, H = 384, round(384 * 752 / 1232)


def clay_mask(path):
    """Blender 出的 alpha.png 是「白=物体、黑=背景」的灰度图，
    alpha 通道恒为 255（不可用作掩膜），必须走灰度阈值。"""
    arr = np.array(Image.open(path).convert("L"))
    return arr > 128


def bg_mask(path, w=W, h=H, thr=34):
    """复刻前端算法：取四角平均色为底色，色距平方和 > thr^2*3 视为前景。"""
    im = Image.open(path).convert("RGB").resize((w, h))
    a = np.array(im).astype(np.float32)
    corners = a[[2, 2, h - 3, h - 3], [2, w - 3, 2, w - 3], :]  # 4x3
    base = corners.mean(axis=0)
    d = a - base
    dist2 = (d ** 2).sum(axis=2)
    return dist2 > (thr ** 2) * 3


def iou(m1, m2):
    inter = np.logical_and(m1, m2).sum()
    union = np.logical_or(m1, m2).sum()
    return (inter / union if union else 0.0), inter, union


def newest_output(view):
    d = os.path.join(ROOT, "outputs", "GF", view)
    if not os.path.isdir(d):
        return None
    cands = [f for f in os.listdir(d) if f.startswith("ai_render_") and f.endswith(".png")]
    if not cands:
        return None
    cands.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)))
    return os.path.join(d, cands[-1])


print("%-11s %-8s %-8s %-8s %-8s %s" % ("机位", "IoU", "白模%", "成图%", "交集%", "成图文件"))
print("-" * 78)
rows = []
for v in VIEWS:
    ap = os.path.join(ROOT, "assets", "passes", "GF", v, "alpha.png")
    op = newest_output(v)
    if not (os.path.exists(ap) and op):
        print("%-11s %s" % (v, "缺文件（alpha 或成图）"))
        continue
    m1 = clay_mask(ap)
    m1r = np.array(Image.fromarray((m1 * 255).astype(np.uint8)).resize((W, H))) > 128
    m2 = bg_mask(op)
    val, inter, union = iou(m1r, m2)
    rows.append((v, val))
    print("%-11s %-8.3f %-8.1f %-8.1f %-8.1f %s" % (
        v, val, m1r.mean() * 100, m2.mean() * 100,
        (inter / (W * H)) * 100, os.path.basename(op)))

if rows:
    avg = sum(r[1] for r in rows) / len(rows)
    print("-" * 78)
    print("平均 IoU = %.3f   门槛 = 0.900   →  %s" % (avg, "达标" if avg >= 0.90 else "未达标"))
    print("注：此数值为前端同款算法的独立复算，仅作轮廓提示，不代表几何精度结论。")
