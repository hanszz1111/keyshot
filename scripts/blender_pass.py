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
不支持：.ksp(KeyShot) .stp/.step .3dm(Rhino) .c4d .max .rhi —— 请先在原软件里导出为 .glb 或 .obj
"""
import argparse
import json
import math
import os
import sys

import bpy
import mathutils

# ---------------------------------------------------------------- 常量

SUPPORTED = {".blend", ".glb", ".gltf", ".obj", ".stl", ".fbx"}
NEED_CONVERT = {
    ".ksp": "KeyShot 工程 —— 请在 KeyShot 中 文件 → 导出 → glTF(.glb)",
    ".stp": "STEP 工程图 —— 请在 CAD/Rhino 中导出 .glb 或 .obj（Blender 无原生 STEP 导入）",
    ".step": "STEP 工程图 —— 同上",
    ".3dm": "Rhino 工程 —— 请在 Rhino 中 导出 → glTF(.glb)",
    ".c4d": "Cinema 4D —— 请导出 .glb / .obj",
    ".max": "3ds Max —— 请导出 .glb / .obj",
    ".rhi": "Rhino 历史文件 —— 请导出 .glb / .obj",
}

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
    "3q4_left":      (-45.0, 15.0),
    "3q4_right":     (45.0,  15.0),
    "side":          (90.0,   8.0),
    "top":           (0.0,   80.0),
    "detail_keypad": (-30.0, 35.0),
    "detail_window": (30.0,  30.0),
}


def log(msg):
    print("[pass] " + str(msg), flush=True)


# ---------------------------------------------------------------- 参数

def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser(prog="blender_pass.py", add_help=True)
    ap.add_argument("--model", help="3D 模型路径（.blend/.glb/.gltf/.obj/.stl/.fbx）")
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
    ap.add_argument("--no-denorm", action="store_true", help="不做归一化，直接输出原始值")
    ap.add_argument("--self-test", action="store_true",
                    help="不导入模型，用内置几何自检整条 pass 链路")
    ap.add_argument("--probe", action="store_true",
                    help="只导入并报告模型信息（包围盒/物体数/尺度），不渲染")
    return ap.parse_args(argv)


# ---------------------------------------------------------------- 场景准备

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


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
        dist = max(hw / math.tan(fov_h / 2.0), hu / math.tan(fov_v / 2.0)) * args.fit
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
    """一个 File Output 节点只支持一种格式，所以按格式分节点。"""
    node = tree.nodes.new("CompositorNodeOutputFile")
    node.name = name
    node.label = name
    node.base_path = base
    node.format.file_format = fmt
    if color_depth:
        try:
            node.format.color_depth = color_depth
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

    for node, sockets in ((png_node, ["Image", "Alpha", "IndexOB"]),
                          (exr_node, ["Depth", "Normal"])):
        for i, s in enumerate(sockets):
            src = rl.outputs.get(s)
            if src is None:
                log(f"警告：Render Layers 没有 {s} 输出，跳过")
                continue
            tree.links.new(src, node.inputs[i])

    return tree


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
                out = bpy.data.images.new("depth_png", w, h, alpha=False)
                out.colorspace_settings.name = "Non-Color"
                buf = [0.0] * (w * h * 4)
                for i in range(w * h):
                    z = px[i * 4]
                    if z <= 0 or z >= BG_CUT:
                        v = 1.0        # 背景 → 最远
                    else:
                        v = (z - lo) / span
                        v = 1.0 - v    # 反转：近处=白，远处=黑（ControlNet 常用约定）
                    if args.no_denorm:
                        v = min(z, 1.0)
                    buf[i * 4] = v
                    buf[i * 4 + 1] = v
                    buf[i * 4 + 2] = v
                    buf[i * 4 + 3] = 1.0
                out.pixels = buf
                out.file_format = "PNG"
                out.save_render(os.path.join(outdir, "depth.png"))
                bpy.data.images.remove(img)
                bpy.data.images.remove(out)
                log(f"  ✅ depth.png（归一化 {lo:.3f}–{hi:.3f} m）")
        except Exception as e:
            log(f"  ⚠️ depth.png 生成失败：{e}")

    n_exr = os.path.join(outdir, "normal.exr")
    if os.path.exists(n_exr):
        if normal_to_png(n_exr, os.path.join(outdir, "normal.png")):
            log("  ✅ normal.png")

    # 工件清单（本机 pass 级）
    meta = {
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
