# AI 白模渲染器 · 方案资料包

> 目标：把「白模（无材质灰模）」自动变成可用于电商主图 / 详情页的写实产品图。
> 支持三种输入方式：**文字描述**、**结构化参数卡**、**参考产品图仿照**。
> 全流程可批量、可断点续跑、可接详情页 PSD 模板。

---

## 文件导航

| 文件 | 内容 | 什么时候看 |
|---|---|---|
| **`web/`** | **网页版控制台**：一屏出图台（材质预设 / 一键场景 / 实时提示词 / 任务卡片网格）+ 队列，对齐校验 / 项目看板 / 投放区 / 变更记录收在 `⋯` 抽屉 | **直接双击 `启动控制台.bat`** |
| **`assets/`** | **投放区（v1.5）**：`白模/` 放 3D 源文件，`passes/` 放渲染好的 clay/depth/normal 图。**丢进去就会自动归类，不用手打路径** | **要出图时，先看这里** |
| `web/preview/` | 界面截图（9 张），新界面观感参考 | 想先看长什么样时 |
| `web/index.classic.html` | v1.1 的六页版界面，保留作对照 | 想对比新旧信息架构时 |
| **`00-AI白模渲染器-过程文档.md`** | **总纲（唯一权威文档）**：设计理念、设计分析（含 **14 项 ADR**）、可行性分析、实用性分析、GitHub 调研、**云端 API 方案调研（第十四章，含价格与可行性）**、**本机运行可行性（第十五章，含本机显存预算与「中转站」辨析）**、参数基线、脚本要点、四阶段路线、QC 清单、风险登记册 | **先看这份。后续所有更新都在这里留痕** |
| `01-技术方案.md` | 技术方案展开版（架构 / 选型 / 参数 / 阶段 / 风险） | 需要看方案细节时 |
| `02-GitHub参考项目调研.md` | 30+ 开源项目，含链接、许可、可抄点 | 准备动手搭环境时 |
| `03-配置与脚本模板.md` | KeyShot headless / Blender pass / 对齐校验 / ComfyUI 批处理 / 提示词模板库 / PS 回贴脚本 | 开始写代码时 |
| `04-落地检查清单.md` | 从 0 到量产的逐项勾选 + QC 标准 | 每个阶段验收时 |
| **`05-P0形准验证方案.md`** | **P0 硬门槛的执行手册（v1.6 新增）**：本机适配的环境与模型清单、出 pass 步骤、对齐校验、最小工作流、判据三层、失败诊断决策树、记录表、5 天时间盒 | **动手前先读这份** |
| **`scripts/下载模型.bat`** | **一键下载运行时与模型（v1.7 新增）**：ComfyUI 官方便携版 + SDXL 写实底模 + ControlNet-union + VAE，共约 **10.9 GiB**。可续传、自动重试、下完自动体积校验并算 SHA-256 | **第一次跑之前，双击这个** |
| `scripts/download_models.ps1` | 上者的 PowerShell 实现（断线重跑即续传，已完成的文件不重下） | 想看/改下载源时 |
| **`scripts/出pass.bat`** | **一键出结构 pass（OPT-01）**：把 3D 模型**拖上去**就行，输出 `clay/alpha/depth/normal/objectid` 到投放区。`--self-test` 可用内置几何自检 | **有 3D 模型时，先跑这个** |
| `scripts/blender_pass.py` | 上者背后的 Blender 脚本（固定相机、同尺寸同裁切、色彩空间明确、可重跑） | 想调相机/分辨率/采样时 |
| **`scripts/make_manifest.py`** | **工件清单 + QA 报告（OPT-05/06）**：产物自动建 `artifact_manifest.json`（哈希/尺寸/参数）并生成 `QA报告.md` | **出完图归档时** |
| `scripts/comfy_smoke_test.py` | 命令行出图冒烟测试（文生图 / ControlNet 锁形），纯标准库 | 想跳过界面直接验证时 |
| **`启动全部.bat`** | **一键同时启动 ComfyUI + 网页控制台并打开浏览器** | **日常开工** |
| `config/comfy_workflow_*.json` | ComfyUI 工作流模板，节点 ID 与前端 `SLOTS` **严格对齐**（文生图 / 双 ControlNet） | 想改工作流时 |
| `config/render_defaults.json` | 出图参数基线（底模 / 步数 / cfg / 采样器 / ControlNet 类型） | 想改默认参数时 |
| **`TEMP-出图监看.md`** | **临时监看板**：就绪度总表 + 实测出图记录 + 待办（非权威，结论稳定后并入 00 文档） | 想看当前进度时 |
| `config/` | 参数卡 schema（接口契约）+ 示例参数卡 | 配置阶段 |
| **`web/index.html` · `web/styles.css` · `web/app.js`** | **「形照」控制台（v1.9 重构）**：三步式出图台 + 预览舞台 + 六个管理面板（投放区 / 对齐校验 / 参数卡 / 服务详情 / 看板 / 变更记录） | **UI 全在这里** |
| `web/index.v17.html` | v1.7 的单文件控制台，**归档留对照**，不再维护 | 想看旧版时 |
| `web/index.classic.html` | v1.1 的六页版，最早的对照件 | 想看最早版本时 |
| `ui/` | 「形照」的**设计存档**（已合并进 `web/`），可删 | 只作参考 |
| `启动控制台.bat` | 一键启动控制台（新界面） | 想用工具时 |

> ⚠️ **留痕约定**：`00-...过程文档.md` 是 Single Source of Truth。任何结论、参数、决策的变更，都必须先在该文档「二、变更记录」登记，再改正文并在章节末尾留痕。`01`–`04` 是它的展开与补充，不作为权威来源。控制台的「变更记录」页面只读展示该文档，**不代替文档留痕**。

---

## 「形照」控制台（v1.9 重构）

```powershell
# 一键全起（ComfyUI + 控制台 + 自动开浏览器）
启动全部.bat

# 只起控制台
启动控制台.bat

# 命令行
python web/server.py            # 默认 http://127.0.0.1:8765
python web/selftest.py          # 后端自检，16 项断言
python web/test_assets.py       # 投放区归类自检，20 项断言
```

零第三方依赖（Python 标准库）。界面是**三步式工作台**：

```
1 选择产品  →  2 描述想要的效果  →  3 检查并出图
左侧控制栏                     右侧「产品预览」舞台（白模 / 深度 / 成图 三态切换）+ 候选图网格
```

右上「任务」抽屉里除结构图准备与任务列表外，还收着六个管理面板：

| 面板 | 作用 |
|---|---|
| **投放区总览** | SKU × 机位就绪度矩阵，哪个机位缺 depth/normal 一眼看到 |
| **对齐校验 · 轮廓 IoU** | 白模掩膜 vs 成图剪影，**画布内算 IoU + 三色叠加图**，门槛 0.90 直接判通过/未达标 |
| **参数卡 · RenderSpec** | 载入 / 保存参数卡（材质·配色·灯光·背景·张数） |
| **渲染服务详情** | ComfyUI 版本·显卡·显存·底模·Blender 路径·脚本就位情况 |
| **项目看板** | 阶段与硬门槛 |
| **变更记录** | 只读展示 `00 文档` 第二节 |

**已直连本机 ComfyUI**：按 `SLOTS` 契约把任务填进工作流模板提交给 `127.0.0.1:8188`，轮询完成后把图拉回落进
`outputs/<SKU>/<机位>/`。**有 depth/normal 自动走双 ControlNet 锁形**；顶部状态点实时显示 ComfyUI 在线与否。

> ⚠️ **护栏**：选了「结构约束出图」但该机位缺深度图时，**界面会直接拦住、不会偷偷降级成纯文生图** ——
> 免得你以为锁了形其实没锁（这条风险已实测过，见 `00 文档` 17.7）。

---

## 参考图怎么用（v1.10 接入）

在第 2 步「描述想要的效果」里有一块**参考图**：

1. **上传参考图** → 存到 `assets/refs/<SKU>/`（只新增不覆盖，重名自动加序号）
2. 自动提取 **6 个主色 + 影调**（浏览器 canvas 内完成，零依赖）
3. 选**参考强度**（ADR-005 要求显式选择）：

| 档位 | 借什么 |
|---|---|
| **L1 风格轻参考** | 只借氛围与光感 |
| **L2 材质参考**（默认） | 借材质、配色与表面处理 |
| **L3 整体仿照** | 借材质、配色、光照与构图（**仍不改形状**） |

4. 点任一色块可直接**设为主体色**；出图时提示词会自动追加一段，例如：

   > `Borrow materials, colour palette and surface finish from a supplied reference photo. Its dominant colour palette is #828282, #787878, #292929, #181917. clean mid-grey seamless background, soft studio lighting. Do not copy the reference product's silhouette; keep the supplied product shape.`

**已接入 IPAdapter（v1.11）—— 图片真正参与生成**：

- 参考图经 **CLIP-ViT-H** 编码后注入模型交叉注意力，**同时**把配色与影调写进提示词。
- 三档强度映射：`L1` → weight 0.35 + `style transfer` ｜ `L2` → 0.55 + `linear` ｜ `L3` → 0.75 + `linear`。
- 实测：`with_ref=True`，**8GB 显存未爆**，单张 **36.2 s**（不带参考图约 17 s）。材质真实感明显提升，
  先前「AI 臆造格栅」的现象消失。对照图见 `outputs\_对比\GF_参考图接入对照.jpg`。
- 装了 `ComfyUI_IPAdapter_plus`（**GPL-3.0**，本地工具）+ `ip-adapter-plus_sdxl_vit-h`（**apache-2.0**）
  + `CLIP-ViT-H-14-laion2B-s32B-b79K`（**apache-2.0**），权重均按官方 SHA-256 校验通过。

**边界（界面如实标注，不假装）**：

- ⚠️ **不改形状**：参考图只影响材质与配色；**形状的最终约束仍是 ControlNet 的深度/法线图**，
  提示词里也固定带 `Do not copy the reference product's silhouette`，与「参考图只借视觉特征」原则一致。
- 界面会显示当前参考图处于哪种生效方式（`ipadapter+prompt` 或仅 `prompt_palette_only`）。
- （FLUX Redux 那条路仍然否决：权重属 FLUX.1 [dev] 家族＝**非商用**，且本机 8GB 跑不了 FLUX + ControlNet。）

确切文件、坑与接线细节见 `00-...过程文档.md` **第十九章 19.4 / 19.6**。

> **启动排错**：双击后若窗口一闪而过，多半是 `.bat` 被文本编辑器存成了 LF 换行——本机 `cmd.exe` 会因此报「此时不应有 ‖」。批处理必须为 **CRLF + cp936** 编码，且只用 `if errorlevel` + `goto` 分支。端口 8765 被旧实例占用时服务会自动改用 8766（最多 +20），不会启动失败。详见 `00-...过程文档.md` 第 10.4 节。

---

## 白模怎么放进来（v1.5）

**不用手打路径了。** 所有素材都从**投放区**进：

```
assets/
├── 白模/                  ← 3D 源文件（.ksp / .blend / .glb / .fbx / .stp …）
│   └── LS-360G.ksp
├── passes/                ← 白模渲染出的 pass 图
│   └── LS-360G/           ← 目录名 = SKU
│       ├── front/         ← 目录名 = 机位
│       │   ├── clay.png   ← 文件名 = 通道
│       │   ├── depth.png
│       │   └── normal.png
│       └── 3q4_left/
│           ├── clay.png
│           └── depth.png
├── refs/                  ← 参考图（v1.10）：只借配色/材质/光照，不换形状
│   └── LS-360G/
│       └── ref_01.jpg
└── _待归类/                ← 认不出来的先扔这儿，绝不丢文件
```

**三种投放方式，效果一样：**

1. **拖** —— 把文件或**整个文件夹**拖到出图台的「白模投放」区（会自动读子目录、递归上传）
2. **拷** —— 用资源管理器拷进 `assets/`，界面里有「打开投放区」按钮一键跳过去
3. **灌** —— `robocopy` 批量拷，刷新页面即重新扫描

**命名随便写，中英文都认：** `LS-360G_左前_法线.png`、`LS-360G/front/depth.png`、`正面/深度.png` 都能正确归位。
昵称对照：机位认 `front/正面` `3q4_left/左前` `side/侧面` `top/俯视` `detail_window/透明件`；通道认 `clay|beauty|白模` `depth|深度` `normal|法线` `alpha|蒙版`。

**规整性检查在界面上直接看：** 每个机位必须凑齐 `clay` + `depth` + `normal` 三件才能跑 ControlNet，缺哪个会标红；点文件名能直接预览。

> **原则：只新增，不删除、不改名。** 同名冲突默认覆盖（重传同一张图是常态），可改成自动加 `_2` 保两份。原文件任何时候都不会被移动或删除。
> 如果 pass 已经渲染在别的位置（比如 KeyShot 输出目录），不用搬 —— 在「高级 → 关键参数 → Pass 根目录」改 `_pass_dir` 指过去即可。

---

## 一句话结论

**没有现成的「白模 → 写实产品图」一站式开源项目**，必须自己组装。但每一段都有成熟轮子：

```
白模 ──▶ 多通道 Pass ──▶ 结构控制 + 参考图注入 + 重打光 ──▶ 后处理 ──▶ 交付
         (KeyShot/Blender)   (ComfyUI / ControlNet / Redux / IC-Light)   (抠图/超分/贴字)
```

最接近的两个参考架构：
- **OpenX-Inc/clay** —— 「编排器 + 可插拔模型 + 引擎后处理」的架构范式，直接照抄它的组织方式
- **DLR-RM/BlenderProc** —— 程序化出 pass（RGB/depth/normal/seg）的工程实现

---

## 三条路线速览

| 路线 | 做法 | 单张耗时 | 适合 | 短板 |
|---|---|---|---|---|
| **A. 2D 图像侧**（主力） | 白模出 depth/normal → ControlNet 锁形 → 参考图注材质风格 → IC-Light 重打光 | 6–30s | 批量、多风格、快速迭代 | 丝印/刻度/透明件会漂 |
| **B. 3D 材质侧**（辅助） | DreamMat / Hunyuan3D-2.1 / TRELLIS.2 给模型生成真 PBR 材质，再真渲染 | 10min–1h/模型 | 需要多视角成套图、要真材质 | 慢、几何要求高、部分许可非商用 |
| **C. 引擎内置 AI**（对照） | KeyShot 2026.1 自带 AI Shots（本地跑，定制 Qwen），可 Transform / Replace | 数十秒 | 单件精修、赶单 | 不可批量编排、不可版本控制 |

**推荐：A 为主 + B 为辅 + C 做单件兜底。** 详见 `01-技术方案.md`。

---

## 不买显卡能不能跑？（v1.4 新增调研）

结论先说：**能，但不能靠「调图像 API」，要靠「租 GPU 跑自己的工作流」。**

| 路线 | 做法 | 单张成本 | 能否锁形 | 1000 张 |
|---|---|---|---|---|
| **R-A 本地 ComfyUI** | 自有显卡跑 ControlNet Depth | ≈¥0.02–0.05（电费） | ✅ | ¥20–50 |
| **R-D 托管 ComfyUI** | 把同一套 workflow 上传到 RunComfy / RunPod，按 GPU 秒付费 | ≈¥0.12 | ✅ | ¥120–190 |
| **R-C1 FLUX.1 Depth [pro]** | 官方 control 模式，接受 depth map，一次调用同时锁形 + 上材质 | ≈¥0.36–0.43 | ✅ | ¥360–430 |
| **R-C 其他图像 API** | Seedream 5.0 / Nano Banana / GPT Image / Kontext / Qwen-Image-Edit | ¥0.28–0.30 | ❌ **不能** | ¥140–300 |

> **关键判断**：除 **FLUX.1 Depth** 与 **托管 ComfyUI** 外，**所有公共图像 API 都不接受 depth/normal 结构图** —— 它们把输入图当语义暗示而不是几何约束，出来的图「漂亮但不是同一台仪器」。
> 本项目 P0 的验收线是 **IoU ≥ 0.90**，所以「纯 API 出图」这条路在激光水平仪 / 气体检测仪这类目上**不成立**。

全部价格、来源、可行性分析与接入前置要求（账号 / 资质 / 内容审核 / 数据出境 / QPS 提额）见 `00-...过程文档.md` **第十四章**。

---

## 这台电脑能跑什么？（v1.6 新增）

本机实测：**RTX 4060 Ti 8GB** / i5-14600KF / 32GB DDR5 / F 盘 212GB / **没装 git、pip、conda**。

**能装，且不用配环境** —— 用 ComfyUI **官方 Windows 便携版**（自带 Python 3.13 + PyTorch CUDA），解压双击就跑，全程不需要 git / pip。

| 组合（1024px） | 峰值显存 | 本机 8GB | 单张 |
|---|---|---|---|
| **SDXL + depth 单 ControlNet** | 10–14GB | ⚠️ 靠 `--lowvram` 硬撑 | **60–120s** |
| FLUX GGUF Q4 底模（无 ControlNet） | ~7GB | ✅ 能跑但慢 | 90–150s |
| **FLUX + ControlNet** | **20–22GB** | ❌ **不可用** | — |

> ⚠️ 文档里「SDXL+2CN = 6–10s」「FLUX+2CN = 18–30s」是 **4090 级**数据，**本机要按 5–10 倍折算**。
> ⚠️ **FLUX.1 [dev] 权重是非商用许可** —— 本地跑商用图不合规，商用要换 schnell / Klein。

**「中转站」要分两种，结论完全相反**：

| | 图像 API 聚合 | 托管 ComfyUI（R-D） |
|---|---|---|
| 观感 | 更好看 ✅ | 好 |
| **锁形（depth/normal）** | ❌ **完全不接受** | ✅ 同一套工作流 |
| 1000 张 | ¥280–430 | **¥120–190 / 4–7 小时** |

→ 前者「更好看」在本项目里是**无效优势**（锁不住形，过不了 P0）。后者**比本机更快更全，画质只升不降**。
→ **本机定位：验证 + 打样。量产走托管，不需要升级显卡。** 详见 `00-...过程文档.md` **第十五章**。

---

## 与 mac 分支方案的融合（v1.7 新增）

`ai渲染mac/` 下另有一套平行方案（经 Codex with ChatGPT 审阅）。v1.7 做了 **15 项逐项裁决**：吸收 8 项、保留 5 项、合并 2 项 —— 详见 `00-...过程文档.md` **第十六章**。

最重要的三件事：

1. **P0 判据从「一句话否决」改成两级**，项目不再被单点风险卡死：
   - **P0-A 结构优先（低风险硬门槛）** —— 产品本体像素 100% 来自 KeyShot/Blender，AI 只做背景。与原始方案 diff = 0，几乎不会失败。
   - **P0-B 创意探索（高风险升级项）** —— 只开 Depth ControlNet、prompt 不写形状词，出图须「一眼辨认为同一产品」，`align_check.py` IoU ≥ 0.90。过了才升到 A 级路线。
2. **新增 5 条架构决策（ADR-015~019）**：结构优先默认 / 确定性基线可独立交付（`baseline_completed`）/ 全 pass 走工件清单 + 哈希 + 色彩空间约定 / KeyShot 出本体、Blender 出控制图 / 云端 API 分层使用且不硬编码模型名。
3. **纠正了两个已下线的 API 模型**（`gpt-image-1`、`gemini-2.5-flash-image`），补上 **Batch 档半价** 这个省钱杠杆，并新登记 **Gemini 出图带 SynthID 隐形水印 + C2PA** 的商用风险。

> **本机定位不变**：验证 + 打样；量产走托管 ComfyUI（R-D）。本机装的是 **SDXL 系**（不是 FLUX），8GB 显存靠 `--lowvram` 跑得动 depth 单 ControlNet。

---

## 第一次跑之前：下运行时与模型

**双击 `scripts/下载模型.bat` 就行。** 它会往 `F:\AI-Renderer\` 拉这 5 个文件（共约 **18.6 GiB**）：

| 文件 | 体积 | 许可 | 放到哪 |
|---|---|---|---|
| `ComfyUI_windows_portable_nvidia.7z` | 1.79 GiB | GPL-3.0（工具本身，不注入产出物） | `packs/` → 解压 |
| `RealVisXL_V5.0_Lightning_fp16.safetensors` | 6.46 GiB | **openrail++**（可商用，**4–8 步采样**） | `models/checkpoints/` |
| `sd_xl_base_1.0.safetensors` | 6.46 GiB | **OpenRAIL++-M**（官方底模，对照用） | `models/checkpoints/` |
| `controlnet-union-sdxl-1.0-promax.safetensors` | 2.34 GiB | **Apache-2.0** | `models/controlnet/` |
| `sdxl_vae.safetensors` | 0.32 GiB | **MIT** | `models/vae/` |

- **可续传**：断线/关机后**重新双击即可**，已下好且校验通过的文件不会重下。
- **校验**：下完按**字节数 + SHA-256** 双查（SHA-256 取自源站官方字段），并写入 `F:\AI-Renderer\sha256.txt`。ComfyUI 压缩包另用 `WinRAR t` 做完整性测试。
- **下载源**（2026-09-24 本机实测）：底模走 **ModelScope（17–19 MB/s）**；ControlNet / VAE 走 `hf-mirror.com`（2–5 MB/s，波动大）；ComfyUI 便携版只能走 GitHub 加速站 `ghfast.top`——**它只放行 Range 请求，所以脚本里对这一个文件用分块下载**。
- 下完解压：本机有 **WinRAR**（`C:\Program Files\WinRAR`），右键 → 解压到当前文件夹即可（没有 7-Zip 也没关系）。

> ⚠️ 计划里原本要的标准版 `RealVisXL_V5.0_fp16` 在 ModelScope 无镜像、HuggingFace 侧只有 0.2–0.9 MB/s，未取到；现用同族的 **Lightning 版**（对 8GB 显存更友好）+ 官方 **SDXL base 1.0** 替代。三者同为 SDXL 1.0 架构，**流水线与 ControlNet 无需改动**。

---

## 现在怎么出图（三步）

> 环境、模型、运行时**都已就位并实测通过**（18–25 秒/张）。下面是从零到一个成品的完整链路。

```powershell
# ① 开工：一键起 ComfyUI + 控制台（并自动打开浏览器）
启动全部.bat

# ② 出结构 pass：把 3D 模型【拖到 scripts\出pass.bat 上】就行
#    → 自动产出 assets\passes\<SKU>\<机位>\{clay,alpha,depth,normal,objectid}
#    没有模型想先试：scripts\出pass.bat --self-test
#    ⚠️ 只吃 .blend/.glb/.gltf/.obj/.stl/.fbx；.ksp/.stp/.3dm 请先在原软件导出 .glb

# ③ 出图：在控制台里 生成任务 → 到「队列」点该行的「▶」
#    有 depth/normal 自动走【双 ControlNet 锁形】，没有则退回纯文生图
#    顶部徽标绿 = ComfyUI 在线；结果自动落到 outputs\<SKU>\<机位>\

# ④ 归档：自动建工件清单 + QA 报告
python scripts\make_manifest.py     # → outputs\artifact_manifest.json + outputs\QA报告.md
```

**两条红线**（详见 `00-AI白模渲染器-过程文档.md`）：
- ⛔ **丝印 / LOGO / 刻度 / 量程 / 认证标识 / 透明件** 一律**不得由 AI 生成**，必须引擎真渲染 + 图层回贴（ADR-002）。实测已两次出现文字被臆造。
- ⛔ **不许用 `controlnet_aux` 的预估深度冒充真 pass**；有 3D 就用 `出pass.bat` 出真几何深度。

逐项执行细节见 **`05-P0形准验证方案.md`**，当前进度见 **`TEMP-出图监看.md`**。
