# 关于版本管理（GitHub）

> 本文件说明**哪些内容入仓、哪些不入仓，以及为什么**。
> 面向两类读者：① 拿到本仓库、想在自己机器上跑起来的人；② 未来的维护者。

---

## 一、入仓范围

本仓库**只纳入「代码 + 配置 + 文档」**，不纳入产品资产与运行态数据。

| 入仓 | 内容 | 体积 |
|---|---|---|
| ✅ | `web/` —— 「形照」控制台（前端 + 零第三方依赖的后端） | ~2 MB |
| ✅ | `config/` —— 工作流 JSON 与出图参数基线 | ~320 KB |
| ✅ | `scripts/` —— Blender 出 pass、启动/停止、工具脚本 | ~186 KB |
| ✅ | `docs/` —— 技术方案、验收证据（纯界面截图与文本）、历史归档 | ~350 KB |
| ✅ | `AI/` —— 跨机协作材料 | ~52 KB |
| ✅ | 根目录 `.md` 文档与 `.bat` 启动器 | ~85 KB |
| ❌ | `assets/` —— 产品 3D 模型、结构图、源图、参考图 | 217 MB |
| ❌ | `outputs/` —— 出图产物 | 28 MB |
| ❌ | `_隔离区/` —— 历史清理物的可回滚暂存 | 6.5 MB |
| ❌ | `config/tasks.db`、`web/data/` —— 运行态数据 | — |

**入仓后约 3 MB。**

---

## 二、为什么不纳入产品资产

1. **含未上市产品的外观设计**。`assets/白模/` 里有真实产品的三维模型，
   `assets/passes/` 与 `outputs/` 是产品渲染图。公开等于把这些设计数据交出去。
2. **体积会撑爆仓库**。3D 模型约 192 MB，且二进制文件每次改动都存全量副本，
   Git 历史会持续膨胀，**几乎无法真正删除**（需重写历史）。
3. **GitHub 有硬限制**：单文件 100 MB、单仓库建议 ≤1 GB。

**如果确实需要版本管理产品资产**，两个可选做法：

- 另建**私有仓库**，并启用 **Git LFS**（`git lfs track "*.stl" "*.3dm"` 等）
- 用云盘 / NAS 做资产备份，Git 只管代码

同理，`docs/验收证据-20260927/` 中的产品对照图（`bug2_lab/` 与 `07_gf_four.png`）
也已排除，只保留纯界面截图。

---

## 三、换机器怎么跑起来

代码里对**本机路径**做了默认值，同时都留了**环境变量开关**。换机器时按下面改：

复制 `.env.example` 为参考，依次设置这 5 个变量（全部可选，不设就用默认值）：

| 变量 | 作用 | 默认值 |
|---|---|---|
| `COMFY_HOST` | ComfyUI 服务地址 | `http://127.0.0.1:8188` |
| `COMFY_INPUT_DIR` | ComfyUI 的 input 目录（**换机器通常必改**） | `F:\AI-Renderer\...\ComfyUI\input` |
| `BLENDER_EXE` | Blender 可执行文件 | 先查 PATH，再查代码内登记路径 |
| `RENDERER_PORT` | 控制台端口 | `8765` |
| `RENDERER_NO_BROWSER` | 启动时不自动开浏览器 | `0` |

**外部依赖**（本仓库不含）：

| 依赖 | 说明 |
|---|---|
| ComfyUI 0.37.0 | 需自行安装；模型建议放独立目录并用 `extra_model_paths.yaml` 映射（零复制） |
| Blender 4.x | 用于从 3D 白模渲染结构 pass（depth / normal / alpha） |
| ComfyUI 自定义节点 | 至少需要 **ControlNet Union** 支持；参考图功能额外需要 **IPAdapter_plus** |
| 底模 | 本项目实测用 `RealVisXL_V5.0_Lightning_fp16`（8 步快速版） |
| ControlNet | `controlnet-union-sdxl-1.0-promax` |

**许可提醒**：ComfyUI 本体是 GPL-3.0；`IPAdapter_plus` 也是 GPL 系。
本仓库自身只调用它们，不分发其代码。若用于商业服务对外分发，请自行核对许可。

---

## 四、首次推送

```bash
git init -b main
git add -A
git commit -m "初始提交：AI 白模渲染器"

# 在 GitHub 建好空仓库后（不要勾选初始化 README）
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

推送前自检：

```bash
# 确认没有大文件混进去
git ls-files | xargs -I{} du -h {} 2>/dev/null | sort -rh | head -10

# 确认产品资产没被纳入
git ls-files | grep -E "^(assets|outputs|_隔离区)/" && echo "⚠️ 有资产混入！" || echo "✅ 干净"
```

---

## 五、仓库可见性建议

| 选择 | 适合 | 注意 |
|---|---|---|
| **私有（Private）** | 只想自己多机同步 / 备份 | 可以放宽入仓范围，但仍不建议放 192 MB 的 3D 模型 |
| **公开（Public）** | 想分享这套控制台的实现思路 | **务必确认**：入仓内容不含产品外观、不含客户信息、不含本机用户名等隐私 |

当前 `.gitignore` 是按**公开也安全**的标准写的 —— 即使仓库设为公开，
入仓内容也只有代码与文档，不含产品资产。

### 多机同步（Mac 侧）

Mac 与 Windows 用的是**同一个 GitHub 账号**，因此**不需要加协作者、不需要任何授权配置** ——
仓库本来就是账号自己的，只要那台机器上配好认证即可。

**操作手册见 `ai渲染mac/MAC-同步手册.md`**（含 SSH 与 Token 两种认证的完整步骤、
首次拉取、日常三条命令、冲突处理、排查表）。要点：

1. **认证优先用 SSH**。Windows 侧实测 `github.com:443` 的 HTTPS 通路不稳定
   （直连超时、走代理 502），SSH 两端都稳。
2. **动手前先 `git pull`**，改完就 `git push`，不要攒。
3. **Mac 侧不要跑出图链路**（需 NVIDIA GPU + ComfyUI + 模型权重，都不在仓库里）。
   Mac 适合改 `web/` 前端、`docs/`、`AI/` 这些纯文本部分。
4. **两端不要并行改同一个文件**，否则会产生冲突。

---

## 六、当前状态

| 项 | 状态 |
|---|---|
| 本地仓库 | ✅ 已 `git init`（分支 `main`） |
| `.gitignore` | ✅ 已配置并验证 |
| 首次提交 | ✅ 已完成（97 文件 / 20,209 行） |
| 远程仓库 | ✅ <https://github.com/hanszz1111/keyshot>（**public**，默认分支 `main`） |
| 推送 | ✅ 已推送，本地与远程 SHA 一致 |
| 多机同步 | ✅ Mac 侧手册已就位（`ai渲染mac/MAC-同步手册.md`），同账号免授权 |

提交记录：

| SHA | 提交信息 |
|---|---|
| `3479598` | 合并远程占位 README（保留本地项目说明） |
| `edd899f` | 初始提交：AI 白模渲染器（形照工作台 + ComfyUI 出图链路） |
| `efb8a95` | Initial commit（GitHub 建仓时自动生成，仅含 2 行占位 README） |

> 本仓库提交身份为本仓库级配置（未改动全局）：
> `user.name=hanszz1111`、`user.email=hanszz1111@users.noreply.github.com`。

### 建仓时踩过的坑

**remote 已含「Initial commit」导致首次 push 被拒**（`! [rejected] ... (fetch first)`）。
在 GitHub 网页建仓时若勾选了 *Add a README file*，远程会先有一条与本地**无共同祖先**的提交，
直接 `git push` 必被拒。两种处理：

```bash
# 做法 A：保留本地 README（推荐，本项目采用的）
git fetch origin main
git merge origin/main --allow-unrelated-histories -X ours -m "合并远程占位 README"
git push -u origin main

# 做法 B：干脆不要远程那条历史（未采用）
git push -u origin main --force
```

另：首次推送会弹出 Git Credential Manager 的 **「Connect to GitHub」** 授权窗口，
须在弹出的窗口里完成浏览器登录 / Token 授权；授权成功后凭证会缓存，后续推送不再询问。
在无图形交互的自动化会话里，该弹窗会让命令一直挂起 —— 所以推送要放到后台跑，用户手动完成授权。

---

## 七、日常维护

```bash
cd "D:\Dsektop\AI渲染\AI渲染"

git status                    # 看改动
git add -A                    # 暂存（.gitignore 会自动挡掉资产）
git diff --cached --name-only | grep -E "^(assets|outputs|_隔离区)/"   # 复查有无资产混入
git commit -m "..."
git push                      # 已设置 upstream，无需再写 origin main
```

> 中文路径下 `git diff --cached --name-only | grep "\.png$"` 会因秒字符转义而**误报为空**。
> 本仓库已设 `core.quotepath false` 规避；换机器克隆后建议同样设置一次。
