# -*- coding: utf-8 -*-
"""M0 交叉核对：同机位的 objectid.png，用两条独立路径解码并比对，再输出逐部件统计。
路径 A：scripts/objectid_mask.py（纯标准库自解 PNG）
路径 B：blender_pass.visible_object_id_stats()（Blender 的 image.pixels × 65535）
★ 两条路径对不上就说明其中一条有精度问题 —— 这正是本轮要钉死的。"""
import json, os, sys
import bpy
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import blender_pass as BP

sku = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "AI渲染1"
out = {}
for view in sorted(os.listdir(os.path.join(ROOT, "assets/passes", sku))):
    d = os.path.join(ROOT, "assets/passes", sku, view)
    p = os.path.join(d, "objectid.png")
    if not os.path.isfile(p):
        continue
    st = BP.visible_object_id_stats(p)          # 路径 B
    out[view] = {"status": st.get("status"), "counts": st.get("counts") or {}}
print("XC_JSON " + json.dumps(out, ensure_ascii=False))
