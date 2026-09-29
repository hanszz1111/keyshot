# QWEN21 · Qwen-Image-2.1 本地部署与最小试跑实测

> **日期**：2026-09-29 ｜ **执行方**：Windows 本机（RTX 4060 Ti 8 GB）
> **依据**：[Qwen-Image-2.1 Windows 部署与模型切换执行方案](../docs/Qwen-Image-2.1-Windows-部署与模型切换执行方案.md) 第 1–4 阶段
> **结论**：**阶段 1–4 实机跑通**；**阶段 5（18 张成对盲评）与阶段 6（网页模型选择）未执行**，网页上不存在任何 Qwen 选项。
> **定位**：本文件是本次实验的**独立证据记录**，不占用 R2 的 `TASK.md` / `RESULT.md` / `REVIEW.md`（R2 当前仍为 `READY_FOR_REVIEW`，按协议不并行改同一文件）。本轮因此未开 R3。
> 路径约定：项目内路径相对仓库根；实验实例在**机外** `F:\AI-Renderer\experiments\`，不属于本仓库。

---

## 0. 方案第 8 节要求的回填项（逐项）

| 要求项 | 本次实测结果 |
|---|---|
| 日期 | 2026-09-29 |
| 机器 / 驱动 | RTX 4060 Ti 8 GB ／ 驱动 616.92（CUDA UMD 13.4）；内存 32,604 MB |
| ComfyUI 版本 | **0.37.0**（实验实例与正式实例同版本） |
| 模板版本 | `comfyui_workflow_templates 0.11.66` / `comfyui_workflow_templates_json 0.1.92` / 前端 1.52.7 |
| 模型文件名 | `qwen_image_2.1_int8_convrot.safetensors`、`qwen3vl_8b_w4a8.safetensors`、`qwen_image_2.1_vae_bf16.safetensors` |
| 下载 / 安装检查 | 三文件 sha256 **与 HF 官方 LFS oid 逐一相等**；三者在对应 Loader 下拉可见 |
| 文生图 | ✅ 1 张，`qwen21_t2i_probe_00001_.png`，832×512，14.87 s |
| 图片编辑 | ✅ 1 张，`qwen21_edit_probe_00001_.png`，992×608，21.49 s |
| 是否 OOM | **否**。文生图峰值显存 7561 / 8188 MiB（92%） |
| 单张耗时 | 文生图 14.87 s ／ 图片编辑 21.49 s（25 步） |
| 峰值显存 | 7561 MiB（92%）；编辑完成后回落 5271 MiB |
| 结构问题 | 编辑输出保留轮廓/机位/部件数/底部 USB-C 图标；**但仅 1 SKU × 1 机位 × 1 种子，不足以判断形准** |
| 原 SDXL 是否仍能出图 | ✅ 正式实例 8188 独立启动 HTTP 200，SDXL 与 ControlNet/IPAdapter 模型列表完整；原目录关键文件 mtime 未变 |

---

## 1. 环境隔离（阶段 1–2）

| 项 | 值 |
|---|---|
| 正式实例（**未改动**） | `F:\AI-Renderer\packs\ComfyUI_windows_portable`，端口 8188 |
| 实验实例（新建） | `F:\AI-Renderer\experiments\Qwen21\ComfyUI_windows_portable\`，端口 **8190** |
| 建立方式 | `robocopy` 复制本地已有的官方 NVIDIA 便携版副本：3.911 GB / 6,062 目录 / 58,614 文件 / 47 s |
| 启动命令 | `python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --lowvram --port 8190` |
| 探活 | `GET http://127.0.0.1:8190/` → HTTP 200 |
| Python / torch | 3.13.14 ／ 2.13.0+cu130 |
| 量化算子支持 | `comfy-kitchen 0.2.35`：`int8_linear`、`w4a8_int8_linear`、`dequantize_int8_convrot_weight`、`quantize_int8_convrot_weight` |
| 磁盘 | F 盘 244 GB / 可用 172 GB（方案要求预留 35 GB） |

**方案第 2.2 步（更新实验实例以补齐模板节点）无需执行**：本地这份 0.37.0 的 `comfy_extras\nodes_qwen.py` 已内置 `TextEncodeQwenImage21` 与 `QwenImage21Cache`；模板库已带 `image_qwen_image_2_1_t2i.json` 与 `image_qwen_image_2_1_image_edit.json`。

**非阻塞异常**：启动日志出现

```
[ERROR] Failed to initialize database. ... [WinError 5] 拒绝访问。:
'F:\AI-Renderer\experiments\Qwen21\ComfyUI_windows_portable\ComfyUI\user\comfyui.db.lock'
[INFO] Using RAM pressure cache.
[INFO] Starting server
```

服务照常启动，出图不受影响。

---

## 2. 权重下载与校验（阶段 3）

| 角色 | 文件 | 字节数 | sha256 vs 官方 LFS oid | 速度 | 耗时 |
|---|---|---|---|---|---|
| 扩散模型 | `qwen_image_2.1_int8_convrot.safetensors` | 7,256,783,064 | ✅ 相同 | 42.9 MB/s | 169.3 s |
| 图文编码器 | `qwen3vl_8b_w4a8.safetensors` | 6,312,105,364 | ✅ 相同 | 45.3 MB/s | 139.4 s |
| 图像 VAE | `qwen_image_2.1_vae_bf16.safetensors` | 675,509,688 | ✅ 相同 | 45.2 MB/s | 15.0 s |

- 合计 **14.24 GB / 5 分 30 秒**（方案预估 20–90 分钟）。
- **镜像源实测差异**：同一 VAE 文件 **ModelScope 42–45 MB/s**，**hf-mirror 2.27 MB/s**（约 20 倍差距）→ 全程走 ModelScope。
- 官方 sha256 取自 `https://hf-mirror.com/api/models/Comfy-Org/Qwen-Image-2.1/tree/main/<sub>` 的 `lfs.oid`。
- 未下载：BF16 主模型（14.23 GB）、BF16 编码器（17.53 GB）、提示词增强器 `qwen3.5_9b_…_pe_t2i/i2i`（各 9.47 GB）、额外 LoRA。

---

## 3. 最小试跑（阶段 4）

### 3.1 官方模板参数（取自模板 JSON 的子图内部）

两个模板一致：`KSampler = [seed=0, "fixed"/"randomize", steps=25, cfg=1, "euler", "simple", denoise=1]`。
模板默认 UNET 为 `qwen_image_2.1_int8_convrot.safetensors`、CLIP 为 `qwen3vl_8b_int8_convrot.safetensors`、VAE 为 `qwen_image_2.1_vae_bf16.safetensors`。本次 CLIP 换为方案指定的更低显存 **w4a8** 版本。

### 3.2 结果

| 项 | 文生图 | 图片编辑 |
|---|---|---|
| 载荷 | 纯提示词 | 白模 `assets/passes/AI渲染1/front/clay.png`（1232×752） |
| 输出尺寸 | 832×512 | 992×608（`resolution=768` 按原图 1.64:1 折算） |
| 种子 | 43 | 43 |
| 采样速度 | — | 1.77–1.80 it/s |
| 执行耗时 | **14.87 s** | **21.49 s** |
| 产物 | `qwen21_t2i_probe_00001_.png`（527,102 B） | `qwen21_edit_probe_00001_.png`（571,097 B） |
| `node_errors` | `{}` | `{}` |

日志给出的模型装载信息：

```
[INFO] Requested to load QwenImage21
[INFO] Model QwenImage21 prepared for dynamic VRAM loading. 6920MB Staged. 0 patches attached.
[INFO] Model WanVAE prepared for dynamic VRAM loading. 644MB Staged.
[INFO] Set vram state to: LOW_VRAM
[INFO] Using async weight offloading with 2 streams
[INFO] Enabled pinned memory 13041.0
[INFO] DynamicVRAM support detected and enabled
```

### 3.3 编辑结果的人工观察

输出**完整保留**原白模的：外轮廓、机位与透视、部件数量、**底部 USB-C 充电口图标**、机身侧面小齿纹。
按提示词改变的只有：机身 → 细砂纹深灰塑料；圆环与镶边 → 拉丝铝；背景 → 浅灰无缝影棚。
即方案要求的「确认输出真的变化且主体不是重新设计」**成立**。

⚠️ 但本阶段只跑了 **1 个 SKU 的 1 个机位、1 个种子**。项目既有结论「AI 会臆造 CAD 中不存在的表面细节、产品本体应走真渲染」**不因此改变**；形准判断要等阶段 5。

---

## 4. 实现层两个必须记住的格式（阶段 6 会用到）

1. **`POST /prompt` 必须包外层**
   直接提交节点图 → `{"error":{"type":"no_prompt"}}` / HTTP 400。
   正确载荷：`{"prompt": {节点图}, "client_id": "..."}`。

2. **参考图（Autogrow）在 API 里是扁平点号键**
   `TextEncodeQwenImage21.images` 的类型是 `COMFY_AUTOGROW_V3`，API 中须写成：
   `"images.image_1": ["4", 0]`
   依据：`comfy_api/latest/_io.py` 中 `finalize_prefix()` 以 `.` 连接前缀、`build_nested_inputs()` 以 `.` 拆路径取值。
   **写成嵌套 dict 会被静默忽略** —— 不报错，但参考图完全不生效（最容易误判为「模型没效果」）。

3. 两条附带事实：
   - `TextEncodeQwenImage21` 有 **3 路输出**：`positive` / `negative` / **`latent`**；第三路是「按第一张参考图尺寸的空 latent」，**编辑时必须用作 KSampler 的 `latent_image`**（改用 `EmptyLatentImage` 会因尺寸不一致产生偏移）。
   - `CLIPLoader.type` 填 **`qwen_image`**（不是 `qwen_image21`）。

---

## 5. 未做 / 不可宣称

| 项 | 状态 |
|---|---|
| 阶段 5：≥3 产品 × ≥3 机位 × 2–3 种子的成对盲评（≥18 张） | ☐ 未做 |
| 阶段 6：`/api/renderers`、`engine_id`、网页下拉、`config/comfy_workflow_qwen21_edit.json` | ☐ **未写任何代码** |
| 阶段 7：日常部署、一键启动接入、回退演练 | ☐ 未做 |
| 整机 / 多机位 / 1536 / 2048 分辨率 | ☐ 未测（仅 832×512、992×608） |
| 2K 原生输出、RGBA 透明、多参考图（≤10 张） | ☐ 未测 |
| 长批次稳定性（OOM、重试、冷启动分布） | ☐ 未测（各只 1 张） |
| 与 SDXL 的画质对比结论 | ☐ **无任何对比数据，不作结论** |

**许可提醒（不阻碍个人试用）**：Qwen-Image-2.1 官方权重采用 Qwen Research License（非商用）；本项目 `AI/DECISIONS.md` 的 ADR-008 是**商用选型**规则。当前按个人本地研究/评估推进；若日后用于收费客户项目或对外服务，须先核对当时的官方许可。

---

## 6. 证据索引

| 内容 | 位置 |
|---|---|
| 执行方案 | `docs/Qwen-Image-2.1-Windows-部署与模型切换执行方案.md` |
| 过程文档（SSOT，含本次变更行与「八」章） | `00-AI白模渲染器-过程文档.md` |
| 本文件 | `AI/QWEN21-本地部署实测.md` |
| 实验实例根目录（机外，不入仓） | `F:\AI-Renderer\experiments\Qwen21\` |
| API 工作流（机外） | `F:\AI-Renderer\experiments\qwen21_t2i.json`、`qwen21_edit.json` |
| 输出样张（机外，含产品外观，不入公开仓库） | `…\ComfyUI\output\qwen21_*_probe_00001_.png` |
| 启动与下载日志（机外） | `F:\AI-Renderer\experiments\_comfy8190.log`、`_dl.log`、`_sha256.txt` |

产品白模图与生成结果**未提交公开仓库**；如需 Mac 侧独立核对视觉部分，请说明需要哪一项，再评估脱敏后提供的方式。
