# RESULT.md · 本轮执行结果与原始证据

> **轮次**：R2 ｜ **执行方**：Windows 本机（Blender 4.5 / ComfyUI 0.37.0 / RTX 4060 Ti 8GB）
> **base_commit**：`fd870cb` ｜ **result_commit**：`7ac3995`
> **日期**：2026-09-28
> 评审者请用本文件作为判断依据。**每个结论都应能在此找到出处。**
> 路径一律写成项目内相对路径（仓库根 = `AI/` 的上一级）。

---

## 0. 本轮任务来源

用户原话（逐字）：

> 「导入的白膜显示不全，只有一半，也没有其他面的展示，增加一个类似3D软件中的自由旋转视角进行选择的功能，让这个页面可以完整显示这个图片，目前的材质太少了，增加更多的材质包」

以及在此之前的一条：

> 「还是会出现这种报错」（附截图：`.3dm 已保存。Blender 安装 import_3dm 插件后可生成结构图…`）

**注意**：用户没有指定修法，根因定位本身是本轮主要工作的一部分。

---

## 1. 起点状态：v2.8 带入的两条 CAD 通道在本机都不可用

`fd870cb` 合并进来的 v2.8 声称支持 STEP/STP 与 Rhino 3DM，但本机实测两条都不通。

### 1.1 依赖探测（原始输出）

| 项 | 探测方式 | 结果 |
|---|---|---|
| FreeCAD | `shutil.which("FreeCADCmd")` + `C:\Program Files\FreeCAD*` | **未找到** |
| `import_3dm` | 插件目录扫描 | **未安装** |
| Blender | `blender_executable()` | ✅ `D:\...\blender-4.5.0-windows-x64\blender.exe` |

### 1.2 但同时发现：STEPper 已经装了

扫描 Blender 插件目录时发现 `STEPper`（版本 1.1.9，GJJ 汉化版），
自带**完整 OpenCASCADE 内核**：

```
OCC 目录：1023 个模块 / 313 个 .pyd / 共 328 MB
运行日志：--> STEPper OpenCASCADE version: 7.7.2
```

→ **结论：`.stp/.step` 根本不需要 FreeCAD。** FreeCAD 被降级为「STEPper 缺失时的回退通道」。

---

## 2. 条件 C1：两条 CAD 通道的实机跑通记录

### 2.1 `.stp` — 走 STEPper 直读

| 项 | 值 |
|---|---|
| 输入 | `assets/白模/GF(1).stp`，**18,108,945 B（18 MB）** |
| 读入结果 | **15 个网格 / 总面 53,365** |
| 耗时 | STEP 加载 **6.26 s** |
| 端到端出图 | front 机位，**约 20 s**，产出 `clay/alpha/depth/normal/objectid` 全部 7 个文件 |

日志原文（节选）：

```
[pass] 导入模型 GF(1).stp
--> STEPper OpenCASCADE version: 7.7.2
STEP loading time elapsed: 6.26
[pass] 包围盒：尺寸 0.10 x 0.08 x 0.04，中心 (0.04, 0.02, -0.0)
[pass]   ✅ clay.png  1,495,370 B
[pass]   ✅ depth.png（归一化 0.249–0.306 m）
```

### 2.2 `.3dm` — 走 `bl_ext.user_default.import_3dm`

本轮为此**新装** `import_3dm` v0.0.18（Windows x64，4.57 MB）：

```bash
blender.exe --command extension install-file -r user_default -e import_3dm-0.0.18-windows_x64.zip
```

**关键细节**：包内自带 `rhino3dm 8.17.0` wheel（含 cp311 / cp313）。
Blender 4.5 用 **Python 3.11.11**，因此命中 `rhino3dm-8.17.0-cp311-cp311-win_amd64.whl`，
被自动解到 `extensions/.local/lib/python3.11/site-packages/rhino3dm/`，无需手动 pip。

| 项 | 值 |
|---|---|
| 输入 | `assets/白模/AI渲染1.3dm`，**49,180,885 B（46.9 MB）** |
| 读入结果 | **2530 个网格 / 136,201 顶点 / 113,373 面** |
| 耗时 | **2.5 s** |
| 端到端出图 | front 机位成功，7 个文件齐全 |

**踩到的坑**：装完的**模块名是 `bl_ext.user_default.import_3dm`**（Blender 4.2+ 扩展命名空间）。
裸名 `import_3dm` 会报 `ModuleNotFoundError: No module named 'import_3dm'`。

---

## 3. ★ 条件 C1 的核心：两条通道原本同时失败的根因

**这一节是本轮最关键的归因，请重点质疑（见 TASK.md 问题 1）。**

两条通道**同时**失败，且失败点都不在转换器/读取器本身，而在**插件启用时机**。

### 3.1 对照实验（同一份代码，只改顺序）

我写了两个只差「启用与清场的先后顺序」的脚本，跑同一份 `.stp`：

| 写法 | `scene.stepper` 属性 | 结果 |
|---|---|---|
| `read_factory_settings()` **之后**再 `addon_utils.enable("STEPper")` | **False** | ❌ `KeyError: 'bpy_prop_collection[key]: key "STEPper" not found'` |
| 先 `bpy.ops.preferences.addon_enable(module="STEPper")`，**再**手工清场 | **True** | ✅ 导入成功（15 网格 / 53,365 面 / 11.3 s） |

### 3.2 归因一：`reset_scene()` 用 `read_factory_settings` 会卸载插件

原实现：

```python
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)   # ← 会把已启用插件一起卸掉
```

`read_factory_settings` 不只是清场景，它会**重置用户偏好**，已启用的插件随之卸载。
STEPper 的 `Scene` PointerProperty（`bpy.types.Scene.stepper`）就挂不上了。

**修复**：改为手工删数据块，不碰偏好。

```python
def reset_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
```

### 3.3 归因二：`addon_utils.enable()` 在 `--background` 下不可靠

```python
addon_utils.enable("STEPper", default_set=True, persistent=True)
# → 抛 KeyError，但 hasattr(bpy.ops.import_scene, "occ_import_step") 竟然是 True
#   插件类注册了，Scene 属性却没挂载 → 算子内部一取就崩
```

**修复**：改用 `bpy.ops.preferences.addon_enable(module=...)`，并用
`hasattr(bpy.context.scene, "stepper")` 作为「真的启用成功」的判据。

### 3.4 ★ STEPper 的调用契约（又一个必踩的坑）

```python
bpy.ops.import_scene.occ_import_step(
    filepath=path, override_file=path,        # ★ 两个都要给
    lin_deflection=0.8, ang_deflection=0.5,
    hierarchy_types="FLAT")                    # 枚举只有 FLAT/TREE/EMPTIES，没有 NONE
```

- 算子名是 **`occ_import_step`**，不是 `import_scene.step`；
- **`filepath` 只被当目录用**，真正目标必须走 `override_file`。
  插件内部是 `folder = dirname(filepath)` + 遍历 `self.files`（多文件集合）。
  只给 `filepath` 会 `report ERROR "未选择任何STEP文件"` 然后 CANCELLED。

### 3.5 修复后：探测与链路自洽

```
blender_has_stepper()   = True    （命中 Blender\4.4\scripts\addons\STEPper）
blender_has_import3dm() = True    （命中 Blender\4.5\extensions\user_default\import_3dm）
freecad_cmd_executable() = None   ← FreeCAD 仍未装
```

**注意**：STEPper 实际装在 `Blender\4.4\scripts\addons`，而 Blender 本体是 **4.5**。
所以探测器**必须遍历版本目录**（用 `*` 通配），写死 `4.5` 会漏掉。

---

## 4. 条件 C2：界面提示必须反映真实能力状态

### 4.1 问题

用户截图显示的文案是：

> `AI渲染1.3dm 已保存。Blender 安装 import_3dm 插件后可生成结构图；…`

**而插件早就装好了。** 原因：该文案在 `app.js` 里是**硬编码**的，无条件显示，
不查插件状态——上一轮只给 STEP 加了 `stepper` 探测，**漏了 3DM**。

### 4.2 修复

后端加**通用插件探测**（覆盖三种安装位置），`/api/ui/info` 返回两个能力字段：

```python
def _blender_addon_dir(dir_names):
    roots = [<APPDATA>/Blender Foundation/Blender, <blender.exe 同级>, <同级>/4.5]
    for root in roots:
        for name in dir_names:
            for pat in (root/*/scripts/addons/<name>,
                        root/*/extensions/*/<name>,
                        root/*/extensions/*/*/<name>,
                        root/scripts/addons/<name>,
                        root/extensions/*/<name>):
                if glob.glob(pat): return hit[0]
    return None

blender_has_stepper()   = bool(_blender_addon_dir(("STEPper",)))
blender_has_import3dm() = bool(_blender_addon_dir(("import_3dm",)))
```

响应实测：

```json
{"blender": true, "freecad_cmd": "", "stepper": true, "import3dm": true, "blender_script": true}
```

前端按 `state.ui.import3dm` 分流：**已装** → 「读取能力已就绪，请选择视角并生成结构图」；
未装才提示安装（并给出 Blender 4.2+ 的正确模块名）。

### 4.3 附带发现：浏览器启发式缓存

用户看到的其实是**改之前的文案**——因为静态资源响应只有 `Last-Modified`、
没有 `Cache-Control`，浏览器**不询问就直接复用**旧 `app.js`。

**修复**：静态资源（`.html/.js/.css`）补 `Cache-Control: no-cache, must-revalidate`。

实现方式（这个组合是必需的）：覆写 `send_head()` 置标志 + 覆写 `end_headers()` 注入 ——
因为 `send_head` 内部就是靠调 `end_headers` 落盘的。接口保持 `no-store`，未被误改（有实测）。

---

## 5. 条件 C3：上传两道预检

### 5.1 第一道：格式分类

`.rhi` 是 **Rhino 插件安装包**，不是模型（R1 之前的文档已纠正过这一点，但代码没跟上）。

```python
MODEL_EXTS = {".ksp",".blend",".glb",".gltf",".fbx",".obj",".stp",".step",".3dm",".c4d",".max",".stl"}
# ★ .rhi 故意不在列表里
NOT_A_MODEL = {".rhi": "Rhino 插件安装包（不是模型）", ".rhp": ..., ".yak": ..., ".3dmbak": ...}
```

### 5.2 第二道：几何预检（文件头签名）

签名表**实测校准**（这是关键，写错会误杀好文件）：

| 扩展名 | 签名 |
|---|---|
| `.stp/.step` | `ISO-10303-21` |
| `.3dm` | `3D Geometry File Format` |
| `.glb` | `glTF` |
| `.fbx` | `Kaydara FBX Binary` / `; FBX` |
| `.blend` | `BLENDER` / gzip `\x1f\x8b` |
| `.obj` | 文本，按内容特征找 `v `/`f ` 行 |
| `.gltf` | 文本，应以 `{` 开头 |

**`.stl` 必须特殊处理**——实测发现 Rhino 导出的二进制 STL 头部是：

```
b'Rhinoceros Binary STL ( Feb  9 2021 )\r\n ...'
```

**既不是 ASCII 的 `solid`，也不是标准空头**，所以不能靠文件头判断。
改用二进制 STL 的硬约束：

```
size == 84 + 50 × 面数      （80 字节说明 + 4 字节小端面数 + 每面 50 字节）
```

实测两份真实 STL 都**精确一致**：

| 文件 | 声明面数 | 应有字节 | 实际字节 |
|---|---|---|---|
| `GF.stl` | 417,483 | 20,874,234 | 20,874,234 ✅ |
| `stl.stl` | 434,677 | 21,733,934 | 21,733,934 ✅ |

### 5.3 设计取舍（见 TASK.md 问题 2）

代码注释里写明了原则：**「宁可漏判，不可误杀 —— 没把握的格式一律返回通过」**
（`.ksp/.c4d/.max` 没有可靠签名，直接放过）。

预检失败时**删除刚写盘的文件**（而不是保留+标记），理由是「不然投放区里会留下
看起来在、其实用不了的文件」。**这个决定请评审者重点质疑。**

### 5.4 实测结果

| 用例 | HTTP | 返回 |
|---|---|---|
| `.rhi` 插件包 | **400** | 「`.rhi` 不是可用的白模文件（Rhino 插件安装包（不是模型））」 |
| 改名骗过的 `.stp` | **400** | 「文件内容与 .stp 格式不符（可能改了扩展名，或文件损坏/未传完）」 |
| 损坏的 `.stl` | **400** | 「STL 结构不自洽：声明 2021161080 个面应有 101058054084 字节，实际 5000」 |
| 真实 `.stp` | 200 | 正常保存 |
| 真实 `.3dm` / `.stl` | 200 | **零误杀** |

---

## 6. 条件 C4：结构图任务的完成状态

### 6.1 问题

原实现只用 `proc.returncode == 0` 判断成功。但 Blender 完全可能在某个通道写失败、
或写出 0 字节文件的情况下退出码仍为 0 —— 界面照样报「结构图已生成」，
用户点「队列」出图才发现没有深度图。

### 6.2 修复

新增 `verify_pass_outputs(sku, view)`，逐项核对：**存在 · 体积非零 · 三通道尺寸一致**
（只读 PNG 头 24 字节，不解码整图）。

**★ 一个必须注意的一致性要求**：这个函数**不能**用 `safe_file(sku)` 转义 SKU ——
`blender_pass.py` 那边是 `os.path.join(pass_root, args.sku, view)` **原样拼**目录。
两边算法不一致的话，含特殊字符的 SKU 就永远找不到目录。

改为原样拼 + `os.path.commonpath` 越界防护。实测：

```
GF(1)/front  → PASS
GF/front     → FAIL 缺少：clay.png、depth.png、normal.png
..           → FAIL SKU 或机位名非法，产物路径越出结构图目录
GF(1)/../..  → FAIL 同上（越界防护生效）
```

界面文案同步改为「结构图已生成（clay / 深度 / 法线 三通道已校验）」。

---

## 7. 条件 C5：主预览图被裁切

### 7.1 问题复现与测量

用浏览器实际打开页面（选中产品 `AI渲染1`），用 JS 读真实盒模型：

```json
{"natural":[1232,752], "client":[742,453], "objectFit":"contain",
 "hero":[742,388]}
```

**图高 453px，容器只有 388px** —— 图比容器高 65px，被 `.hero` 的
`overflow: hidden` 裁掉上下。这正是用户说的「只有一半」。

### 7.2 根因

`.hero { display: grid; place-items: center; }`，而 `#heroImage` 只靠 `height: 100%`。

**grid area 高度不确定时，百分比高度会失效**，浏览器回退成
「按图片固有比例算高度」→ `742 × 752/1232 = 453`。

### 7.3 修复与复测

```css
#heroImage{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;z-index:1}
```

复测：`client = [742,388]`，`hero = [742,388]` —— **完全一致**。
截图确认望远镜完整显示（目镜 + 机身 + 底部）。

---

## 8. 条件 C6：3D 自由旋转预览

### 8.1 实现链路

1. `blender_pass.py` 增 `--export-glb`：从**导入后**的网格导出 GLB，
   显式 `export_cameras=False / export_lights=False`；临时文件 + `os.replace` 原子发布。
2. 后端：`assets/_预览模型/<SKU>.glb` + `GET /api/model/glb?sku=`；
   **与缩略图共用一次 Blender 调用**（省一次启动）。
3. three.js 0.169.0 放 `web/vendor/`（本地，1.48 MB）——**不走境外 CDN**
   （实测 jsdelivr 拉 1.3 MB 的 `three.module.js` 要 9.4 s，本机网络对它不稳）。
4. 前端加「3D 自由旋转」档位：OrbitControls 拖动旋转 / 滚轮缩放 / 双击复位。

### 8.2 GLB 实测

```
magic = b'glTF'   version = 2   声明长度 = 7,050,556  实际 = 7,050,556
meshes = 2530   nodes = 2541   materials = 0   accessors = 8832
含 cameras: False   含 KHR_lights: False
```

→ 保留 **2530 个部件**（未合并成单 mesh），且**无相机无灯光**。

浏览器端加载实测：**105 ms**，包围盒 `[0.041, 0.074, 0.111]`（真实米制），非空。

### 8.3 开发中踩并修掉的三个 three.js 坑

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | canvas **一片空白** | 同时给 `root` 设 `scale` 与 `position`。矩阵是 `T(position)·S(scale)`，顶点**先缩放再平移**，用未缩放的世界坐标当 position 会把模型推出画面 | 放进 `Group`：`root.position.sub(center)` 是 Group 局部坐标，缩放由 Group 施加 |
| 2 | 模型「X 光透视」 | GLB 无材质 + STL/STEP 常是**单面壳体**，`FrontSide` 下背面被剔除 | 统一换本地白模材质 + `side: THREE.DoubleSide` |
| 3 | 模型**躺着**，与结构图姿态不符 | Blender 是 Z-up，three.js 是 Y-up | 按包围盒判断（最长边落在 Z 轴则绕 X 轴 -90° 扶正）|

**坑 3 是启发式，我自己有疑虑，见 TASK.md 问题 3。**

### 8.4 「可旋转」的证据强度（请评审者评估，见 TASK.md 问题 5）

我用的方法是：截图 A → 派发 `pointerdown`/`pointermove`(×10)/`pointerup` → 截图 B，
**两图字节数不同（80,616 → 79,327）**，且肉眼可见模型转到了另一角度。

**这是一个间接证据。** 我没有做「旋转角度 vs 鼠标位移」的定量校验。

---

## 9. 条件 C7：材质 4 → 12 种

| 分组 | 材质（key） |
|---|---|
| 塑料与涂层 | `matte_plastic` / `glossy_plastic` / `soft_touch` |
| 金属 | `brushed_aluminum` / `sandblasted_metal` / `gunmetal` / `polished_metal` / `chrome` |
| 其他 | `carbon_fiber` / `rubber` / `leather` / `wood` |

**★ 材质定义分散在三处，必须同步**（漏一处就会出现「选了没反应」）：

| 位置 | 作用 |
|---|---|
| `web/app.js` `MATERIAL` | 拼进提示词的英文描述 |
| `web/app.js` `CARD_MATERIAL` | 参数卡（type/finish/roughness/metallic） |
| `web/index.html` `<select id="materialSelect">` | 用户可见选项 |

已写脚本校验三处 key **完全一致**（12 / 12 / 12）。

**故意不提供**「玻璃 / 透明 PC」——按 ADR-002，AI 生成透明件必翻车，走真渲染合成。
`chrome`（镜面镀铬）提供了，但它只适合金属高光，不代表能处理透明件。

---

## 10. 条件 C8：R1 指出的「可绕过受控校验的入口」整改

### 10.1 R1 的原判定

> 实验脚本走 `/api/comfy/submit`，而网页走 `/api/ui/comfy/submit`；
> 前者在服务端直接调用 `comfy_submit()`，绕过 `guarded_submit()` 的结构图/模式校验。
> 它不能作为「真实网页受控链路全部验收」的证据，**且留下可以跳过受控校验的入口**。

**我核实：确认存在。** `comfy_submit` 与 `guarded_submit` 是两个独立函数，
前者不做任何 mode/depth 校验。

### 10.2 整改内容

1. **`/api/comfy/submit` 默认改为走 `guarded_submit()`**；
   确需旁路必须显式写 `?unsafe=1` —— 让旁路成为**可审计的显式选择**，而不是默认行为。
2. **`scripts/imitate_render.py`** 改为走 `/api/ui/comfy/submit`（与网页**同一个端点**），
   并给任务补上 `"_meta": {"mode": "controlled"}`（它本来就带 depth/normal，本质是受控任务）。
   顺带把脚本文档里「与网页完全是同一条链路」这句**改成名副其实**。
3. **`/api/ui/comfy/submit`** 原本把受控拒绝（`RuntimeError`）报成 **500**，
   与另一个端点的 400 不一致；已补 `RuntimeError` 到 except 里改为 400。

### 10.3 整改实测

造一个「声明 `controlled` 但故意不给深度图」的任务（#497）：

| 端点 | HTTP | 返回 |
|---|---|---|
| `/api/comfy/submit`（默认） | **400** | 「缺少当前机位的深度图，已阻止自动降级为纯文生图。请先生成/上传结构图。」 |
| `/api/ui/comfy/submit` | 400（修前是 500） | 同上 |

测试任务 #497 已清理；清理前备份任务库到 `_隔离区/20260928_r1check/`。
任务库剩余 39 条。

**遗留**：`docs/验收证据-20260927/bug2_e2e_cn.py` 仍指向 `/api/comfy/submit`（现在会走受控）。
那是**历史证据脚本**，我**故意没改**它——改了会污染当时证据的原始性。
若需重跑，应显式加 `?unsafe=1` 或改用受控端点。**请评审者确认这个处理是否恰当。**

---

## 11. 条件 C9：回归

```
web/selftest.py  →  通过 18 / 18
从过程文档解析变更记录   15 条，最新 v3.0 FIX
```

`web/selftest.py` 未在本轮修改，跑的是既有 18 项。

---

## 12. 本轮改动清单（对照 result_commit）

| 文件 | 改动 |
|---|---|
| `web/server.py` | 缩略图/GLB 模块、插件探测、上传两道预检、产物校验、受控提交统一、静态缓存头 |
| `web/app.js` | 3D 预览模块、缩略图加载、材质 12 种、提示按状态分流、档位 |
| `web/index.html` | importmap、canvas、档位按钮、材质 optgroup、过时文案修正 |
| `web/styles.css` | `#heroImage` 绝对定位修复、`#heroCanvas`、`.model-thumb` |
| `web/vendor/three/` | three.js 0.169.0（4 个文件，1.48 MB，新增） |
| `scripts/blender_pass.py` | `--thumb`、`--export-glb`、`reset_scene` 修正、插件启用修正、STEPper 导入 |
| `scripts/imitate_render.py` | 改走受控端点 + 补 `_meta.mode` |
| `AI/` | R1 快照归档到 `AI/history/R1/`，本轮新写 `TASK.md` / `RESULT.md` |

---

## 13. 本轮**未**验证 / 未做的事（请勿当作已完成）

- ❌ **多零件 STEP**、**纯 NURBS 无渲染网格的 3DM** —— 两周边界样本都没测。
  端到端正例只有**单件**模型。
- ❌ **`import_jobs` 作业化与哈希版本管理**（过程文档 7.3 的设计）未实施。
- ❌ **预览卡片的信息栏**（部件数/三角数/单位/外包围尺寸）未做。
- ❌ 3D 预览的**旋转是间接证据**（截图比对），没有定量校验。
- ❌ **Z-up 判据是启发式**，未在「天然细长且长边沿 Z」的模型上验证是否会误转。
- ❌ 缩略图/GLB 的**并发场景**未测（多 SKU 连续上传时是否排队正确）。
- ❌ 所有实测均在**本机单环境**（Blender 4.5 / 一张 4060 Ti），**未跨机器复验**。

---

## 14. 证据索引

| 内容 | 位置 |
|---|---|
| 过程文档（SSOT，含 v3.0 变更行） | `00-AI白模渲染器-过程文档.md` |
| 使用说明 | `README.md` |
| 导出/预览脚本 | `scripts/blender_pass.py` |
| 服务端 | `web/server.py` |
| 自检 | `web/selftest.py` |
| 本轮隔离区（测试文件、任务库备份） | `_隔离区/20260928_*/` |

**未入仓的证据**（按协议，`assets/`、`outputs/` 不在公开仓库）：
缩略图 PNG、GLB 预览模型、结构图产物、浏览器截图。
如需独立复核视觉部分，请说明需要哪一项，我再评估脱敏后提供的方式。
