> # ⚠️ 已归档 · 请勿直接照此执行
>
> **本文是 Mac 侧历史平行方案（v0.4，2026-09-21），已于 2026-09-27 归档。**
>
> | 本文写的 | 当前实际 |
> |---|---|
> | 项目路径 `/Users/a/Desktop/ai渲染` | 真实项目根 `D:\Dsektop\AI渲染\AI渲染` |
> | “本文件是本项目唯一的方案与过程主记录” | **唯一权威文档是根目录 `00-AI白模渲染器-过程文档.md`（SSOT）** |
> | 第 12 节追加登记 | SSOT 的 **§2 变更记录表** 才是登记处 |
> | 各种“尚未安装/未实测”表述 | 属 9-21 当时状态，多数已完成，以 SSOT 为准 |
>
> **保留原因**：其 15 项逐项裁决的原始出处（SSOT v1.7 第十六章引用）。归档文档，仅供追溯。

# 产品白模 AI 渲染器：方案与过程记录

版本：v0.4（加入 Windows 详细执行手册）  
创建日期：2026-09-19，时区 Asia/Shanghai  
项目目录：`/Users/a/Desktop/ai渲染`  
本文件是本项目唯一的方案与过程主记录，后续需求、设计、代码、配置、工作流、模型版本和验证结果的修改均须在第 12 节追加登记。

## 1. 需求与当前交付边界

用户希望制作一个面向产品白模的自动化 AI 渲染器：可以描述产品外观、材质、灯光，也可以提供类似产品图片，让系统参考其视觉风格完成渲染。本次交付是具体实施方案、GitHub 项目调研和持续更新的 Markdown 过程文件；尚未要求本轮实现完整软件。

三类入口必须分开设计：

| 入口 | 系统行为 | 结果性质 |
|---|---|---|
| 已有 3D 白模 + 文字 | 导入几何、确认部件，按描述赋材质与灯光，生成受几何约束的效果图 | 主流程，优先实现 |
| 已有白模 + 类似产品参考图 | 从参考图提取颜色、表面质感、布光与背景，用到自己的白模 | 参考风格，不默认替换自身产品结构 |
| 只有文字或产品照片 | 先产生可编辑概念白模，确认后进入渲染；复杂形状需补图或人工修整 | 第二阶段，不能承诺工程精度 |

补充入口：白模截图可做单视角图生图，但缺少真实几何与背面信息，不应标为可准确多视角渲染的 3D 模型。

暂定使用场景是单用户桌面工作台、静态工业产品效果图。已知目标工作站为 RTX 4060 Ti 8 GB、i5-14600KF、32 GB DDR5-6000，F 盘剩余 212 GB、D 盘剩余 113 GB；方案采用本地与 API 混合推理，不把中转服务当成唯一后端。

**MVP 边界**：输入为已有 GLB/glTF、OBJ 或 STL 网格白模，用户用文字定义材质与灯光，并可选参考图作为外观提示；输出为一个确定相机下的基础渲染及候选效果图。自由文字到 3D、STEP/STP、制造精度、多视角纹理一致性和可直接使用的转台资产均不进入 MVP。

## 2. 推荐方案与取舍

推荐“Blender 几何与基础渲染 + ComfyUI 可控生成 + 独立产品界面”。先做导入白模、按部件赋材质、受控单视角出图和批量任务，再扩展文字建模及多视角贴图。

几何与生成应有清楚的职责边界：白模决定轮廓、尺寸比例、孔位、按钮和相机；传统渲染决定可重现的材质与光照基底；AI 补充表面质感、环境和视觉表现。Depth/Normal/边缘约束只能降低漂移，不能保证几何绝对不变。

产品提供两个模式：

- **结构优先**：产品本体最终像素来自 Blender 基础渲染；AI 主要生成背景，或仅在用户明确选定且受遮罩约束的非关键区域增强。产品轮廓、可见部件、Logo、文字和保护区域由几何渲染保留。背景通过相同相机生成的 alpha 合成；接触阴影与反射必须单独生成或保留，简单抠图不等于物理正确的重光照。面向正式展示与结构敏感产品。
- **创意探索**：允许对产品本体进行受控图生图，提供“结构保持”和“参考强度”调节，结果明确标记为概念图。面向外观探索。

不建议首版训练自己的基础模型。首版选择一套已验证的模型组合和少量工作流，减少自定义节点兼容问题。新图像编辑模型作为可替换后端进行对照测试，不直接假定能与旧 ControlNet/IP-Adapter 任意组合。

## 3. 用户操作流程

1. 新建产品项目，导入 GLB/glTF、OBJ 或 STL；显示模型、尺寸、单位、正面方向与部件列表。STEP/STP 进入独立 CAD 转网格流程，不假定 Blender 原生支持。
2. 确认主体、按钮、玻璃、金属边框等部件；无部件信息的模型可先手工选区。STL 通常缺少颜色和可靠单位，必须补充确认。
3. 输入描述，例如“主体暖白磨砂塑料、上盖拉丝铝、左上方大柔光、浅灰背景”，或上传参考图并指定参考材质、配色、灯光、构图中的哪些项。
4. 系统把描述转成可见参数，用户可改“主体—磨砂塑料”“上盖—拉丝铝”等映射。未知部件不自动猜成确定映射。
5. 对无法确定的部件、材质、参考图推断参数逐项确认；“观察到的”与“系统推测的”值使用不同标记。
6. 选择正面、侧面或三分之四视角，预览白模与基础材质图，检查裁切和遮挡。即使 AI 服务不可用，也能直接导出基础渲染。
7. 先生成 4 张小尺寸候选，比较原白模、基础渲染和 AI 图；对选中方案输出高分辨率图片。
8. 一次添加多个材质、灯光、相机组合，显示任务数量和估算工作量，自动排队、重试、导出。
9. 保存图片、参数、模型及工作流版本、随机种子、质量检查结果。可以重跑单张，不必重跑整个批次。

界面建议为“左侧模型与部件、中间预览与对比、右侧材质和灯光、底部任务队列”。普通使用者无需接触节点图；高级用户可以查看实际工作流。

## 4. 技术架构与数据流

```text
3D 白模 / 白模截图 / 文字 / 参考图
          ↓
资产检查与需求解析 → 结构化 RenderSpec → 参数确认
          ↓
Blender Worker：归一化、部件、材质、相机、灯光
          ↓
基础渲染 + 深度 + 法线 + 轮廓 + 部件遮罩
          ↓
ComfyUI Worker：选定兼容工作流、图生图、参考控制、局部编辑
          ↓
质量检查 → 不合格重试或人工确认 → 导出与任务档案
```

### 4.1 模块建议

| 模块 | 建议实现 | 首版职责 |
|---|---|---|
| 前端 | React + TypeScript + Three.js | 导入、预览、部件选择、参数表单、结果对比 |
| API 与任务编排 | Python + FastAPI | 验证 RenderSpec、资产登记、任务状态、取消与重试 |
| 数据存储 | SQLite + 项目文件目录 | 单用户任务、版本和结果索引；以后再扩展多人数据库 |
| 几何与渲染 | Blender 后台进程 | 模型检查、相机、材质、基础图与控制图 |
| AI 生成 | 独立 ComfyUI 服务 | 固定版本 API 工作流、推理队列、进度与结果 |
| 自然语言解析 | 可替换文本/视觉模型适配器 | 输出受 schema 约束的配置；规则表单可以独立工作 |
| QA | 图像算法 + 人工复核 | 轮廓、关键部件、遮罩边界、标识、视角一致性 |

以上是本项目的设计建议，尚未进行实际版本组合测试。

### 4.2 模型导入和控制图

- 保留原文件及哈希，转换生成新资产；不要覆盖原模型。
- 统一坐标轴、单位、变换和法线；异常尺寸、缺失贴图、破面给出可操作提示。
- STEP/STP 通过 CAD 转换器生成网格及装配/部件映射；用原 CAD 的包围盒核对转换误差。该能力列为后续阶段，先打通网格格式。
- 每个相机输出基础 Beauty、线性深度原始数据、适配控制模型的深度图、法线图、对象 ID/部件 Mask、轮廓图。保存深度归一化范围与法线坐标约定。
- 控制图、背景和 AI 输入必须使用相同相机、分辨率和裁切；不能分别任意拉伸。
- 保留原始深度/法线与展示用图，避免显示变换损坏控制信号。
- 首版工件契约：规范 Beauty 同时保留场景线性 EXR 和经指定显示变换导出的 sRGB 无损 PNG；普通照片输入可按工作流转换为 sRGB。alpha 与部件 Mask 使用无损单通道 PNG 并保留数值，不应用摄影图像的色彩变换；深度保存 32-bit float EXR，并在元数据记录米制近远范围及映射；法线保存 16-bit PNG 或 EXR，约定为相机空间、右手系、`[-1,1]` 映射，不套用普通 sRGB 传递函数。对象 ID 保持整数/分类值。面向 AI 的深度、法线、Mask 与边缘图由工作流专用适配器生成，工件清单记录目标控制模型所需编码。每项工件记录相机内外参、分辨率、裁切、Blender 色彩管理设置和 SHA-256。
- 每个任务生成 `artifact_manifest.json`，列出逻辑名称、文件名、MIME、尺寸、色彩空间、坐标约定、哈希和上游工件。缺少必需工件或元数据即在进入 ComfyUI 前失败。

### 4.3 自然语言与参考图

文字解析只产生受验证的参数，不直接执行模型生成的脚本。材质使用白名单模板及有界数值；颜色、roughness、metallic、transmission、灯光角度和强度可编辑。

参考图解析输出：主辅色、表面工艺、粗糙度范围、光线方向、阴影软硬、背景类型和构图。把图中观察与推测分开；不能从单张照片准确反推出真实 IOR、粗糙度、灯具功率或隐藏几何。

使用参考图时先裁出材质区域，降低把参考产品形状带入结果的概率。参考影响和结构约束分开调节。文字与参考冲突时，以明确的用户参数为准，并显示冲突提示。

### 4.4 AI 工作流与兼容性

第一条实验基线：同一模型家族下的 img2img + Depth/边缘控制 + 可选 IP-Adapter。SDXL 可作为成熟的对照路线，最终选择由样品评测确定。

另设 Qwen-Image 编辑路线作为对照，评估文字遵循、材质编辑与结构保持；不假设它能直接加载 SDXL 的控制模型。IC-Light 是可选重光照阶段，必须使用其对应模型与工作流，不能当成所有后端通用的灯光参数接口。

工作流注册表保存基础模型、控制模型、参考适配器、VAE、自定义节点 commit/version 和模型哈希，并声明兼容的模型家族。缺依赖时在排队前失败，不在渲染中途自动安装未知节点。

Blender 基础渲染是独立、确定性的可交付基线；ComfyUI 是可选实验阶段。ComfyUI、模型或自定义节点不可用时，任务可以以 `baseline_completed` 结束并导出基础渲染，同时报告 AI 阶段未执行，不能把该结果冒充 AI 成功。SDXL + 同家族控制模型是待验证基线；Qwen-Image 单独评估，不混用不兼容的 ControlNet/IP-Adapter 权重。

一致性原则：多视角共用同一几何、材质定义和场景灯光；相同随机种子并不能保证不同角度的生成纹理一致。首版导出独立视角概念图；要求转台视频或可旋转成品时，进入贴图投射/烘焙和接缝验证流程。

### 4.5 任务与复现

权威任务状态模型：执行阶段为 `created → validated → queued → rendering → generating → checking`；结果状态只有 `completed / baseline_completed / failed / cancelled / needs_review`。`completed` 表示用户请求的完整流程完成且通过适用检查；`baseline_completed` 表示 Blender 基线已交付，但请求的 AI 阶段不可用或被明确跳过，不能计作 AI 成功；`failed` 表示未产出可接受交付；`cancelled` 表示取消已最终确认；`needs_review` 是持久复核状态，为队列统计的终态，但复核决定可以显式转为 `completed`、`baseline_completed` 或 `failed`，且必须保留状态变更记录。

每张图保存 task_id、资产哈希、RenderSpec、相机、seed、模型与工作流版本、尝试次数、各阶段耗时和 QA 结果。相同输入生成幂等键，网络恢复时先查询已有任务，避免重复计费和重复出图。跨 GPU/软件版本不承诺逐像素一致。

每个 Worker 独占其正在处理的任务，超时和失败分别处理：临时连接问题有限重试；显存不足降级尺寸或串行；文件不支持、缺模型等确定性错误直接报告。取消后停止后续阶段，不把半成品标为成功。

只有网络瞬断、服务短暂不可用等标记为 `transient` 的错误允许有限重试；输入无效、资产损坏、模型缺失或版本不兼容属于 `deterministic`，不得自动重试。取消请求写入持久状态，Worker 在阶段边界检查；一旦为 `cancelled`，迟到的结果只能归档为诊断工件，不能把任务改回 `completed`。超时必须指出发生阶段、已保留工件和建议动作。

ComfyUI 自动化可参考官方 WebSocket 示例中的任务提交、完成监听和结果读取方式。[官方示例](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/websockets_api_example.py)

## 5. RenderSpec 示例与接口草案

下面是本项目拟定的数据契约，不是任何现有渲染后端可直接接受的请求。适配层负责转换；数值是实验起点，不是验证后的最佳参数。

```json
{
  "schema_version": "0.1",
  "asset_id": "product_001",
  "mode": "structure_first",
  "units": "mm",
  "geometry_locked": true,
  "materials": [
    {"part_id": "body", "preset": "matte_plastic", "color": "#E8E3D8", "roughness": 0.55},
    {"part_id": "lid", "preset": "brushed_metal", "metallic": 1.0, "roughness": 0.3}
  ],
  "lighting": {"preset": "softbox_studio", "key_azimuth_deg": -45, "key_elevation_deg": 45},
  "camera": {"preset": "front_three_quarter", "projection": "perspective"},
  "reference": {"asset_id": null, "use_for": ["material", "lighting"], "strength": 0.35},
  "output": {"width": 1024, "height": 1024, "candidates": 4, "seed": 42},
  "workflow_id": "baseline_v1",
  "protected_parts": ["logo", "buttons"],
  "protected_regions": [{"mask_id": "front_label", "policy": "preserve_pixels"}],
  "input_hashes": {"mesh_sha256": "<sha256>", "reference_sha256": null},
  "execution": {
    "blender_version": "<resolved-at-validation>",
    "workflow_sha256": "<resolved-at-validation>",
    "model_versions": {}
  }
}
```

`geometry_locked` 表示编排器不得修改源几何，不表示生成图天然满足几何约束。后者由遮罩策略、渲染模式和 QA 决定。

拟定 API：`POST /assets` 导入，`POST /specs/parse` 解析描述，`POST /jobs` 提交，`GET /jobs/{id}` 查询，`POST /jobs/{id}/cancel` 取消，`POST /jobs/{id}/retry` 重试，`GET /jobs/{id}/artifacts` 下载产物。实际接口在实现时补充文件大小、错误码、幂等键和权限约束。

正式 schema 将“用户可编辑意图”与“校验后执行元数据”分开；服务端解析版本、哈希和实际模型，不接受客户端伪造执行记录。数值设置允许范围，例如参考强度 `0..1`、候选数 `1..8`、输出边长按部署容量限制。统一错误体包含 `code`、`stage`、`retryable`、`message`、`details` 与 `artifact_manifest_id`。`POST /jobs` 接受幂等键；相同键和相同输入返回原任务，不重复排队。

## 6. GitHub 调研与推荐阅读顺序

调研日期：2026-09-19。以下项目通过 GitHub 页面及其 README/官方示例核实用途，未下载运行，未验证当前节点兼容性。页面抓取可能存在缓存，未核对的最后提交时间不写成“当前活跃”；星数不是选型依据。

许可证一栏仅记录页面显示的仓库代码许可证，不替代模型权重、依赖或最终分发方式的逐项核查。

| 顺序 | 项目与来源 | 已核实用途 | 本项目可借鉴部分 | 局限 / 复用策略 |
|---|---|---|---|---|
| 1 | [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | 节点化生成后端与 API | 工作流执行、队列、进度、参数化 | 推荐作为独立推理服务；具体许可证和版本在锁定依赖时复核 |
| 2 | [ComfyUI-BlenderAI-node](https://github.com/AIGODLIKE/ComfyUI-BlenderAI-node) | Blender 内使用 ComfyUI，支持相机/合成输入、Mask、批量任务 | 最贴近“白模—控制图—AI”交互；查看 presets、SDNode、相机及遮罩节点 | 页面标注 GPL-3.0；节点并非全部兼容，优先参考原型和集成方式 |
| 3 | [ControlNet](https://github.com/lllyasviel/ControlNet) | 为扩散生成增加空间条件 | 深度、边缘等几何约束思路 | 条件约束不是几何保证；必须选与基础模型匹配的控制模型 |
| 4 | [IP-Adapter](https://github.com/tencent-ailab/IP-Adapter) | 给文生图模型增加图像提示 | 参考图材质、颜色、风格引导 | 页面标注 Apache-2.0；容易同时带入参考对象身份/形状，要控制裁切与权重 |
| 5 | [ComfyUI-productfix](https://github.com/MiddleKD/ComfyUI-productfix) | 保留电商产品文字、Logo 与细节的自定义节点 | 查看 workflows、OCR 和细节保护设计 | 页面标注 MIT；主要围绕已有产品图，不等于白模材质恢复或完整 CAD 渲染器 |
| 6 | [IC-Light](https://github.com/lllyasviel/IC-Light) | 用文本或背景条件对前景图重光照 | 调整环境光照气氛，作为实验后处理 | 页面标注 Apache-2.0；会改变像素，不能替代准确物理灯光和色彩管理 |
| 7 | [StableGen](https://github.com/sakalond/StableGen) | Blender 内的生成式 3D 纹理工作流 | 多视角生成、纹理投射与后续烘焙方向 | 页面标注 GPL-3.0；功能面广，宜第二阶段参考；模型和第三方组件许可需单独检查 |
| 8 | [Dream Textures](https://github.com/carson-katri/dream-textures) | Blender 内使用 Stable Diffusion | 插件交互与纹理生成路径 | 作为历史/设计参考；本轮未运行，不作为首版强依赖 |
| 9 | [Qwen-Image](https://github.com/QwenLM/Qwen-Image) | 图像生成与编辑模型项目 | 对比自然语言改材质、参考图编辑能力 | 仅作为候选后端，显存、控制方案和速度需实测 |
| 10 | [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) | 高分辨率 3D 资产生成 | “只有照片→概念白模”的扩展入口 | 自动生成网格不代表可制造 CAD；模型许可、尺寸和拓扑另行评估 |

最接近整体需求的是 ComfyUI-BlenderAI-node；产品细节保护重点看 productfix；多角度纹理路线重点看 StableGen。没有发现经本轮验证即可直接满足“导入白模、描述外观、参考产品、稳定批量、结构验收”全部要求的开箱即用项目，因此建议组合后端并自建工作台。

下一次验证每个候选仓库时记录：commit SHA、依赖版本、代码/权重许可证链接、最小工作流、硬件、安装耗时、首图耗时、成功/失败样例。当前仅完成资料级核实，不能写成“已跑通”。

实施前检查表还必须覆盖：仓库代码许可证、模型权重许可证、数据集或第三方依赖限制分别核实；保存最小可运行工作流与输出；记录能复现的安装命令和锁文件；至少一份正例与一份失败证据。任何一项缺失，该候选只保持“资料参考”状态。

## 7. 实施阶段与交付物

以下为一名熟悉 Python、Blender 和前端的开发者的粗估，依赖硬件与模型下载条件；不构成工期承诺。先通过技术样机决定是否扩大投入。

| 阶段 | 估算 | 范围 | 完成门槛 |
|---|---|---|---|
| P0 样品与可行性门 | 2–3 天 | 选 3 类产品、固定硬件与版本，验证 Blender 工件契约、基础渲染及至少一条 AI 对照 | 每个样品有可重跑基线、工件清单、正例和失败案例；未达标则缩减 AI 范围，不进入 P1 |
| P1 最小闭环 | 5–8 天 | GLB/OBJ/STL 导入、部件、模板材质/灯光、一个视角、文字输入、4 张候选、任务记录 | 以一个真实白模完成“导入→确认→基础渲染→可选 AI→QA→导出”的可执行垂直切片，确定性错误可定位 |
| P2 参考与批量 | 4–6 天 | 参考图、局部材质、批次、取消/重试、对比和 QA | 参考与文字都可用；20 个任务全部在规定超时内进入 `completed / baseline_completed / failed / cancelled / needs_review` 之一，分别统计完整成功、仅基线交付与待复核，不把后两者计作 AI 成功；取消任务不回到成功，重复幂等请求不新增任务 |
| P3 产品化 | 4–7 天 | 环境检测、依赖锁定、打包、缓存、归档与文档 | 换环境按说明可安装，未通过 QA 的结果不会自动通过 |
| P4 可选扩展 | 单独估算 | STEP、文字/图片建模、多视角烘焙、转台动画、多人和云队列 | 每项单独建立测试与验收，不绑进首版承诺 |

首版建议总范围为 P0–P2；是否进入 P3/P4 由样品结果决定。文字到模型先支持参数化模板品类，例如方盒、瓶罐、圆柱设备；自由复杂造型作为独立实验。

## 8. 验收设计

固定测试集至少 6 个白模：简单盒体、圆柱瓶罐、带小孔按钮的电器、金属器件、玻璃件和多部件装配。每件设置 2 种材质、2 种光照和至少 2 个视角。首轮可先用其中 3 件缩小评测。

以下数值是建议起点，需用标注样品校准，不是已测成绩：

- 结构：AI 输出前景与相同相机白模遮罩比较，轮廓 IoU 初始目标 ≥0.95；透明件单列评测，分割置信度不足转人工。
- 细节：按钮、接口、孔位数量和位置不能出现无说明变更。轮廓指标不能覆盖内部结构，必须逐项核对。
- 标识：Logo/文字使用原贴图、贴花或保护区；OCR 和人工检查，不能把生成的错字当成功。
- 材质：区分塑料、金属、玻璃等指定外观；色彩容差在固定色彩管理和灯光下另行标定，不能拿任意光照图片直接比色号。
- 参考遵循：分别评价配色、表面工艺、光照、构图，不把形状模仿当作材质成功。
- 自动化：20 个任务最终都进入权威结果状态之一，分别报告 `completed`、`baseline_completed`、`failed`、`cancelled`、`needs_review` 的数量与比例；`needs_review` 在队列统计中为终态，复核后另记决策转换。模拟中断后不漏任务、不重复归档。服务稳定性、完整 AI 成功率、仅基线交付率与视觉通过率分开报告。
- 多视角：关键部件保持一致；贴图接缝、文字、纹理方向不通过时，不能称为可直接转台输出。
- 性能：记录硬件、分辨率、批量、冷/热启动、显存峰值和 P50/P95 耗时；完成基线前不承诺“几秒出图”。

候选不通过时先降低图生图强度或参考影响、提高有效几何约束，再局部重生成；仍失败则返回基础渲染并标记需要人工确认。禁止无限自动重试。

## 9. 硬件、成本与部署

### 9.1 已知工作站与结论

| 项目 | 当前配置 | 结论 |
|---|---|---|
| GPU | RTX 4060 Ti 8 GB | 足够承担 Blender CUDA 渲染、SD 1.5/SDXL 的单图可控工作流、遮罩/深度/边缘预处理与后期；8 GB 显存是大型生成/编辑模型的主要瓶颈 |
| CPU | i5-14600KF，14 核 20 线程 | 足够承担 Blender 场景准备、网格转换、任务编排和图像后处理；不能替代 GPU 显存 |
| 内存 | 32 GB DDR5-6000 | 能支持常规工作流和一定 CPU offload；大型模型卸载时会牺牲速度，仍可能触及容量上限 |
| 磁盘 | F: 212 GB 可用；D: 113 GB 可用 | 能安装一套精选模型栈，但不适合无节制保留多套大模型与重复缓存 |

建议结论：**不需要先换硬件，先做混合方案 P0。** 4060 Ti 8 GB 作为“确定性渲染、控制图、本地预览、局部编辑和 QA”节点；高难度材质表现、复杂参考图遵循和最终 Hero 图交给 API。这样既保留产品结构与可复现性，又能达到高于纯本地 8 GB 大模型方案的视觉上限。

### 9.2 推荐的三级渲染后端

| 等级 | 后端 | 用途 | 当前建议 |
|---|---|---|---|
| L0 确定性基线 | Blender Cycles/Eevee | Beauty、Alpha、Depth、Normal、Object ID、接触阴影、反射与产品本体 | 必须始终可用；结构优先模式的最终产品像素来源 |
| L1 本地 AI 预览 | ComfyUI + SDXL，同家族 Depth/边缘 Control-LoRA 或 T2I-Adapter，局部 Inpaint | 768–1024 候选、背景探索、受遮罩材质微调 | 8 GB 的生产基线；批量大小固定为 1，逐步启用 FP16/低显存与注意力优化 |
| L2 API 高质终稿 | Nano Banana 2 / Nano Banana Pro / GPT-Image-2 | 高级布光氛围、复杂材质、参考图迁移、广告级候选与高分辨率终稿 | 采用同一评测集做 A/B；不先凭名称决定唯一供应商 |

这里把用户所说的“nano”按 Google 官方 Nano Banana 模型族理解，把“image2”按 OpenAI 的 GPT-Image-2 理解；中转商可能使用自定义别名，正式接入时必须验证其实际模型 ID、版本、尺寸、压缩行为和失败语义。Google 官方当前列出 `gemini-3.1-flash-image`（Nano Banana 2）、`gemini-3-pro-image`（Nano Banana Pro）及轻量版本；OpenAI 官方当前把 GPT-Image-2列为图像生成模型。上述属于 2026-09-21 的资料核实，不代表任何中转已通过实测。

不把 FLUX.1 Schnell、FLUX Kontext 或 Qwen-Image 的大型本地路线作为本机首版核心。ComfyUI 官方示例提供 FP8 与卸载路径，FLUX.1 Schnell 也支持少步生成；但在 8 GB 显存上通常需要量化/卸载，会增加内存占用、延迟和失败变量。可以把 FLUX Schnell FP8/GGUF 作为一次“能否运行”的探索实验，不能在得到本机显存峰值和耗时前承诺生产体验。

### 9.3 推荐执行流

```text
白模 → Blender 固定相机与材质基线
     → Beauty / Alpha / Depth / Normal / Edge / 部件 Mask
     → 本地 SDXL 快速候选与局部修改
     → 选中 1–2 个方案发送给 API 做高质终稿
     → 本地恢复 Logo/文字/关键结构、合成阴影与反射
     → 轮廓/部件/OCR/人工 QA → 归档
```

远程阶段默认只发送派生的栅格图、遮罩和必要文字，不发送 STEP、原始网格或完整客户资产。结构敏感项目可关闭 L2，仅使用本地路径。正式 Logo、铭牌和小字由 Blender 贴花或后期原像素回填，不依赖生成模型重写。

### 9.4 磁盘与安装预算

- F 盘用于 `ComfyUI/runtime/models`，首期模型与运行环境预算 100–140 GB，并保持至少约 50 GB 空闲。
- D 盘用于项目资产、缓存、临时控制图和输出，首期预算 40–60 GB，并保持至少约 30 GB 空闲。
- 通过 ComfyUI 额外模型路径或 NTFS 目录联接复用权重，禁止不同前端各复制一份模型。
- 缓存按任务 ID 管理；只有可重建的临时工件允许自动清理，源白模、RenderSpec、最终图和清单不可自动删除。

### 9.5 API 与中转接入边界

统一实现 Provider Adapter，而不是把业务逻辑写死到某个中转：`local_sdxl`、`google_nano_banana_2`、`google_nano_banana_pro`、`openai_gpt_image_2`。每次请求至少记录自有 `task_id`、声明的 provider/model、服务返回的模型标识（若有）、request ID、尺寸、耗时、费用、输入输出 SHA-256 和失败类型。

中转服务能够接触 API 密钥、提示词和产品图片，也可能改写模型名、压缩图片、改变限流与日志保留规则。接入前必须用非敏感样品验证：真实模型身份、输出原图尺寸/格式、透明通道、参考图数量、超时、幂等、退款/重复计费和数据保留。密钥只存操作系统凭据或环境变量，日志打码；官方直连与中转使用不同密钥和独立额度。涉及未公开产品时，若无法获得可接受的数据条款，则禁用中转。

OpenAI 官方图像指南给出的 GPT-Image-2 示例输出价约为：1024×1024 低/中/高质量分别 0.006/0.053/0.211 美元，且不含输入 token；实际账单、地区与中转加价以调用时为准。Google 费用在正式接入时读取官方定价页并写入配置，不把当前网页展示值硬编码进方案。

### 9.6 P0 本机/API 对照实验

用同一组三个产品（简单塑料、拉丝金属、多部件带 Logo）和完全相同的相机/提示词测试：

1. Blender Cycles 基线；
2. 本地 SDXL + Depth T2I-Adapter；
3. 本地 SDXL + Depth/Canny Control-LoRA + Mask Inpaint；
4. 可选 FLUX.1 Schnell FP8/GGUF，仅做可运行性记录；
5. Nano Banana 2；
6. Nano Banana Pro；
7. GPT-Image-2 高质量。

每条路线记录峰值 VRAM/RAM、冷/热启动、P50/P95 耗时、失败率、单张实付成本、轮廓 IoU、部件错漏、Logo/OCR、材质真实感、参考图遵循和人工盲评分。API 先各生成少量候选，不自动大批量付费。只有本机实测后才填写速度和容量结论。

## 10. 计划目录与后续工作规范

本次实际创建主文档与 AGENTS.md；下列其他目录是未来实现结构，不代表已经存在：

```text
ai渲染/
  AI渲染器_方案与过程记录.md
  AGENTS.md
  apps/web/
  services/api/
  workers/blender/
  workers/comfyui/
  workflows/
  schemas/render_spec.schema.json
  presets/materials/
  presets/lighting/
  assets/
  outputs/
  evaluations/
```

每轮开始先读本文件及最新变更记录。修改前标记本轮范围，修改后更新对应正文并追加记录：日期、变更编号、原因、文件/章节、验证、结论、待办。保留旧记录，不通过重写历史掩盖错误。渲染样例和详细数据可另存，但这里必须链接并概述结论。用户后续在本目录启动任务时，AGENTS.md 提醒执行同一规则。

## 11. Codex with ChatGPT 协作状态与待办

用户指定使用 [Codex with ChatGPT 技能](/Users/a/.codex/skills/codex-with-chatgpt/SKILL.md)，并选择临时地址。

指定的 ChatGPT 项目：[渲染](https://chatgpt.com/g/g-p-6aae2540fe90819193fe724e33b1202a-xuan-ran/project)。这是用户提供的项目地址，尚未通过页面读写完成绑定验证。

截至 v0.2：临时安全连接可用；ChatGPT 已通过“Codex with ChatGPT · ai渲染”连接器确认工作区名并读取主方案与 AGENTS.md，随后针对架构边界、工件契约、RenderSpec、任务语义、验收与协作状态返回了两轮 C2C PLAN。两轮修订完成后，ChatGPT 再次读取完整文档、执行摘要与验证状态，并在任务 `c2c_a719` 第 2 轮返回 DONE / Accepted。用户提供的“渲染”项目页面承载本次审阅对话；这一结论只验收方案文档，不等于渲染器实现、Blender/ComfyUI 运行或视觉指标已经验证。

本轮协作审阅已完成。下一开发里程碑是 P0：在已知的 RTX 4060 Ti 8 GB 工作站上，使用真实产品白模建立可复现的 Blender 基线，并验证本地 SDXL 与三种 API 终稿路线。当前仍未安装模型或运行性能测试。

待确定但不阻塞本轮方案的问题：第一个产品样品及格式、正式产品图还是概念探索、首版是否必须支持 STEP、可用中转的具体 API 兼容格式与数据条款。下一步最有价值的是用一个真实白模完成 P0，量化结构保持、视觉质量、速度与实际费用。

## 12. 过程与修改登记（只追加）

| 编号 | 日期 | 原因/动作 | 影响范围 | 验证与结果 | 待办 |
|---|---|---|---|---|---|
| R001 | 2026-09-19 | 用户提出白模 AI 渲染器、文字/参考图输入、GitHub 调研和持续登记要求 | 需求基线 | 已明确本轮先交付方案文档 | 选择连接方式 |
| R002 | 2026-09-19 | 用户选择临时地址并给出 ChatGPT“渲染”项目 | 协作配置 | 已保存临时方式；项目地址已记录 | 验证绑定 |
| R003 | 2026-09-19 | 检查与恢复连接 | 协作流程 | 本地检查通过；临时地址启动超时；浏览器读取超时；兼容模式重试中 | 获得可用连接后再请求 ChatGPT 审阅 |
| R004 | 2026-09-19 | 完成 GitHub 资料级调研 | 第 6 节 | 核对 10 个项目用途及部分代码许可；未运行或做性能测试 | 锁定候选版本并制作样例 |
| R005 | 2026-09-19 | 编写 v0.1 方案与长期登记规范 | 本文件、AGENTS.md | 包含输入边界、架构、参数、路线、验收、成本和待办；明确未完成联合审阅 | 补充 ChatGPT 审阅记录 |
| R006 | 2026-09-21 | 恢复 Codex with ChatGPT 协作并完成正式 PLAN | 第 1–12 节 | ChatGPT 已读取工作区与主文档；指出结构优先合成、工件契约、RenderSpec、任务语义和验收边界需加强 | 按 PLAN 修订并请求复核 |
| R007 | 2026-09-21 | 将 PLAN 落实为 v0.2 | 第 1–7、11–12 节 | 明确 MVP 排除项、产品像素保留、工件格式/坐标/哈希、AI 降级、重试与取消、扩展 RenderSpec、可行性门及批量验收 | 完成文档级检查并发送 EXECUTED |
| R008 | 2026-09-21 | 根据 ChatGPT 独立复核修正两项技术不一致 | 第 4.2、4.5、7、8、11–12 节 | 数值型控制图不再套用摄影图像色彩变换；统一五种结果状态，并在 P2 与验收指标中一致引用 | 重新验证并请求最终 DONE |
| R009 | 2026-09-21 | 记录 Codex with ChatGPT 最终验收 | 第 11–12 节、文档版本状态 | ChatGPT 复读完整 v0.2、执行摘要和检查结果后返回 `DONE / Accepted`；确认色彩空间、状态模型、P2 验收、指标与 R001–R008 通过 | 后续以真实白模启动 P0；本轮不实施代码 |
| R010 | 2026-09-21 | 用户补充 RTX 4060 Ti 8 GB、i5-14600KF、32 GB 内存及 F/D 剩余空间，并要求评估本地模型、Nano/Image2 API 与更高级效果 | 版本升至 v0.3；第 1、9、11–12 节 | 完成资料级硬件适配判断；确定 L0 Blender、L1 本地 SDXL、L2 Nano Banana/GPT-Image-2 的混合架构；加入磁盘预算、中转安全边界和七路线 P0 对照矩阵。尚未安装、调用或测速 | 用户提供一个真实白模与参考图后执行 P0；核实中转 API 文档、实际模型 ID、数据政策与计费 |
| R011 | 2026-09-21 | 用户要求在过程文档内补充 Windows 详细执行文档 | 版本升至 v0.4；新增第 13 节 | 已编写适配 RTX 4060 Ti 8 GB 的 Windows 分阶段安装、目录、启动、模型、API、P0 验收、安全、回滚与故障处理手册；仅完成文档检查，未在目标 Windows 主机执行 | 在目标机按 W0–W7 执行；每完成一阶段记录实际版本、命令、截图/日志和结果 |

后续登记模板：`编号 / 时间 / 用户要求或原因 / 修改内容 / 文件及版本 / 验证证据 / 结论 / 剩余风险与下一步`。

## 13. Windows 详细执行手册

本节面向目标工作站：Windows 10/11 64 位、RTX 4060 Ti 8 GB、i5-14600KF、32 GB 内存、F 盘约 212 GB可用、D 盘约 113 GB 可用。它是一份执行基线，不代表已经安装成功。所有命令默认在 **PowerShell 7 或 Windows PowerShell** 中逐段执行；不要一次粘贴整章，也不要在命令中写真实密钥。

官方参考入口：[ComfyUI 安装文档](https://docs.comfy.org/installation/overview)、[ComfyUI GitHub](https://github.com/Comfy-Org/ComfyUI)、[PyTorch Windows/CUDA 选择器](https://pytorch.org/get-started/locally/)、[Python Windows 文档](https://docs.python.org/3/using/windows.html)、[Blender 下载](https://www.blender.org/download/)。安装当天须在 R011 的后续记录中补充实际版本和下载来源。

### 13.1 执行原则和阶段门

| 阶段 | 目标 | 通过条件 | 失败时动作 |
|---|---|---|---|
| W0 | 备份与基线检查 | 驱动、磁盘、GPU、Windows 版本有记录 | 不安装，先解决硬件/磁盘问题 |
| W1 | 建立目录和工具 | Git、Blender、Python/ComfyUI 可分别启动 | 只修复当前工具，不叠加更多软件 |
| W2 | Blender GPU 基线 | 能输出一张固定相机 PNG 和控制图 | 保留日志，先用 CPU 验证场景，再查 GPU |
| W3 | ComfyUI 最小本地基线 | 1024 单图成功，CUDA 被识别，8 GB 不溢出 | 降到 768、batch=1，停用自定义节点 |
| W4 | 受控产品工作流 | Depth/Edge/Mask 输入和输出尺寸一致 | 回退到最小工作流逐节点恢复 |
| W5 | API 适配 | 非敏感样品分别调用成功且有审计记录 | 禁止自动重试付费请求，检查模型和错误体 |
| W6 | 混合闭环 | 本地结构基线、API 候选、Logo 回填和 QA 全部归档 | 任务标记 `needs_review`，不冒充成功 |
| W7 | P0 评测 | 三个样品的质量、耗时、显存和费用有可比记录 | 缩减模型范围，决定是否升级显存/改云端 |

原则：每阶段单独验收；模型和自定义节点按需增加；先保留能运行的最小基线，再做优化。不要先安装“整合包大全”或几十个未知节点。

### 13.2 W0：安装前检查

1. 在 Windows 设置中运行系统更新并重启。
2. 安装当前 NVIDIA Studio Driver；需要游戏驱动时也可使用 Game Ready，但项目机器优先 Studio 分支。使用 NVIDIA 官方安装器，选择“全新安装”仅在已有驱动异常时使用。
3. 打开 PowerShell，记录基线：

```powershell
nvidia-smi
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum
Get-PSDrive F,D | Select-Object Name, Used, Free
```

4. 将输出复制到项目的 `evaluations\environment\baseline.txt`；若目录尚未建立，先执行 13.3。
5. `nvidia-smi` 必须显示 RTX 4060 Ti 和驱动版本。PyTorch/ComfyUI 使用带 CUDA 运行时的官方构建时通常不需要另装完整 CUDA Toolkit；只有编译特定自定义节点时才按该节点要求安装，避免多个 CUDA 版本污染环境。
6. Windows 页面文件保持“系统管理的大小”，放在空间更充足的盘；不要为了省盘关闭页面文件。运行期间关闭占显存的游戏、视频增强和其他生成软件。

### 13.3 目录规划

以管理员身份不是必需条件。普通 PowerShell 执行：

```powershell
New-Item -ItemType Directory -Force -Path F:\AI-Renderer\runtime
New-Item -ItemType Directory -Force -Path F:\AI-Renderer\models
New-Item -ItemType Directory -Force -Path F:\AI-Renderer\packages
New-Item -ItemType Directory -Force -Path D:\AI-Renderer\projects
New-Item -ItemType Directory -Force -Path D:\AI-Renderer\cache
New-Item -ItemType Directory -Force -Path D:\AI-Renderer\outputs
New-Item -ItemType Directory -Force -Path D:\AI-Renderer\logs
New-Item -ItemType Directory -Force -Path D:\AI-Renderer\evaluations\environment
```

用途约定：

```text
F:\AI-Renderer\
  runtime\       Blender、ComfyUI、API 服务和隔离环境
  models\        checkpoints、VAE、ControlNet、LoRA、upscaler
  packages\      下载的原始安装包及其校验值
D:\AI-Renderer\
  projects\      每个产品项目及源资产，只读保存原件
  cache\         可重建临时文件
  outputs\       正式导出
  logs\          启动、任务和错误日志，不含密钥
  evaluations\   P0 数据、截图和评分
```

不要把模型放在桌面、OneDrive 同步目录或含中文/特殊符号的深层路径。F 盘至少保留 50 GB，D 盘至少保留 30 GB。清理时只删除已确认可重建的 `cache`，不使用针对 `F:\` 或 `D:\` 根目录的递归删除命令。

### 13.4 W1：安装基础工具

#### Git

从 [Git for Windows](https://git-scm.com/download/win) 安装，默认选项即可。验证：

```powershell
git --version
git config --global core.longpaths true
```

`core.longpaths` 只减少模型/节点深路径问题，不代表所有第三方程序都支持超长路径。

#### Blender

优先使用 Blender 官方 LTS 或团队锁定版本。安装到默认位置即可，并记录确切版本：

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" --version
```

上面路径中的版本号必须替换成实际安装目录。启动 GUI 后，在 `Edit → Preferences → System → Cycles Render Devices` 选择 OptiX，并勾选 RTX 4060 Ti；不要同时勾选不需要的 CPU，先单独验证 GPU。

#### Python

ComfyUI Portable 自带隔离 Python，首选使用它，不向系统 Python 安装 torch。项目 API 服务另用独立环境。若需要系统 Python，从 python.org 安装兼容项目依赖的 64 位版本；初始建议 Python 3.11，最终以锁文件为准。验证并建立 API 环境：

```powershell
py --list
py -3.11 -m venv F:\AI-Renderer\runtime\api-venv
F:\AI-Renderer\runtime\api-venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
deactivate
```

如果 PowerShell 阻止激活脚本，可以不更改全局执行策略，直接调用 `F:\AI-Renderer\runtime\api-venv\Scripts\python.exe`。不要混用 ComfyUI 的嵌入式 Python、系统 Python和 API venv。

### 13.5 W2：Blender 基线配置

在 Blender 中创建一次最小测试场景：立方体、地面、一个 Area Light、固定相机，渲染器选择 Cycles，设备选择 GPU Compute，启用 OptiX 降噪。首轮参数：1024×1024、64 samples、透明背景按任务需要启用。

应输出以下文件：

```text
beauty.png
beauty_linear.exr
alpha.png
depth.exr
normal.exr
object_id.png
scene.blend
scene_manifest.json
```

命令行验证示例：

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" `
  -b "D:\AI-Renderer\projects\smoke-test\scene.blend" `
  -o "D:\AI-Renderer\outputs\smoke-test\frame_####" `
  -f 1
```

验收：命令退出码为 0、输出非空、相机视角正确、产品未裁切、Depth/Normal 与 Beauty 同尺寸。GPU 渲染失败时，先在 GUI 中确认设备，再以 CPU 跑同一场景区分“场景错误”和“CUDA/OptiX 错误”。

### 13.6 W3：安装并验证 ComfyUI

首选 ComfyUI 官方 Windows Portable NVIDIA 包，解压到 `F:\AI-Renderer\runtime\ComfyUI_windows_portable`。不要覆盖旧版本升级；新版本解压到带日期或版本的独立目录，验证后再切换启动快捷方式。

启动：

```powershell
Set-Location F:\AI-Renderer\runtime\ComfyUI_windows_portable
.\run_nvidia_gpu.bat
```

浏览器打开终端显示的本地地址，默认通常是 `http://127.0.0.1:8188`。只监听 `127.0.0.1`；除非已经配置身份认证、防火墙和可信局域网，否则不要使用公网监听参数。

在 ComfyUI 自带 Python 中验证 CUDA：

```powershell
F:\AI-Renderer\runtime\ComfyUI_windows_portable\python_embeded\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

通过条件：`torch.cuda.is_available()` 为 `True`，设备名为 RTX 4060 Ti。若为 False，不要盲目安装不同 torch；先保存完整启动日志，再依据 [PyTorch 官方选择器](https://pytorch.org/get-started/locally/) 和 ComfyUI 当前要求重装匹配版本。

8 GB 初始运行规则：

- batch size 固定为 1；先用 768×768，通过后再测试 1024×1024。
- 使用 SDXL FP16 基线；一次只加载一个 checkpoint，先不装自定义节点。
- 关闭其他占显存应用；每次 OOM 后完全停止 ComfyUI 再启动，避免残留显存误判。
- 只有确有需要时尝试 `--lowvram`；正常可运行时不默认牺牲性能。
- 模型使用 SHA-256 和来源清单管理，不运行来源不明的 `.exe`、安装脚本或节点。

模型统一放在 `F:\AI-Renderer\models`。可用 ComfyUI 的额外模型路径配置指向该目录，示意结构：

```text
F:\AI-Renderer\models\
  checkpoints\
  vae\
  controlnet\
  loras\
  upscale_models\
  clip\
```

配置文件名称和键值以当前 ComfyUI 官方示例为准；修改前复制模板，不在两处重复模型。首次只准备一套经过许可证核对的 SDXL checkpoint、匹配的 VAE、一个 Depth 控制模型/适配器和一个放大模型。

### 13.7 W4：产品受控工作流

按以下顺序建立工作流，每加一层都保存独立 JSON：

1. `wf_01_sdxl_smoke.json`：纯 SDXL 文生图，确认核心推理。
2. `wf_02_img2img.json`：输入 Blender Beauty，小幅 denoise。
3. `wf_03_depth.json`：加入与目标模型家族匹配的 Depth Control-LoRA 或 T2I-Adapter。
4. `wf_04_edge_mask.json`：加入 Edge 与产品 Mask，只编辑允许区域。
5. `wf_05_product_final.json`：加入背景、局部 inpaint、可选 upscale 和结果元数据。

禁止将 SD 1.5、SDXL、FLUX、Qwen 的 ControlNet/LoRA/文本编码器混搭。每个工作流注册：ComfyUI commit、节点版本、模型文件名、SHA-256、显存峰值、分辨率、seed、steps、CFG/denoise 和成功样例。

4060 Ti 8 GB 的建议起点，不是最终最优值：

| 参数 | 初始值 |
|---|---|
| 分辨率 | 768×768，稳定后测试 1024×1024 |
| Batch | 1 |
| 候选数 | 顺序生成 4 张，不并行 |
| Img2img denoise | 0.15–0.35，结构优先从低值开始 |
| 结构控制强度 | 0.7–1.0，再按样品校准 |
| API 前预览 | 先低分辨率选方向，只送 1–2 张终稿 |

Logo、铭牌、按钮、孔位建立保护 Mask。结构优先模式下，产品最终像素优先来自 Blender；AI 主要处理背景、气氛和允许区域。即使轮廓 IoU 合格，只要关键部件或文字错漏，也必须标记 `needs_review`。

### 13.8 W5：API 与中转配置

后端统一采用适配器配置，建议的非敏感配置结构：

```yaml
providers:
  google_official:
    base_url: "官方地址"
    model: "安装时核实的 Nano Banana 模型 ID"
    api_key_env: "GOOGLE_IMAGE_API_KEY"
  openai_official:
    base_url: "官方地址"
    model: "安装时核实的 GPT-Image-2 模型 ID"
    api_key_env: "OPENAI_IMAGE_API_KEY"
  relay_candidate:
    base_url: "中转商提供的地址"
    model: "中转商声明的模型 ID"
    api_key_env: "RELAY_IMAGE_API_KEY"
```

真实密钥不得写入 YAML、Markdown、Git、截图或日志。仅在当前 PowerShell 会话测试时可使用：

```powershell
$env:OPENAI_IMAGE_API_KEY = Read-Host "输入临时 API Key"
```

该方式输入仍可能在会话环境中存在；测试结束关闭该终端。正式版使用 Windows Credential Manager、DPAPI 或受控的密钥服务。每个供应商设置独立预算、并发数 1、明确超时；付费生成遇到超时应先按 request ID 查询，不能直接无限重试。

中转验收必须使用非敏感样品，逐项记录：请求端点、模型别名、响应中的真实模型字段、参考图数量、原图尺寸、格式/alpha、是否二次压缩、耗时、错误体、内容策略、数据保留、退款和重复计费。任一关键项无法确认，就只能标为实验后端。

### 13.9 W6：每日启动与关停顺序

启动：

1. 检查 F/D 剩余空间，关闭占显存软件。
2. 启动 ComfyUI，等待日志显示监听地址。
3. 运行 CUDA 自检或最小 smoke workflow。
4. 启动 API 服务的独立 venv；确认 `/health` 同时报告 Blender、ComfyUI、磁盘和 provider 状态。
5. 打开前端，导入资产副本并验证哈希。
6. 先跑 Blender 基线，确认后再跑本地 AI，最后才允许付费 API。

关停：

1. 停止接收新任务，等待当前任务进入终态。
2. 保存 RenderSpec、workflow JSON、manifest、日志和费用记录。
3. 依次停止 API 服务和 ComfyUI；不要在写文件时强制结束进程。
4. 检查输出能打开且哈希已记录，再清理可重建缓存。

建议的健康检查字段：

```json
{
  "status": "ok_or_degraded",
  "blender": {"available": true, "version": "recorded"},
  "comfyui": {"available": true, "commit": "recorded", "cuda": true},
  "gpu": {"name": "RTX 4060 Ti", "vram_mb": "measured"},
  "disk": {"F_free_gb": "measured", "D_free_gb": "measured"},
  "providers": {"local_sdxl": "ready", "api": "configured_or_disabled"}
}
```

### 13.10 W7：P0 实测表和通过门槛

每个样品建立目录：

```text
D:\AI-Renderer\evaluations\P0\<sample_id>\
  source\
  blender\
  local_sdxl\
  nano_banana_2\
  nano_banana_pro\
  gpt_image_2\
  qa\
  metrics.csv
  notes.md
```

`metrics.csv` 至少包含：日期、task_id、sample_id、backend、model、版本/哈希、分辨率、seed、steps、denoise、峰值 VRAM、峰值 RAM、冷/热耗时、费用、轮廓 IoU、关键部件通过、OCR 通过、材质评分、参考遵循评分、失败类型和最终状态。

P0 建议门槛：

- 三个样品均有可复现 Blender 基线和完整工件清单。
- 本地 SDXL 至少有一条 768 或 1024 工作流连续成功 10 次；失败必须可归因。
- API 每个候选仅做小样本，至少获得一张完整响应并记录实际费用。
- 结构优先结果达到第 8 节的结构与关键部件要求；Logo/OCR 不通过不得用综合美观分掩盖。
- 能从新终端按记录重新启动并重跑指定 seed；跨版本不要求逐像素一致，但版本与哈希必须一致。

完成后再做决策：若本地预览质量够且速度可接受，保持 8 GB；若主要问题是终稿上限，优先增加 API 用量；只有当本地大模型、批量速度或隐私要求成为明确瓶颈时，再评估 16/24 GB 显存设备。

### 13.11 常见故障处理

| 症状 | 排查顺序 | 处理边界 |
|---|---|---|
| `torch.cuda.is_available()` 为 False | `nvidia-smi` → ComfyUI 启动日志 → torch/CUDA 构建来源 | 不反复混装 torch；保存环境后按官方组合重建 |
| CUDA out of memory | 关闭其他 GPU 程序 → batch=1 → 768 → 停止重启 → `--lowvram` | 不用页面文件伪装成显存；仍失败则换轻量工作流/API |
| ComfyUI 启动即报节点错误 | 禁用全部自定义节点 → 最小工作流 → 逐个恢复 | 未验证节点不得进入生产注册表 |
| Blender 没用 GPU | Preferences 设备 → Cycles/GPU Compute → 启动日志 | CPU 能跑仅证明场景有效，不证明 GPU 已配置 |
| 深度控制失真 | 核对相机/裁切/尺寸 → 深度近远范围 → 控制模型编码要求 | 不把展示用伪彩深度图直接当控制输入 |
| 产品变形或按钮丢失 | 降 denoise → 提高有效控制 → 收紧 Mask → 回退 Blender 像素 | 关键结构失败直接 `needs_review` |
| API 超时 | 保存 request ID → 查询供应商状态 → 检查账单/任务 | 未确认前不重复付费提交 |
| 中转返回尺寸或模型不符 | 保存原始响应头/体和文件哈希 → 与官方端点对照 | 停用该后端，不通过后处理掩盖来源问题 |
| 磁盘快速下降 | 查重复模型、输出候选、缓存与临时 EXR | 只清理可重建缓存，保留源资产与 manifest |

### 13.12 升级、回滚与记录

- Blender、ComfyUI、torch、自定义节点、模型和工作流禁止同一天无记录地一起升级。
- 升级 ComfyUI 时保留旧目录，复制配置但不覆盖旧环境；用 smoke workflow 和三个固定 seed 验证后再切换。
- 每个模型保存来源 URL、许可证、下载日期、文件名、大小和 SHA-256。PowerShell 计算哈希：

```powershell
Get-FileHash "F:\AI-Renderer\models\checkpoints\model.safetensors" -Algorithm SHA256
```

- 优先使用 `safetensors`；模型文件仍视为不可信外部输入。自定义节点代码必须记录 commit 并审查安装脚本。
- 回滚是将启动路径切回已验证旧目录和旧 workflow，不删除失败的新版本；失败环境留到日志归档完成后再处理。
- 每完成 W0–W7 的任一阶段，都在第 12 节追加一条新记录，写明真实命令、版本、验证文件、成功/失败结论和下一步。不得把“已写执行手册”登记为“已安装”或“已跑通”。
