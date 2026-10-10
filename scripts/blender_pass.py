# -*- coding: utf-8 -*-
"""
AI 白模渲染器 · OPT-01  Blender 确定性基线 pass 渲染器
=========================================================
作用：把 3D 模型用**同一固定相机**渲染成一套结构 pass，直接落进投放区
      assets/passes/<SKU>/<机位>/，供 ComfyUI 做 ControlNet 锁形。

输出（默认全部产出）：
    clay.png      Beauty 成像（RGBA，白模本色，未加材质）  ← 投放区认的 clay 通道
    alpha.png     物体遮罩（单通道，用于抠图/合成）
    depth.exr     深度，32 位浮点相机空间（米）           ← 正规规格，ComfyUI 可读 EXR
    depth.png     深度，16 位灰阶（0=近 1=远，归一化）     ← 给控制台/预览用的降级件
    normal.exr    法线，16 位半浮点相机空间 [-1,1]        ← 正规规格
    normal.png    法线，8 位 RGB（+1..-1 → 0..255）        ← 降级件
    objectid.png  物体 ID 掩码（16 位）+ objectid_map.json 索引

用法（在 Windows 命令行 / 双击 出pass.bat）：
    blender.exe -b -P blender_pass.py -- \
        --model "D:\\...\\LS-360G.glb" --sku LS-360G --view front \
        --azimuth 0 --elevation 15 --width 1232 --height 752

自检（不需要任何模型，内置几何跑通全链路）：
    blender.exe -b -P blender_pass.py -- --self-test --out D:\\tmp\\passtest

支持导入：.blend .glb .gltf .obj .stl .fbx
          .3dm 需 Blender 扩展 import_3dm（Blender 4.2+ 装成 bl_ext.user_default.import_3dm）
          .stp/.step 优先用 STEPper 插件自带 OCC 内核直接读；插件缺失时
          由服务端先用 FreeCAD 转成缓存 STL 再送进来。
          .ksp/.c4d/.max/.rhi 仍需手动导出（KeyShot 导 GLB，C4D/Max 导 GLB/OBJ）。
"""
import argparse
import copy
import json
import math
import os
import sys

import bpy
import numpy as np
import mathutils

# ---------------------------------------------------------------- 常量

SUPPORTED = {".blend", ".glb", ".gltf", ".obj", ".stl", ".fbx", ".3dm",
             ".stp", ".step"}
NEED_CONVERT = {
    ".ksp": "KeyShot 工程 —— 请在 KeyShot 中 文件 → 导出 → glTF(.glb)",
    ".c4d": "Cinema 4D —— 请导出 .glb / .obj",
    ".max": "3ds Max —— 请导出 .glb / .obj",
    ".rhi": "Rhino 历史文件 —— 请导出 .glb / .obj",
}

# STEP/STP 直接由 Blender 侧导入：
#   首选 STEPper 插件（自带 OCC 内核，无需外部依赖）；
#   插件缺失时，服务端会先用 FreeCAD 转成缓存 STL 再送进来。
STEPPER_MODULES = ("STEPper",)
# Rhino .3dm 导入器的模块名。Blender 4.2+ 把扩展装到带命名空间的
# bl_ext.<repo>.<id> 下，所以扩展形式要排前面（实测裸名 import_3dm 找不到）。
THREEDM_MODULES = ("bl_ext.user_default.import_3dm", "import_3dm")

# ── 可见部件反解（S2）────────────────────────────────────────────────────────
# encoding_version 随「编码方式或判定规则改变」而递增；清单里记下它，
# 才能把「旧清单缺字段 / 版本不同」与「确实没有部件」区分开。
_VISIBLE_ENCODING_VERSION = 1
# 「出现过」与「足够大可做材质选区」的分界（真值像素数）。
# ★ 取保守小值：宁可放进细按钮/边缘件，也不要因为阈值过高把它们判成不可见。
#   在真实样张校准之前，这个值只用于提示，不作为拒绝依据。
_VISIBLE_MIN_EDITABLE_PIXELS = 24

# 机位别名（与 web/index.html 的机位词表保持一致）
VIEW_ALIAS = {
    "front": "front", "正面": "front", "正视图": "front", "前视": "front", "主视": "front",
    "3q4_left": "3q4_left", "左前": "3q4_left", "左45": "3q4_left",
    "3q4_right": "3q4_right", "右前": "3q4_right", "右45": "3q4_right",
    "side": "side", "侧面": "side", "侧视": "side",
    "top": "top", "俯视": "top", "顶视": "top",
    "detail_keypad": "detail_keypad", "按键": "detail_keypad", "面板": "detail_keypad",
    "detail_window": "detail_window", "透明件": "detail_window", "视窗": "detail_window",
}

# 机位 → (方位角, 仰角)。az 0=正前方，正值向右绕；el 正值从上往下看。
# ⚠️ 2026-09-27 修复：此前 --azimuth/--elevation 有默认值 (0, 12)，而 web/server.py
#    只传 --view 不传角度 → 五个机位全部用同一组 (0,12) 取景，出图角度完全雷同，
#    "front" 实际是仰视端面、"3q4_*" 完全没绕角。现改为按机位查表。
VIEW_ANGLES = {
    "front":         (0.0,    8.0),
    "back":          (180.0,  8.0),
    "3q4_left":      (-45.0, 15.0),
    "3q4_right":     (45.0,  15.0),
    "side":          (90.0,   8.0),     # 右侧（历史沿用，不要改）
    "side_left":     (-90.0,  8.0),     # 左侧
    "top":           (0.0,   90.0),
    "bottom":        (0.0,  -90.0),     # 真正的正仰视，强制正交投影
    "detail_keypad": (-30.0, 35.0),
    "detail_window": (30.0,  30.0),
}

# 6 视图（正交六面）—— 网页「6 视图」按钮与 3D 预览共用同一套角度，
# 保证「3D 里看到的」与「出结构图拿到的」是同一个机位。
SIX_VIEWS = ("front", "back", "side", "side_left", "top", "bottom")


def log(msg):
    print("[pass] " + str(msg), flush=True)


# ---------------------------------------------------------------- 参数

def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser(prog="blender_pass.py", add_help=True)
    ap.add_argument("--model", help="3D 模型路径（.blend/.glb/.gltf/.obj/.stl/.fbx/.3dm）")
    ap.add_argument("--sku", default="TEST", help="SKU，用于落盘目录名")
    ap.add_argument("--view", default="front", help="机位名（中文别名会自动归一）")
    ap.add_argument("--out", default=None,
                    help="输出根目录；默认落到项目的 assets/passes/")
    ap.add_argument("--azimuth", type=float, default=None,
                    help="方位角（度）。0=正前方，正值向右绕。默认按 --view 查表")
    ap.add_argument("--elevation", type=float, default=None,
                    help="仰角（度）。正值从上往下看。默认按 --view 查表")
    ap.add_argument("--width", type=int, default=1232)
    ap.add_argument("--height", type=int, default=752)
    ap.add_argument("--fit", type=float, default=1.18, help="取景余量，1.0=紧贴")
    ap.add_argument("--ortho", action="store_true", help="使用正交相机（工业图更常见）")
    ap.add_argument("--samples", type=int, default=64, help="Cycles 采样数")
    ap.add_argument("--no-gpu", action="store_true", help="强制 CPU 渲染")
    ap.add_argument("--no-denorm", action="store_true", help="仅为旧命令兼容；控制图始终规范化，原始米值保留在 depth.exr")
    ap.add_argument("--self-test", action="store_true",
                    help="不导入模型，用内置几何自检整条 pass 链路")
    ap.add_argument("--probe", action="store_true",
                    help="只导入并报告模型信息（包围盒/物体数/尺度），不渲染")
    ap.add_argument("--thumb", default=None, metavar="PATH",
                    help="只渲染一张缩略图到该路径，不产 pass。"
                         "复用与正式结构图相同的相机方位、取景算法与轴向，"
                         "所以缩略图里看得见的部位，正式机位一定也在画面内。")
    ap.add_argument("--export-glb", default=None, metavar="PATH",
                    help="顺带把导入后的模型导出为 GLB，供网页 3D 预览使用。"
                         "只导出几何（不含相机/灯光），源文件不被修改。"
                         "网页只读这个已验证的 GLB，不直接读原始 STEP/3DM。")
    ap.add_argument("--product-render", metavar="PATH",
                    help="按 CMF 方案真渲染一张独立产品底图；不修改已有结构 pass")
    ap.add_argument("--product-batch", metavar="JSON",
                    help="按同一导入模型、CMF 与灯光批量渲染多个机位；JSON 含 views 列表")
    ap.add_argument("--cmf-scheme", help="跨机位 CMF 方案 JSON，网格名必须与导入模型一致")
    ap.add_argument("--cmf-presets", help="项目统一 CMF 预设 JSON")
    ap.add_argument("--body-cmf", help="未单独指定部件时使用的预设 ID")
    ap.add_argument("--body-color", help="未单独指定部件时的 #RRGGBB 颜色")
    ap.add_argument("--background-color", default="#F3F5F6", help="产品底图的纯净背景色")
    return ap.parse_args(argv)


# ---------------------------------------------------------------- 场景准备

def reset_scene():
    """清空场景里的数据块，但**不重置用户偏好**。

    不能用 bpy.ops.wm.read_factory_settings —— 它会把已启用的插件一并卸载，
    而 STEPper 重新启用的时机若晚于清场，它的 Scene PointerProperty
    （scene.stepper）就挂不上，后续导入会 KeyError。这里手工删数据块即可。
    """
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)


def _enable_addon(name):
    """启用插件，返回是否真的可用。

    ★ 必须用 bpy.ops.preferences.addon_enable，不能用 addon_utils.enable。
    两者差别很大：addon_utils.enable 在 --background 下会因为
    bpy.context.preferences.addons 尚未就绪而抛 KeyError，插件类虽然注册了，
    但 Scene 上的 PointerProperty（如 STEPper 的 scene.stepper）没挂上，
    随后算子内部取该属性就崩。用 bpy.ops 走正常启用路径才拿得到完整上下文。
    """
    if _addon_active(name):
        return True
    try:
        bpy.ops.preferences.addon_enable(module=name)
    except Exception as exc:
        log(f"  启用 {name} 失败：{exc}")
        return False
    return _addon_active(name)


def _addon_active(name):
    """插件是否已启用（兼容 Blender 4.2+ 扩展命名空间 bl_ext.*）。"""
    prefs = bpy.context.preferences.addons
    for key in (name, f"bl_ext.user_default.{name}", f"bl_ext.blender_org.{name}"):
        if key in prefs:
            return True
    return False


def _enable_first(addon_names):
    """按顺序尝试启用插件，返回真正启用成功的模块名；都失败返回 None。"""
    for name in addon_names:
        if _enable_addon(name):
            return name
    return None


def _import_stepper(path):
    """用 STEPper 直接读 .stp/.step（插件自带 OCC 内核，不依赖 FreeCAD）。

    注意：STEPper 的 filepath 只被当作所在目录，真正的目标文件必须走
    override_file 传完整路径，否则报「未选择任何STEP文件」。
    """
    mod = _enable_first(STEPPER_MODULES)
    if not mod:
        raise SystemExit(
            "[pass] STEP/STP 需要 Blender 的 STEPper 插件（或在服务端配置 FreeCAD）。"
            "请在 Blender 中安装并启用 STEPper 后重试。")
    if not hasattr(bpy.ops.import_scene, "occ_import_step"):
        raise SystemExit("[pass] STEPper 已装但未注册 occ_import_step 算子，请重启 Blender 后再试。")
    try:
        bpy.ops.import_scene.occ_import_step(
            filepath=path, override_file=path,
            lin_deflection=0.8, ang_deflection=0.5, hierarchy_types="FLAT")
    except Exception as exc:
        raise SystemExit(f"[pass] STEP 导入失败：{exc}") from exc
    if not any(ob.type == "MESH" for ob in bpy.data.objects):
        raise SystemExit("[pass] STEP 文件里没有可渲染的网格（可能只含曲线或曲面未生成网格）。")


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    if not os.path.isfile(path):
        raise SystemExit(f"[pass] 找不到模型文件：{path}")
    if ext in NEED_CONVERT:
        raise SystemExit(f"[pass] 不支持的格式 {ext}：{NEED_CONVERT[ext]}")
    if ext not in SUPPORTED:
        raise SystemExit(f"[pass] 不支持的格式 {ext}；支持：{sorted(SUPPORTED)}")

    log(f"导入模型 {os.path.basename(path)}")
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".stp", ".step"):
        _import_stepper(path)
    elif ext == ".3dm":
        mod = _enable_first(THREEDM_MODULES)
        if not mod:
            raise SystemExit(
                "[pass] Rhino .3dm 导入失败：请在 Blender 中安装并启用 "
                "jesterKing/import_3dm 扩展及其 rhino3dm 依赖；"
                "或先在 Rhino 里导出 GLB/OBJ 再导入。")
        try:
            bpy.ops.import_3dm.some_data(filepath=path)
        except Exception as exc:
            raise SystemExit(f"[pass] Rhino .3dm 导入失败（{mod}）：{exc}") from exc
        if not any(ob.type == "MESH" for ob in bpy.data.objects):
            raise SystemExit("[pass] .3dm 中没有可渲染网格。请在 Rhino 先生成渲染网格，或导出 GLB/OBJ。")


def _export_glb(dest):
    """把当前场景的网格导出成 GLB，给网页 3D 预览用。

    只导几何：**显式关掉相机与灯光**，否则预览里会凭空多出一盏灯和一个相机。
    导出的是「导入后」的网格（STEP/3DM 此时已三角化），源文件不受任何影响。
    网页只读这个已验证的 GLB —— 原始 STEP/3DM 不直接喂浏览器。
    """
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part.glb"
    try:
        bpy.ops.export_scene.gltf(
            filepath=tmp, export_format="GLB",
            export_apply=True,          # 应用修改器
            export_yup=True,            # 网页 3D 通用约定：Y 轴向上
            export_cameras=False,
            export_lights=False,
            use_selection=False)
        if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, dest)       # 原子发布，前端不会读到半个文件
            log(f"  ✅ 预览模型 {os.path.getsize(dest):,} B")
        else:
            log("  ⚠️ 预览模型未产出")
    except Exception as exc:
        log(f"  ⚠️ 预览模型导出失败：{exc}")
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def build_self_test():
    """内置几何：一个底盘 + 一个圆柱旋钮，足够验证 pass 链路。"""
    log("自检模式：生成内置几何")
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0.5))
    bpy.context.active_object.name = "Body"
    bpy.ops.object.transform_apply(scale=True)
    bpy.context.active_object.scale = (0.75, 0.45, 0.30)
    bpy.ops.object.transform_apply(scale=True)

    bpy.ops.mesh.primitive_cylinder_add(radius=0.22, depth=0.30, location=(0, 0, 1.05))
    bpy.context.active_object.name = "Knob"

    bpy.ops.mesh.primitive_cylinder_add(radius=0.09, depth=0.16,
                                        location=(0.45, 0.0, 0.85), rotation=(math.pi / 2, 0, 0))
    bpy.context.active_object.name = "Boss"


def model_bounds():
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    found = False
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        found = True
        for corner in ob.bound_box:
            w = ob.matrix_world @ mathutils.Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    if not found:
        raise SystemExit("[pass] 场景里没有网格物体")
    center = mathutils.Vector([(lo[i] + hi[i]) / 2.0 for i in range(3)])
    size = mathutils.Vector([hi[i] - lo[i] for i in range(3)])
    return center, size


def setup_camera(args, center, size):
    cam_data = bpy.data.cameras.new("PassCam")
    cam_data.lens = 85.0          # 长焦压缩透视，接近电商图
    cam_data.clip_start = 0.001
    cam = bpy.data.objects.new("PassCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)

    az = math.radians(args.azimuth)
    el = math.radians(args.elevation)
    direction = mathutils.Vector((
        math.sin(az) * math.cos(el),
        -math.cos(az) * math.cos(el),
        math.sin(el),
    )).normalized()

    # ---- 按「当前视角下的实际投影范围」取景（不能只用包围盒对角线，否则正视图会很小）----
    # Blender 约定：相机局部 -Z 指向视线方向，局部 Y 尽量对齐世界 +Z
    zc = -direction
    yc = (mathutils.Vector((0.0, 0.0, 1.0)) - zc * zc.z)
    if yc.length < 1e-8:
        yc = mathutils.Vector((0.0, 1.0, 0.0))
    yc.normalize()
    xc = yc.cross(zc).normalized()

    half = size * 0.5
    hw = hu = 0.0
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                v = mathutils.Vector((sx * half.x, sy * half.y, sz * half.z))
                hw = max(hw, abs(v.dot(xc)))
                hu = max(hu, abs(v.dot(yc)))
    hw = max(hw, 1e-6)
    hu = max(hu, 1e-6)

    aspect = args.width / float(args.height)
    if args.ortho:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = 2.0 * max(hw, hu * aspect) * args.fit
        dist = max(size.length * 2.0, 1.0)
    else:
        cam_data.sensor_fit = "AUTO"
        fov_h = 2.0 * math.atan((cam_data.sensor_width / 2.0) / cam_data.lens)
        fov_v = 2.0 * math.atan((cam_data.sensor_width / (2.0 * aspect)) / cam_data.lens)
        # 透视取景必须逐个包围盒角点计入「靠近镜头」的深度；只按中心平面
        # 的投影宽高求距离，会让长机身/3/4 机位的前端越过画框。
        dist = 0.0
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    v = mathutils.Vector((sx * half.x, sy * half.y, sz * half.z))
                    needed = max(abs(v.dot(xc)) / math.tan(fov_h / 2.0),
                                 abs(v.dot(yc)) / math.tan(fov_v / 2.0))
                    dist = max(dist, v.dot(direction) + needed * args.fit)
        dist = max(dist, size.length * 0.5)

    cam.location = center + direction * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

    scene = bpy.context.scene
    scene.camera = cam
    log(f"相机：az={args.azimuth}° el={args.elevation}° "
        f"{'正交' if args.ortho else '透视 85mm'}｜投影范围 横{hw*2:.1f} 纵{hu*2:.1f}"
        f"｜距中心 {dist:.1f}")
    return cam


def setup_world():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("PassWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.16, 0.16, 0.16, 1.0)   # 中性灰环境，白模成像关键
        bg.inputs[1].default_value = 1.0


def setup_lights(center, radius):
    """三点影棚灯：让 clay 成像是"灰模"而不是纯剪影。
    结构 pass（depth/normal/objectid）不受灯光影响，这一步只为 beauty/clay 服务。"""
    def add_area(name, direction, watt, size_factor):
        d = bpy.data.lights.new(name, type="AREA")
        d.energy = watt * max(radius * radius, 0.05)
        d.size = size_factor * max(radius, 0.2)
        ob = bpy.data.objects.new(name, d)
        bpy.context.scene.collection.objects.link(ob)
        loc = center + mathutils.Vector(direction).normalized() * (radius * 3.0)
        ob.location = loc
        ob.rotation_euler = (center - loc).to_track_quat("-Z", "Y").to_euler()
        return ob

    add_area("Key",  (-1.2, -1.6, 1.5), 26.0, 1.4)    # 主光：左上前
    add_area("Fill", (1.7, -1.1, 0.35), 9.0, 1.8)     # 辅光：右前（压阴影）
    add_area("Rim",  (0.5, 1.9, 1.2), 16.0, 1.0)      # 轮廓光：后上
    log("已布置三点影棚灯（Key/Fill/Rim）")


def assign_pass_index():
    """给每个网格物体分配 pass_index，供 objectid.png 使用。"""
    mapping = {}
    idx = 1
    for ob in sorted([o for o in bpy.data.objects if o.type == "MESH"], key=lambda o: o.name):
        ob.pass_index = idx
        mapping[str(idx)] = ob.name
        idx += 1
    return mapping


def _linear_rgb(value):
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ValueError("CMF 颜色必须是 #RRGGBB")
    channels = [int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                 for c in channels)


# ── 材质表面纹理（P1）───────────────────────────────────────────────────────
# 背景：`config/cmf_presets.json` 早就写了 texture.kind / scale / direction 与工艺说明，
# 但 `apply_product_cmf()` 只把颜色、金属度、粗糙度（透明件另加透射）接到 Principled BSDF
# —— 也就是说**细砂纹、颗粒橡胶、定向拉丝这些元数据从来没有变成可见的表面纹理**。
# 结果：不同工艺只靠粗糙度区分，塑料和橡胶可能共享同一高光，金属也不会出现方向性反光。
#
# 设计要点：
#  ★ **纹理坐标必须用 Object（或 UV），不能用 Generated/Window** ——
#    后者会随相机与取景变化，导致同一部件在不同机位纹理尺度/方向不一致（"纹理游走"）。
#  ★ 幅度刻意做小：微纹理是"让高光产生变化"，不是"画图案"。
#    过强会在倒角/分模线上生成原模型不存在的视觉线条。
#  ★ 只改材质节点，**不新增几何**。
_TEX_SCALE = {"fine": 240.0, "medium": 90.0}   # 物体空间的基础频率
_TEX_BUMP = {"fine_grain": 0.05, "sandblast": 0.09, "satin": 0.03,
             "brushed": 0.10, "pebbled": 0.22, "leather_grain": 0.26,
             "wood_grain": 0.14, "woven": 0.16}
_TEX_ANISO = {"brushed": 0.85, "satin": 0.35}


def _apply_surface_texture(mat, bsdf, preset):
    """把 texture.kind/scale/direction 落成程序纹理 → Bump（+ 金属各向异性）。

    返回一段可写进日志与事实卡的描述；`smooth`/`none` 返回 None（不建任何节点）。
    """
    tex = preset.get("texture") or {}
    kind = str(tex.get("kind") or "smooth")
    scale = str(tex.get("scale") or "none")
    direction = str(tex.get("direction") or "isotropic")
    if kind == "smooth" or scale == "none" or kind not in _TEX_BUMP:
        return None

    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    base = _TEX_SCALE.get(scale, 160.0)

    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-1100, 0)
    source = coord.outputs["Object"]          # ★ 固定在模型上，不随相机移动

    if kind == "brushed":
        node = nodes.new("ShaderNodeTexWave")
        node.wave_type = "BANDS"
        # 纵向拉丝：把条纹沿物体 X 轴排布，体现方向性
        node.bands_direction = {"longitudinal": "X", "woven": "Y"}.get(direction, "Z")
        node.inputs["Scale"].default_value = base * 0.06
        node.inputs["Distortion"].default_value = 0.0
        node.inputs["Detail"].default_value = 2.0
    elif kind in ("pebbled", "leather_grain"):
        node = nodes.new("ShaderNodeTexVoronoi")
        node.feature = "F1"
        node.distance = "EUCLIDEAN"
        node.inputs["Scale"].default_value = base * (0.7 if kind == "leather_grain" else 0.5)
        node.inputs["Randomness"].default_value = 0.9
    elif kind == "woven":
        node = nodes.new("ShaderNodeTexWave")
        node.wave_type = "BANDS"
        node.bands_direction = "X"
        node.inputs["Scale"].default_value = base * 0.25
        node.inputs["Distortion"].default_value = 1.5
    elif kind == "wood_grain":
        node = nodes.new("ShaderNodeTexWave")
        node.wave_type = "RINGS"
        node.inputs["Scale"].default_value = base * 0.15
        node.inputs["Distortion"].default_value = 6.0
        node.inputs["Detail"].default_value = 3.0
    else:                                     # fine_grain / sandblast / satin
        node = nodes.new("ShaderNodeTexNoise")
        node.inputs["Scale"].default_value = base * (1.8 if kind == "sandblast" else 1.0)
        node.inputs["Detail"].default_value = 10.0 if kind == "sandblast" else 8.0
        node.inputs["Roughness"].default_value = 0.5
    node.location = (-850, 0)
    links.new(source, node.inputs["Vector"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (-450, -200)
    bump.inputs["Strength"].default_value = _TEX_BUMP[kind]
    bump.inputs["Distance"].default_value = 0.004 if scale == "fine" else 0.012
    links.new(node.outputs["Fac"] if "Fac" in node.outputs else node.outputs["Color"],
              bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    aniso = _TEX_ANISO.get(kind)
    if aniso is not None and "Anisotropic" in bsdf.inputs:
        bsdf.inputs["Anisotropic"].default_value = aniso
    return "%s/%s/%s bump=%.2f%s" % (kind, scale, direction, _TEX_BUMP[kind],
                                     (" 各向异性=%.2f" % aniso) if aniso else "")


def apply_product_cmf(args):
    """按稳定网格名赋 Principled BSDF；不猜缺失部件，也不改变源文件。"""
    if not all((args.cmf_scheme, args.cmf_presets, args.body_cmf, args.body_color)):
        raise ValueError("产品底图缺少 CMF 方案、预设或主体材质/颜色")
    if os.path.isfile(args.cmf_scheme):
        with open(args.cmf_scheme, "r", encoding="utf-8") as stream:
            scheme = json.load(stream)
    else:
        scheme = {"assignments": {}}
    with open(args.cmf_presets, "r", encoding="utf-8") as stream:
        presets = {p["id"]: p for p in json.load(stream)["presets"]}
    assignments = scheme.get("assignments") or {}
    meshes = {obj.name: obj for obj in bpy.data.objects if obj.type == "MESH"}
    missing = set(assignments) - set(meshes)
    if missing:
        raise ValueError("CMF 方案里有 %d 个网格在本次导入中不存在" % len(missing))
    material_cache = {}
    textured = {}          # key=(预设,颜色) -> 表面纹理描述，写进日志便于审计
    for name, obj in meshes.items():
        assigned = assignments.get(name) or {}
        preset_id = assigned.get("cmf") or args.body_cmf
        preset = presets.get(preset_id)
        if preset is None:
            raise ValueError("未知 CMF 预设：%s" % preset_id)
        color = assigned.get("color") or args.body_color
        key = (preset_id, color.upper())
        mat = material_cache.get(key)
        if mat is None:
            mat = bpy.data.materials.new("CMF_%s_%s" % (preset_id, color[1:]))
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            nodes.clear()
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Base Color"].default_value = (*_linear_rgb(color), 1.0)
            bsdf.inputs["Metallic"].default_value = max(0.0, min(1.0, float(preset["metalness"])))
            bsdf.inputs["Roughness"].default_value = max(0.02, min(1.0, float(preset["roughness"])))
            if preset_id == "glass_clear":
                transmission = bsdf.inputs.get("Transmission Weight") or bsdf.inputs.get("Transmission")
                if transmission:
                    transmission.default_value = 1.0
            # P1：把 texture.kind/scale/direction 落成可见的表面纹理
            surface_desc = _apply_surface_texture(mat, bsdf, preset)
            if surface_desc:
                textured[key] = surface_desc
            output = nodes.new("ShaderNodeOutputMaterial")
            mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
            mat.diffuse_color = (*_linear_rgb(color), 1.0)
            material_cache[key] = mat
        if obj.data.users > 1:
            obj.data = obj.data.copy()  # 共享 Mesh 不能让一个部件的材质覆盖其他实例
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    log("CMF 真材质：%d 网格 / %d 种 Principled 材质 / %d 个指定部件 / %d 种带表面纹理" %
        (len(meshes), len(material_cache), len(assignments), len(textured)))
    for _key, _desc in sorted(textured.items()):
        log("  表面纹理 %s：%s" % (_key[0], _desc))


def render_product_base(args, center, size, prepared=False):
    """与结构图共用模型、机位、取景；透明渲染后合成统一背景。"""
    if not prepared:
        apply_product_cmf(args)
        setup_world()
        setup_lights(center, max(size.length / 2.0, 1e-3))
    if bpy.context.scene.camera:
        bpy.data.objects.remove(bpy.context.scene.camera, do_unlink=True)
    setup_camera(args, center, size)
    setup_render(args)
    scene = bpy.context.scene
    scene.render.film_transparent = True
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layer = tree.nodes.new("CompositorNodeRLayers")
    background = tree.nodes.new("CompositorNodeRGB")
    background.outputs[0].default_value = (*_linear_rgb(args.background_color), 1.0)
    over = tree.nodes.new("CompositorNodeAlphaOver")
    composite = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(background.outputs[0], over.inputs[1])
    tree.links.new(layer.outputs["Image"], over.inputs[2])
    tree.links.new(over.outputs[0], composite.inputs[0])
    dest = os.path.abspath(args.product_render)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    scene.render.filepath = dest
    bpy.ops.render.render(write_still=True)
    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        raise RuntimeError("产品底图未产出")
    log("产品底图：%s（%d B）" % (dest, os.path.getsize(dest)))


def render_product_batch(args, center, size):
    with open(args.product_batch, "r", encoding="utf-8") as stream:
        batch = json.load(stream)
    views = batch.get("views")
    if not isinstance(views, list) or not 1 <= len(views) <= 10:
        raise ValueError("产品底图批次必须包含 1–10 个机位")
    seen = set()
    for item in views:
        view = item.get("view") if isinstance(item, dict) else None
        if view not in VIEW_ANGLES or view in seen:
            raise ValueError("产品底图批次含无效或重复机位")
        seen.add(view)
        resolution = item.get("resolution")
        camera = item.get("camera")
        if (not isinstance(resolution, list) or len(resolution) != 2 or
                any(not isinstance(v, int) or not 256 <= v <= 4096 for v in resolution) or
                not isinstance(camera, dict) or
                any(not isinstance(camera.get(k), (int, float)) for k in ("azimuth", "elevation")) or
                not isinstance(item.get("output"), str) or not item["output"].endswith(".png")):
            raise ValueError("产品底图批次相机、尺寸或输出路径无效")
    for index, item in enumerate(views):
        shot = copy.copy(args)
        shot.view = item["view"]
        shot.azimuth = float(item["camera"]["azimuth"])
        shot.elevation = float(item["camera"]["elevation"])
        shot.fit = float(item["camera"].get("fit", args.fit))
        shot.ortho = bool(item["camera"].get("ortho"))
        shot.width, shot.height = item["resolution"]
        shot.product_render = item["output"]
        log("产品底图批次 %d/%d：%s" % (index + 1, len(views), shot.view))
        render_product_base(shot, center, size, prepared=index > 0)
        if isinstance(batch.get("progress"), str):
            progress = batch["progress"]
            with open(progress + ".tmp", "w", encoding="utf-8") as stream:
                json.dump({"completed": index + 1, "view": shot.view}, stream)
            os.replace(progress + ".tmp", progress)


def setup_render(args):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    if not args.no_gpu:
        try:
            prefs = bpy.context.preferences.addons.get("cycles")
            if prefs:
                prefs.preferences.compute_device_type = "OPTIX"
            scene.cycles.device = "GPU"
            log("渲染后端：Cycles / GPU")
        except Exception as e:
            scene.cycles.device = "CPU"
            log(f"GPU 不可用，回落 CPU（{e}）")
    else:
        scene.cycles.device = "CPU"
        log("渲染后端：Cycles / CPU")

    r = scene.render
    r.resolution_x = args.width
    r.resolution_y = args.height
    r.resolution_percentage = 100
    r.film_transparent = True                 # 让 beauty 带 alpha
    r.image_settings.color_mode = "RGBA"
    r.image_settings.file_format = "PNG"

    # 色彩管理：beauty 用 Standard，避免 Filmic/AgX 改动观感
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except Exception:
        pass


def enable_passes():
    vl = bpy.context.view_layer
    vl.use_pass_combined = True
    vl.use_pass_z = True
    vl.use_pass_normal = True
    vl.use_pass_object_index = True
    log("已启用 pass：Combined / Z(Depth) / Normal / ObjectIndex")


def get_node_tree():
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = getattr(scene, "node_tree", None)
    if tree is None:
        tree = getattr(scene, "compositing_node_group", None)
    if tree is None:
        raise SystemExit("[pass] 无法获取合成节点树")
    return tree


def add_file_output(tree, base, slots, fmt, color_depth, name):
    """一个 File Output 节点只支持一种格式，所以按格式分节点。

    ★ 顺手把**每个 slot 的 format** 也显式设一遍。
    Blender 4.x 的 `CompositorNodeOutputFile` 给每个 `file_slots[i]` 都带了一份独立的
    `format`；明写出来更稳（节点级那份有时被当成模板/回退）。
    ⚠️ **更正**：我曾据此以为"节点级设置没生效、产出全是 8 位"——**那是误判**。
    实测（读 IHDR）本机产出**本来就是 16 位**；之所以看着像 8 位，是因为
    **PIL 读 16 位 RGBA 时会静默降成 8 位**。所以这不是 bug，只是把隐含行为写明。
    """
    node = tree.nodes.new("CompositorNodeOutputFile")
    node.name = name
    node.label = name
    node.base_path = base
    node.format.file_format = fmt
    if color_depth:
        try:
            node.format.color_depth = color_depth     # 节点级：保留，作为模板
        except Exception:
            pass

    # 第 0 个槽位是节点自带的，改名字即可；之后的新增
    first = slots[0]
    node.file_slots[0].path = first[0]
    for slot_name, _ in slots[1:]:
        try:
            node.file_slots.new(slot_name)
        except Exception:
            node.file_slots.new()
        node.file_slots[-1].path = slot_name

    # ★ 真正决定写盘位深的是 slot 级 format —— 逐个设一遍。
    for slot in node.file_slots:
        try:
            slot.format.file_format = fmt
            if color_depth:
                slot.format.color_depth = color_depth
        except Exception as exc:
            log(f"警告：设置 {name} 槽位 {slot.path} 的输出格式失败：{exc}")
    return node


def setup_compositor(outdir, do_demorm=True):
    """输出到临时目录，随后由 Python 改名到目标（File Output 会自动加帧号后缀）。"""
    tree = get_node_tree()
    tree.nodes.clear()

    rl = tree.nodes.new("CompositorNodeRLayers")
    rl.location = (-400, 0)

    # 各 socket → 目标文件名
    # beauty/alpha/objectid 用 PNG；depth/normal 用 EXR（保留范围）
    png_node = add_file_output(
        tree, outdir,
        [("clay", "Image"), ("alpha", "Alpha"), ("objectid", "IndexOB")],
        "PNG", "16", "png_out")
    exr_node = add_file_output(
        tree, outdir,
        [("depth", "Depth"), ("normal", "Normal")],
        "OPEN_EXR", "32", "exr_out")

    for node, sockets in ((png_node, ["Image", "Alpha", None]),
                          (exr_node, ["Depth", "Normal"])):
        for i, s in enumerate(sockets):
            if s is None:
                continue          # objectid 单独接（见下），这里跳过
            src = rl.outputs.get(s)
            if src is None:
                log(f"警告：Render Layers 没有 {s} 输出，跳过")
                continue
            tree.links.new(src, node.inputs[i])

    # ★ objectid 必须先除以 65535 再输出：
    #   IndexOB 给的是**原始 ID 数值**（1.0, 2.0, … 2530.0），
    #   而 PNG 16 位只能表示 0–1，直连会把所有 ID **饱和成 65535** ——
    #   实测产物只剩 0 / 65535 两个值，等于 ID 信息全丢，只是一张前景掩膜。
    #   压到 0–1 存下来，读取时再乘回 65535 即可还原真实部件号。
    id_src = rl.outputs.get("IndexOB")
    if id_src is None:
        log("警告：Render Layers 没有 IndexOB 输出，objectid 无法生成")
    else:
        id_scale = tree.nodes.new("CompositorNodeMath")
        id_scale.operation = "DIVIDE"
        id_scale.inputs[1].default_value = 65535.0
        id_scale.location = (-150, -250)
        id_scale.label = "ID/65535"
        tree.links.new(id_src, id_scale.inputs[0])
        tree.links.new(id_scale.outputs[0], png_node.inputs[2])

    return tree


def visible_object_id_stats(png_path, min_editable=_VISIBLE_MIN_EDITABLE_PIXELS):
    """从已写出的 objectid.png 反解「本机位**实际可见**的部件号」及每个的真值像素数。

    ★ 为什么需要它：`objectid_map` 覆盖的是**整个网格列表**（本项目 2530 项），
      而一个机位只渲染得到其中少数几个。于是「方案把材质分配给了一个在本机位
      根本不出现的部件」这种情况，**只校验名字是发现不了的** ——
      实测 `AI渲染1` 的 4 个分配部件在 10 个机位里全部不可见，而校验一路放行、
      出图时分区静默失效。

    ★ 三个关键的实现要求（《材质真实感更新审核纠正》S2）：

    1. **必须全像素扫描，不能抽样。** 早先的 `step=2` 版本会**漏掉只落在奇数行/列的
       细部件**（细按钮、边缘件）。而且抽样并不省内存 —— `list(img.pixels)` 已经把整图
       读进来了。这里改用 `foreach_get` 直读进 numpy 连续数组，**既省内存又不漏检**。
    2. **读取失败必须返回明确状态，不能返回 `[]`。** 把"解码失败"和"确实没有前景"
       混为一谈，会让失败被当成正常，静默放行。
       `status` 取 `ok` / `no_foreground` / `read_failed`；`[]` 只属于 `no_foreground`，
       而那种 pass 本身应当判为失败。
    3. **"出现过"与"足够大可做材质选区"要分开。** 一个噪声像素也能算"出现"，
       但不能拿它做选区。`counts` 记真实计数，`editable_ids` 按 `min_editable` 过滤；
       阈值取保守小值，避免把细按钮/边缘件排除掉。

    存储时 ID 被除以 65535 压进 16 位 PNG（见上方注释），所以读回乘 65535 还原。
    """
    stats = {"encoding_version": _VISIBLE_ENCODING_VERSION, "status": "read_failed",
             "total_pixels": 0, "foreground_pixels": 0, "counts": {},
             "min_editable_pixels": int(min_editable), "editable_ids": [], "message": ""}
    img = None
    try:
        img = bpy.data.images.load(png_path)
        img.colorspace_settings.name = "Non-Color"
        width, height = img.size
        if width <= 0 or height <= 0:
            stats["message"] = "图像尺寸无效：%sx%s" % (width, height)
            return stats
        buf = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)                     # ★ 直读进连续数组，不建 Python 浮点列表
        ids = np.rint(buf[0::4] * 65535.0).astype(np.int32)
        stats["total_pixels"] = int(ids.size)
        foreground = ids[ids > 0]
        stats["foreground_pixels"] = int(foreground.size)
        if foreground.size == 0:
            stats["status"] = "no_foreground"
            stats["message"] = "该机位 objectid 图没有非零像素（前景为空，pass 应判失败）"
            return stats
        uniq, counts = np.unique(foreground, return_counts=True)
        stats["counts"] = {int(k): int(v) for k, v in zip(uniq.tolist(), counts.tolist())}
        stats["editable_ids"] = sorted(int(k) for k, v in zip(uniq.tolist(), counts.tolist())
                                       if v >= int(min_editable))
        stats["status"] = "ok"
        return stats
    except Exception as exc:
        stats["message"] = "%s: %s" % (type(exc).__name__, exc)
        return stats
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)             # ★ 放 finally：异常时也别把图像留在会话里
            except Exception:
                pass


def visible_object_ids(png_path):
    """兼容入口：返回排序后的可见部件号；**读取失败返回 None（而不是 `[]`）**。

    `[]` 只会在 `status == "no_foreground"`（确实没有前景）时出现，
    调用方应把这种情况与 `None` 区别对待。
    """
    stats = visible_object_id_stats(png_path)
    if stats["status"] == "read_failed":
        log("警告：无法反解 objectid 可见部件号：%s" % stats["message"])
        return None
    return sorted(stats["counts"])


def normal_to_png(exr_path, png_path):
    """把 EXR 法线降级成 8 位 PNG（用于预览/控制台）。"""
    try:
        img = bpy.data.images.load(exr_path)
        img.colorspace_settings.name = "Non-Color"
        w, h = img.size
        px = list(img.pixels)              # RGBA float
        out = bpy.data.images.new("normal_png", w, h, alpha=False)
        out.colorspace_settings.name = "Non-Color"
        buf = [0.0] * (w * h * 4)
        for i in range(w * h):
            for c in range(3):
                v = px[i * 4 + c]
                v = max(0.0, min(1.0, v * 0.5 + 0.5))
                buf[i * 4 + c] = v
            buf[i * 4 + 3] = 1.0
        out.pixels = buf
        out.file_format = "PNG"
        out.save_render(png_path)
        bpy.data.images.remove(img)
        bpy.data.images.remove(out)
        return True
    except Exception as e:
        log(f"法线降级 PNG 失败（不影响 EXR）：{e}")
        return False


def find_written(outdir, stem):
    """File Output 会写成 stem0001.exr / stem0001.png 这种，找回真实路径。"""
    names = sorted(os.listdir(outdir))
    for n in names:
        low = n.lower()
        if low.startswith(stem.lower()) and ("." in low):
            return os.path.join(outdir, n)
    return None


# ---------------------------------------------------------------- 主流程

def main():
    args = parse_args()

    if not args.self_test and not args.model:
        raise SystemExit("[pass] 必须给 --model，或用 --self-test 自检")

    if args.out:
        pass_root = args.out
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        proj = os.path.dirname(here)
        pass_root = os.path.join(proj, "assets", "passes")
    view = VIEW_ALIAS.get(args.view.strip().lower(), VIEW_ALIAS.get(args.view.strip(), args.view))

    # 未显式给角度时，按机位查表（2026-09-27 修复：此前所有机位共用默认 (0,12)）
    default_az, default_el = VIEW_ANGLES.get(view, (0.0, 8.0))
    if args.azimuth is None:
        args.azimuth = default_az
    if args.elevation is None:
        args.elevation = default_el
    if view in ("top", "bottom") and abs(args.elevation) == 90.0:
        args.ortho = True

    outdir = os.path.join(pass_root, args.sku, view)
    tmpdir = os.path.join(outdir, "_raw")
    os.makedirs(tmpdir, exist_ok=True)

    log("=" * 60)
    log(f"SKU={args.sku}  机位={view}  尺寸={args.width}x{args.height}")
    log(f"输出目录={outdir}")

    reset_scene()
    if args.self_test:
        build_self_test()
    else:
        import_model(args.model)

    (center, size) = model_bounds()
    log(f"包围盒：尺寸 {size.x:.2f} x {size.y:.2f} x {size.z:.2f}，中心 {tuple(round(v,2) for v in center)}")

    if args.probe:
        meshes = sorted([o for o in bpy.data.objects if o.type == "MESH"], key=lambda o: o.name)
        log("=" * 60)
        log("PROBE 模式：只报告，不渲染")
        log(f"物体数（网格）：{len(meshes)}")
        for ob in meshes[:40]:
            d = ob.dimensions
            log(f"  {ob.name:<30} dims=({d.x:.2f},{d.y:.2f},{d.z:.2f}) verts={len(ob.data.vertices)}")
        if len(meshes) > 40:
            log(f"  …其余 {len(meshes)-40} 个略")
        m = max(size.x, size.y, size.z)
        unit = "疑似毫米（STP/3dm 常见）" if m > 1000 else ("疑似米" if m < 1 else "量级正常")
        log(f"最大边长 {m:.2f} → {unit}")
        log(f"轴向估计：X={size.x:.2f} Y={size.y:.2f} Z={size.z:.2f}（长边通常为枪身/光轴方向）")
        log("=" * 60)
        return 0

    if args.product_batch:
        render_product_batch(args, center, size)
        return 0

    if args.product_render:
        render_product_base(args, center, size)
        return 0

    if args.thumb:
        # 缩略图模式：不产 pass，只出一张预览。
        # 相机方位、取景算法、灯光、轴向与正式结构图**完全共用**，
        # 所以不会出现「缩略图看得见、正式机位全在画面外」。
        if args.export_glb:
            _export_glb(args.export_glb)   # 几何未受灯光影响，先导再布景
        setup_world()
        setup_lights(center, max(size.length / 2.0, 1e-3))
        setup_camera(args, center, size)
        setup_render(args)
        dest = os.path.abspath(args.thumb)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        bpy.context.scene.render.filepath = dest
        log("=" * 60)
        log(f"缩略图模式：只渲染一张预览，不产 pass")
        log(f"输出={dest}")
        bpy.ops.render.render(write_still=True)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            log(f"✅ 缩略图 {os.path.getsize(dest):,} B")
        else:
            raise SystemExit("[pass] 缩略图未产出")
        log("=" * 60)
        return 0

    mapping = assign_pass_index()
    setup_world()
    radius = max(size.length / 2.0, 1e-3)
    setup_lights(center, radius)
    setup_camera(args, center, size)
    setup_render(args)
    enable_passes()
    setup_compositor(tmpdir)

    log(f"开始渲染（{args.samples} 采样）…")
    bpy.ops.render.render(write_still=False)
    log("渲染完成，整理文件…")

    # 改名到规范文件名
    final = {}
    rename_map = {
        "clay": "clay.png", "alpha": "alpha.png", "objectid": "objectid.png",
        "depth": "depth.exr", "normal": "normal.exr",
    }
    for stem, target in rename_map.items():
        src = find_written(tmpdir, stem)
        if not src:
            log(f"⚠️ 未产出 {stem}")
            continue
        dst = os.path.join(outdir, target)
        if os.path.exists(dst):
            os.remove(dst)
        os.replace(src, dst)
        final[target] = os.path.getsize(dst)
        log(f"  ✅ {target}  {os.path.getsize(dst):,} B")

    # 降级件：depth.png / normal.png
    depth_stats = None
    d_exr = os.path.join(outdir, "depth.exr")
    if os.path.exists(d_exr):
        try:
            img = bpy.data.images.load(d_exr)
            w, h = img.size
            px = list(img.pixels)
            # Z pass 里"没打到任何物体"的背景像素是极大值（约 1e10），必须排除，
            # 否则归一化区间会被拉到 1e10，物体全被压成 0。
            BG_CUT = 1.0e6
            vals = [px[i * 4] for i in range(w * h) if 0.0 < px[i * 4] < BG_CUT]
            if vals:
                lo, hi = min(vals), max(vals)
                span = (hi - lo) or 1.0
                # 黑色背景、物体 0.12..1.0：即使侧视深度跨度很小，轮廓也不会
                # 像旧版「背景=1、最近表面=1」那样一起融进白色。
                out = bpy.data.images.new("depth_png", w, h, alpha=False)
                out.colorspace_settings.name = "Non-Color"
                buf = [0.0] * (w * h * 4)
                for i in range(w * h):
                    z = px[i * 4]
                    if z <= 0 or z >= BG_CUT:
                        v = 0.0        # 未命中物体：黑色背景，与最近表面的白色分离
                    else:
                        v = 0.12 + 0.88 * (1.0 - (z - lo) / span)
                    buf[i * 4] = v
                    buf[i * 4 + 1] = v
                    buf[i * 4 + 2] = v
                    buf[i * 4 + 3] = 1.0
                out.pixels = buf
                out.file_format = "PNG"
                out.save_render(os.path.join(outdir, "depth.png"))
                depth_stats = {"encoding": "near_white_far_dark_bg_black_v2",
                               "background": 0.0, "foreground_min": 0.12,
                               "near_m": lo, "far_m": hi,
                               "foreground_pixels": len(vals), "pixels": w * h}
                bpy.data.images.remove(img)
                bpy.data.images.remove(out)
                log(f"  ✅ depth.png（归一化 {lo:.3f}–{hi:.3f} m）")
            else:
                log("  ⚠️ 深度 EXR 没有有效前景像素")
        except Exception as e:
            log(f"  ⚠️ depth.png 生成失败：{e}")

    n_exr = os.path.join(outdir, "normal.exr")
    if os.path.exists(n_exr):
        if normal_to_png(n_exr, os.path.join(outdir, "normal.png")):
            log("  ✅ normal.png")

    # 工件清单（本机 pass 级）
    _oid_stats = visible_object_id_stats(os.path.join(outdir, "objectid.png"))
    if _oid_stats["status"] != "ok":
        log("警告：可见部件反解状态=%s（%s）" % (_oid_stats["status"], _oid_stats["message"]))
    meta = {
        "pass_format_version": 2,
        "depth_encoding": depth_stats,
        "sku": args.sku, "view": view,
        "resolution": [args.width, args.height],
        "camera": {"azimuth": args.azimuth, "elevation": args.elevation,
                   "ortho": bool(args.ortho), "lens_mm": 85.0,
                   "fit": args.fit, "type": "ORTHO" if args.ortho else "PERSP"},
        "model": os.path.basename(args.model) if args.model else "SELFTEST",
        "self_test": bool(args.self_test),
        "samples": args.samples,
        "renderer": f"Cycles/{bpy.context.scene.cycles.device}",
        "color_management": "view_transform=Standard / film_transparent=True",
        "objectid_map": mapping,
        # ★ 本机位实际可见的部件号（从 objectid.png 反解）。
        #   校验端据此判断"方案分配的部件在这一面到底出没出现"，
        #   否则名字齐全会让不可见的分配静默通过（AI渲染1 实测）。
        # ★ 本机位实际可见的部件号（从 objectid.png **全像素**反解）。
        #   校验端据此判断「方案分配的部件在这一面到底出没出现」，
        #   否则名字齐全会让不可见的分配静默通过（AI渲染1 实测）。
        #   `visible_object_ids` 保持纯列表以兼容旧读取方；
        #   `visible_object_stats` 带 status / 每 ID 像素数 / 编码版本 ——
        #   用来区分「读取失败」与「确实没有部件」，S2 明确要求两者不能混。
        "visible_object_ids": visible_object_ids(os.path.join(outdir, "objectid.png")),
        "visible_object_stats": _oid_stats,
        "passes": final,
        "blender": bpy.app.version_string,
    }
    with open(os.path.join(outdir, "pass_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 清理临时目录
    try:
        for n in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, n))
        os.rmdir(tmpdir)
    except Exception:
        pass

    log("=" * 60)
    log(f"完成。投放区已就绪：{outdir}")
    log("下一步：控制台「投放区」会识别 clay/depth/normal，可直接出图")
    return 0


if __name__ == "__main__":
    sys.exit(main())
