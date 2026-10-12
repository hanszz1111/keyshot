# -*- coding: utf-8 -*-
"""M0 交叉核对：同机位的 objectid.png，用两条独立路径解码并比对，再输出逐部件统计。
路径 A：scripts/objectid_mask.py（纯标准库自解 PNG）
路径 B：blender_pass.visible_object_id_stats()（Blender 的 image.pixels × 65535）
★ 两条路径对不上就说明其中一条有精度问题 —— 这正是本轮要钉死的。"""
import json, os, sys
import bpy
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import blender_pass as BP
import objectid_mask as OM

sku = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "AI渲染1"
out = {}
for view in sorted(os.listdir(os.path.join(ROOT, "assets/passes", sku))):
    d = os.path.join(ROOT, "assets/passes", sku, view)
    p = os.path.join(d, "objectid.png")
    if not os.path.isfile(p):
        continue
    st = BP.visible_object_id_stats(p)          # 路径 B
    if st.get("status") != "ok":
        raise RuntimeError("%s: Blender 解码失败：%s" % (view, st.get("status")))
    width, height, ids = OM.read_ids(p)         # 路径 A：独立 PNG 解码
    unique, pixel_counts = np.unique(ids, return_counts=True)
    standard_counts = {str(int(part)): int(count) for part, count in zip(unique, pixel_counts)
                       if int(part) > 0}
    blender_counts = {str(key): int(value) for key, value in (st.get("counts") or {}).items()}
    if standard_counts != blender_counts:
        missing = sorted(set(standard_counts) ^ set(blender_counts))[:10]
        changed = sorted(k for k in set(standard_counts) & set(blender_counts)
                         if standard_counts[k] != blender_counts[k])[:10]
        raise RuntimeError("%s: 两路 ID 不一致；缺失/额外=%s，像素数不同=%s" %
                           (view, missing, changed))
    out[view] = {"status": "matched", "width": width, "height": height,
                 "visible_parts": len(standard_counts), "counts": standard_counts}
print("XC_JSON " + json.dumps(out, ensure_ascii=False))
