# -*- coding: utf-8 -*-
"""一次性诊断：用 Blender 正确读 16 位 objectid.png，输出每个机位的可见 id 与像素数。
（PIL 读 16-bit RGBA 会降成 8 位，所以不能用 PIL 做这件事。）"""
import glob, json, os, sys
import bpy, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pass as BP

sku = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "AI渲染1"
out = {}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in sorted(glob.glob(os.path.join(ROOT, "assets/passes", sku, "*"))):
    view = os.path.basename(d.rstrip("/\\"))
    op = os.path.join(d, "objectid.png")  # ★ 必须是绝对路径：Blender 的 CWD 不是项目根
    if not os.path.isfile(op):
        continue
    st = BP.visible_object_id_stats(op)
    out[view] = st
print("DUMP_JSON " + json.dumps(out, ensure_ascii=False))
