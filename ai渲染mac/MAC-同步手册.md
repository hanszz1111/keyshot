# Mac 侧同步手册

> 目标：让 Mac 能**拉取** Windows 侧的改动，也能**推送**自己的改动上去。
> 前提：Mac 上用的是**同一个 GitHub 账号** `hanszz1111`。

---

## 一、先选认证方式

同一账号，两种方式都行，**选一个即可**（推荐顺序：SSH → Token）。

| 方式 | 优点 | 缺点 | 适合 |
|---|---|---|---|
| **SSH**（推荐） | 配一次永久有效；不受 HTTPS 网络问题影响 | 要生成密钥并贴到 GitHub | 长期用 |
| **Token** | 不用管密钥，交互简单 | Token 有有效期，过期要重配 | 临时用 / 公司网络挡 22 端口 |

> 背景：Windows 侧实测 `github.com:443` **HTTPS 通路不稳定**（直连超时、走代理 502），
> 所以那边改用了 SSH。Mac 侧通常没这个限制，但 **SSH 两边都稳**，建议统一。

---

## 二、方式 A：SSH（推荐）

### 1. 检查 Mac 上有没有现成密钥

```bash
ls -la ~/.ssh/
```

有 `id_ed25519` 或 `id_rsa` 就跳到第 3 步。没有就生成：

```bash
ssh-keygen -t ed25519 -C "hanszz1111@users.noreply.github.com"
# 一路回车即可（密码留空最省事；设了密码则每次要输）
```

### 2. 把公钥贴到 GitHub

```bash
pbcopy < ~/.ssh/id_ed25519.pub     # 直接复制到剪贴板
```

浏览器打开 <https://github.com/settings/ssh/new> → **Title** 随便填（如 `macbook`）→
**Key** 粘贴 → **Add SSH key**。

> ⚠️ 先确认公钥**还没加过**。同一个公钥重复添加会报 `Key is already in use`。
> 若 Mac 上已有配好的密钥，直接用它，不要重复生成。

### 3. 验证认证

```bash
ssh -T git@github.com
```

看到 `Hi hanszz1111! You've successfully authenticated` 就成功了。

> 首次连接会问 `Are you sure you want to continue connecting?` → 输 `yes`。

**若失败：**

| 报错 | 含义 | 处理 |
|---|---|---|
| `Permission denied (publickey)` | 通道通、公钥没生效 | 回第 2 步确认已加到 GitHub；`ssh-add ~/.ssh/id_ed25519` 后重试 |
| `Connection timed out` / `Connection refused`（22 端口） | 网络挡了 22 端口 | 改用 443 端口，见下 |
| `Connection reset` | 当前网络抖动 | 稍后重试，或换 443 端口 |

**22 端口不通时走 443** —— 编辑 `~/.ssh/config`：

```
Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/id_ed25519
```

---

## 三、方式 B：Personal Access Token（HTTPS）

### 1. 生成 Token

打开 <https://github.com/settings/tokens> → **Generate new token (classic)**
→ 勾选 **`repo`** 权限 → 生成后**立刻复制**（页面关掉就再也看不到）。

### 2. 用 Token 当密码

```bash
git clone https://github.com/hanszz1111/keyshot.git
# Username: hanszz1111
# Password: 粘贴刚才的 Token（不是账号密码！）
```

> macOS 的钥匙串会自动记住，之后不用再输。

### 3. 让它记住（避免反复输）

```bash
git config --global credential.helper osxkeychain
```

---

## 四、首次拉取仓库

### 全新开始（Mac 上没有这个项目）

```bash
cd ~/Documents                    # 或你想放的位置
git clone git@github.com:hanszz1111/keyshot.git
cd keyshot
```

> 若第 2 步没用 SSH，把地址换成 `https://github.com/hanszz1111/keyshot.git`。

### 已经有一份旧副本

```bash
cd <已有的项目目录>
git rev-parse --is-inside-work-tree # 必须先确认这是 Git 克隆
git remote -v                     # 看有没有配 remote
```

- **没有 `.git` 或上述检查失败** → 它只是普通文件夹，**不要**直接 `git pull` 或 `git remote add`；另选新目录克隆，再对照迁移需要的文件。
- **已有 Git 历史但没配 remote** → 先确认与远端是同一历史，再考虑 `git remote add origin git@github.com:hanszz1111/keyshot.git`。
- **配的是 HTTPS 想改 SSH** → `git remote set-url origin git@github.com:hanszz1111/keyshot.git`

然后拉：

```bash
git pull origin main
```

> ⚠️ **如果 Mac 上那份是独立 init 的历史**（`git log` 显示的提交和远程对不上），
> 直接 pull 会报 `refusing to merge unrelated histories`。**先别强推**——告诉我，
> 我帮你判断哪边要留、怎么合。强推会覆盖远程，可能丢掉 Windows 侧的工作。

---

## 五、日常使用（分支交接）

两台电脑可用同一个 GitHub 账号，但仍须按 [AI/README.md](../AI/README.md) 分工；一轮一个分支和基线，另一端通过 PR 审核。以下例子只提交 R1 的复审文件：

```bash
git status                   # 若有未提交改动，先检查并保留
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c codex/ai-r1-review
# ... 只改本轮负责的文件 ...
git add AI/REVIEW.md
git diff --cached --name-only # 核对暂存范围
git commit -m "docs(ai): review R1"
git push -u origin codex/ai-r1-review
```

> `codex/ai-r1-review` 在当前仓库**已经存在**，上述名称仅为示例；新轮次必须换新的分支名，不得照抄创建同名分支。推送后创建指向 `main` 的 PR，审核通过再合并；不要直接推 `main` 或 `git add -A`。

**冲突了怎么办？** 先看是哪些文件：

```bash
git status
```

先停止推送，核对冲突双方的修改和本轮文件归属；不要自动选择某一端覆盖，也不要用 `push --force`。**搞不定就把 `git status` 的输出贴给我**，别硬来。

---

## 六、Mac 侧不要做什么

| 别做 | 原因 |
|---|---|
| 跑 ComfyUI / 出图链路 | 需要 NVIDIA GPU + 模型权重，仓库里没有 |
| 跑 `scripts/blender_pass.py` | 需要本机装 Blender，且路径是本机配置 |
| 提交 `assets/` / `outputs/` | 含未上市产品外观，已明确排除 |
| 改 `.gitignore` 放行资产 | 同上，且会让两端不一致 |
| 强行 `git push --force` | 会覆盖另一端的工作 |

**Mac 侧适合做**：改 `web/` 前端、写 `docs/`、维护 `AI/` 评审材料、做方案与设计。

---

## 七、快速排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `Permission denied (publickey)` | SSH 公钥没加到 GitHub | 加公钥，或 `ssh-add` |
| `Authentication failed` | Token 过期/权限不足 | 重新生成 Token，确认勾了 `repo` |
| `Support for password authentication was removed` | 用了账号密码 | 必须用 Token，不能用密码 |
| `refusing to merge unrelated histories` | 两边历史独立 | **别强推**，先问 |
| `CONFLICT (content): Merge conflict in <文件>` | 同一文件两端都改了 | 手动解决；或 `git stash` → `pull` → `stash pop` |
| `Updates were rejected ... (fetch first)` | 远程有你没有的提交 | 先 `git pull` 再 `push` |
| `remote: Permission to ... denied` | 账号没有该仓库权限 | 确认登录的是 `hanszz1111` |
| `Filename too long` | 路径过长 | `git config --global core.longpaths true` |
| 中文文件名显示成 `\351\252\214` | Git 转义非 ASCII | `git config --global core.quotepath false` |

---

## 八、一次性配置（省心用，可选）

```bash
git config --global user.name "hanszz1111"
git config --global user.email "hanszz1111@users.noreply.github.com"
git config --global core.quotepath false      # 中文路径正常显示
git config --global pull.rebase false         # pull 默认用 merge
git config --global init.defaultBranch main   # 新仓库默认 main
```

> **`user.email` 用什么？** 想隐藏真实邮箱就用
> `hanszz1111@users.noreply.github.com`（和 Windows 侧保持一致，提交能正确归属到你账号）。
