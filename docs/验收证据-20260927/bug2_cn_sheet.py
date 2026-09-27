# -*- coding: utf-8 -*-
"""生成对照拼图：源图 + 4 个变体，横排，带标签。"""
import os
from PIL import Image, ImageDraw, ImageFont

COMFY_ROOT = r"F:/AI-Renderer/packs/ComfyUI_windows_portable/ComfyUI"
OUT = os.path.join(COMFY_ROOT, "output")
SRC = os.path.join(COMFY_ROOT, "input", "bug2_src.png")
OUTDIR = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(OUTDIR, "bug2_lab")
os.makedirs(LAB, exist_ok=True)

ITEMS = [
    ("源图（白模）", SRC),
    ("N1 无CN 12步 d0.85", os.path.join(OUT, "bug2_cn_00001_.png")),
    ("C1 CN0.75 12步 d0.85", os.path.join(OUT, "bug2_cn_00002_.png")),
    ("C2 CN1.00 12步 d0.85", os.path.join(OUT, "bug2_cn_00003_.png")),
    ("C3 CN0.75 12步 d0.70", os.path.join(OUT, "bug2_cn_00004_.png")),
]

CELL_W = 480
try:
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
except Exception:
    font = ImageFont.load_default()

tiles = []
for label, p in ITEMS:
    if not os.path.exists(p):
        print("缺失", p); continue
    im = Image.open(p).convert("RGB")
    r = CELL_W / im.width
    im = im.resize((CELL_W, int(im.height * r)), Image.LANCZOS)
    tiles.append((label, im))

h = max(t.height for _, t in tiles) + 40
sheet = Image.new("RGB", (CELL_W * len(tiles), h), (24, 24, 27))
d = ImageDraw.Draw(sheet)
for i, (label, t) in enumerate(tiles):
    x = i * CELL_W
    sheet.paste(t, (x, 40))
    d.text((x + 10, 10), label, fill=(235, 235, 240), font=font)
    if i:
        d.line([(x, 0), (x, h)], fill=(90, 90, 100), width=2)

p = os.path.join(LAB, "bug2_cn_sheet.png")
sheet.save(p)
print("已写", p, sheet.size)

# 单独导出 C3 大图（最佳候选）
c3 = os.path.join(OUT, "bug2_cn_00004_.png")
if os.path.exists(c3):
    im = Image.open(c3).convert("RGB")
    q = os.path.join(LAB, "C3_CN0.75_d0.70.png")
    im.save(q)
    print("已写", q)
