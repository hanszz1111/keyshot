#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 白模渲染器 · 控制台后端

零第三方依赖（仅标准库）。职责：
  L0/L1  参数卡 CRUD（落盘为 JSON）
  L3     任务队列（SQLite，对应文档 ADR-007）
  L4     导出 ComfyUI 任务载荷（对应 comfy_batch.py 的 SLOTS 映射）
  L5     项目看板 + 变更记录（变更记录从 00-...过程文档.md 只读解析）

启动：python server.py  然后浏览器打开 http://127.0.0.1:8765
"""

import json
import glob
import hashlib
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

# ---------- 路径 ----------
BASE = os.path.dirname(os.path.abspath(__file__))          # .../AI渲染/web
ROOT = os.path.dirname(BASE)                               # .../AI渲染
DATA = os.path.join(BASE, "data")
CARDS_DIR = os.path.join(DATA, "cards")
BOARD_FILE = os.path.join(DATA, "board.json")
DB_FILE = os.path.join(ROOT, "config", "tasks.db")
DOC_FILE = os.path.join(ROOT, "00-AI白模渲染器-过程文档.md")

# 投放区（v1.4.1）：用户只需把文件拖进来，后端自动归类
ASSETS = os.path.join(ROOT, "assets")
MODELS_DIR = os.path.join(ASSETS, "白模")      # 3D 源文件投放
PASSES_DIR = os.path.join(ASSETS, "passes")    # 白模渲染出的 pass 图投放
INBOX_DIR = os.path.join(ASSETS, "_待归类")     # 认不出来的先放这儿，不丢
REFS_DIR = os.path.join(ASSETS, "refs")        # 参考图：只借配色/材质/光照，不替换形状（文档 §三.3）
SOURCE_DIR = os.path.join(ASSETS, "source")    # 图片改图的实际输入

PORT = int(os.environ.get("RENDERER_PORT", "8765"))

for d in (DATA, CARDS_DIR, os.path.dirname(DB_FILE), ASSETS, MODELS_DIR, PASSES_DIR, INBOX_DIR, REFS_DIR, SOURCE_DIR):
    os.makedirs(d, exist_ok=True)


# ---------- SQLite ----------
DB_LOCK = threading.Lock()


def db():
    con = sqlite3.connect(DB_FILE, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with DB_LOCK, db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT, view TEXT, variant INTEGER,
                positive TEXT, negative TEXT,
                payload TEXT,
                status TEXT DEFAULT 'pending',
                prompt_id TEXT, output TEXT,
                retry INTEGER DEFAULT 0,
                err TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.commit()


# ---------- 变更记录解析（只读 00 文档）----------
CHANGELOG_ROW = re.compile(
    r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(v[\d.]+)\s*\|\s*`?([A-Z]+)`?\s*\|(.+)\|\s*$"
)


def read_changelog():
    """从 00-...过程文档.md 解析「二、变更记录」表格。失败时返回空列表，不报错。"""
    if not os.path.isfile(DOC_FILE):
        return []
    try:
        with open(DOC_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []

    rows, in_section = [], False
    for ln in lines:
        ln = ln.rstrip("\n")
        if ln.startswith("# 二、变更记录"):
            in_section = True
            continue
        if in_section and ln.startswith("# "):
            break
        if not in_section:
            continue
        m = CHANGELOG_ROW.match(ln)
        if m:
            date, ver, typ, rest = m.group(1), m.group(2), m.group(3), m.group(4)
            cells = [c.strip() for c in rest.split("|")]
            rows.append({
                "date": date, "version": ver, "type": typ,
                "summary": cells[0] if len(cells) > 0 else "",
                "reason": cells[1] if len(cells) > 1 else "",
                "scope": cells[2] if len(cells) > 2 else "",
            })
    return rows


def read_doc_meta():
    """取文档版本号与创建日期。"""
    meta = {"version": "—", "created": "—"}
    if not os.path.isfile(DOC_FILE):
        return meta
    try:
        with open(DOC_FILE, "r", encoding="utf-8") as f:
            head = f.read(4000)
    except Exception:
        return meta
    m = re.search(r"\*\*当前版本\*\*：\s*(v[\d.]+)", head)
    if m:
        meta["version"] = m.group(1)
    m = re.search(r"\*\*创建日期\*\*：\s*(\d{4}-\d{2}-\d{2})", head)
    if m:
        meta["created"] = m.group(1)
    return meta


# ---------- 参数卡 ----------
def card_path(sku):
    safe = re.sub(r"[^\w\-.一-龥]", "_", sku or "unknown")
    return os.path.join(CARDS_DIR, f"{safe}.json")


def list_cards():
    out = []
    for fn in sorted(os.listdir(CARDS_DIR)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(CARDS_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append({
                "file": fn,
                "sku": data.get("asset", {}).get("sku", fn[:-5]),
                "category": data.get("asset", {}).get("category", ""),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                "data": data,
            })
        except Exception as e:
            out.append({"file": fn, "sku": fn[:-5], "category": "⚠ 解析失败",
                        "mtime": "", "data": None, "err": str(e)})
    return out


def save_card(card):
    sku = card.get("asset", {}).get("sku")
    if not sku:
        raise ValueError("参数卡缺少 asset.sku")
    with open(card_path(sku), "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
    return sku


def delete_card(sku):
    p = card_path(sku)
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False


# ---------- 看板 ----------
DEFAULT_BOARD = {
    "phases": [
        {"id": "P0", "name": "可行性验证", "duration": "3–5 天",
         "goal": "证明「白模 → 写实图」在本类目上形准可用",
         "accept": "不写任何形状描述词的前提下，产品轮廓、厚度、按键位置一眼可辨认为同一产品；align_check IoU ≥ 0.90",
         "gate": True, "status": "未开始"},
        {"id": "P1", "name": "单机流水线", "duration": "1–2 周",
         "goal": "从「手点」变成「脚本跑」",
         "accept": "喂 20 个 SKU 参数卡无人值守跑完，成品率 ≥ 70%；单张总耗时 ≤ 60s",
         "gate": False, "status": "未开始"},
        {"id": "P2", "name": "批量量产", "duration": "2–3 周",
         "goal": "覆盖存量 PSD 对应的产品资产",
         "accept": "800 SKU 全套 48 小时内完成（双卡），一次通过率 ≥ 85%；kill 进程可续跑且不重复出图",
         "gate": False, "status": "未开始"},
        {"id": "P3", "name": "3D 材质线", "duration": "3–4 周",
         "goal": "补足材质真实度与多视角一致性天花板",
         "accept": "一个 SKU 出 8 视角，跨视角色差 ΔE < 3；仅用 MIT/Apache 模型",
         "gate": False, "status": "未开始"},
        {"id": "P4", "name": "详情页对接", "duration": "1 周",
         "goal": "渲染产物直接落进现有详情页 PSD 流程",
         "accept": "单套详情页从拿到渲染图到出 JPG ≤ 10 分钟（中英双版）",
         "gate": False, "status": "未开始"},
    ],
    "risks": [
        {"id": 1, "name": "丝印 / LOGO / 刻度错乱", "level": "高",
         "action": "不靠 AI，走图层回贴。AI 只出壳体材质（ADR-002）"},
        {"id": 2, "name": "透明件（亚克力视窗）崩坏", "level": "高",
         "action": "降低 AI 占比，透明件区域用 KeyShot 真渲染后合成"},
        {"id": 3, "name": "广告合规：生成图与实物不符", "level": "高",
         "action": "QC 清单强制比对实拍照片；关键参数禁止 AI 生成（ADR-010）"},
        {"id": 4, "name": "P0 形准验证不通过", "level": "高",
         "action": "若不过方案暂停；优先排查相机参数一致性与法线空间"},
        {"id": 5, "name": "镜面金属反射出现幽灵物体", "level": "中",
         "action": "ControlNet normal 权重提到 0.45+；负向词排除反射物"},
        {"id": 6, "name": "同款多图一致性差", "level": "中",
         "action": "固定 seed 组 + 同一参考图 + 提示词骨架只换风格词"},
        {"id": 7, "name": "Pass 与成图不对齐", "level": "中",
         "action": "相机参数单一来源；P0 必须验证；align_check 自动校验"},
        {"id": 8, "name": "开源模型许可风险", "level": "中",
         "action": "商用只选 MIT/Apache（ADR-008）；建立许可过滤清单"},
        {"id": 9, "name": "调参人力黑洞", "level": "中",
         "action": "参数卡固化为预设，每类目一套，不再逐张调"},
        {"id": 10, "name": "ComfyUI 插件更新破坏既有工作流", "level": "中",
         "action": "锁定工作流 JSON 版本 + 记录插件版本号"},
        {"id": 11, "name": "成本估算偏差（耗时依赖实测）", "level": "中",
         "action": "P1 阶段实测后回填文档 6.4 节数据"},
        {"id": 12, "name": "显存溢出导致批次中断", "level": "低",
         "action": "断点续跑 + 超时重试 + 分批降分辨率"},
        {"id": 13, "name": "透明件 / 异形件需人工兜底", "level": "低",
         "action": "沉淀专用模板；建立回退到真渲染的快速通道"},
    ],
    "todos": [
        {"id": 1, "name": "P0 形准验证", "type": "验证", "priority": "最高", "done": False},
        {"id": 2, "name": "验证 KeyShot lux.renderImage 的 opts 在本机版本的确切签名", "type": "验证", "priority": "高", "done": False},
        {"id": 3, "name": "验证 Blender Normal pass 空间约定与 ControlNet 训练约定是否一致", "type": "验证", "priority": "高", "done": False},
        {"id": 4, "name": "单张耗时实测，回填文档 6.4 节", "type": "数据", "priority": "高", "done": False},
        {"id": 5, "name": "透明件「真渲染合成」具体流程设计", "type": "设计", "priority": "高", "done": False},
        {"id": 6, "name": "参考图库初始化（材质 5 / 打光 3 / 构图 2）", "type": "资产", "priority": "中", "done": False},
        {"id": 7, "name": "参数卡 → PSD 命名映射表设计", "type": "设计", "priority": "中", "done": False},
        {"id": 8, "name": "评估是否引入自有产品 LoRA 微调", "type": "评估", "priority": "中", "done": False},
        {"id": 9, "name": "评估试用 Z-Image 处理详情页文案渲染", "type": "评估", "priority": "中", "done": False},
    ],
    "pitfalls": [
        {"date": "", "symptom": "（待登记）", "cause": "", "fix": "", "source": "设计阶段预判"},
    ],
}


def load_board():
    if os.path.isfile(BOARD_FILE):
        try:
            with open(BOARD_FILE, "r", encoding="utf-8") as f:
                b = json.load(f)
            for k, v in DEFAULT_BOARD.items():
                b.setdefault(k, v)
            return b
        except Exception:
            pass
    save_board(DEFAULT_BOARD)
    return json.loads(json.dumps(DEFAULT_BOARD))


def save_board(b):
    with open(BOARD_FILE, "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False, indent=2)


# ---------- 投放区：路径解析与扫描 ----------
# 白模投放区接受的扩展名。
# 注意 `.rhi` **故意不在列表里**：它是 Rhino 的插件安装包，不是模型文件。
# 收下它只会让结构图按钮永远点不亮、用户也看不出为什么（见过程文档 7.2）。
MODEL_EXTS = {".ksp", ".blend", ".glb", ".gltf", ".fbx", ".obj",
              ".stp", ".step", ".3dm", ".c4d", ".max", ".stl"}

# 这几个扩展名要**明确拒绝并给出可读原因**，而不是当成未知格式静默丢弃。
NOT_A_MODEL = {
    ".rhi": "Rhino 插件安装包（不是模型）",
    ".rhp": "Rhino 插件（不是模型）",
    ".yak": "Rhino 插件包（不是模型）",
    ".3dmbak": "Rhino 备份文件（请在 Rhino 中另存为 .3dm）",
}
SUPPORTED_MODEL_HINT = "支持 .blend/.glb/.gltf/.obj/.stl/.fbx/.stp/.step/.3dm"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".exr"}

# 各白模格式的文件头签名（实测校准，2026-09-28）。用于上传后立刻发现
# 「改了扩展名骗过白名单」和「传了一半/已损坏」——这两类文件以前会静静躺在
# 投放区里，等结构图任务跑完才失败，用户看不出为什么。
# 没有把握的格式（.ksp/.c4d/.max）**故意不列**，一律放过：宁可漏判不可误杀。
MODEL_MAGIC = {
    ".stp":   (b"ISO-10303-21", b"ISO-10303"),
    ".step":  (b"ISO-10303-21", b"ISO-10303"),
    ".3dm":   (b"3D Geometry File Format",),
    ".glb":   (b"glTF",),
    ".fbx":   (b"Kaydara FBX Binary", b"; FBX"),
    ".blend": (b"BLENDER", b"\x1f\x8b"),      # 未压缩 / gzip 压缩
}
# 二进制 STL 的硬约束：80 字节头 + 4 字节面数 + 每面 50 字节
STL_HEADER, STL_FACET = 84, 50


def _probe_stl(path, size):
    """STL 校验。ASCII 看 facet 关键字；二进制用字节数硬约束核对。

    注意 Rhino 导出的 STL 头部是 `Rhinoceros Binary STL (...)`，
    既不是 ASCII 的 `solid`，也不是标准空头 —— 所以**不能只看文件头**。
    """
    with open(path, "rb") as f:
        head = f.read(1024)
    if head[:5] == b"solid" and (b"facet" in head or b"vertex" in head):
        return True, ""
    with open(path, "rb") as f:
        f.seek(80)
        raw = f.read(4)
    if len(raw) < 4:
        return False, "STL 文件不完整（读不到面数字段）"
    faces = int.from_bytes(raw, "little")
    if faces == 0:
        return False, "STL 声明的面数为 0，没有可渲染的三角面"
    expect = STL_HEADER + STL_FACET * faces
    if size == expect:
        return True, ""
    return False, ("STL 结构不自洽：声明 %d 个面应有 %d 字节，实际 %d 字节"
                   "（文件可能未传完或已损坏）" % (faces, expect, size))


def probe_model_file(path):
    """上传后的**轻量几何预检**，返回 (ok, reason)。

    只做便宜的、能立刻发现问题的检查（不解析几何）：
      · 非空、不小于最小体积
      · 文件头与该扩展名的签名一致
      · STL 额外核对字节数硬约束
    真正的几何有效性（曲面数、三角面、包围盒、单位、可见性）由 Blender/FreeCAD
    侧负责，本函数不做也不该做。

    设计原则：**宁可漏判，不可误杀** —— 没把握的格式一律返回通过。
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        size = os.path.getsize(path)
    except OSError:
        return False, "文件不可读"
    if size == 0:
        return False, "文件是空的（0 字节）"
    if size < STL_HEADER:
        return False, "文件只有 %d 字节，不可能包含有效几何" % size

    if ext == ".stl":
        return _probe_stl(path, size)

    with open(path, "rb") as f:
        head = f.read(1024)

    # 文本格式单独判断：它们没有固定魔数，只有内容特征
    if ext == ".obj":
        if any(k in head for k in (b"\nv ", b"\nf ", b"\r\nv ", b"\r\nf ")) or head.startswith(b"v "):
            return True, ""
        return False, "文件里找不到 OBJ 的顶点/面数据（可能改过扩展名，或文件损坏）"
    if ext == ".gltf":
        if head.lstrip()[:1] == b"{":
            return True, ""
        return False, "不是 glTF JSON（文件头应以 { 开头）"

    sigs = MODEL_MAGIC.get(ext)
    if not sigs:
        return True, ""          # 无签名可查 → 放过
    for sig in sigs:
        if head.startswith(sig):
            return True, ""
    return False, ("文件内容与 %s 格式不符（可能改了扩展名，或文件损坏/未传完）" % ext)

VIEW_KEYS = ["front", "3q4_left", "3q4_right", "side", "top",
             "detail_keypad", "detail_window"]

# 机位别名（中英混写、常见简写都吃）
VIEW_ALIASES = {
    "front": ["front", "正面", "正视图", "前视", "主视", "正", "frontview"],
    "3q4_left": ["3q4_left", "left", "leftfront", "左前", "左45", "左三四",
                 "四分之三左", "3q4l", "左前三四"],
    "3q4_right": ["3q4_right", "right", "rightfront", "右前", "右45", "右三四",
                  "四分之三右", "3q4r", "右前三四"],
    "side": ["side", "profile", "侧面", "侧视", "侧", "sideview"],
    "top": ["top", "topdown", "俯视", "顶视", "正俯", "上视", "topview"],
    "detail_keypad": ["detail_keypad", "keypad", "按键", "键盘", "面板",
                      "特写按键", "局部按键", "detailkeypad"],
    "detail_window": ["detail_window", "window", "透明件", "视窗", "窗口",
                      "镜片", "detailwindow"],
}

# 通道别名 → 标准名（标准名即落盘文件名，与 web/index.html 的 payload 对应）
ROLE_KEYS = ["clay", "depth", "normal", "alpha"]
ROLE_ALIASES = {
    "clay": ["clay", "beauty", "rgb", "shaded", "color", "白模", "灰模", "素模", "白膜"],
    "depth": ["depth", "depthmap", "z", "disparity", "深度", "景深", "深度图"],
    "normal": ["normal", "normals", "nrm", "nmap", "法线", "法线图"],
    "alpha": ["alpha", "mask", "matte", "cutout", "蒙版", "通道", "遮罩"],
}

# 拖进来的容器目录名，直接剥掉（用户可能整包拖）
DROP_HEADS_NORM = {"passes", "pass", "output", "outputs", "assets", "asset",
                   "白模", "白膜", "白模库", "模型", "模型库", "渲染", "渲染图",
                   "ai渲染", "airender", "ai_render"}


def safe_file(s):
    """文件名安全化：去掉 Windows 非法字符。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", (s or "").strip())
    s = s.strip(". ")
    return s or "unnamed"


def _norm_token(s):
    return re.sub(r"[\s_\-\.]+", "", (s or "").strip().lower())


NOISE_TOKENS = {"", "img", "image", "pic", "photo", "shot", "render", "output",
                "图", "图片", "截图", "渲染", "导出", "未命名"}
# 通用的容器目录名 —— 这些不能当 SKU
GENERIC_DIRS_NORM = {"新建文件夹", "newfolder", "未命名", "untitled", "untitledfolder",
                     "图片", "images", "image", "photos", "导出", "export", "exports",
                     "output", "outputs", "temp", "tmp", "其他", "others", "杂项"}


def _match_alias(text, keys, aliases):
    """先精确、再别名精确、最后按别名长度倒序做包含匹配。"""
    t = _norm_token(text)
    if not t:
        return ""
    for k in keys:
        if _norm_token(k) == t:
            return k
    for k in keys:
        for a in aliases.get(k, ()):
            if _norm_token(a) == t:
                return k
    pool = []
    for k in keys:
        for a in aliases.get(k, ()):
            na = _norm_token(a)
            if na:
                pool.append((len(na), na, k))
    pool.sort(reverse=True)
    for _, na, k in pool:
        if na in t:
            return k
    return ""


def detect_view(text):
    return _match_alias(text, VIEW_KEYS, VIEW_ALIASES)


def detect_role(text):
    return _match_alias(text, ROLE_KEYS, ROLE_ALIASES)


def _sku_from_stem(stem):
    """从文件名剥离机位/通道词反推 SKU。

    返回 (sku, strong)。**strong=True 才可信** —— 它表示文件名里确实剥掉过
    机位或通道词（例 `LS-360G_front_depth` → `LS-360G`）。
    没有剥离证据的名字（`毫无线索`、`My Product`）一律返回空字符串，
    否则随便一张图都会被当成一个 SKU，比认不出来还糟。
    """
    toks = [t for t in re.split(r"[\s_\-.]+", stem or "") if t]
    keep, dropped = [], 0
    for t in toks:
        if (detect_view(t) or detect_role(t)
                or _norm_token(t) in NOISE_TOKENS or _norm_token(t) in GENERIC_DIRS_NORM):
            dropped += 1
        else:
            keep.append(t)
    if dropped == 0 or not keep:
        return "", False
    return "-".join(keep).strip("-"), True


def guess_sku(stem):
    """宽松版：只要剥掉了东西就返回，用于扫描白模文件时的兜底。"""
    return _sku_from_stem(stem)[0]


def parse_asset_rel(rel, fb_sku="", fb_view="", is_model=False):
    """统一的归类规则 —— 扫描与上传共用，保证「看到的」=「放进去的」。

    返回 (kind, sku, view, role)
      kind: model / pass / pass_noview / inbox
    """
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        parts = ["unnamed.bin"]

    # 剥掉容器目录
    while len(parts) > 1 and _norm_token(parts[0]) in DROP_HEADS_NORM:
        parts.pop(0)

    name = parts[-1]
    ext = os.path.splitext(name)[1].lower()
    stem = os.path.splitext(name)[0]

    if is_model or ext in MODEL_EXTS:
        # 模型文件名本身就是它最好的标识：`LS-360G.ksp` → SKU = LS-360G
        m_sku, _ = _sku_from_stem(stem)
        return "model", (m_sku or fb_sku or safe_file(stem)), "", ""

    # 不是图也不是模型 —— 不进 passes，直接进待归类（否则 xlsx/psd 会被当 pass）
    if ext not in IMAGE_EXTS:
        return "inbox", "", "", ""

    # 已经躺在「待分机位」里的，直接按 pass_noview 报，不再二次推断
    if "_待分机位" in parts:
        i = parts.index("_待分机位")
        sku = parts[i - 1] if i > 0 else fb_sku
        return "pass_noview", (safe_file(sku) if sku else ""), "", (detect_role(stem) or "clay")

    ctx = "/".join(parts[:-1])
    role = detect_role(stem) or detect_role(ctx) or "clay"
    g_sku, strong = _sku_from_stem(stem)

    sku, view = "", ""
    if len(parts) >= 3:
        sku = parts[-3]
        view = detect_view(parts[-2]) or detect_view(stem)
    elif len(parts) == 2:
        d = parts[-2]
        if detect_view(d):
            view, sku = detect_view(d), g_sku
        elif _norm_token(d) in GENERIC_DIRS_NORM:
            sku, view = "", detect_view(stem)      # 文件夹名是「新建文件夹」这种，不算 SKU
        else:
            sku, view = d, detect_view(stem)
    else:
        sku, view = g_sku, detect_view(stem)

    view = view or detect_view(stem) or fb_view
    # SKU 优先级：路径里剥出来的（有证据） > 用户填的 > 通用目录名
    if len(parts) == 1:
        sku = (sku if strong else "") or fb_sku or sku
    else:
        sku = sku or fb_sku
    sku = safe_file(sku) if sku else ""

    if sku and view:
        return "pass", sku, view, role
    if sku:
        return "pass_noview", sku, "", role
    return "inbox", "", view, role


def _dedup(path):
    """目标已存在时自动加 _2 _3，绝不覆盖已有文件。"""
    if not os.path.exists(path):
        return path
    d, n = os.path.split(path)
    stem, ext = os.path.splitext(n)
    for i in range(2, 1000):
        p = os.path.join(d, "%s_%d%s" % (stem, i, ext))
        if not os.path.exists(p):
            return p
    return path


def plan_upload(rel, fb_sku="", fb_view="", overwrite=False):
    """算出落盘位置。返回 (dest, kind, meta)。overwrite=True 时同名直接覆盖。"""
    kind, sku, view, role = parse_asset_rel(rel, fb_sku, fb_view)
    name = safe_file(os.path.basename((rel or "unnamed").replace("\\", "/")))
    ext = os.path.splitext(name)[1].lower()

    if kind == "model":
        # 新上传模型按 SKU 分目录；重复文件仍留在同一 SKU 下，不会因 _2 后缀变成新产品。
        dest = os.path.join(MODELS_DIR, safe_file(sku), name)
    elif kind == "pass":
        dest = os.path.join(PASSES_DIR, sku, view, role + (ext or ".png"))
    elif kind == "pass_noview":
        dest = os.path.join(PASSES_DIR, sku, "_待分机位", role + (ext or ".png"))
    else:
        dest = os.path.join(INBOX_DIR, name)

    return (dest if overwrite else _dedup(dest)), kind, {
        "sku": sku, "view": view, "role": role, "name": name}


def scan_models():
    out = []
    if not os.path.isdir(MODELS_DIR):
        return out
    for folder, dirs, files in os.walk(MODELS_DIR):
        dirs[:] = [] if folder != MODELS_DIR else [d for d in dirs if not d.startswith("_")]
        for fn in files:
            p = os.path.join(folder, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in MODEL_EXTS or not os.path.isfile(p):
                continue
            size = os.path.getsize(p)
            if size == 0:
                continue
            stem = os.path.splitext(fn)[0]
            if folder == MODELS_DIR:  # 兼容历史平铺模型
                _, sku, _, _ = parse_asset_rel(fn, is_model=True)
            else:
                sku = os.path.basename(folder)
            out.append({
                "file": fn,
                "rel": os.path.relpath(p, ASSETS).replace("\\", "/"),
                "path": p.replace("\\", "/"),
                "ext": ext.lstrip("."),
                "size": size,
                "size_h": human_size(size),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                "mtime_ns": os.stat(p).st_mtime_ns,
                "sku": sku or stem,
            })
    out.sort(key=lambda m: (m["mtime_ns"], m["rel"]), reverse=True)
    return out


def human_size(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%.0f %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024.0


def scan_passes():
    """返回 (tree, loose)。tree[sku][view][role] = [rel,...]（rel 相对 PASSES_DIR）"""
    tree, loose = {}, []
    if not os.path.isdir(PASSES_DIR):
        return tree, loose
    for root, dirs, files in os.walk(PASSES_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in IMAGE_EXTS:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, PASSES_DIR).replace("\\", "/")
            kind, sku, view, role = parse_asset_rel(rel)
            if kind == "pass":
                tree.setdefault(sku, {}).setdefault(view, {}).setdefault(role, []).append(rel)
            else:
                loose.append({
                    "rel": rel, "file": fn, "sku": sku, "view": view, "role": role,
                    "size_h": human_size(os.path.getsize(full)),
                    "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(full))),
                })
    return tree, loose


def scan_inbox():
    out = []
    if not os.path.isdir(INBOX_DIR):
        return out
    for fn in sorted(os.listdir(INBOX_DIR)):
        p = os.path.join(INBOX_DIR, fn)
        if not os.path.isfile(p):
            continue
        out.append({"file": fn, "size_h": human_size(os.path.getsize(p)),
                    "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
    return out


def scan_refs(sku=""):
    """列出参考图。放在 assets/refs/<SKU>/ 下；不带 SKU 就全列。

    ★ 用途边界（文档 §三.3）：参考图**只借视觉特征**（配色 / 材质 / 光照 / 构图），
      参考产品的**形状不替换**源白模。当前阶段由前端从参考图提取调色板与影调，
      翻成提示词里的材质与配色描述；图像编码器（IPAdapter）接入前，图片本身不参与条件注入。
    """
    out = []
    root = os.path.join(REFS_DIR, safe_file(sku)) if sku else REFS_DIR
    if not os.path.isdir(root):
        return out
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in IMAGE_EXTS:
                continue
            p = os.path.join(dirpath, fn)
            out.append({
                "file": fn,
                "rel": os.path.relpath(p, ASSETS).replace("\\", "/"),
                "sku": os.path.basename(os.path.dirname(p)),
                "size_h": human_size(os.path.getsize(p)),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
            })
    return out


def scan_sources():
    """每个产品以最新上传的源图作为图片改图输入；旧图仍保留。"""
    out = []
    if not os.path.isdir(SOURCE_DIR):
        return out
    for sku in sorted(os.listdir(SOURCE_DIR)):
        folder = os.path.join(SOURCE_DIR, sku)
        if not os.path.isdir(folder):
            continue
        files = [os.path.join(folder, name) for name in os.listdir(folder)
                 if os.path.splitext(name)[1].lower() in (".png", ".jpg", ".jpeg", ".webp")
                 and os.path.isfile(os.path.join(folder, name))]
        if files:
            path = max(files, key=os.path.getmtime)
            out.append({"sku": sku, "file": os.path.basename(path),
                        "rel": os.path.relpath(path, ASSETS).replace("\\", "/"),
                        "size_h": human_size(os.path.getsize(path))})
    return out


def asset_report():
    """投放区总览：哪些 SKU 齐了、缺什么、哪些没认出来。"""
    models = scan_models()
    tree, loose = scan_passes()
    sources = scan_sources()

    EXT_RANK = {".png": 0, ".tif": 1, ".tiff": 1, ".webp": 2, ".jpg": 3, ".jpeg": 3, ".exr": 4}

    def pick(rels):
        """同一 role 有多个文件时：先优先规范名（depth.png 优于 depth_v2.png），
        再优先 PNG —— 因为送进 ComfyUI 的是位图，.exr 只是留档件，不能被选中。"""
        def key(r):
            stem, ext = os.path.splitext(os.path.basename(r))
            canon_ok = 0 if (detect_role(stem) or "") == stem.lower() else 1
            return (canon_ok, EXT_RANK.get(ext.lower(), 9), r)
        return sorted(rels, key=key)[0]

    skus = sorted(set(list(tree.keys()) + [m["sku"] for m in models if m.get("sku")] + [s["sku"] for s in sources]))
    items = []
    for sku in skus:
        views = tree.get(sku, {})
        rows = []
        for v in VIEW_KEYS + sorted(k for k in views if k not in VIEW_KEYS):
            if v not in views:
                continue
            roles = views[v]
            files = {r: pick(v2) for r, v2 in roles.items()}
            missing = [r for r in ("clay", "depth", "normal") if r not in files]
            rows.append({
                "view": v,
                "files": files,
                "extra": sorted(r for r in roles if r not in ("clay", "depth", "normal")),
                "missing": missing,
                "ok": not missing,
            })
        ms = [m for m in models if m.get("sku") == sku]
        n_ok = sum(1 for r in rows if r["ok"])
        items.append({
            "sku": sku,
            "model": ms[0] if ms else None,
            "source": next((s for s in sources if s["sku"] == sku), None),
            "views": rows,
            "views_ok": n_ok,
            "views_total": len(rows),
            "ready": bool(rows) and n_ok == len(rows),
            "blocked": [r["view"] + " 缺 " + "/".join(r["missing"]) for r in rows if not r["ok"]],
        })

    return {
        "root": ROOT.replace("\\", "/"),
        "assets": ASSETS.replace("\\", "/"),
        "modelsDir": MODELS_DIR.replace("\\", "/"),
        "passesDir": PASSES_DIR.replace("\\", "/"),
        "inboxDir": INBOX_DIR.replace("\\", "/"),
        "exists": os.path.isdir(ASSETS),
        "models": models,
        "sources": sources,
        "items": items,
        "loose": loose,
        "inbox": scan_inbox(),
        "views": VIEW_KEYS,
    }


def place_loose():
    """把散落/未分机位的 pass 图**复制**到规范位置（只复制，从不删除/移动原文件）。"""
    _, loose = scan_passes()
    done, skipped = [], []
    for it in loose:
        if not (it.get("sku") and it.get("view")):
            skipped.append(it["rel"])
            continue
        src = os.path.join(PASSES_DIR, it["rel"].replace("/", os.sep))
        if not os.path.isfile(src):
            skipped.append(it["rel"])
            continue
        dest = _dedup(os.path.join(PASSES_DIR, it["sku"], it["view"],
                                   it["role"] + os.path.splitext(src)[1].lower()))
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            done.append({"from": it["rel"], "to": os.path.relpath(dest, PASSES_DIR).replace("\\", "/")})
        except Exception as e:
            skipped.append("%s (%s)" % (it["rel"], e))
    return {"copied": done, "skipped": skipped}


# ---------- 任务 ----------
TASK_COLS = ("id", "sku", "view", "variant", "positive", "negative",
             "payload", "status", "prompt_id", "output", "retry", "err",
             "created_at", "updated_at")


def list_tasks(limit=2000):
    with DB_LOCK, db() as con:
        rows = con.execute(
            f"SELECT {','.join(TASK_COLS)} FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        stats = dict(con.execute(
            "SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall())
    total = con_total = sum(stats.values())
    return {
        "tasks": [dict(r) for r in rows],
        "stats": {"total": total, **{s: stats.get(s, 0) for s in
                                     ("pending", "running", "done", "failed")}},
    }


def insert_tasks(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("每批任务须为 1–200 张")
    ids = []
    with DB_LOCK, db() as con:
        for t in items:
            cur = con.execute(
                "INSERT INTO tasks (sku, view, variant, positive, negative, payload, status) "
                "VALUES (?,?,?,?,?,?,'pending')",
                (t.get("sku"), t.get("view"), t.get("variant", 0),
                 t.get("positive", ""), t.get("negative", ""),
                 json.dumps(t.get("payload", {}), ensure_ascii=False)),
            )
            ids.append(cur.lastrowid)
        con.commit()
    return ids


def update_task(tid, status=None, output=None, err=None, retry=None):
    sets, vals = [], []
    if status is not None:
        sets.append("status=?"); vals.append(status)
    if output is not None:
        sets.append("output=?"); vals.append(output)
    if err is not None:
        sets.append("err=?"); vals.append(err)
    if retry is not None:
        sets.append("retry=?"); vals.append(retry)
    if not sets:
        return 0
    sets.append("updated_at=CURRENT_TIMESTAMP")
    vals.append(tid)
    with DB_LOCK, db() as con:
        cur = con.execute(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", vals)
        con.commit()
        return cur.rowcount


def reset_running():
    """启动时把残留 running 重置为 pending —— 断点续跑（文档 5.6）。"""
    with DB_LOCK, db() as con:
        cur = con.execute(
            "UPDATE tasks SET status='pending', updated_at=CURRENT_TIMESTAMP "
            "WHERE status='running'")
        con.commit()
        return cur.rowcount


def clear_tasks():
    with DB_LOCK, db() as con:
        con.execute("DELETE FROM tasks")
        con.commit()


# ---------- HTTP ----------
# =========================================================
# ComfyUI 直连（OPT-03）
# 把控制台的任务真正送到 ComfyUI /prompt，并轮询 /history 回填结果。
# 设计要点：
#   · 工作流模板落在 config/comfy_workflow_*.json，节点 ID 与 index.html 的 SLOTS 严格对齐
#   · 填充时"节点或字段不存在就跳过"，这样以后装 Redux / IPAdapter 只加节点、不动代码
#   · 生成结果从 ComfyUI 拉回来存到 项目/outputs/<SKU>/<机位>/（结果落 D 盘，见 OPT-15）
# =========================================================
COMFY = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")
CONFIG_DIR = os.path.join(ROOT, "config")
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
WF_TXT2IMG = os.path.join(CONFIG_DIR, "comfy_workflow_sdxl.json")
WF_CONTROLNET = os.path.join(CONFIG_DIR, "comfy_workflow_sdxl_cn.json")
WF_IMG2IMG = os.path.join(CONFIG_DIR, "comfy_workflow_sdxl_img2img.json")
RENDER_DEFAULTS_FILE = os.path.join(CONFIG_DIR, "render_defaults.json")
COMFY_INPUT_DIR = os.environ.get(
    "COMFY_INPUT_DIR",
    r"F:\AI-Renderer\packs\ComfyUI_windows_portable\ComfyUI\input")

os.makedirs(OUTPUTS_DIR, exist_ok=True)

# 与 web/index.html 的 SLOTS 严格一致：载荷键 -> (节点ID, 输入字段)
# 末尾几项是"可选覆盖"：载荷里带了就用载荷的，没带就用 render_defaults.json 的基线
SLOTS = {
    "positive":   ("6", "text"),
    "negative":   ("7", "text"),
    "seed":       ("3", "seed"),
    "denoise":    ("3", "denoise"),
    "width":      ("5", "width"),
    "height":     ("5", "height"),
    "depth_img":  ("10", "image"),
    "normal_img": ("11", "image"),
    "ref_img":    ("12", "image"),
    "source_img": ("15", "image"),
    "ref_w":      ("14", "weight"),
    "ref_weight_type": ("14", "weight_type"),
    "depth_w":    ("20", "strength"),
    "normal_w":   ("21", "strength"),
    # 图片改图（结构锁定版）专属：节点 30=Canny 预处理，31=Canny→CN 的应用强度
    # 2026-09-27 新增，见 render_defaults.img2img（img2img 只有 denoise 一个旋钮时必然二选一：
    # 要么不渲染，要么臆造别的产品，故补 ControlNet 约束形状）
    "canny_low":  ("30", "low_threshold"),
    "canny_high": ("30", "high_threshold"),
    "canny_w":    ("20", "strength"),
    "redux_f":    ("30", "downsampling_factor"),
    "steps":      ("3", "steps"),
    "cfg":        ("3", "cfg"),
    "sampler_name": ("3", "sampler_name"),
    "scheduler":  ("3", "scheduler"),
    "ckpt_name":  ("1", "ckpt_name"),
}

DEFAULT_RENDER = {
    "checkpoint": "RealVisXL_V5.0_Lightning_fp16.safetensors",
    "controlnet": "controlnet-union-sdxl-1.0-promax.safetensors",
    "steps": 8, "cfg": 2.0,
    "sampler_name": "dpmpp_sde", "scheduler": "karras",
    "filename_prefix": "ai_render",
    "controlnet_type_depth": "depth",
    "controlnet_type_normal": "normal",
    "default_size": {"width": 1232, "height": 752},
}


def load_render_defaults():
    """读 config/render_defaults.json；缺失或损坏则用内置基线。"""
    d = dict(DEFAULT_RENDER)
    try:
        with open(RENDER_DEFAULTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for k, v in raw.items():
            if not k.startswith("_"):
                d[k] = v
    except Exception:
        pass
    return d


# 本机 ComfyUI 必须直连：绕开环境里的 http_proxy，否则请求会被代理绕一圈（甚至 502）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _urlopen(req, timeout=30):
    return _OPENER.open(req, timeout=timeout)


def http_json(url, payload=None, timeout=30):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    with _urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode("utf-8")) if body else None


def comfy_models(node, field):
    """取某个 loader 节点的可选模型名列表（COMBO 型输入）。"""
    try:
        d = http_json("%s/object_info/%s" % (COMFY, node), timeout=8)
        spec = d[node]["input"]["required"][field]
        opts = spec[0]
        if isinstance(opts, dict):            # 新版把候选放在 {"options": [...]}
            opts = opts.get("options", [])
        return list(opts)
    except Exception:
        return []


def comfy_status():
    try:
        st = http_json(COMFY + "/system_stats", timeout=6)
        dev = (st.get("devices") or [{}])[0]
        ck = comfy_models("CheckpointLoaderSimple", "ckpt_name")
        defaults = load_render_defaults()
        return {
            "online": True,
            "url": COMFY,
            "version": (st.get("system") or {}).get("comfyui_version"),
            "device": dev.get("name"),
            "vram_total_gb": round((dev.get("vram_total") or 0) / 2 ** 30, 1),
            "vram_free_gb": round((dev.get("vram_free") or 0) / 2 ** 30, 1),
            "checkpoints": ck,
            "controlnets": comfy_models("ControlNetLoader", "control_net_name"),
            "ipadapter_ok": ipadapter_available(),
            "ipadapter_models": comfy_models("IPAdapterModelLoader", "ipadapter_file"),
            "clip_visions": comfy_models("CLIPVisionLoader", "clip_name"),
            "preferred_checkpoint": defaults.get("checkpoint"),
            "preferred_ok": (not ck) or (defaults.get("checkpoint") in ck),
        }
    except Exception as e:
        return {"online": False, "url": COMFY, "error": str(e)}


def load_workflow(use_cn, image_mode=False):
    path = WF_IMG2IMG if image_mode else WF_CONTROLNET if use_cn else WF_TXT2IMG
    with open(path, "r", encoding="utf-8") as f:
        wf = json.load(f)
    out = {}
    for k, v in wf.items():
        if k.startswith("_"):
            continue
        # 节点内的 _comment 也剥掉（ComfyUI 虽然会忽略，但送干净的 prompt 更稳）
        if isinstance(v, dict):
            v = {ik: iv for ik, iv in v.items() if not str(ik).startswith("_")}
        out[k] = v
    return out


def pick_checkpoint(defaults, available):
    """首选底模不可用时自动切 fallback（避免换机后直接报错）。"""
    ck = defaults.get("checkpoint")
    if not available or ck in available:
        return ck, defaults
    fb = defaults.get("fallback") or {}
    if fb.get("checkpoint") in available:
        merged = dict(defaults)
        for k in ("checkpoint", "steps", "cfg", "sampler_name", "scheduler"):
            if fb.get(k) is not None:
                merged[k] = fb[k]
        return fb["checkpoint"], merged
    return (available[0] if available else ck), defaults


def fill_workflow(wf, payload, defaults, ckpt, use_cn):
    """先用 render_defaults.json 打底，再把载荷按 SLOTS 覆盖上去（**载荷优先**）。
    节点或字段不存在 -> 跳过（向前兼容：以后装 Redux/IPAdapter 只加节点、不动代码）。"""
    applied, skipped = [], []

    # ---- 1) 基线打底 ----
    if "1" in wf:
        wf["1"]["inputs"]["ckpt_name"] = ckpt
    if use_cn:
        for nid in ("2", "9"):
            if nid in wf:
                wf[nid]["inputs"]["control_net_name"] = defaults["controlnet"]
        if "22" in wf:
            wf["22"]["inputs"]["type"] = defaults.get("controlnet_type_depth", "depth")
        if "23" in wf:
            wf["23"]["inputs"]["type"] = defaults.get("controlnet_type_normal", "normal")
    if "13" in wf:
        # 参考图统一加载器：preset 决定用它配哪个 ipadapter + clip_vision
        wf["13"]["inputs"]["preset"] = defaults.get("ipadapter_preset", "PLUS (high strength)")
    if "3" in wf:
        ks = wf["3"]["inputs"]
        ks["steps"] = int(defaults["steps"])
        ks["cfg"] = float(defaults["cfg"])
        ks["sampler_name"] = defaults["sampler_name"]
        ks["scheduler"] = defaults["scheduler"]
        ks.setdefault("denoise", 1.0)
    if "8" in wf:
        wf["8"]["inputs"]["filename_prefix"] = defaults["filename_prefix"]

    # ---- 2) 载荷覆盖（含可选的 steps/cfg/sampler/ckpt_name）----
    for key, (nid, field) in SLOTS.items():
        if key not in payload:
            continue
        val = payload.get(key)
        if val is None or val == "":
            continue
        node = wf.get(str(nid))
        if not node:
            skipped.append(key)
            continue
        node.setdefault("inputs", {})[field] = val
        applied.append(key)

    return applied, skipped


def comfy_upload(rel):
    """把投放区里的图传给 ComfyUI，返回它在 input 目录下的文件名。
    投放区里的 pass 图与参考图都能传（两侧口径见 _asset_path）。"""
    src = _asset_path(rel)
    if not src:
        raise RuntimeError("找不到素材：%s" % rel)
    name = os.path.basename(src)
    try:
        with open(src, "rb") as f:
            blob = f.read()
        boundary = "----renderer" + uuid.uuid4().hex
        head = (
            "--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n" % (boundary, name)
        ).encode("utf-8")
        tail = ("\r\n--%s--\r\n" % boundary).encode("utf-8")
        req = urllib.request.Request(COMFY + "/upload/image", data=head + blob + tail, method="POST")
        req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
        with _urlopen(req, timeout=90) as r:
            res = json.loads(r.read().decode("utf-8"))
        sub = res.get("subfolder") or ""
        return (sub + "/" + res["name"]) if sub else res["name"]
    except Exception:
        os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
        shutil.copyfile(src, os.path.join(COMFY_INPUT_DIR, name))
        return name


def task_by_id(tid):
    with DB_LOCK, db() as con:
        r = con.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    return dict(r) if r else None


def _asset_path(rel):
    """把投放区里的相对路径解析成真实文件路径。

    rel 有两种口径：pass 图相对 PASSES_DIR（GF/side/depth.png），
    参考图等相对 ASSETS（refs/GF/GF.29.jpg）—— 两侧都试，先命中先返回，并做越界校验。
    """
    if not rel:
        return None
    rel = str(rel).replace("\\", "/").lstrip("/")
    root = os.path.abspath(ASSETS)
    for base in (PASSES_DIR, ASSETS):
        p = os.path.abspath(os.path.join(base, rel.replace("/", os.sep)))
        if p.startswith(root) and os.path.isfile(p):
            return p
    return None


def _pass_exists(rel):
    return _asset_path(rel) is not None


_ipadapter_cache = {"checked_at": 0.0, "ok": False}


def ipadapter_available():
    """参考图条件注入是否可用（装了 ComfyUI_IPAdapter_plus 才有 IPAdapterAdvanced 节点）。"""
    # 失败只短暂缓存，避免 ComfyUI 刚启动时一次超时就让本次服务一直误判为未安装。
    ttl = 60 if _ipadapter_cache["ok"] else 5
    if time.monotonic() - _ipadapter_cache["checked_at"] >= ttl:
        try:
            d = http_json("%s/object_info/IPAdapterAdvanced" % COMFY, timeout=8)
            _ipadapter_cache["ok"] = "IPAdapterAdvanced" in (d or {})
        except Exception:
            _ipadapter_cache["ok"] = False
        _ipadapter_cache["checked_at"] = time.monotonic()
    return _ipadapter_cache["ok"]


def comfy_submit(tid):
    t = task_by_id(tid)
    if not t:
        raise RuntimeError("任务不存在：#%s" % tid)
    payload = json.loads(t.get("payload") or "{}")
    image_mode = (payload.get("_meta") or {}).get("mode") == "image"
    # 2026-09-27 加固：带 source_img 却没有 _meta.mode 的任务说明提交方丢了模式标记，
    # 静默走 txt2img 会产出一张与产品毫无关系的图（实测产物是人像），且界面无任何提示。
    # 这里显式拒绝，把「静默出错图」变成「明确报错」。
    if not image_mode and payload.get("source_img"):
        raise RuntimeError(
            "任务缺少模式标记（_meta.mode），无法判断是「结构约束出图」还是「图片改图」。"
            "已拒绝提交以免产出无关图片，请在控制台重新发起。")
    defaults = load_render_defaults()
    ckpt, defaults = pick_checkpoint(defaults, comfy_models("CheckpointLoaderSimple", "ckpt_name"))

    d_rel = payload.get("depth_img") or ""
    n_rel = payload.get("normal_img") or ""
    use_cn = not image_mode and _pass_exists(d_rel)
    with_normal = use_cn and _pass_exists(n_rel)

    wf = load_workflow(use_cn, image_mode)
    if image_mode:
        source_rel = payload.get("source_img") or ""
        source_path = _asset_path(source_rel)
        if not source_rel.startswith("source/") or not source_path or os.path.commonpath((os.path.abspath(SOURCE_DIR), source_path)) != os.path.abspath(SOURCE_DIR):
            raise RuntimeError("缺少有效产品图片，已停止图片改图任务。")
        width, height = int(payload.get("width") or 0), int(payload.get("height") or 0)
        denoise = float(payload.get("denoise") or 0)
        if min(width, height) < 256 or max(width, height) > 1024 or width % 8 or height % 8:
            raise RuntimeError("图片尺寸无效：宽高须为 256–1024 且为 8 的倍数。")
        # 2026-09-27：区间从写死的 0.2–0.8 改为读 render_defaults.img2img，
        # 因为实测 0.45–0.50 在 8 步 Lightning 下有效仅 4 步、出不来渲染（见 §2 图片改图）。
        i2i = defaults.get("img2img") or {}
        dmin = float(i2i.get("denoise_min", 0.35))
        dmax = float(i2i.get("denoise_max", 0.90))
        if not dmin <= denoise <= dmax:
            raise RuntimeError("改动幅度须在 %d%%–%d%% 之间。" % (round(dmin * 100), round(dmax * 100)))
        payload = dict(payload)
        payload["source_img"] = comfy_upload(source_rel)
        # 图片模式单列采样参数：不再沿用白模结构出图的 8 步基线（见 render_defaults.img2img 说明）
        if not payload.get("steps"):
            payload["steps"] = int(i2i.get("steps", defaults["steps"]))
        if not payload.get("cfg"):
            payload["cfg"] = float(i2i.get("cfg", defaults["cfg"]))
        if i2i.get("sampler_name"):
            payload.setdefault("sampler_name", i2i["sampler_name"])
        if i2i.get("scheduler"):
            payload.setdefault("scheduler", i2i["scheduler"])
        # Canny → ControlNet 锁形状（2026-09-27）：img2img 只靠 denoise 会在
        # 「不渲染」与「臆造别的产品」之间二选一，必须补形状约束。
        payload.setdefault("canny_low", float(i2i.get("canny_low", 0.06)))
        payload.setdefault("canny_high", float(i2i.get("canny_high", 0.18)))
        payload.setdefault("canny_w", float(i2i.get("canny_w", 0.75)))
    if use_cn:
        payload = dict(payload)
        payload["depth_img"] = comfy_upload(d_rel)
        if with_normal:
            payload["normal_img"] = comfy_upload(n_rel)
        else:
            # 没有法线：短路掉第二条 ControlNet 链（节点 9/11/21/23）
            payload.pop("normal_img", None)
            for nid in ("9", "11", "21", "23"):
                wf.pop(nid, None)
            wf["3"]["inputs"]["positive"] = ["20", 0]
            wf["3"]["inputs"]["negative"] = ["20", 1]

    # ---- 参考图（IPAdapter）：有图 + 装了插件才接，否则整条链摘掉，KSampler 退回裸底模 ----
    ref_rel = payload.get("ref_img") or ""
    ref_meta = ((payload.get("_meta") or {}).get("reference")) or {}
    ref_strength = ref_meta.get("strength") or payload.get("ref_strength") or defaults.get("ref_default_strength")
    use_ref = bool(ref_rel) and _pass_exists(ref_rel) and ipadapter_available()
    if use_ref:
        smap = defaults.get("ref_strength_map") or {}
        rcfg = smap.get(ref_strength) or smap.get(defaults.get("ref_default_strength")) \
            or {"weight": 0.55, "weight_type": "linear"}
        payload = dict(payload)
        payload["ref_img"] = comfy_upload(ref_rel)
        payload["ref_w"] = float(rcfg.get("weight", 0.55))
        payload["ref_weight_type"] = rcfg.get("weight_type", "linear")
    else:
        payload = dict(payload)
        for nid in ("12", "13", "14"):
            wf.pop(nid, None)
        wf["3"]["inputs"]["model"] = ["1", 0]

    applied, skipped = fill_workflow(wf, payload, defaults, ckpt, use_cn)

    res = http_json(COMFY + "/prompt",
                    {"prompt": wf, "client_id": "ai-renderer-console"}, timeout=60)
    if res.get("node_errors"):
        raise RuntimeError("ComfyUI 节点校验失败：%s"
                           % json.dumps(res["node_errors"], ensure_ascii=False)[:600])
    pid = res.get("prompt_id")
    with DB_LOCK, db() as con:
        con.execute("UPDATE tasks SET status='running', prompt_id=?, err=NULL, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid, tid))
        con.commit()
    # v2.2 修正：此前图片任务被一并标成 txt2img，与真实链路
    # （LoadImage → ImageScale → VAEEncode → KSampler）不符，见验收文档 §6.2。
    if image_mode:
        mode_tag = "img2img"
    elif use_cn:
        mode_tag = "controlnet"
    else:
        mode_tag = "txt2img"
    return {
        "ok": True, "id": tid, "prompt_id": pid,
        "mode": mode_tag,
        "with_normal": with_normal,
        "with_ref": use_ref,
        "ref_weight": payload.get("ref_w"),
        "ref_weight_type": payload.get("ref_weight_type"),
        "checkpoint": ckpt,
        "applied": applied, "skipped": skipped,
    }


def comfy_poll(tid):
    t = task_by_id(tid)
    if not t:
        raise RuntimeError("任务不存在：#%s" % tid)
    pid = t.get("prompt_id")
    if not pid:
        return {"state": "nosubmit"}
    try:
        h = http_json("%s/history/%s" % (COMFY, pid), timeout=20)
    except Exception as e:
        return {"state": "offline", "error": str(e)}
    if pid not in h:
        return {"state": "running"}

    info = h[pid]
    status = info.get("status") or {}
    if status.get("status_str") == "error":
        msg = json.dumps(status.get("messages", []), ensure_ascii=False)[:600]
        update_task(tid, status="failed", err=msg)
        return {"state": "error", "error": msg}

    imgs = []
    for out in (info.get("outputs") or {}).values():
        imgs.extend(out.get("images") or [])
    if not imgs:
        return {"state": "empty"}

    sku = safe_file(t.get("sku") or "UNKNOWN")
    view = safe_file(t.get("view") or "front")
    ddir = os.path.join(OUTPUTS_DIR, sku, view)
    os.makedirs(ddir, exist_ok=True)

    saved = []
    for im in imgs:
        q = urlencode({"filename": im.get("filename", ""),
                       "subfolder": im.get("subfolder", "") or "",
                       "type": im.get("type", "output")})
        try:
            with _urlopen("%s/view?%s" % (COMFY, q), timeout=90) as r:
                data = r.read()
        except Exception as e:
            return {"state": "error", "error": "取图失败：%s" % e}
        dst = os.path.join(ddir, im.get("filename"))
        with open(dst, "wb") as f:
            f.write(data)
        saved.append(os.path.relpath(dst, ROOT).replace("\\", "/"))

    update_task(tid, status="done", output=",".join(saved))
    return {"state": "done", "saved": saved, "files": [os.path.basename(s) for s in saved]}


# =========================================================
# 结构图生成（Blender 后台任务）· 新版「形照」界面支持
# 说明：这块原在已归档的独立 UI（`_隔离区/20260927/_archived_ui-older/ui/server.py`，
#       2026-09-27 起不再是运行入口）里以子类方式实现，现合并进唯一后端，
#       让界面只有一套服务；同时修掉原实现的 Blender 探测缺口（本机 Blender 装在 D 盘而非 Program Files）。
# =========================================================
PASS_MODEL_EXTS = {".blend", ".glb", ".gltf", ".obj", ".stl", ".fbx", ".stp", ".step", ".3dm"}
BLENDER_SCRIPT = os.path.join(ROOT, "scripts", "blender_pass.py")
STEP_CONVERTER = os.path.join(ROOT, "scripts", "step_to_stl_freecad.py")
BLENDER_HINTS = [
    r"D:\Dsektop\blender-4.5.0-windows-x64\blender.exe",
]
_pass_lock = threading.Lock()
_pass_state = {"status": "idle", "sku": "", "view": "", "message": "",
               "returncode": None, "started_at": None, "finished_at": None}


def blender_executable():
    """按 环境变量 → PATH → 已登记路径 → Program Files 的顺序找 Blender。"""
    custom = (os.environ.get("BLENDER_EXE") or "").strip().strip('"')
    if custom and os.path.isfile(custom):
        return custom
    found = shutil.which("blender")
    if found:
        return found
    for cand in BLENDER_HINTS:
        if os.path.isfile(cand):
            return cand
    if os.name == "nt":
        import glob as _glob
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        for c in sorted(_glob.glob(os.path.join(pf, "Blender Foundation", "Blender *", "blender.exe")),
                        reverse=True):
            return c
    return None


def freecad_cmd_executable():
    """FreeCADCmd is used only for STEP tessellation; Blender remains the renderer."""
    custom = (os.environ.get("FREECAD_CMD") or "").strip().strip('"')
    if custom and os.path.isfile(custom):
        return custom
    found = shutil.which("FreeCADCmd") or shutil.which("freecadcmd")
    if found:
        return found
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        for cand in sorted(glob.glob(os.path.join(pf, "FreeCAD*", "bin", "FreeCADCmd.exe")), reverse=True):
            return cand
    return None


def converted_step_path(source):
    stat = os.stat(source)
    marker = "%s|%s|%s" % (os.path.abspath(source), stat.st_size, stat.st_mtime_ns)
    digest = hashlib.sha256(marker.encode("utf-8")).hexdigest()[:20]
    return os.path.join(ASSETS, "_转换缓存", digest + ".stl")


# Blender 侧的 STEPper 插件目录名。装在用户扩展目录或程序内置目录都算数。
STEPPER_DIR_NAMES = ("STEPper",)


def blender_has_stepper():
    """探测 Blender 是否装了 STEPper（能直接读 .stp/.step，就不必用 FreeCAD）。

    只看文件系统，不启动 Blender —— 这个判断在每次出 pass 前都会跑，必须便宜。
    """
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(os.path.join(appdata, "Blender Foundation", "Blender"))
    exe = blender_executable()
    if exe:
        roots.append(os.path.join(os.path.dirname(exe), "4.5"))
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in STEPPER_DIR_NAMES:
            for pat in (os.path.join(root, "*", "scripts", "addons", name),
                        os.path.join(root, "*", "extensions", "*", name),
                        os.path.join(root, "scripts", "addons", name),
                        os.path.join(root, "extensions", "*", name)):
                if glob.glob(pat):
                    return True
    return False


def convert_step(source):
    """Create a cached STL using FreeCAD; never alter the source STEP file.

    这是 .stp/.step 的**回退通道**：Blender 侧若装了 STEPper 插件就能直接读
    STEP，根本不会走到这里。只有 STEPper 缺失时才需要 FreeCAD。
    """
    exe = freecad_cmd_executable()
    if not exe:
        raise ValueError(
            "STEP/STP 需要 Blender 的 STEPper 插件，或 FreeCAD 命令行转换器。"
            "推荐在 Blender 里安装并启用 STEPper（自带 OCC 内核，无需额外依赖）；"
            "或安装 FreeCAD 并将 FREECAD_CMD 设为 FreeCADCmd.exe 的完整路径")
    if not os.path.isfile(STEP_CONVERTER):
        raise ValueError("缺少 scripts/step_to_stl_freecad.py")
    dest = converted_step_path(source)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    temp = dest + "." + uuid.uuid4().hex + ".part.stl"
    env = os.environ.copy()
    env.update(AI_RENDER_CAD_SOURCE=source, AI_RENDER_CAD_OUTPUT=temp)
    try:
        proc = subprocess.run([exe, STEP_CONVERTER], capture_output=True, text=True,
                              errors="replace", timeout=900, env=env)
        if proc.returncode != 0 or not os.path.isfile(temp) or os.path.getsize(temp) == 0:
            tail = (proc.stdout + "\n" + proc.stderr).strip()[-1000:]
            raise ValueError("STEP 转换失败：" + (tail or "FreeCAD 未输出网格"))
        os.replace(temp, dest)
        return dest
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


# 一个机位要能跑 ControlNet，必须凑齐这三个通道（与 index.html 的 payload 对应）
PASS_REQUIRED = ("clay.png", "depth.png", "normal.png")


def _png_size(path):
    """只读 PNG 头拿宽高，不解码整图。非 PNG 或读不出返回 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


def verify_pass_outputs(sku, view):
    """校验结构图产物是否真的齐了。返回 (ok, reason)。

    以前只认 Blender 的退出码：退出码 0 就算「结构图已生成」，可 Blender 完全
    可能在某个通道写失败、或写出 0 字节文件的情况下退出码仍为 0 —— 界面照样
    报成功，用户点「队列」出图才发现没有深度图。这里逐项核对：
    文件存在 · 体积非零 · 三个通道尺寸一致（见过程文档 7.3 的 P0 项）。
    """
    # ★ 必须与 scripts/blender_pass.py 的 outdir 算法一致：那边是
    # os.path.join(pass_root, args.sku, view) —— SKU **原样**拼目录，不做
    # safe_file 转换。这里若擅自 sanitize，含特殊字符的 SKU 就永远找不到目录。
    folder = os.path.abspath(os.path.join(PASSES_DIR, sku or "", view or ""))
    root = os.path.abspath(PASSES_DIR)
    if os.path.commonpath((root, folder)) != root:
        return False, "SKU 或机位名非法，产物路径越出结构图目录"
    missing, zero, dims = [], [], {}
    for fn in PASS_REQUIRED:
        p = os.path.join(folder, fn)
        if not os.path.isfile(p):
            missing.append(fn)
        elif os.path.getsize(p) == 0:
            zero.append(fn)
        else:
            size = _png_size(p)
            if size:
                dims[fn] = size
    if missing:
        return False, "结构图不完整，缺少：%s" % "、".join(missing)
    if zero:
        return False, "结构图有 0 字节文件：%s" % "、".join(zero)
    if len(set(dims.values())) > 1:
        return False, ("三个通道尺寸不一致，无法叠加出图：%s"
                       % "、".join("%s=%s×%s" % (k, dims[k][0], dims[k][1])
                                   for k in sorted(dims)))
    if len(dims) < len(PASS_REQUIRED):
        return False, "结构图里有文件不是有效 PNG，无法确认尺寸"
    return True, ""


def pass_status():
    with _pass_lock:
        return dict(_pass_state)


def start_pass(sku, view, model_rel=""):
    """后台用 Blender 给某个 SKU 的某个机位出结构 pass（clay/alpha/depth/normal/objectid）。"""
    global _pass_state
    if view not in VIEW_KEYS:
        raise ValueError("不支持的机位：%s" % view)
    model = next((m for m in scan_models() if m["sku"] == sku and
                  (not model_rel or m["rel"] == model_rel)), None)
    if not model:
        raise ValueError("投放区里没有 %s 的白模文件，请先导入" % sku)
    src = os.path.abspath(model["path"])
    if os.path.commonpath((os.path.abspath(MODELS_DIR), src)) != os.path.abspath(MODELS_DIR) or not os.path.isfile(src):
        raise ValueError("白模路径不在项目投放区内")
    if os.path.splitext(src)[1].lower() not in PASS_MODEL_EXTS:
        raise ValueError("这个格式不能自动生成结构图；支持 BLEND/GLB/GLTF/OBJ/STL/FBX/STEP/STP/3DM")
    exe = blender_executable()
    if not exe:
        raise ValueError("未找到 Blender。请安装 Blender，或设置环境变量 BLENDER_EXE 指向 blender.exe")
    if not os.path.isfile(BLENDER_SCRIPT):
        raise ValueError("缺少 scripts/blender_pass.py")
    # .stp/.step 不再强制要求 FreeCAD：Blender 侧若装了 STEPper 会直接读 STEP，
    # 只有 STEPper 缺失时才会回退到「先转缓存 STL」，那时 convert_step 再报错。

    with _pass_lock:
        if _pass_state["status"] == "running":
            raise ValueError("已有结构图任务在运行，请等它完成")
        _pass_state = {"status": "running", "sku": sku, "view": view,
                       "message": "正在用 Blender 生成白模 / 深度图 / 法线图…",
                       "returncode": None,
                       "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "finished_at": None}

    def worker():
        global _pass_state
        try:
            # .stp/.step 优先原样交给 Blender（STEPper 直接读），
            # 只有 STEPper 缺失、且本机装了 FreeCAD 时才转成缓存 STL 兜底。
            render_src = src
            if os.path.splitext(src)[1].lower() in (".stp", ".step") and not blender_has_stepper():
                render_src = convert_step(src)
            args = [exe, "-b", "-P", BLENDER_SCRIPT, "--",
                    "--model", render_src, "--sku", sku, "--view", view]
            proc = subprocess.run(args, capture_output=True, text=True,
                                  errors="replace", timeout=1800)
            tail = (proc.stdout + "\n" + proc.stderr).strip()[-1500:]
            ok = proc.returncode == 0
            reason = ""
            if ok:
                # 退出码 0 不等于产物可用：逐项校验通道齐全、体积非零、尺寸一致
                ok, reason = verify_pass_outputs(sku, view)
            with _pass_lock:
                _pass_state = {"status": "done" if ok else "failed",
                               "sku": sku, "view": view,
                               "message": ("结构图已生成（clay / 深度 / 法线 三通道已校验）" if ok
                                           else (reason or tail or "Blender 执行失败")),
                               "returncode": proc.returncode,
                               "started_at": _pass_state.get("started_at"),
                               "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        except subprocess.TimeoutExpired:
            with _pass_lock:
                _pass_state = {"status": "failed", "sku": sku, "view": view,
                               "message": "生成超过 30 分钟，请检查模型与 Blender 日志",
                               "returncode": None,
                               "started_at": _pass_state.get("started_at"),
                               "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        except Exception as exc:
            with _pass_lock:
                _pass_state = {"status": "failed", "sku": sku, "view": view,
                               "message": str(exc), "returncode": None,
                               "started_at": _pass_state.get("started_at"),
                               "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    threading.Thread(target=worker, daemon=True).start()


def guarded_submit(tid):
    """受控提交：结构约束模式缺深度图时**拒绝自动降级**为纯文生图（避免"以为锁了形其实没锁"）。"""
    t = task_by_id(tid)
    if not t:
        raise ValueError("任务不存在：#%s" % tid)
    payload = json.loads(t.get("payload") or "{}")
    mode = (payload.get("_meta") or {}).get("mode")
    if mode == "controlled" and not _pass_exists(payload.get("depth_img")):
        raise RuntimeError("缺少当前机位的深度图，已阻止自动降级为纯文生图。请先生成/上传结构图。")
    if mode == "explore" and payload.get("depth_img") and _pass_exists(payload.get("depth_img")):
        raise RuntimeError("外观探索模式的任务意外带了深度图，已停止（避免混淆两种模式）")
    if mode == "image":
        if payload.get("depth_img") or payload.get("normal_img"):
            raise RuntimeError("图片改图任务不能混入结构图。")
        rel = payload.get("source_img") or ""
        if not rel.startswith("source/") or not _pass_exists(rel):
            raise RuntimeError("图片改图任务缺少源图，请重新上传产品图片。")
    return comfy_submit(tid)


class Handler(SimpleHTTPRequestHandler):
    server_version = "ClayRenderer/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    # --- helpers ---
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        return json.loads(raw.decode("utf-8"))

    # --- 投放区辅助 ---
    _MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}

    def serve_asset(self, rel):
        """读取投放区里的图（只允许 ASSETS 内，防目录穿越）。

        rel 有两种口径：pass 图相对 PASSES_DIR（如 GF/side/clay.png），
        参考图等其它素材相对 ASSETS（如 refs/GF/GF.29.jpg）—— 两边都试，先命中先返回。
        """
        rel = (rel or "").replace("\\", "/").lstrip("/")
        root = os.path.abspath(ASSETS)
        full = None
        for base in (PASSES_DIR, ASSETS):
            cand = os.path.abspath(os.path.join(base, rel.replace("/", os.sep)))
            if cand.startswith(root) and os.path.isfile(cand):
                full = cand
                break
        if full is None:
            return self.send_json({"error": "not found"}, 404)
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", self._MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_output(self, rel):
        """读取 outputs/ 下生成的成品图（同样防目录穿越）。"""
        rel = (rel or "").replace("\\", "/").lstrip("/")
        full = os.path.abspath(os.path.join(OUTPUTS_DIR, rel.replace("/", os.sep)))
        root = os.path.abspath(OUTPUTS_DIR)
        if not full.startswith(root) or not os.path.isfile(full):
            return self.send_json({"error": "not found"}, 404)
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", self._MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def save_upload(self, rel, fb_sku, fb_view, overwrite=False):
        """裸二进制上传：分块写盘，避免大模型文件把内存顶爆。

        写盘前后各有一道预检（见过程文档 7.3 的 P0 项）：
          ① 格式分类 —— `.rhi`/`.rhp` 这类「不是模型」的文件明确拒绝并说明；
          ② 几何预检 —— 改过扩展名、传了一半、损坏的文件当场拦下。
        """
        n = int(self.headers.get("Content-Length") or 0)
        plain = (rel or "").replace("\\", "/").rsplit("/", 1)[-1]
        ext0 = os.path.splitext(plain)[1].lower()
        if ext0 in NOT_A_MODEL:
            return self.send_json(
                {"error": "%s 不是可用的白模文件（%s）。%s。"
                          % (ext0, NOT_A_MODEL[ext0], SUPPORTED_MODEL_HINT)}, 400)
        dest, kind, meta = plan_upload(rel, fb_sku, fb_view, overwrite)
        if n <= 0:
            return self.send_json({"error": "文件为空或未提供长度，未保存"}, 400)
        if n > (2 * 1024 * 1024 * 1024 if kind == "model" else 100 * 1024 * 1024):
            return self.send_json({"error": "文件过大，模型上限 2 GB、结构图上限 100 MB"}, 400)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        left = n
        tmp = dest + "." + uuid.uuid4().hex + ".part"
        try:
            with open(tmp, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(262144, left))
                    if not chunk:
                        raise ValueError("上传中断：文件未接收完整，原文件未改变")
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(tmp, dest)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        # 几何预检：不合格的文件当场删除，不留进投放区（否则会「看起来在、其实用不了」）
        if kind == "model":
            ok, reason = probe_model_file(dest)
            if not ok:
                try:
                    os.unlink(dest)
                except OSError:
                    pass
                return self.send_json(
                    {"error": "%s 未通过导入预检：%s" % (meta.get("name") or "文件", reason)}, 400)
        return self.send_json({
            "ok": True, "kind": kind,
            "saved": os.path.relpath(dest, ASSETS).replace("\\", "/"),
            "size_h": human_size(os.path.getsize(dest)),
            **meta,
        })

    def save_source(self, sku, name):
        """上传图片改图源图；限制格式/体积并保留同名历史版本。"""
        ext = os.path.splitext(name or "")[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            return self.send_json({"error": "产品图片只接受 PNG / JPG / WEBP"}, 400)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 20 * 1024 * 1024:
            return self.send_json({"error": "图片须在 20 MB 以内"}, 400)
        sku = safe_file(sku or os.path.splitext(name)[0])
        stem = safe_file(os.path.splitext(name)[0])
        folder = os.path.join(SOURCE_DIR, sku)
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, stem + ext)
        i = 2
        while os.path.exists(dest):
            dest = os.path.join(folder, "%s_%d%s" % (stem, i, ext))
            i += 1
        data = self.rfile.read(n)
        signatures = {".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
                      ".jpg": data.startswith(b"\xff\xd8\xff"),
                      ".jpeg": data.startswith(b"\xff\xd8\xff"),
                      ".webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP"}
        if len(data) != n or not signatures[ext]:
            return self.send_json({"error": "文件内容不是有效的所选图片格式"}, 400)
        with open(dest, "xb") as f:
            f.write(data)
        return self.send_json({"ok": True, "sku": sku,
                               "saved": os.path.relpath(dest, ASSETS).replace("\\", "/")})

    def save_ref(self, sku, name):
        """参考图上传 → assets/refs/<SKU>/。遵守「只新增」铁律：重名自动加序号，绝不覆盖。"""
        sku = safe_file(sku) or "_未指定"
        ext = os.path.splitext(name or "")[1].lower()
        if ext not in IMAGE_EXTS:
            return self.send_json({"error": "参考图只接受 png / jpg / jpeg / webp / tif / bmp"}, 400)
        stem = safe_file(os.path.splitext(name)[0]) or "ref"
        d = os.path.join(REFS_DIR, sku)
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, stem + ext)
        i = 2
        while os.path.exists(dest):
            dest = os.path.join(d, "%s_%d%s" % (stem, i, ext))
            i += 1
        n = int(self.headers.get("Content-Length") or 0)
        left, tmp = n, dest + ".part"
        with open(tmp, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(262144, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        os.replace(tmp, dest)
        return self.send_json({"ok": True, "sku": sku,
                               "saved": os.path.relpath(dest, ASSETS).replace("\\", "/"),
                               "size_h": human_size(os.path.getsize(dest))})

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("  %s %s\n" % (self.command, self.path))

    # --- routes ---
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            if p == "/api/state":
                return self.send_json({
                    "doc": read_doc_meta(),
                    "board": load_board(),
                    "cards": list_cards(),
                    "stats": list_tasks()["stats"],
                    "assets": asset_report(),
                })
            if p == "/api/refs":
                return self.send_json({"items": scan_refs(q.get("sku", [""])[0])})
            if p == "/api/assets":
                return self.send_json(asset_report())
            if p == "/api/assets/file":
                return self.serve_asset(q.get("rel", [""])[0])
            if p == "/api/changelog":
                return self.send_json({"rows": read_changelog()})
            if p == "/api/tasks":
                return self.send_json(list_tasks(int(q.get("limit", ["2000"])[0])))
            if p == "/api/card":
                sku = q.get("sku", [""])[0]
                for c in list_cards():
                    if c["sku"] == sku:
                        if not c.get("data"):
                            return self.send_json({"error": "参数卡解析失败: " + c.get("err", "")}, 500)
                        # 与 POST /api/card 对称：返回裸参数卡
                        return self.send_json(c["data"])
                return self.send_json({"error": "not found"}, 404)
            if p == "/api/comfy/status":
                return self.send_json(comfy_status())
            if p == "/api/comfy/poll":
                return self.send_json(comfy_poll(int(q.get("id", ["0"])[0])))
            if p == "/api/comfy/file":
                return self.serve_output(q.get("rel", [""])[0])
            if p == "/api/ui/info":
                exe = blender_executable()
                return self.send_json({"blender": bool(exe), "blender_path": exe or "",
                                       "freecad_cmd": freecad_cmd_executable() or "",
                                       "stepper": blender_has_stepper(),
                                       "blender_script": os.path.isfile(BLENDER_SCRIPT),
                                       "project": ROOT, "ui": "2.0"})
            if p == "/api/ui/pass/status":
                return self.send_json(pass_status())
            if p == "/api/health":
                return self.send_json({"ok": True, "root": ROOT, "db": DB_FILE,
                                       "assets": ASSETS, "models": MODELS_DIR,
                                       "passes": PASSES_DIR, "outputs": OUTPUTS_DIR,
                                       "comfy": COMFY,
                                       "doc": os.path.isfile(DOC_FILE)})
            if p.startswith("/api/"):
                return self.send_json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            return self.send_json({"error": str(e)}, 500)
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            # 裸二进制上传要抢在 read_json 之前，否则二进制会被当 JSON 解析
            if p == "/api/assets/upload":
                return self.save_upload(
                    q.get("rel", [""])[0],
                    q.get("sku", [""])[0],
                    q.get("view", [""])[0],
                    q.get("overwrite", ["0"])[0] in ("1", "true", "yes"),
                )

            if p == "/api/refs/upload":
                return self.save_ref(q.get("sku", [""])[0], q.get("name", [""])[0])

            if p == "/api/source/upload":
                return self.save_source(q.get("sku", [""])[0], q.get("name", [""])[0])

            body = self.read_json()
            if p == "/api/card":
                return self.send_json({"ok": True, "sku": save_card(body)})
            if p == "/api/board":
                save_board(body)
                return self.send_json({"ok": True})
            if p == "/api/assets/place":
                return self.send_json({"ok": True, **place_loose()})
            if p == "/api/assets/open":
                which = (body or {}).get("which") or "assets"
                target = {"models": MODELS_DIR, "passes": PASSES_DIR}.get(which, ASSETS)
                try:
                    os.startfile(target)          # Windows
                except AttributeError:
                    import subprocess
                    subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", target])
                return self.send_json({"ok": True, "opened": target.replace("\\", "/")})
            if p == "/api/comfy/submit":
                return self.send_json(comfy_submit(int((body or {}).get("id"))))
            if p == "/api/ui/pass/start":
                try:
                    start_pass(str((body or {}).get("sku", "")), str((body or {}).get("view", "")),
                               str((body or {}).get("model", "")))
                    return self.send_json({"ok": True, "status": "running"})
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/ui/comfy/submit":
                try:
                    return self.send_json(guarded_submit(int((body or {}).get("id"))))
                except (ValueError, TypeError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/tasks":
                try:
                    ids = insert_tasks((body or {}).get("tasks", []))
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                return self.send_json({"ok": True, "inserted": len(ids), "ids": ids})
            if p == "/api/tasks/clear":
                clear_tasks()
                return self.send_json({"ok": True})
            if p == "/api/task/status":
                n = update_task(body.get("id"),
                                status=body.get("status"),
                                output=body.get("output"),
                                err=body.get("err"),
                                retry=body.get("retry"))
                return self.send_json({"ok": True, "updated": n})
            return self.send_json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            return self.send_json({"error": str(e)}, 500)

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path == "/api/card":
            sku = parse_qs(u.query).get("sku", [""])[0]
            return self.send_json({"ok": delete_card(sku)})
        return self.send_json({"error": "unknown endpoint"}, 404)


def main():
    init_db()
    n = reset_running()
    port = PORT
    for _ in range(20):
        try:
            httpd = HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        print("找不到可用端口，退出。")
        return

    url = f"http://127.0.0.1:{port}/"
    print("=" * 62)
    print("  AI 白模渲染器 · 控制台")
    print("=" * 62)
    print(f"  地址      {url}")
    print(f"  项目根    {ROOT}")
    print(f"  任务库    {DB_FILE}")
    print(f"  参数卡    {CARDS_DIR}")
    print(f"  投放区    {ASSETS}")
    print(f"            白模  -> {MODELS_DIR}")
    print(f"            passes -> {PASSES_DIR}")
    ar = asset_report()
    print(f"  已识别    白模 {len(ar['models'])} 个 · SKU {len(ar['items'])} 个 · "
          f"未归类 {len(ar['loose']) + len(ar['inbox'])} 个")
    print(f"  过程文档  {'已找到' if os.path.isfile(DOC_FILE) else '未找到（看板仍可用）'}")
    if n:
        print(f"  断点续跑  已将 {n} 个残留 running 任务重置为 pending")
    print("=" * 62)
    print("  Ctrl+C 停止服务")

    if os.environ.get("RENDERER_NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
