# Qwen-Image-2.1：Windows 下载、安装、测试与模型切换执行方案

> 制定日期：2026-09-29。状态：**待 Windows 实施与验收**。本文是执行方案，**不是已安装、已接入或已证明画质更好**的记录。
> 适用机器：RTX 4060 Ti 8GB、i5-14600KF、32GB RAM；已安装本项目与 ComfyUI。Windows 执行方按阶段记录实际版本、耗时、峰值显存和样张；不能把本文的估计写成实测。

## 0. 先读：本次目标和使用范围

当前稳定链路是 `白模 → Blender 白模/深度/法线 → SDXL + ControlNet → 质检`，图片模式是 `原图 → SDXL img2img + Canny → 质检`。Qwen-Image-2.1 **先作为单独的图片编辑实验引擎**，输入同机位白模截图、产品照片或参考图，评估材质、灯光、氛围和产品保持能力；不得仅更换 checkpoint 文件名来复用 SDXL 工作流。原 SDXL 链路和一键启动保持不变。Qwen 不能自动修复缺失/过期深度图、错误机位、CAD 导入失败，也不能保证孔位、文字和尺寸。

**本阶段按个人本地研究/试用推进**：下载、安装、对比测试和在个人程序里加入实验模型选项，不必等商用许可手续。Qwen-Image-2.1 官方权重采用 Qwen Research License，研究/评估与商业使用的条件不同；若以后用于收费客户项目、对外提供服务或正式商业交付，再核对当时的[官方许可](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/LICENSE)，必要时取得相应授权。项目 `AI/DECISIONS.md` 的 ADR-008 是**商用选型**规则，不阻碍本次个人试验；ADR-001 的结构保真要求仍要测试。第三方量化版不会自动改变底模许可。无论用途如何，不要把他人的 CAD、产品图、密钥或模型权重上传公开 GitHub。[官方仓库](https://github.com/QwenLM/Qwen-Image-2.1)

## 1. 环境隔离与容量检查（Windows，预计 15 分钟）

1. 保留现有 `F:\AI-Renderer\packs\ComfyUI_windows_portable` 与项目根目录，不在其上直接覆盖更新 Qwen。另建实验目录 `F:\AI-Renderer\experiments\Qwen21\`；若 F 盘空间不足，换到剩余更多的盘，所有路径随实际位置替换。
2. 在 PowerShell 运行 `nvidia-smi`，记录驱动版本、显卡名称和空闲显存；运行 `Get-PSDrive F,D` 记录剩余空间。下载前建议实验盘至少预留 **35 GB**（便携运行环境、三个权重、缓存与输出的规划余量，**不是模型官方最低空间要求**）。
3. 记录原项目 Git 分支/提交、现用 ComfyUI 版本、现有 SDXL 单张出图能否成功。只记录路径和版本，不复制客户素材到实验目录。
4. 测试时先关闭现有 ComfyUI 任务，避免两个进程争抢同一块 8GB 显存；不要在真实长批次任务运行时更新或安装模型。

验收：原程序仍能独立启动，`nvidia-smi` 可读，实验目录与正式 ComfyUI 目录分开。失败则停在本阶段。

## 2. 下载并安装独立 ComfyUI（预计 20–60 分钟，取决于网速）

1. 从 [ComfyUI 官方 Windows 便携版发布页](https://github.com/Comfy-Org/ComfyUI/releases)下载当前适配 NVIDIA 的便携版，解压到 `F:\AI-Renderer\experiments\Qwen21\ComfyUI_windows_portable\`。不要下载来历不明的“一键整合包”。解压后应看到 `ComfyUI\main.py`、`python_embeded\python.exe` 和启动脚本；如目录层级不同，以实际解压结构为准。
2. 如官方 2.1 模板提示节点缺失，先使用该便携版自带的更新机制更新**实验实例**，不要更新正式实例。记录更新前后版本和报错；不推荐在没有备份的正式 ComfyUI 上直接 `git pull`。
3. 用 PowerShell 进入实验便携版根目录，先确认路径：

   ```powershell
   cd 'F:\AI-Renderer\experiments\Qwen21\ComfyUI_windows_portable'
   Test-Path '.\python_embeded\python.exe'
   Test-Path '.\ComfyUI\main.py'
   ```

4. 两项均为 `True` 后启动实验实例（端口 8190，避免覆盖正式的 8188）：

   ```powershell
   .\python_embeded\python.exe -s .\ComfyUI\main.py --windows-standalone-build --lowvram --port 8190
   ```

5. 浏览器打开 `http://127.0.0.1:8190/`，确认页面出现。首次安装阶段不连接本项目网页；若报 CUDA/驱动/节点错误，保存终端最后 100 行脱敏日志并停止，不要反复安装不同社区包碰运气。

验收：实验 ComfyUI 可独立访问，正式端口 8188 配置未改动。

## 3. 下载三个模型文件（预计 20–90 分钟）

从 [Comfy-Org 官方适配文件页](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main)下载**实际所需的三个文件**。通过网页逐项下载并放到下列目录；浏览器下载完成后核对文件大小非零、扩展名是 `.safetensors`，不要下载网页的几 KB 指针文件。文件名以下载页最新实际名称为准，变更时同时更新执行记录。

| 角色 | 8GB 首测选型 | 放置目录 |
|---|---|---|
| 扩散模型 | `qwen_image_2.1_int8_convrot.safetensors` | `ComfyUI\models\diffusion_models\` |
| 图文编码器 | `qwen3vl_8b_w4a8.safetensors`；若实验模板不兼容，再试官方 `qwen3vl_8b_int8_convrot.safetensors` | `ComfyUI\models\text_encoders\` |
| 图像 VAE | `qwen_image_2.1_vae_bf16.safetensors` | `ComfyUI\models\vae\` |

不要一开始下载 BF16 主模型、BF16 编码器、提示词增强器、多张参考图组件或额外 LoRA。INT8 主模型文件约 7.26 GB，**文件体积不等于运行显存**；编码器和 VAE 还会占资源。8GB 能否跑通由 Windows 实测决定。官方下载页给出了目录及[文生图模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_t2i.json)、[图片编辑模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_image_edit.json)。

下载校验建议（在实验实例根目录；文件名若变更需替换）：

```powershell
Get-Item '.\ComfyUI\models\diffusion_models\qwen_image_2.1_int8_convrot.safetensors', '.\ComfyUI\models\text_encoders\qwen3vl_8b_w4a8.safetensors', '.\ComfyUI\models\vae\qwen_image_2.1_vae_bf16.safetensors' | Select-Object Name,Length
```

验收：三项存在、体积非零、ComfyUI 重启后下拉可选。缺项时**不进入下一阶段**。

## 4. 先在独立 ComfyUI 做最小试跑（预计 30–90 分钟）

1. 在 8190 的 ComfyUI 模板库打开 **Qwen Image 2.1 Text to Image** 官方模板。模板中手工选中上节的三个实际文件；若默认指向 BF16 或附带 prompt enhancer，先改为已下载的低显存文件并关闭增强器。不要把 SDXL 的 ControlNet 或 IPAdapter 节点拖进来。
2. 第一次只做**一张、一个种子、低分辨率**：从 768×768 或与产品画幅接近的 832×512 开始，使用模板默认采样参数，不同时改步数、采样器和精度。Windows 报告记录：输入提示词、种子、最终节点文件名、模型版本、输出尺寸、冷启动时间、单张时间、`nvidia-smi` 峰值显存和系统内存峰值。官方支持 2K 输出不代表此 8GB 卡可直接 2K 生成。
3. 成功后再打开 **Qwen Image 2.1 Image Edit** 模板，输入一张自己的或已获使用许可的白模/产品图，提示词仅要求“保持轮廓、机位、部件数量及孔位，只改变外壳材质为细砂纹深灰塑料，金属件为拉丝铝，柔和影棚灯”。只做一张；图像编辑要确认输出真的变化且主体不是重新设计。
4. 若出现显存不足：保持单张，关闭其他占 GPU 程序；确认 `--lowvram` 与低显存权重；再把尺寸降到 768×768 或更小的近似原比例。仍失败则记录 OOM 并判定“本机原配置不可用”，**不要自动把模型加到正式网页**。
5. 若输出全黑、噪声、纯原图或参考图未生效：核对模板版本、三个模型文件和输入节点连接；保存工作流与日志。不要仅凭 HTTP 成功判定出图成功。

验收：文生图和图片编辑各至少 1 张可打开的 PNG，记录日志与资源峰值；无 OOM、无误用 BF16/未安装组件。只跑通文生图而编辑失败时，不能进入本项目图片编辑接入阶段。

## 5. 与现有 SDXL 做成对画质测试（预计 1–2 天）

**测试素材**：至少 3 个自己的或已获使用许可的产品，分别覆盖复杂孔位、曲面外壳、透明/镜面件；每个取 `front`、`side`、`3q4_left`、`3q4_right` 中至少 3 个机位。先在 v3.4 中重生成并核对白模、深度、法线，确认旧图未混用。测试图若包含他人的未公开设计，不放公开仓库。

**对照设置**：同机位白模或产品照片、同一 CMF 描述、尽量相同画幅；每引擎每机位先 2–3 个固定种子。逐张运行，不能在 8GB 卡上同时启动 Blender、正式 ComfyUI 和实验 ComfyUI。Qwen 先走“白模/照片图片编辑”，SDXL 走项目当前结构约束或 img2img；这是两种不同约束机制，应分别注明，不宣称完全同条件模型榜单。结果统一收集成盲评包，不在文件名暴露模型。

| 指标 | 记录方法 | 判定 |
|---|---|---|
| 可见性 | 四机位白模、深度和成图均可打开，非空白 | 任一机位空白即该流程不通过 |
| 结构保真 | 人工逐一核对轮廓、孔位、窗口、部件数、文字/LOGO | 关键结构错位、凭空新增即标记失败；辅助轮廓指标不能替代人工 |
| CMF/美感 | 两位评审盲评材质真实感、纹理、工艺、灯光，各 1–5 分 | 记录逐张分数、分歧及最差样例；不只展示最佳图 |
| 稳定性 | 成功数 / 提交数、OOM、重试、冷启动与单张耗时 | 日常默认模型决策前建议完成至少 18 张小样；个人单张试用不必等待这一步，不直接跑 15/30/50 张 |
| 资源 | 峰值 GPU/内存、模型磁盘与输出磁盘 | 8GB 卡不能出现频繁 OOM 或把系统盘耗尽 |

**个人使用的升级门槛（项目建议）**：Qwen 在材质/美感上确有提升、关键结构错误可接受、连续小样无 OOM，就可以作为个人程序里的可选实验模式开放；不必等待大规模盲评或商用授权。若只提升背景/氛围但产品变形，保留为“后期背景/材质探索”，不作为“几何准确”默认引擎。以后用途转为商业交付时再单独核对许可。

## 6. 程序增加“出图模型”选择：实现任务清单（此处尚未写代码）

**建议界面**：在“材质与灯光”之后、“开始生成”之前增加一项 `出图模型`：

- `稳定模式 · SDXL / ControlNet（默认）`：现有路径不变；白模结构约束、图片改图均可用。
- `实验模式 · Qwen-Image-2.1（图片精修）`：第 4 阶段单张图片编辑跑通、实验实例在线即可在个人使用模式下选择；第 5 阶段用于决定是否推荐给日常使用。白模/产品图单张编辑先开放；**纯文字新视角、多视角结构约束、局部掩膜、15/30/50 张批量先禁用**，逐项验收后再开。
- 若未来引入远端商业服务，显示供应商与**真实模型 ID**，另做 API 适配；阿里云公开型号列表未列 `qwen-image-2.1` 时不得假定中转同名接口就是官方 2.1。[阿里云型号列表](https://help.aliyun.com/zh/model-studio/image-model)

实现顺序与代码位置：

1. `config/render_defaults.json` 增加 `render_engines` 配置：`sdxl_controlled` 默认可用；`qwen21_edit_local` 初始 `enabled:false`、`experimental:true`、`comfy_host:http://127.0.0.1:8190`、权重文件名和简短使用范围说明。完成第 4 阶段单张测试后可手动开启，不设置商用许可布尔开关来阻断个人试用。开关不能只由浏览器本地状态决定；服务端仍要校验模型是否可运行。
2. `web/server.py` 增加只读 `/api/renderers`，返回可用状态及原因（模型文件/实验端口/必需节点）；任务载荷新增 `engine_id`，旧任务缺字段默认 SDXL，保持兼容。任务入队和提交时双重校验，Qwen 不可用时返回中文具体原因，**绝不静默降级为 SDXL**。
3. `web/index.html` 与 `web/app.js` 增加下拉及状态文字；选择 Qwen 时提示“实验模式、8GB 速度待测、目前仅图片精修”，另在帮助说明中简述未来商业使用需核对许可；不支持的结构/批次按钮禁用并解释原因。切换模型不改变当前 SKU、机位、CMF、已有任务或默认服务。
4. 将**已在第 4 阶段手工跑通的图片编辑图**从 ComfyUI 导出为 `API format`，另存 `config/comfy_workflow_qwen21_edit.json`；不能直接把官方**界面格式** JSON 当 `/prompt` API JSON。做单独 Qwen 工作流填充器，校验实际节点 `class_type`、输入槽和模型文件；不得复用 SDXL 的节点 ID、采样参数或 ControlNet/denoise 逻辑。
5. Qwen 输出继续写项目 `outputs/<SKU>/<机位>/`，文件前缀或任务元数据标明 `qwen21`；保存 `engine_id`、真实权重文件名/哈希、工作流哈希、种子、输入图哈希、尺寸、耗时、峰值资源和人工 QC 状态。旧结果、旧参数卡保持可读。
6. 队列限制为一次只执行一个 GPU 作业；Qwen 运行时不并发生成 Blender 结构图。失败可回退**下一条新任务**选 SDXL，但不得把失败任务私自改引擎重跑。停止/重启后显示真实任务状态。

**最小测试**：`/api/renderers` 在未安装时返回 Qwen 不可用；旧任务仍走 SDXL；Qwen 选择后载荷与结果均记录 `engine_id`；缺文件、端口离线或错误工作流时准确阻断；一张图片编辑从网页提交、轮询、落盘、预览全通。再做两机位与 3 个种子测试，之后才评估批量。现有 `web/selftest.py` 必须扩展无 GPU 的路由/兼容性契约，Windows 另做 GPU 端到端验收。

## 7. 个人电脑上的日常部署与回退

第 4 阶段单张跑通、网页最小测试通过后，就可以在个人电脑上把 Qwen 作为可选实验引擎使用；第 5 阶段决定是否推荐为日常默认选项。优先仍使用独立 8190 引擎进程，避免升级实验 ComfyUI 破坏原 SDXL 8188；一键启动应继续默认启动稳定版，不自动下载数十 GB 权重。是否自动启动第二进程，以显存/内存实测决定；8GB 卡可能只能**二选一顺序启动**，不能保证双实例常驻。

日常启用前备份并标记原 `config/`、工作流、启动配置；部署后做 SDXL 原链路、Qwen 单图、服务重启和断点续跑回归。出现 OOM、素材漂移或工作流节点不兼容，关闭 `qwen21_edit_local.enabled`，保留原 SDXL 默认路径和历史结果；不要删除模型或用户产物。此回退**不需要改变旧任务记录**。

## 8. Windows 回填模板与完成定义

执行方将脱敏结果写入 `AI/RESULT.md`，并在过程文档新增一条变更记录；Mac 侧据此更新 `AI/REVIEW.md`。首次个人试用至少回填：日期、机器/驱动、ComfyUI 与模板版本、模型文件名、下载/安装检查、文生图和编辑各一张、是否 OOM、单张耗时及峰值显存、结构问题、原 SDXL 是否仍能出图。18 张对照和盲评是决定**是否推荐为日常默认模型**的下一阶段，不阻碍先在个人程序中试用。未实际安装和测试前，本方案仍标记为**待验证**，网页模型选择项仍为**待实现**。
