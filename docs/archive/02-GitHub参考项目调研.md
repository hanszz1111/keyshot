# GitHub 参考项目调研

> 调研时间：2026-09-19
> 目的：找出可直接复用 / 可参考架构的开源项目，避免重复造轮子。
> 所有链接均为 GitHub 仓库地址。许可与星标以仓库当前页面为准，落地前请再核一次（尤其商用）。

---

## 〇、先给结论

**没有找到「白模 → 写实产品图」一站式开源项目。** 这个需求在开源社区是"片段化"的，需要自己组装。但有 4 个仓库在**架构层面**值得直接照抄：

| 仓库 | 为什么值得抄 |
|---|---|
| **OpenX-Inc/clay** | 「编排器 + 可插拔模型 + 引擎后处理」的三层架构，把"生成"和"交付级后处理"分离。它的工具注册表设计（同一能力同时暴露为 CLI / Agent / MCP）几乎可以 1:1 搬到本方案 |
| **DLR-RM/BlenderProc** | 程序化出 pass（RGB/depth/normal/seg）的成熟工程实现，yaml 配置 + Python API，`pip install blenderproc` 即可 |
| **kaibioinfo/ComfyUI_AdvancedRefluxControl** | 解决"参考图权重高就无视提示词"这个核心矛盾，是把 Redux 当 IP-Adapter 用的关键补丁 |
| **SamratBarai/ComfyAPI** | ComfyUI 的 Python 客户端封装，批量提交 / 轮询 / 下载输出的标准写法 |

---

## 一、生成引擎与核心控制（路线 A 核心）

| 项目 | 链接 | 许可 | 作用 | 可抄什么 |
|---|---|---|---|---|
| ComfyUI | `comfyanonymous/ComfyUI` | GPL-3.0 | 节点式推理引擎，本方案地基 | 工作流 = 可版本控制的生产资产 |
| ControlNet | `lllyasviel/ControlNet` | Apache-2.0 | 结构控制鼻祖 | depth/normal/canny 三种控制的原理与权重直觉 |
| ControlNet Aux 预处理 | `Fannovel16/comfyui_controlnet_aux` | — | 一整套预处理器节点 | Canny/Lineart/Depth/Normal 现算，省得引擎出图 |
| ComfyUI-Manager | `ltdrdata/ComfyUI-Manager` | — | 插件与模型管理 | 一键装装插件、批量下模型 |
| IC-Light | `lllyasviel/IC-Light` | — | 重打光模型（ControlNet 作者作品） | `fc` / `fbc` / `fcon` 三个版本的选型；fbc 会染色 |
| ComfyUI-IC-Light | `kijai/ComfyUI-IC-Light` | — | IC-Light 的 ComfyUI 原生实现（约 1.1k star） | 节点接线方式；`ICLightConditioning` 的 empty_latent 必须用它的输出，不能另接 Empty Latent |
| IPAdapter Plus | `cubiq/ComfyUI_IPAdapter_plus` | — | 参考图风格/材质注入 | 多参考图融合、权重黄金区间 0.7–0.9 |
| AdvancedRefluxControl | `kaibioinfo/ComfyUI_AdvancedRefluxControl` | — | 让 FLUX Redux 听提示词 | `downsampling_factor` 1–9 与 `weight` 的配合；`mode=autocrop with mask` 实现"只参考某个部位" |
| Flux Style Adjust | `tanglup/Comfyui_Flux_Style_Adjust` | — | Redux 权重五档简化控制 | 快速给非技术同事用的简化节点 |
| KJNodes | `kijai/ComfyUI-KJNodes` | — | 一批实用节点 | IC-Light 示例工作流依赖它 |
| Nunchaku（量化加速） | `mit-han-lab/ComfyUI-nunchaku` | — | FLUX 量化推理，低显存 | 8G 显存也能跑 FLUX 的路径；IP-Adapter / Redux 在量化模型上的接法 |

### FLUX.1-Redux 相关（参考图仿照的关键）

- 模型权重：`black-forest-labs/FLUX.1-Redux-dev`（HuggingFace）
- **已知行为**：高权重时完全忽略提示词，只复刻参考图 —— 免费版就是"高级图生图"
- **已知限制**：Redux **只接受正方形输入**，所以插件里才有 `center crop` / `keep aspect ratio` / `autocrop with mask` 三种裁切策略
- **适用判断**：在"结构和细节还原"上比 IP-Adapter 强，在"灵活性和提示词跟随"上比 IP-Adapter 弱。**电商产品图属于前者，优先 Redux。**

---

## 二、Pass / 数据集生成（L2 结构层）

| 项目 | 链接 | 许可 | 作用 | 备注 |
|---|---|---|---|---|
| **BlenderProc** | `DLR-RM/BlenderProc` | GPL-3.0 | 程序化 Blender 管线，出 RGB / depth / normal / seg / optical flow / NOCS | 官方支持 Linux/macOS，**Windows 是社区支持**；`pip install blenderproc`；yaml 配置；有 `--debug` 可在 Blender UI 里跑 |
| Blender-ControlNet | `coolzilj/Blender-ControlNet` | — | Blender 内直接出 ControlNet 输入图 | 参考它的多通道导出思路 |
| Blender headless | （内置） | — | `blender -b scene.blend -P script.py` | 最轻量，无依赖 |

### KeyShot（非 GitHub，但属于同一层）

- Headless scripting 文档：`media.keyshot.com/scripting/headless_doc/2026.1/lux.html`
- 手册：`manual.keyshot.com/?p=6126`
- **注意：Headless scripting 是 Pro 独占功能，需 KeyShot 9.3+**
- 可用函数（已核对文档函数清单）：`lux.openFile()`、`lux.getCameras()` / `lux.setCamera()`、`lux.getObjects()`、`lux.setObjectMaterial()`、`lux.getRenderOptions()`、`lux.renderImage(path, width, height, opts)`、`lux.renderAnimation()`、`lux.exportFile()`（`lux.EXPORT_GLTF` / `EXPORT_FBX` / `EXPORT_OBJ` / `EXPORT_USD`）、`lux.sceneNode.getMetadata()`
- Windows 专用 headless 入口：`keyshot_headless`
- 命令行：`keyshot_headless -headless [scene] -script script.py`，`-progress` 可把进度打到 stdout

---

## 三、3D 材质生成（路线 B）

| 项目 | 链接 | 许可 | 作用 | 判断 |
|---|---|---|---|---|
| **DreamMat** | `zzzyuqing/DreamMat` | **MIT** | SIGGRAPH 2024，文本 + 几何 → PBR 材质（albedo / metallic / roughness），几何与光照感知的 ControlNet | ⭐308。**商用友好**。基于 threestudio + SD2.1 + Blender 3.2.2 预渲数据；首次跑一个模型需 ~15 分钟 Blender 预渲染，之后走缓存 |
| MatGenAI（DreamMat-multi） | `dlgmltjdit/DreamMat-multi` | — | 把模型按语义部件分割，每个部件独立生成材质（解决"金色斧头"这类局部描述错配） | 对"外壳一种材质、旋钮另一种材质"的多材质产品非常对口。依赖 `SAMPart3D` |
| SAMPart3D | （见上条 README 引用） | — | 3D 部件语义分割 | 多材质产品的前置 |
| **TRELLIS.2** | `microsoft/TRELLIS.2` | **MIT** | 4B 参数，图 → 带完整 PBR（BaseColor/Metallic/Roughness/Alpha）的 3D 资产 | 512³ 约 3s，1024³ 约 17s，1536³ 约 60s（H100）。**商用友好**，且有配套的 OpenX clay 已做工程化封装 |
| Hunyuan3D-2.1 | `Tencent-Hunyuan/Hunyuan3D-2.1` | ⚠️ **非商用** | 开源 PBR 材质生成（Albedo/Metallic/Roughness），支持金属反射、SSS | 效果强，**但权重是非商用许可，商用项目慎用** |
| UniTEX | `YixunLiang/UniTEX` | — | CVPR 2026，任意形状高保真贴图（Flux LoRA + Large Texturing Model） | 最新工作，效果上限高；依赖 nvdiffrast / kaolin，环境较重 |
| Pixal3D | `TencentARC/Pixal3D` | ⚠️ **学术许可** | 图 → 3D，像素级反投影，输出带 PBR 的 GLB | SIGGRAPH 2026（腾讯 ARC + 清华）。保真度接近重建，**但学术许可、非商用、EU 不可用** |
| StableMaterials / StableMaterials-2 | `StabilityAI/...` | Apache-2.0 | 程序化 PBR 材质生成 | 被 OpenX clay 作为默认材质 provider |
| Paint3D / SyncMVD | （见 clay README） | commercial-OK | 多视角一致性贴图 | 商用许可友好，值得关注 |
| **OpenX-Inc/clay** | `OpenX-Inc/clay` | MIT（编排器） | 自托管版 Meshy/Rodin：图片/文本 → 游戏级 3D 资产（重拓扑、UV、LOD、碰撞、法线烘焙、自动绑定） | **架构范本**。编排器与 GPU 后端分离，模型 provider 可插拔（TRELLIS-2 / Hunyuan3D-2.1 / Hi3DGen / StableMaterials / Hunyuan3D-Paint），每个能力同时暴露为 CLI + Agent + MCP |

---

## 四、后处理

| 项目 | 链接 | 作用 |
|---|---|---|
| **BiRefNet** | `ZhengPeng7/BiRefNet` | SOTA 抠图 / 分割。多任务版本：`General`（通用）/ `Matting`（精细抠图）/ `General-2K`（2048）/ `HRSOD`。透明玻璃、金属边缘表现显著优于传统方案 |
| ComfyUI-BiRefNet | （ComfyUI 插件生态，搜 "BiRefNet"） | 在 ComfyUI 内直接调用，节点式 |
| **Real-ESRGAN** | `xinntao/Real-ESRGAN` | 图像超分，2–4x |
| Ultimate SD Upscale | （ComfyUI 插件） | 分块放大，保住细节同时升分辨率 |
| WAS Node Suite / LayerStyle | （ComfyUI 插件） | 批处理、图层、文字叠加等杂项 |

---

## 五、引擎桥接 / MCP（AI 直接操作 Blender）

如果你想让 AI 直接驱动 Blender 搭场景、调光线、出图，这几个 MCP 项目是现成入口：

| 项目 | 链接 | 特点 |
|---|---|---|
| **Mu-L/blender-mcp** | `Mu-L/blender-mcp` | 原版作者维护。实时 socket 桥接、对象操作、材质控制、场景检查、**视口截图**（让 AI 看见）、Python 执行、Poly Haven 资产、**Hunyuan3D / Hyper3D Rodin 模型生成**、Sketchfab 搜索导入、远程主机 |
| kleer001/blender-mcp | `kleer001/blender-mcp` | 工程化程度更高：**175 个 typed tools**，覆盖对象/材质/着色器节点/几何节点/修改器/动画/绑定/物理/合成等 25 个域。**不依赖 `execute_blender_code` 万能兜底**，更适合做生产集成 |
| ihub-devs/blender-mcp | `ihub-devs/blender-mcp` | Go 写的 bridge + Python addon，含 `render_scene` / `export_scene` / `set_material` 等工具 |
| ahujasid/blender-mcp | `ahujasid/blender-mcp` | 原始项目（上面几个的上游） |
| 3D-Agent | （见 blendermcp.org 对比） | 商业化替代方案，做参考对照 |

> **用途定位**：这几个工具适合做「探索期 / 单件处理 / 场景搭建」，**不适合跑 800 SKU 的批量流水线** —— 批量要走确定性的脚本，不要走 LLM 决策。

---

## 六、电商 / 产品图相关的场景化参考

| 项目 / 资源 | 链接 | 可借鉴点 |
|---|---|---|
| ecommerce-product-image-gen-sdxl | `Pritesh24gurjar/ecommerce-product-image-gen-sdxl` | SDXL + LoRA 在电商产品图上的完整训练/评估流程；用了 KREAM BLIP Captions 数据集；含 LoRA 训练脚本与评估指标 notebook。**可参考它做你自己的产品 LoRA** |
| CAIG（CTR 驱动的广告图生成） | `JD-GenX/CAIG` | WWW 2025，京东。用 MLLM + 强化学习按 CTR 优化广告图；含预训练数据集与模型。**思路价值 > 代码价值：背景不是随便生成的，是按点击率优化的** |
| KREAM Product BLIP Captions | HuggingFace `hahminlew/kream-product-blip-captions` | 电商产品图 + 自动 caption 数据集，可用于 LoRA 微调 |
| Z-Image（阿里通义） | `Tongyi-MAI/Z-Image` | 6B 参数，**中英文字渲染能力强**，8 步亚秒级出图。**对你的"详情页带文案"场景有额外价值** |

---

## 七、选型建议矩阵（给你这个类目）

| 环节 | 推荐（商用安全） | 备选 | 不推荐 |
|---|---|---|---|
| 推理引擎 | ComfyUI | SD.Next / A1111 | 整合包（改不了节点） |
| 底模 | FLUX.1-dev（看 BFL 条款）/ SDXL 系 | Qwen-Image | — |
| 结构控制 | ControlNet Depth + Normal | Canny/Lineart 补充 | 只靠 prompt |
| 参考注入 | FLUX Redux + AdvancedRefluxControl | IP-Adapter Plus | — |
| 打光 | KeyShot HDR 重渲（最稳） | IC-Light fc | IC-Light fbc（会染色） |
| Pass 生成 | Blender/BlenderProc + KeyShot beauty | — | 只用一张灰模图 |
| PBR 材质（如需） | TRELLIS.2（MIT）、DreamMat（MIT） | UniTEX | Hunyuan3D-2.1（非商用）、Pixal3D（学术许可） |
| 抠图 | BiRefNet | — | 传统色度抠图 |
| 超分 | Real-ESRGAN | Topaz（付费更稳） | — |
| 批量调度 | 自研 SQLite 队列 + ComfyUI HTTP API | ComfyAPI 封装 | 循环起进程 |

---

## 八、许可风险速查（商用必看）

| 许可 | 项目 | 商用 |
|---|---|---|
| MIT | DreamMat、TRELLIS.2、OpenX clay 编排器、Mu-L/blender-mcp | ✅ 可商用 |
| Apache-2.0 | ControlNet、StableMaterials、InstantMesh | ✅ 可商用 |
| GPL-3.0 | ComfyUI、BlenderProc | ⚠️ 调用没问题；**修改后分发**要开源 |
| 非商用 / 学术 | Hunyuan3D-2.1 权重、Pixal3D、Stable Zero123 | ❌ 商用项目不要直接用 |

> 实操建议：**把"是否商用"作为选型第一过滤条件**，再比效果。效果差 10% 但许可干净，比效果好 10% 但法务有风险划算得多。
