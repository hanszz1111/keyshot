#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 白模渲染器 · 仿图对比拼图
================================
把「结构 pass → 深度控制图 → 仿图结果」按机位拼成一张对照图，方便一眼评估锁形效果。

用法：
    python scripts/make_compare.py --sku GF --views side,3q4_left,front
    python scripts/make_compare.py --sku GF --ref "F:\\...\\GF.29.jpg" --ref-view side
"""
import argparse
import datetime as _dt
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("需要 Pillow：pip install pillow")
    raise SystemExit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSES = os.path.join(ROOT, "assets", "passes")
OUTPUTS = os.path.join(ROOT, "outputs")
PANEL_W = 640
PAD = 14
HEAD = 34
LABEL_H = 26


def load_font(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def fit(path, w=PANEL_W):
    """RGBA 的 pass 图要压在白底上（否则透明区会变成黑块）。"""
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    h = int(im.height * w / im.width)
    return im.resize((w, h), Image.LANCZOS)


def latest_result(sku, view):
    d = os.path.join(OUTPUTS, sku, view)
    if not os.path.isdir(d):
        return None
    cands = [f for f in os.listdir(d)
             if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    if not cands:
        return None
    cands.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)))
    return os.path.join(d, cands[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", required=True)
    ap.add_argument("--views", default="side,3q4_left,front")
    ap.add_argument("--ref", default=None, help="额外加一列参考图（整图只加到指定机位行）")
    ap.add_argument("--ref-view", default=None, help="参考图放在哪一行")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    views = [v.strip() for v in args.views.split(",") if v.strip()]
    font = load_font(22)
    font_s = load_font(18)

    rows = []
    for v in views:
        p = os.path.join(PASSES, args.sku, v)
        cells = []
        for name, label in (("clay.png", "结构 pass（clay）"),
                            ("depth.png", "深度控制图（depth）"),
                            (None, "仿图结果（AI）")):
            if name is None:
                path = latest_result(args.sku, v)
            else:
                path = os.path.join(p, name)
            cells.append((label, path if path and os.path.isfile(path) else None))
        rows.append((v, cells))

    ncol = 3
    panel_h = None
    for _, cells in rows:
        for _lab, path in cells:
            if path:
                im = Image.open(path)
                panel_h = int(im.height * PANEL_W / im.width)
                break
        break
    if panel_h is None:
        print("没有可用的图")
        return 1

    W = PAD + ncol * (PANEL_W + PAD)
    H = HEAD + len(rows) * (panel_h + LABEL_H + PAD) + PAD + 40
    sheet = Image.new("RGB", (W, H), (250, 250, 251))
    dr = ImageDraw.Draw(sheet)

    dr.text((PAD, 8), "AI 白模渲染器 · 仿图对照（%s）" % args.sku, (25, 25, 30), font=font)

    y = HEAD
    for v, cells in rows:
        for i, (label, path) in enumerate(cells):
            x = PAD + i * (PANEL_W + PAD)
            dr.text((x, y), "%s ｜ %s" % (v, label), (90, 90, 100), font=font_s)
            if path:
                try:
                    sheet.paste(fit(path), (x, y + LABEL_H))
                except Exception as e:
                    dr.text((x, y + LABEL_H), "读取失败 %s" % e, (200, 60, 60), font=font_s)
            else:
                dr.rectangle([x, y + LABEL_H, x + PANEL_W, y + LABEL_H + panel_h],
                             fill=(238, 238, 240))
                dr.text((x + 20, y + LABEL_H + panel_h // 2), "（缺）", (160, 160, 170), font=font_s)
        y += panel_h + LABEL_H + PAD

    stamp = _dt.datetime.now().strftime("%m%d_%H%M")
    out = args.out or os.path.join(OUTPUTS, "_对比", "%s_%s.jpg" % (args.sku, stamp))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out, "JPEG", quality=88, optimize=True)
    print("=" * 60)
    print("  对照图：%s" % os.path.relpath(out, ROOT))
    print("  尺寸：%dx%d  体积：%.0f KB" % (sheet.width, sheet.height, os.path.getsize(out) / 1024))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
