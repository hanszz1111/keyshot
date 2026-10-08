# QWEN21 · Qwen-Image-2.1 本地部署与最小试跑实测

> **日期**：2026-09-29 ｜ **执行方**：Windows 本机（RTX 4060 Ti 8 GB）
> **依据**：[Qwen-Image-2.1 Windows 部署与模型切换执行方案](../docs/Qwen-Image-2.1-Windows-部署与模型切换执行方案.md) 第 1–4 阶段
> **结论**：**阶段 1–4 实机跑通**；**阶段 6（网页模型选择）已实施并验收**（见第 7 节）；**阶段 5（≥18 张成对盲评）与阶段 7（日常部署/回退）未执行** —— 因此实验引擎在界面上标记为「实验模式」，只开放单张图片精修，未设为默认。
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

---

## 7. 阶段 6：接入网页（2026-09-29 完成）

### 7.1 改了什么

| 位置 | 内容 |
|---|---|
| `config/render_defaults.json` | 新增 `render_engines` 注册表（两引擎的标签/开关/实例地址/能力范围/禁用原因）与 `qwen21_edit` 参数基线（25 步 / CFG 1.0 / euler / simple / denoise 1.0，均为官方模板值） |
| `config/comfy_workflow_qwen21_edit.json`（新增） | 8 节点 **API 格式**工作流；节点 ID 与 SDXL 工作流**零重叠** |
| `web/server.py` | 只读 `GET /api/renderers`；任务载荷 `engine_id`（缺字段 → 稳定模式）；`_submit_qwen()` / `fill_qwen_workflow()` / `QWEN_SLOTS`；`engine_ready()` 五道探测；`update_task_run_meta()`；`qwen_task_running()` 与 Blender 双向互斥；`comfy_poll()` 按任务所属引擎选实例 |
| `web/index.html` / `app.js` / `styles.css` | 「出图模型」下拉 + 状态提示 + 能力围栏 + 精修分辨率选择 |
| `web/selftest.py` | **18 → 41 项**（新增引擎与工作流契约的无 GPU 用例） |

### 7.2 三条硬约束的落实（执行方案第 6 节）

1. **可用性在服务端判定**：`engine_ready()` 依次查「开关 → 8190 端口与三个权重是否出现在下拉 → 必需节点 → 工作流文件」，任一不过就返回中文原因。前端只呈现结果，不自己下结论。
2. **绝不静默降级**：实验引擎不可用时提交直接 400，错误文案给出可执行动作（启动 `启动Qwen21实验服务.bat`），**不会**换回 SDXL 出一张无关的图。自检里有专门用例验证这条。
3. **两条链路物理隔离**：不同端口、不同工作流文件、不同槽位表、不同采样参数；`_submit_qwen()` 明确拒绝带 `depth_img`/`normal_img`/`mask_img` 的载荷。

### 7.3 验收实测

| 项 | 结果 |
|---|---|
| `GET /api/renderers` | 两引擎 `available=true` |
| 端到端 1 张（640 预算） | 提交 200 → 轮询 7 次（~21 s）→ `outputs/_selftest/front/qwen21_00001_.png` → 预览 HTTP 200 / 423,657 B / 有效 PNG |
| 运行元数据 | `gpu_ms=19089`、`weights` 三文件名、`workflow`、`seed`、`resolution`、`source_img` 全部落库 |
| 小样 2 机位 × 3 种子 | **6/6 成功**，GPU 11.1–15.7 s（均值 **13.0 s**） |
| 自检 | **41 / 41** |
| 清理 | 产物与 7 条测试任务隔离至 `_隔离区/20260929_v35_qwen/`，任务库剩 73 条真实任务 |

### 7.4 启用与回退

- **启用**：`render_engines.qwen21_edit_local.enabled`（当前 `true`）+ 让 8190 在线。**v3.6 起直接双击项目根目录 `一键启动.bat` 即可** —— 它一并起 8190（计划任务 `AIRender_Qwen21`，关窗口不死）；只想起前两个就设 `AI_RENDER_NO_QWEN=1`。机外那份 `启动Qwen21实验服务.bat` 仍可用，但不再需要。
- **回退**：把 `enabled` 改回 `false` 即可，界面显示「实验引擎当前为关闭状态」，SDXL 链路与全部历史结果不受影响，**不需要改动任何旧任务记录**。
- **输入**：产品图片，或该机位的白模截图（`passes/<SKU>/<view>/clay.png`）。

### 7.5 仍未做

阶段 5 成对盲评、阶段 7 日常部署与回退演练、高分辨率（1536/2048）、2K 原生输出、RGBA 透明、多参考图、长跑稳定性 —— **均未测**。**没有任何与 SDXL 的画质对比数据，因此不作「更好/更准」的任何结论。**

---

## 8. v3.13「候选系列」Windows 端验收（2026-09-29）

v3.13 让千问在实例就绪时成为界面默认入口，并把八面图改成**候选系列**：
同系列主视图先生成，其余机位以「目标机位白模」为第一参考、**已完成的主视图**为第二参考
（接线到 `TextEncodeQwenImage21` 的 `images.image_2`）。
Mac 侧自检通过，但文档明确标注 **「Windows 真实模型与 GPU 端到端尚未验收」**。本次补上。

**环境**：RTX 4060 Ti 8 GB ／ ComfyUI 0.37.0 ／ 实验实例 8190 ／ 数据 `AI渲染1` 真实白模 ／ 640 像素预算 15 步。

| 检查项 | 结果 |
|---|---|
| 反例：主视图未完成时提交其他机位 | **HTTP 400**「同组主视图尚未完成；请先完成主视图，再继续其他机位」—— 未跨系列串图 ✅ |
| 主视图（`view == anchor_view`） | 不要求锚点，4 次轮询出图完成 ✅ |
| 关联机位（side） | 提交成功，`appearance_ref_task = 699`（主视图任务），6 次轮询出图完成 ✅ |
| **第二参考接线** | `_meta.run.appearance_ref_output = outputs/AI渲染1/front/qwen21_00061_.png`（主视图产物）—— 证明 `images.image_2` 的**扁平点号键**在 ComfyUI 0.37.0 上确实生效 ✅ |
| 人工比对 | 两图**材质一致**（深灰磨砂 + 银色圆环）；**side 相机角度未被主视图带跑**，符合设计意图 ✅ |
| 回归 | `selftest.py` **68 / 68** |
| 清理 | 3 条测试任务 + 2 张产物隔离至 `_隔离区/20260929_v313_series_winverif/` |

**仍未验**：八面全量画质、8 GB 双参考同时驻留时的显存峰值、多候选批量速度。
**因此不宣称「八面一致性已通过」** —— 本次只证明链路接通、单组两机位可用。

> 留痕：Windows 侧 2026-09-29 补第 8 节（对方 v3.13 提交 `94dc748` 的端到端验收）。

---

## 9. 八面候选系列真实运行实测（2026-09-30 上午）

第 8 节只验了「单组两机位」。**本节补上第 8 节末尾标注的「八面全量」** —— 用户在实际使用中跑了三组完整系列，
数据全部来自任务库落库的运行元数据（`_meta.run.gpu_ms` / `appearance_ref_task`），非事后估算。

**环境**：RTX 4060 Ti 8 GB ／ ComfyUI 0.37.0 ／ 实验实例 8190 ／ 引擎 `qwen21_edit_local`
**参数**：分辨率预算 896 ／ 无深度 ControlNet ／ 每机位 1 张候选／数据 `AI渲染1`

### 9.1 系列一：8 机位 / 50 步

系列号 `series-1790730163327-17658d43`，锚点 `front`。

| 任务 | 机位 | 角色 | gpu_ms | 外观参考 |
|---|---|---|---|---|
| #758 | front | **主视图** | 65.4 s | — |
| #759 | back | 关联 | 72.7 s | #758 |
| #760 | side | 关联 | **86.4 s** | #758 |
| #761 | side_left | 关联 | 72.5 s | #758 |
| #762 | top | 关联 | 72.6 s | #758 |
| #763 | bottom | 关联 | 73.1 s | #758 |
| #764 | 3q4_left | 关联 | 75.3 s | #758 |
| #765 | 3q4_right | 关联 | 74.5 s | #758 |

**累计 592.4 s（9.9 分钟）｜平均 74.1 s/张｜主视图 65.4 s vs 关联机位均 75.3 s（+9.9 s）**

### 9.2 系列二：8 机位 / 35 步

系列号 `series-1790730957759-96767ea7`，锚点 `front`。

| 任务 | 机位 | 角色 | gpu_ms | 外观参考 |
|---|---|---|---|---|
| #766 | front | **主视图** | 40.9 s | — |
| #767 | back | 关联 | 55.2 s | #766 |
| #768 | side | 关联 | 55.2 s | #766 |
| #769 | side_left | 关联 | 56.1 s | #766 |
| #770 | top | 关联 | 56.8 s | #766 |
| #771 | bottom | 关联 | 56.7 s | #766 |
| #772 | 3q4_left | 关联 | 57.0 s | #766 |
| #773 | 3q4_right | 关联 | 57.1 s | #766 |

**累计 435.0 s（7.3 分钟）｜平均 54.4 s/张｜主视图 40.9 s vs 关联机位均 56.3 s（+15.4 s）**

### 9.3 系列三：2 机位 / 35 步（锚点换了 side_left）

系列号 `series-1790733428948-1a4317fc`，锚点 `side_left` —— 说明**锚点机位是可配置的**，不限于 front。

| 任务 | 机位 | 角色 | gpu_ms | 外观参考 |
|---|---|---|---|---|
| #774 | side_left | **主视图** | 42.1 s | — |
| #775 | 3q4_left | 关联 | **94.7 s** | #774 |

### 9.4 可复用的结论（仅速度与稳定性，不含画质判断）

1. **8 GB 单卡能完整跑完八面候选系列，全程无 OOM。** 三个系列 18 张全部 `done`，无失败、无中断。
2. **双参考有可测的代价**：关联机位比同系列主视图慢 **约 10–15 s**（35 步组 +15.4 s 更明显），
   与「多送一张参考图进 `images.image_2`」的预期一致。
3. **步数是主要成本杠杆**：同八面、同 896 预算，50 步 592 s vs 35 步 435 s（**约 1.36 倍**）。
   每张 35 步 ≈ 54 s、50 步 ≈ 74 s。
4. **⚠️ 存在单张异常慢的样本**：#760 `side` 86.4 s（较同系列均值高约 15%）、
   **#775 `3q4_left` 94.7 s（是主视图 42.1 s 的 2.25 倍）**。两张都是「关联机位」。
   没有采集到当时的显存峰值，**无法判定是显存压力、参考图尺寸差异还是偶发**，
   需要后续带 `nvidia-smi` 采样复现。**不据此下任何「稳定/不稳定」结论。**
5. **锚点机位可切换**：系列三用 `side_left` 作锚点同样跑通。

### 9.5 产物索引

产物在项目 `outputs/AI渲染1/<机位>/`（**遵循仓库约定不入仓**），本次新增：

```
qwen21_00111_.png   front       qwen21_00119_.png   front
qwen21_00112_.png   back        qwen21_00120_.png   back
qwen21_00113_.png   side        qwen21_00121_.png   side
qwen21_00114_.png   side_left   qwen21_00122_.png   side_left
qwen21_00115_.png   top         qwen21_00123_.png   top
qwen21_00116_.png   bottom      qwen21_00124_.png   bottom
qwen21_00117_.png   3q4_left    qwen21_00125_.png   3q4_left
qwen21_00118_.png   3q4_right   qwen21_00126_.png   3q4_right
                                qwen21_00127_.png   side_left
                                qwen21_00128_.png   3q4_left
```

### 9.6 仍未做的部分（明确边界）

- **八面材质一致性的人工核对尚未做** —— 本次只统计速度与稳定性，**没有逐机位比对材质是否跳色、
  是否丢失同一产品身份**。因此**不能宣称「八面一致性已通过」**。
- 显存峰值未采集（结论 4 里的异常样本因此无法归因）。
- 多候选（每机位 >1 张）未测。

> 留痕：Windows 侧 2026-09-30 补第 9 节（用户实际使用中的三组八面候选系列实测数据）。
> 数据来源：`config/tasks.db` 任务 #758–#775 的 `_meta.run`。按协作协议，**Windows 端签收 GPU 数据**。

---

## 10. 权重到底是哪种量化（2026-10-08 直接读文件头核实）

§2 只记了「与官方 sha256 相同」，但没有记录**量化格式本身**。
本节直接从 safetensors 头部与 ComfyUI 的 `comfy_quant` 元数据块读取，
不靠文件名推断。

### 10.1 权威判据：`comfy_quant` 元数据块

ComfyUI 的量化检查点在每个被量化的层旁附一个名为 `*.comfy_quant` 的 U8 张量，
内容是 **UTF-8 的 JSON**（实测 72 或 89 字节），声明该层的量化算法：

| 文件 | `comfy_quant` 内容 |
|---|---|
| `qwen_image_2.1_int8_convrot` | `{"format": "int8_tensorwise", "convrot": true, "convrot_groupsize": 256}` |
| `qwen3vl_8b_w4a8`（绝大多数层） | `{"format": "asym_w4a8_int8", "group_size": 16, "convrot": true, "convrot_groupsize": 256}` |
| `qwen3vl_8b_w4a8`（`lm_head` / `embed_tokens`） | `{"format": "int8_tensorwise", "convrot": true, "convrot_groupsize": 256}` |

> `convrot` = 量化前对权重做分组旋转（group size 256）以降低激活离群值对 INT8 的影响，
> 与 `comfy-kitchen` 里的 `quantize_int8_convrot_weight` / `dequantize_int8_convrot_weight` 对应
> （见 §0 的算子清单）。

### 10.2 张量级证据

| 文件 | 张量数 | 量化权重 | 伴随张量 | 未量化部分 |
|---|---|---|---|---|
| `qwen_image_2.1_int8_convrot` | 649 | 192 个 **I8**（满尺寸，如 `[4096,4096]`） | 192 个 F32 `weight_scale`（`[out,1]`，**逐输出通道**） | 73 个 BF16（`img_in`/`modulation`/`norm_out`/`proj_out`/时间嵌入） |
| `qwen3vl_8b_w4a8` | 1762 | 254 个 **I8**，但形状是原维度**的一半**（如 `gate_proj [12288,2048]` ≈ 原 `[12288,4096]`）→ **两位一个字节，即 4 bit** | 252 组 `weight_codebook` F32`[16]`（**16 项码本 = 4 bit**）+ `weight_s_channel` F32`[out]`（逐通道）+ `weight_s_rel` F8_E4M3`[out,256]`（分块相对 scale） | 496 个 BF16（LayerNorm / bias 等），另有 `lm_head`/`embed_tokens` 是 INT8（`weight_scale` F32`[151936,1]`） |
| `qwen_image_2.1_vae_bf16` | 238 | **0** | — | 全部 238 个 BF16 |

### 10.3 结论

**「是不是 INT8」要分开回答，三者并不一样：**

- **扩散主体（UNet）：是 INT8** —— `int8_tensorwise` + 逐输出通道 scale + convrot 旋转。
  这与文件名一致。
- **文本编码器：不是 INT8，比 INT8 更低** —— 是 **4 bit 非对称权重（asym_w4a8，group 16，
  码本方式）**，只有 `lm_head`/`embed_tokens` 保持 INT8。**这是本项目主动选择**：
  §3.1 记录官方模板默认 CLIP 是 `qwen3vl_8b_int8_convrot`，本次为省显存换成了更激进的 w4a8。
- **VAE：BF16，完全没量化**（0.63 GiB，量化收益也小）。

### 10.4 完整性复核（2026-10-08 重算）

| 文件 | 本机 sha256 | 官方 LFS oid | 一致 |
|---|---|---|---|
| `qwen_image_2.1_int8_convrot.safetensors` | `cb74113cb03faecd79611b01fd7fd642f0aa60d6f0b95086abee214d75eaa57d` | 同 | ✅ |
| `qwen3vl_8b_w4a8.safetensors` | `7754425e55e7bea2bfde4dde59a4cc236cb44e5ee9c215ea66ef8d47012824eb` | 同 | ✅ |
| `qwen_image_2.1_vae_bf16.safetensors` | `bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9` | 同 | ✅ |

### 10.5 同仓库里还有这些**未下载**的官方替代件（核实于 2026-10-08）

| 路径 | 说明 |
|---|---|
| `diffusion_models/qwen_image_2.1_bf16.safetensors` | UNet 全精度版（`89f4158d…`） |
| `text_encoders/qwen3vl_8b_int8_convrot.safetensors` | **官方模板默认的 INT8 文本编码器**（`8bfd0f6e…`）。想回到「纯 INT8 组合」就换它 |
| `text_encoders/qwen3vl_8b_bf16.safetensors` | 文本编码器全精度版（`68bdc82b…`） |
| `text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | **官方提示词增强器 PE-I2I**（`32707d01…`），对应方案 P2 那条 |
| `text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors` | 官方提示词增强器 PE-T2I（`9182abae…`） |
| `model_patches/qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors` | **Qwen-Image-2.1 的 Union ControlNet**。本项目当前「形状只能靠 SDXL ControlNet」的结论**可能需要复核** —— 但该件属 `qwen_image_2.1_fun` 系列，**能否直接配 `qwen_image_2.1` 主模型未经验证**，不能据此宣称千问已支持深度锁形 |

> 本节只记录**读到的文件事实**与**官方仓库的存在清单**；
> 除 §10.4 的 sha256 外，其余均未做功能验证。
