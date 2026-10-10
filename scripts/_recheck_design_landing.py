# -*- coding: utf-8 -*-
"""用 Blender 正确读 16 位 objectid，重查「设计语言写法」的变亮像素落在哪个部件。
★ 不能用 PIL：PIL 读 16-bit RGBA 会降成 8 位，id 会被压成桶值。"""
import json, os, sys
import bpy, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pass as BP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_rgb(p):
    img = bpy.data.images.load(p)
    img.colorspace_settings.name = "sRGB"
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(h, w, 4)[:, :, :3]

def load_ids(p):
    """★ 用与生产同一套反解（10 位精度足够；这里直接复用 stats）。"""
    st = BP.visible_object_id_stats(p)
    return st

out = {}
for view in ("front", "3q4_left"):
    oidp = os.path.join(ROOT, "assets/passes/AI渲染1", view, "objectid.png")
    cur = load_rgb(os.path.join(ROOT, "outputs/_AB实验/design8/G-current/%s_s43.png" % view))
    des = load_rgb(os.path.join(ROOT, "outputs/_AB实验/design8/G-design/%s_s43.png" % view))
    # 重新按输出尺寸读 id：把 objectid 缩放到输出尺寸后取 id
    img = bpy.data.images.load(oidp)
    img.colorspace_settings.name = "Non-Color"
    ow, oh = img.size
    ib = np.empty(ow * oh * 4, dtype=np.float32)
    img.pixels.foreach_get(ib)
    bpy.data.images.remove(img)
    ids = np.rint(ib.reshape(oh, ow, 4)[:, :, 0] * 65535.0).astype(np.int32)
    # 最近邻缩放到输出尺寸
    H, W = cur.shape[:2]
    ys = (np.arange(H) * oh / H).astype(int).clip(0, oh - 1)
    xs = (np.arange(W) * ow / W).astype(int).clip(0, ow - 1)
    ids_r = ids[np.ix_(ys, xs)]
    bright = (des.mean(axis=2) - cur.mean(axis=2)) > (30.0 / 255.0)   # ★ 像素是 0..1，阈值要除以 255
    tot = int(bright.sum())
    ids_b = ids_r[bright]
    u, c = np.unique(ids_b, return_counts=True)
    top = sorted(zip(u.tolist(), c.tolist()), key=lambda x: -x[1])[:6]
    out[view] = {"bright_px": tot, "bright_pct": tot / bright.size * 100,
                 "top_ids": top, "bg_pct": (c[0] / tot * 100) if len(u) and u[0] == 0 else 0.0}
print("RECHECK_JSON " + json.dumps(out, ensure_ascii=False))
