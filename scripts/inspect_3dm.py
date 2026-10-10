#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读检视 .3dm：网格数、顶点/面数、包围盒、对象名样本。

用途（《材质真实感更新审核纠正》S0）：给用户一页对照，帮助选定**唯一的权威 .3dm**。
★ 本脚本**只读**：不改源文件、不写任何资产目录、不出图。
★ **不能凭「版本号最大」假定最正确** —— 要让用户看着网格数/包围盒/名字自己选。

★ 导入动作**复用 `blender_pass.import_model()`**，而不是在这里另写一份。
  `blender_pass.py` 里对 .3dm 的导入有一段非平凡的坑（Blender 4.2+ 扩展装在
  `bl_ext.user_default.import_3dm` 命名空间下、裸名 `import_3dm` 找不到；
  且必须用 `bpy.ops.preferences.addon_enable` 而不是 `addon_utils.enable`）。
  复制一份迟早会漂移，所以直接调它。

在 Blender 里跑：
    blender.exe -b -P scripts/inspect_3dm.py -- --model "<path.3dm>" --json
"""

import argparse
import json
import os
import sys

import bpy
from mathutils import Vector

# 让 `import blender_pass` 能找到同目录的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pass  # noqa: E402


def inspect(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    blender_pass.import_model(path)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    verts = sum(len(o.data.vertices) for o in meshes)
    faces = sum(len(o.data.polygons) for o in meshes)

    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for obj in meshes:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], world[i])
                hi[i] = max(hi[i], world[i])
    has_bbox = lo[0] != float("inf")
    size = [round(hi[i] - lo[i], 4) for i in range(3)] if has_bbox else None

    names = sorted(o.name for o in meshes)
    return {
        "path": path,
        "mesh_count": len(meshes),
        "vertex_count": verts,
        "face_count": faces,
        "bbox_min": [round(v, 4) for v in lo] if has_bbox else None,
        "bbox_max": [round(v, 4) for v in hi] if has_bbox else None,
        "bbox_size": size,
        "name_sample": names[:8],
        "name_has_mojibake": any("\ufffd" in n for n in names),
        "blender": bpy.app.version_string,
    }


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="inspect_3dm.py")
    ap.add_argument("--model", required=True)
    ap.add_argument("--json", action="store_true", help="输出单行 JSON（便于批量收集）")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.model):
        print("找不到文件: %s" % args.model, file=sys.stderr)
        sys.exit(2)
    try:
        info = inspect(args.model)
    except BaseException as exc:                  # SystemExit 也要兜住（import_model 会抛它）
        info = {"path": args.model, "error": "%s: %s" % (type(exc).__name__, exc)}
    if args.json:
        print("INSPECT_JSON " + json.dumps(info, ensure_ascii=False))
    else:
        print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
