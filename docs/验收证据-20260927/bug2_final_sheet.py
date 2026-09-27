# -*- coding: utf-8 -*-
"""生成最终结论拼图：源图 + 反例(N1) + 推荐(C1) + 端到端真实产出。"""
import os
from PIL import Image, ImageDraw, ImageFont

LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bug2_lab")
ITEMS = [
    ("源白模（输入）", os.path.join(LAB, "N1_noCN_d085.png")),   # 占位，稍后替换
]
# 源图从隔离区取
SRC = r"D:/Dsektop/AI渲染/AI渲染/_隔离区/20260927_v24/comfy_input/bug2_src.png"
ITEMS = [
    ("① 输入：白模截图", SRC),
    ("② 反例：无 CN，d0.85\n形状全丢 + 臆造标牌", os.path.join(LAB, "N1_noCN_d085.png")),
    ("③ 推荐：CN0.75，d0.85\n材质换新 + 形状保留", os.path.join(LAB, "C1_CN075_d085.png")),
    ("④ 端到端真实产出\nai_render_00027_.png", os.path.join(LAB, "E2E_00027_CN075_d095.png")),
]

CELL_W, HDR = 500, 62
try:
    f_big = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 20)
except Exception:
    f_big = ImageFont.load_default()

tiles = []
for label, p in ITEMS:
    if not os.path.exists(p):
        print("缺失", p); continue
    im = Image.open(p).convert("RGB")
    im = im.resize((CELL_W, int(im.height * CELL_W / im.width)), Image.LANCZOS)
    tiles.append((label, im))

h = max(t.height for _, t in tiles) + HDR
sheet = Image.new("RGB", (CELL_W * len(tiles), h), (18, 18, 21))
d = ImageDraw.Draw(sheet)
for i, (label, t) in enumerate(tiles):
    x = i * CELL_W
    sheet.paste(t, (x, HDR))
    d.multiline_text((x + 12, 10), label, fill=(240, 240, 245), font=f_big, spacing=4)
    if i:
        d.line([(x, 0), (x, h)], fill=(70, 70, 82), width=3)

out = os.path.join(LAB, "FINAL_结论总图.png")
sheet.save(out)
print("已写", out, sheet.size)
