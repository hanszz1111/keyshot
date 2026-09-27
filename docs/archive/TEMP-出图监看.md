# TEMP · 出图监看板

> **性质**：临时监看文档。**不是权威文档、不进留痕体系**；等结论稳定后并入 `00-AI白模渲染器-过程文档.md`。
> **用途**：一屏看清「出图链路就绪度」+「已生成内容」，边跑边记。
> **更新**：2026-09-26 08:50 ｜ 本机 RTX 4060 Ti 8GB

## 一句话状态

> ✅ **全线打通，并且已经用真实产品出图了**：`GF.stl`（真实望远镜 CAD，103×42×76mm / 22 万面）→ 三机位结构 pass → 双 ControlNet 仿图，**16–25 秒/张**，源文件零改动。
> ⚠️ 关键边界已实证：**depth/normal 锁得住「轮廓与大体块」，锁不住「表面细节」** —— AI 会臆造 CAD 里不存在的格栅/竖纹，且**拉满强度反而更差**。
> → 所以**产品本体像素必须走「结构优先」**（真渲染合成），AI 负责背景与氛围（ADR-015 / OPT-04）。

---

## 一、就绪度总表

| # | 环节 | 状态 | 证据 / 说明 |
|---|---|---|---|
| 1 | ComfyUI 运行时 | ✅ | 官方便携版 **0.37.0**，`run_nvidia_gpu.bat` 可起 |
| 2 | 内嵌 Python | ✅ | 3.13.14（免装环境） |
| 3 | GPU | ✅ | RTX 4060 Ti · 8.0 GB，`--lowvram` 启动 |
| 4 | 底模 A（首选） | ✅ | `RealVisXL_V5.0_Lightning_fp16`（openrail++，4–8 步） |
| 5 | 底模 B（对照） | ✅ | `sd_xl_base_1.0`（OpenRAIL++-M） |
| 6 | ControlNet | ✅ | `controlnet-union-sdxl-1.0-promax`（Apache-2.0，支持 depth/normal/tile/canny…） |
| 7 | VAE | ✅ | `sdxl_vae.safetensors`（MIT） |
| 8 | 模型路径接线 | ✅ | `extra_model_paths.yaml` 指向 F 盘，**零复制**（省 18 GB） |
| 9 | **Blender 结构 pass** | ✅ **新** | `scripts/blender_pass.py` + `出pass.bat`，一条命令出 `clay/alpha/depth/normal/objectid` |
| 10 | **工作流 JSON** | ✅ **新** | `config/comfy_workflow_sdxl.json`（文生图）+ `comfy_workflow_sdxl_cn.json`（双 ControlNet），节点 ID 与前端 `SLOTS` **严格对齐** |
| 11 | **控制台直连 ComfyUI** | ✅ **新** | `/api/comfy/status\|submit\|poll` + 队列每行「▶」按钮 + 顶部在线徽标 |
| 12 | **工件清单 / QA 报告** | ✅ **新** | `scripts/make_manifest.py` → `outputs/artifact_manifest.json` + `QA报告.md` |
| 13 | **一键启动** | ✅ **新** | 根目录 `启动全部.bat`（同时起 ComfyUI + 控制台并开浏览器） |
| 14 | 对齐校验 | ✅ | 网页控制台内置（IoU / 质心偏移） |
| 15 | AI 插件（custom_nodes） | ⚠️ | 仍未装 Manager / IPAdapter / Impact 等（按 OPT-12 顺序再装） |
| 16 | **结构 pass 素材** | ✅ **新** | `GF` 三机位（side / 3q4_left / front）已就绪；`_demo` 自检件保留 |
| 17 | **真实产品 3D 源** | ✅ **新** | `F:\ID设计-杨\GF望远镜改款\GF.stl`（20MB）＋ `LQ望远镜改款\银.stl`（22MB）；另有 **159 GB** 成图库 `E:\全产品模型渲染图-详情主图源文件` |
| 18 | **参考图索引** | ✅ **新** | `scripts\make_ref_sheet.py` → `outputs\_参考图\GF\`（74 张缩略图 + `清单.md` + `ref_index.json`） |
| 19 | **仿图 runner** | ✅ **新** | `scripts\imitate_render.py`（材质预设 / 自定义提示词 / 覆盖步数·cfg·强度） |
| 20 | **对照拼图** | ✅ **新** | `scripts\make_compare.py` → `outputs\_对比\GF_*.jpg`（三列：结构图｜深度图｜仿图） |
| 21 | **表面细节锁定** | ❌ **新发现缺口** | depth/normal 锁不住表面纹理，AI 会臆造 → 待加第三条 ControlNet 链（clay→lineart）或走结构优先 |

---

## 二、实测出图记录

统一环境：RealVisXL_V5.0_Lightning_fp16 ｜ `--lowvram` ｜ RTX 4060 Ti 8GB ｜ ComfyUI 0.37.0

### 记录 2-1 ｜ 纯文生图（对照组，9-24）

| 项 | 值 |
|---|---|
| 产出 | `outputs/试跑-2026-09-24/01-纯文生图-1024x1024-8步-18.1s.png` |
| 参数 | 1024×1024 ｜ steps **8** ｜ cfg **2.0** ｜ dpmpp_sde / karras |
| **耗时** | **18.1 秒** |
| 结论 | 画质达商业产品照水准，**但产品是自己编的**，文字全乱码 |

### 记录 2-2 ｜ ControlNet tile 锁形（9-24）

| 项 | 值 |
|---|---|
| 产出 | `outputs/试跑-2026-09-24/02-ControlNetTile锁形-1232x752-20.1s.png` |
| 输入 | `assets/passes/LS-360G/front/clay.png` |
| 参数 | 1232×752 ｜ tile 0.65 ｜ 提示词不写形状词 |
| **耗时** | **20.1 秒** |
| 结论 | 结构守住 ✅；质感未重绘；文字被臆造成 `Laser Rauecindor` ⚠️ |

### 记录 2-3 ｜ Blender 结构 pass（9-26，OPT-01 验证）

| 项 | 值 |
|---|---|
| 产出 | `assets/passes/_demo/front/{clay,alpha,depth,normal,objectid}.png` + `depth.exr/normal.exr` + `pass_manifest.json` |
| 命令 | `出pass.bat --self-test`（内置几何，不需要模型） |
| 结论 | **7 个 pass 全部正确**：clay 是有明暗层次的灰模；depth 近白远黑；normal 各面颜色分明。<br>修掉两个 bug：① 深度归一化被背景值 1e10 污染；② 场景无灯光导致成像是剪影 |

### 记录 2-4 ｜ **全链路：投放区 → 控制台 → ComfyUI → 结果落盘**（9-26，OPT-02/03 验证）

| 项 | 值 |
|---|---|
| 流程 | 入队任务 → `POST /api/comfy/submit` → 轮询 `/api/comfy/poll` → 图拉回 `outputs/_demo/front/` |
| 提交结果 | `mode=controlnet` ｜ `with_normal=True` ｜ 底模 Lightning ｜ **9 个槽位全填充、0 跳过** |
| **耗时** | **24.4 秒** |
| 产出 | `outputs/_demo/front/ai_render_00001_.png`（1232×752） |
| 结论 | **方块 / 圆柱 / 小圆台的位置与形态完全守住**（双 ControlNet depth+normal 生效）✅ |

### 记录 2-5 ｜ **真实产品仿图 · GF 望远镜**（9-26，★首次用真实 CAD）

| 项 | 值 |
|---|---|
| 输入模型 | `F:\ID设计-杨\GF望远镜改款\GF.stl`（**只读**，103×42×76 mm，222,629 面） |
| 结构 pass | `assets/passes/GF/{side,3q4_left,front}/`（clay/alpha/depth/normal/objectid + EXR） |
| 参考图 | `F:\...\GF望远镜改款\渲染图\GF.29.jpg`（原厂 KeyShot 渲染：白高光外壳 + 黑橡胶包边 + 黑螺纹目镜 + 灰底影棚） |
| 出图参数 | 双 ControlNet：depth **0.80** / normal **0.55** ｜ 8 步 ｜ cfg 2.0 ｜ 1232×752 |
| 耗时 | side **16.5s** ｜ 3q4_left **18.6s** ｜ front **16.6s** |
| 产出 | `outputs/GF/{side,3q4_left,front}/ai_render_*.png` ｜ 对照图 `outputs/_对比/GF_0926_0847.jpg` |

**逐机位判读**

| 机位 | 轮廓/大体块 | 材质方向 | 表面细节 | 文字 |
|---|---|---|---|---|
| side | ✅ 与 CAD 完全一致 | ✅ 白壳 + 黑目镜 | ❌ 臆造了一块**CAD 里没有的黑色格栅** | ✅ 未生成 |
| 3q4_left | ✅ 双前镜/目镜/按键全中 | ✅ 接近参考图 | ❌ 侧面被加了竖纹 | ✅ 未生成 |
| front | ✅ 双镜筒 + 黑边 + 白机身 | ✅ | ⚠️ 轻微 | ✅ 未生成 |

### 记录 2-6 ｜ 强度对照实验（9-26）

| 强度组合 | 结果 |
|---|---|
| depth 0.65 / normal 0.45 | 结构对，臆造明显 |
| depth 0.80 / normal 0.55 | **最优平衡**（推荐默认） |
| depth **1.00** / normal **0.90** | ❌ **更差**：画面被放大裁切、臆造依旧 |

> **结论**：**靠调强度解决不了表面臆造**。要锁表面细节必须加控制链（clay→lineart/canny），或干脆走「结构优先」用真渲染做产品像素。

### 耗时对照（★需回填文档 15.4）

| 场景 | 8GB 上单张耗时 |
|---|---|
| 过程文档 15.4 原估算 | 60–120 秒 |
| 实测：文生图 1024²，8 步 | **18.1 秒** |
| 实测：+ControlNet tile，1232×752 | **20.1 秒** |
| 实测：**双 ControlNet**（depth+normal），1232×752 | **16.5–24.6 秒** |
| 实测：**真实产品仿图**（GF 三机位） | **16.5 / 18.6 / 16.6 秒** |

> Lightning 版把 8GB 单张耗时压到 **16–25 秒**，比原估算快 **3–6 倍**。

---

## 三、现在能跑什么 / 还不能跑什么

| | 说明 |
|---|---|
| ✅ **能** | ① 从 3D 模型**一条命令出全套结构 pass**（`.blend/.glb/.gltf/.obj/.stl/.fbx`）<br>② 控制台**一键出图**（有 depth/normal 自动走双 ControlNet，没有则退回文生图）<br>③ 背景/氛围生成、P0-A 结构优先合成<br>④ 产物自动建档 + QA 报告 |
| ❌ **不能** | ① **真实产品的 P0-B 形准验证**——缺 `LS-360G` 的 3D 源，出不了它的 depth/normal<br>② 丝印 / 刻度 / 量程 / 认证标识的 AI 生成（ADR-002 禁止，必须图层回贴）<br>③ 透明件 / 镜面件（必须走「真渲染合成」兜底）<br>④ API 终稿接入（Provider Adapter 未做，OPT-08） |

---

## 四、生成内容监看（登记区）

> **登记模板**：`日期 ｜ 文件 ｜ 底模 ｜ 关键参数 ｜ 耗时 ｜ 形状 ｜ 文字 ｜ 结论`
> 也可直接跑 `python scripts\make_manifest.py` 自动生成 `outputs/QA报告.md`。

| # | 日期 | 文件 | 模式 | 关键参数 | 耗时 | 形状 | 文字 | 结论 |
|---|---|---|---|---|---|---|---|---|
| 1 | 09-24 | `试跑-2026-09-24/01-纯文生图…png` | 文生图 | 1024²,8步,cfg2 | 18.1s | ❌ 非目标产品 | ❌ 乱码 | 仅对照，不可交付 |
| 2 | 09-24 | `试跑-2026-09-24/02-ControlNetTile锁形…png` | CN tile | 1232×752,tile 0.65 | 20.1s | ✅ 守住 | ❌ 臆造 | 结构可用，质感需换 depth/normal |
| 3 | 09-26 | `_demo/front/ai_render_00001_.png` | **CN depth+normal** | 1232×752, 0.65/0.45 | 24.4s | ✅ 守住 | —（自检几何无文字） | **全链路验证通过** |
| 4 | 09-26 | `GF/side/ai_render_00008_.png` | **CN depth+normal** | 0.80/0.55 | 16.5s | ✅ 轮廓全中 | ✅ 未生成 | 表面**臆造格栅** ❌ |
| 5 | 09-26 | `GF/3q4_left/ai_render_00009_.png` | **CN depth+normal** | 0.80/0.55 | 18.6s | ✅ 双镜/目镜/按键全中 | ✅ 未生成 | 侧面加竖纹 ❌ |
| 6 | 09-26 | `GF/front/ai_render_00010_.png` | **CN depth+normal** | 0.80/0.55 | 16.6s | ✅ 高吻合 | ✅ 未生成 | **本次最佳** |
| 7 | 09-26 | `GF/side/ai_render_00011_.png` | CN 强度实验 | 1.00/0.90 | 16.4s | ⚠️ 被放大裁切 | ✅ | **反面样本：拉满更差** |

> ⚠️ **铁律**：任何含 **丝印 / LOGO / 刻度 / 量程 / 认证标识 / 透明件** 的图都不得由 AI 生成，
> 必须「引擎真渲染 + 图层回贴」（ADR-002）。上面第 1、2 条的文字臆造就是现实依据。

---

## 五、卡点与下一步

### ✅ 已解除：真实样品

`GF.stl` / `银.stl` 可直接用；另外手里还有 **159 GB** 的成图库和 `GF.ksp`（KeyShot 真渲染工程）。

### 🔴 当前最高优先：OPT-04 分层合成（产品像素走真渲染）

17.7 已实证：AI 参与产品本体会**臆造 CAD 里不存在的表面特征**。所以：

1. **产品本体像素用真渲染**（`GF.ksp` 在 KeyShot 里出图），AI **只出背景/氛围**，再合成；
2. **Logo / 屏幕 / 刻度 / 认证标识** 全部图层回贴（ADR-002），不许 AI 生成。

### 🟠 P1：接着做

- **第三条 ControlNet 链（clay → lineart/canny）**：验证能不能压掉表面臆造。这是「AI 参与本体」路线能不能成立的关键实验（对应 OPT-12）。
- **OPT-08 Provider Adapter**：Nano Banana / GPT-Image-2 接进来做终稿。
- **OPT-07 参考图特征分离**：需要先装 IPAdapter Plus。

### 📌 需要你提供 / 决策的一件事

`GF.stl` 是**单网格**（部件已合并），所以 `objectid` 只能出一整块，做不了「部件级局部重绘」。
如果你能从 Rhino 或 KeyShot 导出 **`.glb` / `.obj`（保留部件层级）**，或者直接给 **`.ksp`**——
那么「部件级蒙版 + 局部编辑」这条更高级的路线就能开跑。

### 🟢 P2：顺手

- 本节耗时表已回填 `00 文档` 15.4；「首选底模 = Lightning」已写进 `config/render_defaults.json`。

---

## 六、常用命令速查

```powershell
# ── 一键全起（ComfyUI + 控制台 + 开浏览器）──
启动全部.bat

# ── 分开起 ──
启动ComfyUI.bat                      # ComfyUI → http://127.0.0.1:8188
启动控制台.bat                        # 控制台 → http://127.0.0.1:8765
```

```powershell
# ── 出结构 pass（OPT-01）──
# 方式一：把 3D 模型拖到 scripts\出pass.bat 上
# 方式二：命令行
scripts\出pass.bat "D:\模型\LS-360G.glb" LS-360G front
# 自检（不需要模型）
scripts\出pass.bat --self-test

# ── 仿图（真实产品）──
# 1) 参考图只读索引 + 缩略图（源图几十 MB 打不开时用）
python scripts\make_ref_sheet.py --tag GF --src "F:\ID设计-杨\GF望远镜改款\渲染图"
# 2) 出结构 pass（把模型拖到 scripts\出pass.bat 上，或命令行）
python scripts\blender_pass.py  # 实际由出pass.bat 调起，见上
# 3) 仿图出图（走控制台 API）
python scripts\imitate_render.py --sku GF --view 3q4_left --preset white_black_rubber --depth-w 0.80 --normal-w 0.55
# 4) 生成对照拼图
python scripts\make_compare.py --sku GF --views side,3q4_left,front

# ── 建档 + QA ──
python scripts\make_manifest.py
```

```bash
# ── 服务自查 ──
curl http://127.0.0.1:8188/system_stats
curl http://127.0.0.1:8765/api/comfy/status        # 控制台看到的 ComfyUI 状态
curl http://127.0.0.1:8765/api/assets              # 投放区就绪度
```

**目录速查**

| 位置 | 内容 |
|---|---|
| `F:\AI-Renderer\packs\ComfyUI_windows_portable\` | ComfyUI 运行时 |
| `F:\AI-Renderer\models\` | 模型本体（18 GB，不复制） |
| `D:\Dsektop\AI渲染\assets\passes\<SKU>\<机位>\` | **结构 pass 投放区**（clay/alpha/depth/normal/objectid） |
| `D:\Dsektop\AI渲染\outputs\<SKU>\<机位>\` | **出图结果**（控制台直连时自动落这里） |
| `D:\Dsektop\AI渲染\outputs\artifact_manifest.json` | 工件清单（可复现档案） |
| `D:\Dsektop\AI渲染\outputs\QA报告.md` | 自动 QA 报告 + 待人工确认清单 |
| `D:\Dsektop\AI渲染\config\comfy_workflow_*.json` | ComfyUI 工作流模板（与 SLOTS 对齐） |
| `D:\Dsektop\AI渲染\config\render_defaults.json` | 出图参数基线（底模/步数/cfg/采样器） |
