# 产品白模 AI 渲染器：设计优化总纲

版本：v1.0｜更新：2026-09-26｜状态：设计大纲，尚未在目标 Windows 主机实测

本文件是供实施和评审使用的总纲。详细参数、Windows 命令、GitHub 调研依据与每次修改记录见 [AI渲染器_方案与过程记录.md](AI渲染器_方案与过程记录.md)。后续修改本总纲时，必须同步更新主文档正文并在其第 12 节追加记录。

## 一、目标与边界

1. 输入：已有产品白模（首版 GLB/glTF、OBJ、STL）＋外观/材质/灯光描述；可附相似产品参考图。
2. 输出：固定相机的产品效果图、基础渲染、候选图、控制图、质量报告及可复现任务档案。
3. 目标质量：外观具有广告级质感，同时保留产品轮廓、按钮、孔位、Logo 和文字。
4. 首版范围：单用户 Windows 工作站、静态单视角或独立多视角图片、批量队列。
5. 后续范围：STEP/STP、文字或照片生成可编辑白模、跨视角一致纹理、转台资产；分别设验证门槛。

## 二、目标硬件与部署策略

| 已知条件 | 设计决定 |
|---|---|
| RTX 4060 Ti 8 GB；i5-14600KF；32 GB 内存 | 本地承担 Blender、控制图、SDXL 预览、局部修复、合成与 QA |
| F 盘剩余 212 GB；D 盘剩余 113 GB | F 放运行环境和精选模型；D 放项目、缓存、结果与评测，保持空闲余量 |
| 可调用 Nano Banana / GPT-Image-2 或中转 | API 承担高质终稿；经统一适配器接入，先用非敏感样品核对身份、尺寸、费用和数据条款 |

采用三个层级：L0 Blender 确定性基线 → L1 ComfyUI + SDXL 本地受控候选 → L2 API 高质终稿。三个层级均保存独立结果，某层不可用时报告其状态。

## 三、核心设计原则

1. **几何锚定**：Blender 白模决定相机、轮廓、部件位置和关键细节；同一相机输出 Beauty、Alpha、Depth、Normal、Object ID、阴影和反射。
2. **双模式**：结构优先模式保留 Blender 产品像素，AI 主要生成背景和允许的局部编辑；创意探索模式允许受控图生图，并明确标为概念效果。
3. **参考图只借视觉特征**：分别抽取材质、配色、光照和构图；参考产品的形状不自动替换源白模。用户明确参数优先。
4. **分层合成**：产品、背景、阴影/反射、局部编辑、Logo/文字各自存档；统一色彩空间和相机裁切，检查透明件、镜面与接触边缘。
5. **可复现**：保留原资产、RenderSpec、模型/节点版本与哈希、工作流 JSON、seed、工件清单、费用和 QA 结果。
6. **有界生成**：从 Blender 基线到本地候选，再到少量 API Hero 图；每阶段有通过或停止条件，避免无上限重试与计费。

## 四、系统模块大纲

```text
资产导入与检查
  → 需求解析与部件确认
  → RenderSpec 校验
  → Blender 工件 Worker
  → ComfyUI 本地候选 Worker
  → 可选 API 终稿 Provider
  → 本地分层合成与细节回填
  → 自动 QA + 人工复核
  → 导出、任务档案与过程登记
```

| 模块 | 核心职责 | 第一版完成标准 |
|---|---|---|
| 资产/部件 | 格式、单位、方向、部件与源文件哈希 | 错误输入可定位，原文件不覆盖 |
| RenderSpec | 文字和参考图变成可编辑的材质、灯光、相机参数 | 白名单与范围校验；未知部件需确认 |
| Blender Worker | 固定相机基础图和精确控制图 | 同尺寸/裁切、明确色彩空间、可重跑 |
| ComfyUI Worker | SDXL 单图、Depth 控制、Mask 局部编辑 | 8 GB 上 batch=1 稳定运行；工作流固定版本 |
| Provider Adapter | Nano Banana、GPT-Image-2、候选中转 | request ID、模型标识、尺寸、费用、失败原因可追踪 |
| 合成/QA | 产品像素与 Logo 回填；结构/部件/文字检查 | 不合格转 `needs_review`，不自动当成功 |
| 工作台 | 预览、对比、任务队列、导出 | 用户无需编辑 ComfyUI 节点图 |

## 五、GitHub 优化采纳顺序

| 顺序 | 项目 | 在本产品里的作用 | 采纳门槛 |
|---|---|---|---|
| 1 | [ComfyUI Core](https://github.com/Comfy-Org/ComfyUI) | 队列、局部重算、遮罩合成、API、模型卸载和可选超分 | 先跑通最小本地工作流 |
| 2 | [ComfyUI-BlenderAI-node](https://github.com/AIGODLIKE/ComfyUI-BlenderAI-node) | 借鉴 Blender 相机、遮罩、批量和纹理烘焙交互 | 与目标 Blender 版本单独验证；主链仍使用后台工件与 API |
| 3 | [IPAdapter Plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) | 参考图的材质/风格条件 | 仅参考图场景启用；结构漂移可控；固定维护版本 |
| 4 | [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) / [LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle) | 局部细节、遮罩边缘和图层合成 | 原生节点不足时引入，逐个验证显存和保护区 |
| 5 | [productfix](https://github.com/MiddleKD/ComfyUI-productfix) / [ControlNet Aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | Logo 保护对照；无 3D 时估深度 | 分别隔离测试；已有 3D 优先用真实几何深度 |

初期节点安装原则：一个 SDXL 基础模型、一套匹配控制权重、ComfyUI Core；每新增一个插件都记录 commit、依赖、模型哈希、成功和失败样例。SUPIR 优先测试 ComfyUI 核心实现，8 GB 可行性由实测决定。

## 六、Windows 落地路线

| 阶段 | 交付件 | 通过条件 |
|---|---|---|
| W0 环境基线 | 驱动/GPU/内存/磁盘/系统记录 | `nvidia-smi` 正常，空间满足预算 |
| W1 工具与目录 | Git、Blender、ComfyUI/Python 的固定版本 | 各工具独立启动，路径和版本已登记 |
| W2 Blender | Beauty、EXR、Depth、Normal、Mask、场景文件 | 同相机同尺寸，GPU 基线成功 |
| W3 ComfyUI | 本地 SDXL 最小工作流 | CUDA 可见，768/1024 单图稳定，无 OOM |
| W4 受控渲染 | Depth/Edge/Mask 工作流与参考图实验 | 结构及关键部件通过 QA |
| W5 API | 官方/中转的独立配置与小样本 | 模型、尺寸、费用、数据规则已核对 |
| W6 混合闭环 | 基线、候选、终稿、分层合成和任务档案 | 可以重跑指定任务；Logo/文字正确 |
| W7 P0 评测 | 三类样品的质量、耗时、显存、费用表 | 达到主文档第 8 节与第 13.10 节门槛 |

具体 PowerShell 命令、目录结构、故障排查和回滚方法见主文档第 13 节。

## 七、P0 决策与验收

1. 样品：简单塑料件、拉丝金属件、多部件带 Logo 产品；同一组相机和提示词横向比较。
2. 对照：Blender 基线、本地 SDXL 受控渲染、可选 FLUX 可运行性实验、Nano Banana 2/Pro、GPT-Image-2。
3. 记录：峰值显存/内存、冷/热耗时、失败率、实付单价、轮廓 IoU、部件错漏、OCR、材质和参考遵循盲评分。
4. 优先级：产品结构与标识正确 → 材质/光照可信 → 视觉高级感 → 速度与成本。
5. 决策：若本地质量或速度不足，先调整工作流或终稿 API 分工；依据实测结果再决定是否采购更大显存设备。

## 八、当前状态与下一步

- 已完成：总体方案、Windows 执行手册、GitHub 候选调研和本总纲。
- 未完成：目标 Windows 主机安装、模型下载、实际 P0 渲染、性能与费用测试、软件实现。
- 下一步：准备一个真实白模和一张期望效果参考图；按 W0–W3 建立可复现基线，再执行 W4–W7。
- 过程记录：任何后续设计、依赖、代码或工作流调整，均同步更新主文档对应章节，并在第 12 节只追加新记录。
