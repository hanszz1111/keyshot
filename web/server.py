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


def load_part_cmf(sku):
    """读某 SKU 的「按部件 CMF 分配」（大纲 §3 P1）。

    存在**参数卡文件**里（`web/data/cards/<sku>.json` 的 `partCmf` 键），
    这样「保存参数卡 → 重新载入」之后部件分配跟着回来，满足大纲 GATE
    「卡片保存再打开后 ID 与覆盖项不变」。
    结构：`{机位: {部件号: {cmf: 预设id, color: 可选覆盖}}}`
    —— 按机位分开存，是为了 GATE 的另一条「切换机位后部件分配不串位」。
    """
    if not sku:
        return {}
    p = card_path(sku)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    table = data.get("partCmf")
    return table if isinstance(table, dict) else {}


def save_part_cmf(sku, view, part_id, cmf_id, color=""):
    """写入一条部件 CMF 分配，返回该 SKU 的完整分配表。

    只动 `partCmf` 这一个键，参数卡里的其他字段原样保留；
    `cmf_id` 传空 → **删除**该部件的分配（等于恢复默认）。
    """
    sku = str(sku or "").strip()
    view = str(view or "").strip()
    if not sku or not view or part_id in (None, ""):
        raise ValueError("缺少 sku / view / partId")
    p = card_path(sku)
    data = {}
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    asset = data.get("asset")
    if not isinstance(asset, dict):
        asset = {}
    asset["sku"] = sku
    data["asset"] = asset

    table = data.get("partCmf")
    if not isinstance(table, dict):
        table = {}
    per_view = table.get(view)
    if not isinstance(per_view, dict):
        per_view = {}
    key = str(part_id)
    if cmf_id:
        item = {"cmf": str(cmf_id)}
        if color:
            item["color"] = str(color)
        per_view[key] = item
    else:
        per_view.pop(key, None)
    if per_view:
        table[view] = per_view
    else:
        table.pop(view, None)
    if table:
        data["partCmf"] = table
    else:
        data.pop("partCmf", None)
    save_card(data)
    return table


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

# ---- 机位表（大纲 P0-1）：config/view_presets.json 是唯一权威源 ----
# 服务端据此做权威校验，并把方位角/仰角**显式**传给 Blender（blender_pass.py
# 内部的 VIEW_ANGLES 退化为回退/自检表）。改机位只改 JSON，不改代码。
VIEW_PRESETS_PATH = os.path.join(ROOT, "config", "view_presets.json")


def load_view_presets():
    """读机位表；文件缺失或损坏时退回内置默认，保证服务照常启动。"""
    fallback = [
        {"key": "front",         "label": "正面",       "azimuth": 0.0,   "elevation": 8.0,   "group": "six",     "renderable": True},
        {"key": "back",          "label": "背面",       "azimuth": 180.0, "elevation": 8.0,   "group": "six",     "renderable": True},
        {"key": "side",          "label": "右侧",       "azimuth": 90.0,  "elevation": 8.0,   "group": "six",     "renderable": True},
        {"key": "side_left",     "label": "左侧",       "azimuth": -90.0, "elevation": 8.0,   "group": "six",     "renderable": True},
        {"key": "top",           "label": "俯视",       "azimuth": 0.0,   "elevation": 90.0,  "group": "six",     "renderable": True},
        {"key": "bottom",        "label": "仰视",       "azimuth": 0.0,   "elevation": -90.0, "group": "six",     "renderable": True},
        {"key": "3q4_left",      "label": "左前 3/4",   "azimuth": -45.0, "elevation": 15.0,  "group": "quarter", "renderable": True},
        {"key": "3q4_right",     "label": "右前 3/4",   "azimuth": 45.0,  "elevation": 15.0,  "group": "quarter", "renderable": True},
        {"key": "detail_keypad", "label": "按键特写",   "azimuth": -30.0, "elevation": 35.0,  "group": "detail",  "renderable": True},
        {"key": "detail_window", "label": "透明件特写", "azimuth": 30.0,  "elevation": 30.0,  "group": "detail",  "renderable": True},
    ]
    try:
        with open(VIEW_PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        presets = data.get("presets") or []
        if not presets:
            raise ValueError("presets 为空")
        keys = [p.get("key") for p in presets]
        if len(keys) != len(set(keys)):
            raise ValueError("机位 key 重复: %s" % keys)
        for p in presets:
            float(p["azimuth"]); float(p["elevation"])
        return presets
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write("[warn] view_presets.json 不可用（%s），退回内置机位表\n" % exc)
        return fallback


VIEW_PRESETS = load_view_presets()
VIEW_KEYS = [p["key"] for p in VIEW_PRESETS if p.get("renderable", True)]


def view_preset(key):
    """查机位预设；没有则 None。"""
    return next((p for p in VIEW_PRESETS if p["key"] == key), None)

# 机位别名（中英混写、常见简写都吃）
# ★ 注意：别名不能重复占用 —— "left" 历史上归 3q4_left，
#   所以 side_left 只用「左侧/左视」这类不会撞车的写法。
VIEW_ALIASES = {
    "front": ["front", "正面", "正视图", "前视", "主视", "正", "frontview"],
    "back": ["back", "背面", "后视", "背", "rear", "backview"],
    "3q4_left": ["3q4_left", "left", "leftfront", "左前", "左45", "左三四",
                 "四分之三左", "3q4l", "左前三四"],
    "3q4_right": ["3q4_right", "right", "rightfront", "右前", "右45", "右三四",
                  "四分之三右", "3q4r", "右前三四"],
    "side": ["side", "profile", "侧面", "侧视", "侧", "sideview"],
    "side_left": ["side_left", "左侧", "左视", "左边", "sideleft"],
    "top": ["top", "topdown", "俯视", "顶视", "正俯", "上视", "topview"],
    "bottom": ["bottom", "仰视", "底部", "底视", "下视", "bottomview"],
    "detail_keypad": ["detail_keypad", "keypad", "按键", "键盘", "面板",
                      "特写按键", "局部按键", "detailkeypad"],
    "detail_window": ["detail_window", "window", "透明件", "视窗", "窗口",
                      "镜片", "detailwindow"],
}

# 一致性自检：机位表里每个可渲染机位都应有别名，否则中文/简称识别不到
_missing_alias = [k for k in VIEW_KEYS if k not in VIEW_ALIASES]
if _missing_alias:
    sys.stderr.write("[warn] 机位 %s 没有配置别名，中文/简称将无法识别\n" % _missing_alias)

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
            issue = _pass_manifest_issue(os.path.join(PASSES_DIR, sku, v))
            # 通道的像素尺寸。**出图必须与结构图同尺寸** —— 否则 ComfyUI 会把
            # 深度/法线图缩放去适配请求尺寸，比例一变产品就被拉变形
            # （曾出现：结构图 1232×752，而前端请求 1024×1024）。
            px = None
            for role in ("depth", "clay", "normal"):
                rel = files.get(role)
                if not rel:
                    continue
                p = _asset_path(rel)
                if p:
                    px = _png_size(p)
                    if px:
                        break
            rows.append({
                "view": v,
                "files": files,
                "size": {"width": px[0], "height": px[1]} if px else None,
                "extra": sorted(r for r in roles if r not in ("clay", "depth", "normal")),
                "missing": missing,
                "stale": bool(issue),
                "issue": issue,
                "ok": not missing and not issue,
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


def update_task_run_meta(tid, patch):
    """把运行元数据合并进 payload._meta.run（不动原载荷字段，旧参数卡仍可读）。

    v3.5 新增：执行方案第 6 节第 5 条要求保存 engine_id / 权重文件名 / 种子 /
    尺寸 / 耗时等，便于事后判断一张图是哪条链路、哪个模型出的。
    """
    with DB_LOCK, db() as con:
        row = con.execute("SELECT payload FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            return 0
        try:
            payload = json.loads(row["payload"] or "{}")
        except Exception:
            payload = {}
        meta = payload.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        run = meta.get("run")
        if not isinstance(run, dict):
            run = {}
        run.update(patch)
        meta["run"] = run
        payload["_meta"] = meta
        con.execute("UPDATE tasks SET payload=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), tid))
        con.commit()
    return 1


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
CMF_PRESETS_PATH = os.path.join(CONFIG_DIR, "cmf_presets.json")
# 大纲 §4（2026-09-29）：设计语言 / 布光预设。只描述「怎么把已有几何拍好」——
# 布光、背景、反射组织、边缘高光、阴影、细节优先级，**不描述 CAD 中不存在的结构**；
# 丝印 / 刻度 / 透明件仍按 ADR-002 走真渲染。
DESIGN_PRESETS_PATH = os.path.join(CONFIG_DIR, "design_presets.json")


def load_design_presets():
    """读设计/布光预设。缺失或损坏 → 返回空表，不影响出图（只是没得选）。"""
    try:
        with open(DESIGN_PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"presets": [], "negative_common": []}
    presets = data.get("presets")
    return {"presets": presets if isinstance(presets, list) else [],
            "negative_common": data.get("negative_common") or []}


def apply_design(payload):
    """把设计预设的提示词片段并入载荷。返回 (预设名, 错误)。

    放在**后端**做：前端只传 `_meta.design` 这个 id，避免两边各拼一份提示词
    （口径一旦不一致，「选了设计预设却没生效」这种问题很难查）。
    未选设计预设时原样返回 —— 行为与以前完全一致。
    """
    meta = payload.get("_meta") or {}
    did = meta.get("design") or ""
    if not did:
        return None, None
    data = load_design_presets()
    preset = next((p for p in data["presets"] if p.get("id") == did), None)
    if not preset:
        return None, "未知的设计预设「%s」" % did
    pos = (payload.get("positive") or "").strip()
    neg = (payload.get("negative") or "").strip()
    extra_pos = (preset.get("prompt") or "").strip()
    extra_neg = [str(v) for v in (preset.get("negative") or [])]
    extra_neg += [str(v) for v in (data.get("negative_common") or [])]
    if extra_pos:
        payload["positive"] = (pos + " " + extra_pos).strip()
    if extra_neg:
        payload["negative"] = (neg + (", " if neg else "") + ", ".join(extra_neg)).strip()
    meta["design"] = did
    meta["design_name"] = preset.get("name") or did
    payload["_meta"] = meta
    return preset.get("name") or did, None


def load_cmf_presets():
    """统一 CMF 目录的最小契约；坏预设不应静默进入生成任务。"""
    with open(CMF_PRESETS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    presets = data.get("presets")
    if not isinstance(presets, list) or not presets:
        raise ValueError("CMF 预设库为空")
    ids, legacy = set(), set()
    for p in presets:
        for key in ("id", "name", "category", "base", "finish", "color", "prompt", "process"):
            if not isinstance(p.get(key), str) or not p[key].strip():
                raise ValueError("CMF 预设缺少 %s：%s" % (key, p.get("id")))
        if p["id"] in ids:
            raise ValueError("CMF ID 重复：%s" % p["id"])
        ids.add(p["id"])
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", p["color"]):
            raise ValueError("CMF 色值无效：%s" % p["id"])
        for key in ("roughness", "metalness"):
            value = p.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError("CMF %s 超出 0–1：%s" % (key, p["id"]))
        if not isinstance(p.get("ai_editable"), bool):
            raise ValueError("CMF ai_editable 必须为布尔值：%s" % p["id"])
        texture = p.get("texture")
        if not isinstance(texture, dict) or not all(texture.get(k) for k in ("kind", "scale", "direction")):
            raise ValueError("CMF 纹理描述不完整：%s" % p["id"])
        for alias in p.get("legacy_ids", []):
            if alias in legacy:
                raise ValueError("CMF 旧 ID 重复：%s" % alias)
            legacy.add(alias)
    return data
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
WF_TXT2IMG = os.path.join(CONFIG_DIR, "comfy_workflow_sdxl.json")
WF_CONTROLNET = os.path.join(CONFIG_DIR, "comfy_workflow_sdxl_cn.json")
WF_IMG2IMG = os.path.join(CONFIG_DIR, "comfy_workflow_sdxl_img2img.json")
# 局部重绘：以白模渲染图为底，只在掩膜区域内重绘材质；depth/normal 双 ControlNet 继续锁形。
WF_INPAINT = os.path.join(CONFIG_DIR, "comfy_workflow_sdxl_inpaint.json")
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
    # 局部重绘（inpaint）专属：31=inpaint 底图（该机位的白模渲染图），
    # 32=重绘掩膜（灰度 PNG，白=要重绘）。工作流里 LoadImage→ImageToMask→VAEEncodeForInpaint。
    "base_img":   ("31", "image"),
    "mask_img":   ("32", "image"),
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


# =========================================================
# 出图引擎注册表（v3.5）
# ---------------------------------------------------------
# 稳定模式 SDXL（8188）与实验模式 Qwen-Image-2.1（8190）并存。
# 三条硬约束（见 docs/Qwen-Image-2.1-Windows-部署与模型切换执行方案.md 第 6 节）：
#   ① 可用性判定放在**服务端**，不能只信浏览器本地状态；
#   ② 实验引擎不可用时返回**中文具体原因**，绝不静默降级为 SDXL；
#   ③ 旧任务没有 engine_id 字段 → 按稳定模式处理（向后兼容）。
# =========================================================

def render_engines():
    """读 config/render_defaults.json 的 render_engines。"""
    d = load_render_defaults().get("render_engines") or {}
    return d if isinstance(d, dict) else {}


def engine_cfg(engine_id):
    """按 id 取引擎配置。空 id = 稳定模式；未知 id 返回错误文案。"""
    eid = (engine_id or "").strip() or "sdxl_controlled"
    cfg = render_engines().get(eid)
    if not isinstance(cfg, dict):
        return eid, None, "未知的出图引擎「%s」，请刷新页面后重试。" % eid
    return eid, cfg, None


def qwen_edit_cfg():
    d = load_render_defaults().get("qwen21_edit") or {}
    return d if isinstance(d, dict) else {}


def task_engine_id(t):
    """从任务载荷取引擎 id；旧任务没有这个字段 → 稳定模式。"""
    try:
        payload = json.loads((t or {}).get("payload") or "{}")
    except Exception:
        return "sdxl_controlled"
    return (payload.get("_meta") or {}).get("engine_id") or "sdxl_controlled"


def engine_host(engine_id):
    _eid, cfg, _err = engine_cfg(engine_id)
    if cfg is None:
        return COMFY
    return cfg.get("comfy_host") or COMFY


def qwen_task_running():
    """是否有实验引擎任务仍在 running（8GB 单卡：它和 Blender 结构图不能同时占 GPU）。

    执行方案第 6 节第 6 条：队列一次只跑一个 GPU 作业。这里给出反向约束 ——
    结构图侧启动前先问一句，避免两个进程把 8GB 显存抢到 OOM。
    """
    try:
        with DB_LOCK, db() as con:
            rows = con.execute("SELECT payload FROM tasks WHERE status='running'").fetchall()
    except Exception:
        return False
    for r in rows:
        try:
            payload = json.loads(r["payload"] or "{}")
        except Exception:
            continue
        eid = (payload.get("_meta") or {}).get("engine_id") or "sdxl_controlled"
        if eid != "sdxl_controlled":
            return True
    return False


def engine_ready(engine_id):
    """服务端可用性探测 → (ok, 中文原因, 细节)。

    检查顺序按「用户自己能修的」排：开关 → 端口/权重 → 节点 → 工作流文件。
    权重检查用 comfy_models()：实例没起来时它拿不到列表，正好一并覆盖端口探测。
    """
    eid, cfg, err = engine_cfg(engine_id)
    if err:
        return False, err, {}
    if eid == "sdxl_controlled":
        return True, "", {"host": cfg.get("comfy_host") or COMFY}

    host = cfg.get("comfy_host") or ""
    detail = {"host": host}
    if not cfg.get("enabled"):
        return False, ("实验引擎当前为关闭状态（config/render_defaults.json → "
                       "render_engines.%s.enabled = false）。改为 true 后即可在界面选择。" % eid), detail

    want = cfg.get("weight_files") or {}
    for node, field, key in (("UNETLoader", "unet_name", "unet"),
                             ("CLIPLoader", "clip_name", "clip"),
                             ("VAELoader", "vae_name", "vae")):
        opts = comfy_models(node, field, host)
        if not opts:
            return False, ("实验实例（%s）没有响应。请先双击 "
                           "「F:\\AI-Renderer\\experiments\\启动Qwen21实验服务.bat」启动它，再重试。" % host), detail
        if want.get(key) and want[key] not in opts:
            return False, ("实验实例缺少权重文件 %s（%s 的候选列表里没有）。"
                           "请按执行方案第 3 节下载后放进对应 models 子目录。"
                           % (want[key], node)), detail

    try:
        info = http_json("%s/object_info" % host, timeout=20)
    except Exception as exc:
        return False, "读取实验实例节点失败：%s" % exc, detail
    missing = [n for n in (cfg.get("required_nodes") or []) if n not in info]
    if missing:
        return False, ("实验实例缺少必需节点：%s。该实例的 ComfyUI 版本过旧，需要更新。"
                       % "、".join(missing)), detail

    wfname = cfg.get("workflow") or ""
    if wfname and not os.path.isfile(os.path.join(CONFIG_DIR, wfname)):
        return False, "缺少工作流文件 config/%s。" % wfname, detail
    return True, "", detail


def renderers_report():
    """GET /api/renderers 的响应。前端下拉、状态文字与禁用规则都读它。"""
    engines = render_engines()
    items = []
    for eid, cfg in engines.items():
        ok, why, detail = engine_ready(eid)
        items.append({
            "id": eid,
            "label": cfg.get("label") or eid,
            "enabled": bool(cfg.get("enabled")),
            "experimental": bool(cfg.get("experimental")),
            "supports": cfg.get("supports") or [],
            "batch_allowed": bool(cfg.get("batch_allowed")),
            "available": ok,
            "reason": why,
            "host": detail.get("host") or cfg.get("comfy_host"),
            "note": cfg.get("note") or "",
            "disabled_reason": cfg.get("disabled_reason") or "",
        })
    # 千问已安装时优先呈现；离线时保留稳定模式作为可用入口。
    preferred = "qwen21_edit_local" if any(
        e["id"] == "qwen21_edit_local" and e["available"] for e in items
    ) else "sdxl_controlled"
    return {"default": preferred, "items": items}


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


def comfy_models(node, field, host=None):
    """取某个 loader 节点的可选模型名列表（COMBO 型输入）。
    host 留空 = 稳定实例（8188）；实验引擎（Qwen 8190）传自己的地址。"""
    host = host or COMFY
    try:
        d = http_json("%s/object_info/%s" % (host, node), timeout=8)
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


def load_workflow(use_cn, image_mode=False, inpaint_mode=False):
    if inpaint_mode:
        path = WF_INPAINT
    else:
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


def comfy_upload(rel, host=None):
    """把投放区里的图传给 ComfyUI，返回它在 input 目录下的文件名。
    投放区里的 pass 图与参考图都能传（两侧口径见 _asset_path）。
    host 留空 = 稳定实例；实验引擎必须传自己的地址，否则图会传进另一个实例的 input 目录。"""
    host = host or COMFY
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
        req = urllib.request.Request(host + "/upload/image", data=head + blob + tail, method="POST")
        req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
        with _urlopen(req, timeout=90) as r:
            res = json.loads(r.read().decode("utf-8"))
        sub = res.get("subfolder") or ""
        return (sub + "/" + res["name"]) if sub else res["name"]
    except Exception:
        # 实验实例使用独立 input 目录，不能把文件悄悄复制进稳定实例的目录。
        if host != COMFY:
            raise RuntimeError("千问参考图上传失败；请确认 8190 服务和磁盘空间后重试")
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


# ---------- 实验引擎：Qwen-Image-2.1 图片精修 ----------

# Qwen 槽位表。**与 SDXL 的 SLOTS 完全独立**：节点 ID 不同、字段名不同，
# 也不共用 ControlNet / canny / denoise 等结构约束参数（执行方案第 6 节明确禁止复用）。
QWEN_SLOTS = {
    "positive":     ("5", "prompt"),
    "negative":     ("5", "negative_prompt"),
    "resolution":   ("5", "resolution"),
    "seed":         ("6", "seed"),
    "steps":        ("6", "steps"),
    "cfg":          ("6", "cfg"),
    "sampler_name": ("6", "sampler_name"),
    "scheduler":    ("6", "scheduler"),
    "denoise":      ("6", "denoise"),
    "unet_name":    ("1", "unet_name"),
    "clip_name":    ("2", "clip_name"),
    "vae_name":     ("3", "vae_name"),
}


def load_qwen_workflow():
    """加载实验引擎的 API 格式工作流。"""
    _eid, cfg, err = engine_cfg("qwen21_edit_local")
    if err:
        raise RuntimeError(err)
    path = os.path.join(CONFIG_DIR, cfg.get("workflow") or "comfy_workflow_qwen21_edit.json")
    with open(path, "r", encoding="utf-8") as f:
        wf = json.load(f)
    out = {}
    for k, v in wf.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            v = {ik: iv for ik, iv in v.items() if not str(ik).startswith("_")}
        out[k] = v
    return out


def fill_qwen_workflow(wf, payload, qcfg, cfg):
    """Qwen 工作流填充：先用 render_defaults.qwen21_edit 打底，再让载荷逐项覆盖。"""
    applied, skipped = [], []
    want = cfg.get("weight_files") or {}

    wf["1"]["inputs"]["unet_name"] = want.get("unet") or wf["1"]["inputs"]["unet_name"]
    wf["2"]["inputs"]["clip_name"] = want.get("clip") or wf["2"]["inputs"]["clip_name"]
    wf["3"]["inputs"]["vae_name"] = want.get("vae") or wf["3"]["inputs"]["vae_name"]

    ks = wf["6"]["inputs"]
    ks["steps"] = int(qcfg.get("steps", 25))
    ks["cfg"] = float(qcfg.get("cfg", 1.0))
    ks["sampler_name"] = qcfg.get("sampler_name", "euler")
    ks["scheduler"] = qcfg.get("scheduler", "simple")
    ks["denoise"] = float(qcfg.get("denoise", 1.0))
    wf["5"]["inputs"]["resolution"] = int(qcfg.get("resolution", 768))
    wf["8"]["inputs"]["filename_prefix"] = qcfg.get("filename_prefix", "qwen21")

    for key, (nid, field) in QWEN_SLOTS.items():
        if key not in payload:
            continue
        val = payload.get(key)
        if val is None or val == "":
            continue
        node = wf.get(str(nid))
        if not node:
            skipped.append(key)
            continue
        if field in ("resolution", "steps", "seed"):
            val = int(val)
        elif field in ("cfg", "denoise"):
            val = float(val)
        node.setdefault("inputs", {})[field] = val
        applied.append(key)
    return applied, skipped


def qwen_input_ok(rel):
    """实验引擎的输入图路径是否合规。

    ★ 口径必须与 payload 的 depth_img 一致：pass 图相对 assets/passes，
      形如 `<SKU>/<机位>/clay.png`，**不带 `passes/` 前缀**（见 _asset_path 注释）。
      2026-09-29 曾在这里错写成要求 `passes/` 开头，导致界面上的正确路径全被判
      「缺少输入图片」→ 千问渲染必定失败。抽成独立函数是为了让自检能直接钉住这条契约。
      注意：本函数只管**路径形态**，文件是否存在由调用方用 _pass_exists() 另判。
    """
    rel = str(rel or "").strip()
    if not rel:
        return False
    return (rel.startswith("source/") or rel.endswith("/clay.png") or
            bool(re.fullmatch(r"_部件/[^/]+/[^/]+/guides/[0-9a-f]{16}_cmf_guide\.png", rel)))


def qwen_clay_input_issue(tid, rel):
    """白模输入必须属于任务自己的 SKU/机位，且不能使用过期结构图。"""
    rel = str(rel or "").replace("\\", "/")
    is_guide = bool(re.fullmatch(r"_部件/[^/]+/[^/]+/guides/[0-9a-f]{16}_cmf_guide\.png", rel))
    if not rel.endswith("/clay.png") and not is_guide:
        return ""
    task = task_by_id(tid)
    if not task:
        return "实验引擎任务不存在"
    sku, view = str(task.get("sku") or ""), str(task.get("view") or "")
    if is_guide:
        if not rel.startswith("_部件/%s/%s/guides/" % (safe_file(sku), safe_file(view))):
            return "实验引擎输入的材质参考与任务产品或机位不一致"
    elif rel != "%s/%s/clay.png" % (sku, view):
        return "实验引擎输入的白模与任务产品或机位不一致，请重新建立任务"
    return _pass_manifest_issue(os.path.join(PASSES_DIR, sku, view))


def qwen_series_anchor(task, meta):
    """同组其他机位只能引用已完成的主视图，不能拿旧批次或别的产品串图。"""
    series = meta.get("series") or {}
    sid = str(series.get("id") or "")
    anchor_view = str(series.get("anchor_view") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", sid) or anchor_view not in VIEW_KEYS:
        raise RuntimeError("多视角关联编号无效，请重新创建任务")
    if task.get("view") == anchor_view:
        return None
    sku, variant = str(task.get("sku") or ""), int(task.get("variant") or 0)
    with DB_LOCK, db() as con:
        rows = con.execute(
            "SELECT id, payload, output FROM tasks WHERE sku=? AND view=? AND variant=? "
            "AND status='done' ORDER BY id DESC LIMIT 200",
            (sku, anchor_view, variant),
        ).fetchall()
    for row in rows:
        try:
            candidate = json.loads(row["payload"] or "{}")
            cm = candidate.get("_meta") or {}
            cs = cm.get("series") or {}
            if (cm.get("engine_id") != "qwen21_edit_local" or cs.get("id") != sid
                    or cs.get("anchor_view") != anchor_view):
                continue
            rel = next((r.strip() for r in (row["output"] or "").split(",")
                        if r.strip().lower().endswith((".png", ".jpg", ".jpeg", ".webp"))), "")
            expected = "outputs/%s/%s/" % (safe_file(sku), safe_file(anchor_view))
            if not rel.startswith(expected) or not _output_path(rel):
                raise RuntimeError("同组主视图结果已丢失或路径不匹配，请重新生成整组")
            return {"task_id": row["id"], "output": rel}
        except (ValueError, TypeError, AttributeError):
            continue
    # 关联机位失败时带上同组主视图的真正报错，避免用户只看到“主视图失败”。
    with DB_LOCK, db() as con:
        failed = con.execute(
            "SELECT id, payload, err FROM tasks WHERE sku=? AND view=? AND variant=? "
            "AND status='failed' ORDER BY id DESC LIMIT 200",
            (sku, anchor_view, variant),
        ).fetchall()
    for row in failed:
        try:
            candidate = json.loads(row["payload"] or "{}")
            cm = candidate.get("_meta") or {}
            cs = cm.get("series") or {}
            if (cm.get("engine_id") == "qwen21_edit_local" and cs.get("id") == sid
                    and cs.get("anchor_view") == anchor_view):
                reason = str(row["err"] or "未记录具体原因").strip().replace("\n", " ")[:280]
                raise RuntimeError("同组主视图 #%s 失败：%s。请修复后重新生成整组。" %
                                   (row["id"], reason))
        except (ValueError, TypeError, AttributeError):
            continue
    raise RuntimeError("同组主视图尚未完成；请先完成主视图，再继续其他机位")


def _submit_qwen(tid, payload, engine_id):
    """实验引擎提交：Qwen-Image-2.1 图片精修（单张）。

    任何不可用情况都**显式抛中文原因**；绝不静默换回 SDXL 出一张无关的图。
    """
    _eid, cfg, err = engine_cfg(engine_id)
    if err:
        raise RuntimeError(err)
    ok, why, detail = engine_ready(engine_id)
    if not ok:
        raise RuntimeError(why)
    host = detail.get("host") or cfg.get("comfy_host")

    meta = payload.get("_meta") or {}
    if meta.get("mode") != "image":
        raise RuntimeError("实验引擎只支持图片精修；多机位会逐机位各提交 1 张，不接受深度结构约束。")
    for k in ("depth_img", "normal_img", "mask_img"):
        if payload.get(k):
            raise RuntimeError("实验引擎不接受结构图/掩膜载荷（%s），请改用稳定模式。" % k)

    rel = payload.get("source_img") or ""
    if meta.get("input_kind") == "clay":
        task_for_guide = task_by_id(tid)
        rel = make_cmf_guide(task_for_guide["sku"], task_for_guide["view"], meta)
        meta["cmf_guide"] = rel
    # 输入可以是产品图，也可以是该机位的白模截图（执行方案第 5 节：同机位白模或产品照片）。
    # 路径形态由 qwen_input_ok() 判定（口径与 depth_img 一致，不带 passes/ 前缀），
    # 文件是否存在在这里实校 —— 两层都过才放行。
    if not qwen_input_ok(rel) or not _pass_exists(rel):
        raise RuntimeError("实验引擎缺少可用的输入图片：需要产品图片，或该机位已有的白模截图 clay.png。")
    clay_issue = qwen_clay_input_issue(tid, rel)
    if clay_issue:
        raise RuntimeError(clay_issue)

    # 8GB 单卡：Qwen 与 Blender 结构图不能同时跑（执行方案第 6 节队列约束）
    if _pass_state.get("status") == "running":
        raise RuntimeError("正在生成结构图（Blender）。8GB 显存放不下两个 GPU 作业，"
                           "请等结构图跑完再提交实验引擎任务。")

    task = task_by_id(tid)
    series = meta.get("series") or {}
    anchor = qwen_series_anchor(task, meta) if series else None
    qcfg = qwen_edit_cfg()
    wf = load_qwen_workflow()

    res = int(payload.get("resolution") or qcfg.get("resolution", 768))
    rmin, rmax = int(qcfg.get("resolution_min", 512)), int(qcfg.get("resolution_max", 1536))
    if not rmin <= res <= rmax:
        raise RuntimeError("精修分辨率（总像素预算）须在 %d–%d 之间。" % (rmin, rmax))
    if res % 32:
        raise RuntimeError("精修分辨率须为 32 的倍数。")
    steps = int(payload.get("steps") or qcfg.get("steps", 25))
    if not 8 <= steps <= 50:
        raise RuntimeError("千问质量步数须在 8–50 之间")

    payload = dict(payload)
    payload["source_img"] = comfy_upload(rel, host)   # 必须传到 8190，不能传到 8188
    payload["resolution"] = res
    payload["steps"] = steps
    if not payload.get("seed"):
        payload["seed"] = int(qcfg.get("seed_default", 43))

    # 参考图接线：LoadImage(4) → TextEncodeQwenImage21(5) 的 Autogrow 输入。
    # 键名必须是**扁平点号键** images.image_1；写成嵌套 dict 不报错但会被静默忽略。
    wf["4"]["inputs"]["image"] = payload["source_img"]
    wf["5"]["inputs"]["images.image_1"] = ["4", 0]
    if anchor:
        staged, stage_err = stage_base_image(task["sku"], task["view"], anchor["output"])
        if stage_err:
            raise RuntimeError("同组主视图无法作为外观参考：%s" % stage_err)
        wf["9"] = {"class_type": "LoadImage",
                   "inputs": {"image": comfy_upload(staged, host)}}
        wf["5"]["inputs"]["images.image_2"] = ["9", 0]

    applied, skipped = fill_qwen_workflow(wf, payload, qcfg, cfg)

    try:
        resp = http_json(host + "/prompt",
                         {"prompt": wf, "client_id": "ai-renderer-qwen21"}, timeout=180)
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("实验引擎（%s）没有响应：%s。请双击「启动Qwen21实验服务.bat」后重试。"
                           % (host, exc)) from exc
    if resp.get("node_errors"):
        raise RuntimeError("实验引擎节点校验失败：%s"
                           % json.dumps(resp["node_errors"], ensure_ascii=False)[:600])
    pid = resp.get("prompt_id")
    with DB_LOCK, db() as con:
        con.execute("UPDATE tasks SET status='running', prompt_id=?, err=NULL, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid, tid))
        con.commit()
    if anchor:
        update_task_run_meta(tid, {"appearance_ref_task": anchor["task_id"],
                                   "appearance_ref_output": anchor["output"]})
    if meta.get("cmf_guide"):
        update_task_run_meta(tid, {"cmf_guide": meta["cmf_guide"],
                                   "cmf_scheme_version": (meta.get("cmf_scheme") or {}).get("version")})
    return {
        "ok": True, "id": tid, "prompt_id": pid,
        "engine_id": engine_id, "mode": "qwen21_edit", "host": host,
        "resolution": res, "steps": steps, "appearance_ref_task": anchor["task_id"] if anchor else None,
        "applied": applied, "skipped": skipped,
    }


def comfy_submit(tid):
    t = task_by_id(tid)
    if not t:
        raise RuntimeError("任务不存在：#%s" % tid)
    payload = json.loads(t.get("payload") or "{}")
    # 大纲 §4：设计/布光预设。选定后由**后端**把提示词片段并进载荷（前端只传 id）。
    # 放在引擎分流**之前**：稳定链路与实验引擎都适用。
    design_name, design_err = apply_design(payload)
    if design_err:
        raise RuntimeError(design_err)
    validate_cmf_task(t, payload)
    # 引擎分流（v3.5）：实验引擎与稳定链路完全分开 —— 不同端口、不同工作流、不同参数。
    _eng = (payload.get("_meta") or {}).get("engine_id") or "sdxl_controlled"
    if _eng != "sdxl_controlled":
        return _submit_qwen(tid, payload, _eng)
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

    # ---- 局部重绘（inpaint）----
    # payload 带 mask_img（掩膜）且底图可用时，改走 inpaint 工作流。
    # 底图有两种来源（大纲 §2 P1）：该机位白模（实验模式），或**已完成的候选图**
    # （版本链，优先）。候选图在 outputs/ 下、_asset_path() 解析不了，
    # 所以这里不能只判 base_img —— 否则「用成图当底图」的任务根本进不了 inpaint 分支。
    mask_rel = payload.get("mask_img") or ""
    _bsrc_pre = ((payload.get("_meta") or {}).get("base_source") or {})
    _base_is_candidate = bool(_bsrc_pre.get("kind") == "candidate" and _bsrc_pre.get("rel"))
    inpaint_mode = (not image_mode and bool(mask_rel) and _pass_exists(mask_rel)
                    and (_base_is_candidate or _pass_exists(payload.get("base_img") or "")))
    if mask_rel and not inpaint_mode and not image_mode:
        raise RuntimeError(
            "带 mask_img 但底图不可用（既没有可用的 base_img，也没有选中的候选底图），"
            "或掩膜文件缺失，已停止局部重绘任务。")

    wf = load_workflow(use_cn, image_mode, inpaint_mode)
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

    # ---- 大纲 §2 P1：ROI 局部重绘（2026-09-29）--------------------------------
    # 整幅重绘时，一个几百像素的部件在 1232×752 上只占很小一块，细节密度低，
    # 且非目标区域容易被连带改动。默认先裁到「部件外接框 + 按尺度留边」的 ROI
    # 再生成；完成后由 composite_roi_output() 贴回原位并做确定性合成。
    # 想关掉：任务载荷带 _meta.roi_auto = false。
    meta_now = payload.get("_meta") or {}
    roi_info = None
    base_for_upload = payload.get("base_img") or ""
    mask_for_upload = mask_rel

    # ---- 大纲 §2 P1：候选底图版本链 --------------------------------------------
    # 局部编辑应在「已完成的候选图」上继续做，而不是每次都从白模起 ——
    # 白模当底图只算实验模式（未选区域仍是白模，不等于整机换材）。
    # 候选图在 outputs/ 下，comfy_upload() 认不了，先复制进部件工作区再上传；
    # 复制而非原地改写，是「可回退」的前提。
    base_src = meta_now.get("base_source") or {}
    base_source_kind = "clay"
    if inpaint_mode and base_src.get("kind") == "candidate" and base_src.get("rel"):
        staged, stage_err = stage_base_image(t.get("sku") or "", t.get("view") or "",
                                             base_src.get("rel"))
        if stage_err:
            raise RuntimeError("候选底图准备失败：%s" % stage_err)
        base_for_upload = staged
        base_source_kind = "candidate"
    elif inpaint_mode:
        base_source_kind = "clay"

    if inpaint_mode and meta_now.get("roi_auto", True):
        roi_info, roi_err = prepare_roi(
            t.get("sku") or "", t.get("view") or "",
            meta_now.get("part") or "x",
            base_for_upload, mask_rel, d_rel, n_rel,
            scale=float(meta_now.get("roi_scale") or 1.0),
            pad_ratio=float(meta_now.get("roi_pad_ratio") or 0.12))
        if roi_err:
            raise RuntimeError("ROI 局部重绘准备失败（可加 _meta.roi_auto=false 关闭 ROI）：%s" % roi_err)
        files = roi_info["files"]
        d_rel = files.get("depth") or d_rel        # 深度/法线一并换成本 ROI 的裁剪版
        n_rel = files.get("normal") or n_rel
        base_for_upload = files["base"]
        mask_for_upload = files["mask"]
        # 羽化按部件尺度走，不用固定像素（大纲 §2 P1 的明确要求）
        roi_info["feather"] = float(meta_now.get("feather")
                                    or max(2.0, round(roi_info.get("pad", 8) * 0.25, 1)))

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

    if inpaint_mode:
        # 局部重绘：底图与掩膜都要先传给 ComfyUI（与 depth/normal 同一套上传机制）。
        # 若启用了 ROI，这里上传的是裁剪版；原图路径记在 roi_info.src，供合成阶段贴回。
        payload = dict(payload)
        payload["base_img"] = comfy_upload(base_for_upload)
        payload["mask_img"] = comfy_upload(mask_for_upload)

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

    try:
        res = http_json(COMFY + "/prompt",
                        {"prompt": wf, "client_id": "ai-renderer-console"}, timeout=60)
    except (urllib.error.URLError, OSError) as exc:
        # 连不上 ComfyUI 时给「人能执行的动作」，而不是原始 WinError 10061 ——
        # 实测 ComfyUI 掉线时用户看到的是「位深图无法使用」，实际与图无关。
        raise RuntimeError(
            "渲染服务（ComfyUI）没有响应：%s。请双击「一键启动.bat」重启渲染服务，"
            "或等待半分钟后重试。" % exc) from exc
    if res.get("node_errors"):
        raise RuntimeError("ComfyUI 节点校验失败：%s"
                           % json.dumps(res["node_errors"], ensure_ascii=False)[:600])
    pid = res.get("prompt_id")
    with DB_LOCK, db() as con:
        con.execute("UPDATE tasks SET status='running', prompt_id=?, err=NULL, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid, tid))
        con.commit()
    # ROI 信息要落库：轮询阶段（另一个请求）要用它把产物贴回原位并合成
    if roi_info:
        roi_info["base_source_kind"] = base_source_kind
        if base_source_kind == "candidate":
            roi_info["base_source_rel"] = (meta_now.get("base_source") or {}).get("rel")
        update_task_run_meta(tid, {"roi": roi_info, "roi_enabled": True})
    elif inpaint_mode:
        update_task_run_meta(tid, {"base_source_kind": base_source_kind})
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
        "roi": roi_info,
        "design": design_name,
    }


def comfy_poll(tid):
    t = task_by_id(tid)
    if not t:
        raise RuntimeError("任务不存在：#%s" % tid)
    pid = t.get("prompt_id")
    if not pid:
        return {"state": "nosubmit"}
    # 按任务所属引擎找实例：实验引擎跑在 8190、稳定链路在 8188（v3.5）
    engine_id = task_engine_id(t)
    host = engine_host(engine_id)
    try:
        h = http_json("%s/history/%s" % (host, pid), timeout=20)
    except Exception as e:
        return {"state": "offline", "error": str(e), "engine_id": engine_id}
    if pid not in h:
        return {"state": "running"}

    info = h[pid]
    status = info.get("status") or {}
    if status.get("status_str") == "error":
        msg = json.dumps(status.get("messages", []), ensure_ascii=False)[:600]
        update_task(tid, status="failed", err=msg)
        update_task_run_meta(tid, {"engine_id": engine_id, "host": host,
                                   "failed": True, "error": msg[:300]})
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
            with _urlopen("%s/view?%s" % (host, q), timeout=90) as r:
                data = r.read()
        except Exception as e:
            return {"state": "error", "error": "取图失败：%s" % e}
        dst = os.path.join(ddir, im.get("filename"))
        with open(dst, "wb") as f:
            f.write(data)
        saved.append(os.path.relpath(dst, ROOT).replace("\\", "/"))

    # ---- 大纲 §2 P1：ROI 任务落盘后做确定性合成 -------------------------------
    # 只在掩膜（含羽化边）内采用 AI 产物，掩膜外**逐像素还原原底图**。
    # 这一步不依赖模型「自觉不改」，由 composite_masked.py 自检保证（外差必须为 0）；
    # 原始 AI 产物会留成 *_raw.png，便于对比。
    try:
        payload = json.loads(t.get("payload") or "{}")
    except Exception:
        payload = {}
    roi = ((payload.get("_meta") or {}).get("run") or {}).get("roi")
    composite_note = None
    if roi:
        fixed, errs = [], []
        for s in saved:
            final, cinfo, cerr = composite_roi_output(s, roi)
            if cerr:
                fixed.append(s)
                errs.append("%s → %s" % (os.path.basename(s), cerr))
            else:
                fixed.append(final)
                composite_note = cinfo
        saved = fixed
        if errs:
            # 合成失败不算任务失败（产物已落地），但必须如实记录，不能假装做了还原
            composite_note = {"ok": False, "errors": errs}

    update_task(tid, status="done", output=",".join(saved))

    # 运行元数据（执行方案第 6 节第 5 条）：事后能查一张图出自哪条链路、哪个模型、什么参数、多久。
    # 产物文件名前缀由工作流的 filename_prefix 决定（Qwen 侧为 qwen21），所以文件名本身也带链路标识。
    run = {
        "engine_id": engine_id,
        "host": host,
        "outputs": [os.path.basename(s) for s in saved],
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if composite_note is not None:
        run["composite"] = composite_note
        run["roi"] = roi
    for k in ("seed", "resolution", "steps", "cfg", "denoise", "source_img"):
        if payload.get(k) not in (None, ""):
            run[k] = payload[k]
    if engine_id != "sdxl_controlled":
        ecfg = render_engines().get(engine_id) or {}
        run["weights"] = ecfg.get("weight_files") or {}
        run["workflow"] = ecfg.get("workflow")
    ts = {}
    for m in (status.get("messages") or []):
        if isinstance(m, (list, tuple)) and len(m) == 2 and isinstance(m[1], dict):
            ts[m[0]] = m[1].get("timestamp")
    if ts.get("execution_start") and ts.get("execution_success"):
        run["gpu_ms"] = int(ts["execution_success"] - ts["execution_start"])
    update_task_run_meta(tid, run)

    return {"state": "done", "saved": saved, "files": [os.path.basename(s) for s in saved],
            "engine_id": engine_id}


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


# Blender 侧的插件目录名（按**目录名**探测，与模块名无关）。
STEPPER_DIR_NAMES = ("STEPper",)          # 直读 .stp/.step（自带 OCC 内核）
IMPORT_3DM_DIR_NAMES = ("import_3dm",)    # 读 Rhino .3dm 的渲染网格


def _blender_addon_dir(dir_names):
    """在 Blender 的插件/扩展目录里找指定名字的目录，返回命中路径或 None。

    只看文件系统，不启动 Blender —— 界面每次读状态都会调，必须便宜。
    同时覆盖三种安装位置：
      · 用户 addons       <Blender>/<ver>/scripts/addons/<name>
      · 用户 extensions   <Blender>/<ver>/extensions/<repo>/<name>    （4.2+ 新式扩展）
      · 程序内置          <blender.exe 同级>/<ver>/scripts|extensions/…
    """
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(os.path.join(appdata, "Blender Foundation", "Blender"))
    exe = blender_executable()
    if exe:
        base = os.path.dirname(exe)
        roots.extend((base, os.path.join(base, "4.5")))
    seen = set()
    for root in roots:
        if not root or root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        for name in dir_names:
            for pat in (os.path.join(root, "*", "scripts", "addons", name),
                        os.path.join(root, "*", "extensions", "*", name),
                        os.path.join(root, "*", "extensions", "*", "*", name),
                        os.path.join(root, "scripts", "addons", name),
                        os.path.join(root, "extensions", "*", name)):
                hit = glob.glob(pat)
                if hit:
                    return hit[0]
    return None


def blender_has_stepper():
    """Blender 是否装了 STEPper —— 装了就能直读 .stp/.step，不必用 FreeCAD。"""
    return bool(_blender_addon_dir(STEPPER_DIR_NAMES))


def blender_has_import3dm():
    """Blender 是否装了 import_3dm —— Rhino .3dm 靠它读渲染网格。

    Blender 4.2+ 装成扩展时目录名仍是 import_3dm（只有**模块名**才带
    bl_ext.<repo>. 前缀），所以这里按目录名探测。
    """
    return bool(_blender_addon_dir(IMPORT_3DM_DIR_NAMES))


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
PASS_FORMAT_VERSION = 2
MANUAL_PASS_ROLES = ("clay", "depth", "normal")


def _record_manual_pass(folder, role, path):
    """记录用户明确替换的通道；仅三通道都新上传时允许绕过旧自动清单。"""
    marker = os.path.join(folder, "manual_override.json")
    try:
        with open(marker, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        data = {}
    manifest = os.path.join(folder, "pass_manifest.json")
    manifest_ns = os.stat(manifest).st_mtime_ns if os.path.isfile(manifest) else 0
    if data.get("manifest_ns") != manifest_ns:
        data = {"manifest_ns": manifest_ns, "roles": {}}
    st = os.stat(path)
    data["roles"][role] = {"file": os.path.basename(path), "size": st.st_size,
                           "mtime_ns": st.st_mtime_ns}
    tmp = marker + "." + uuid.uuid4().hex + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, marker)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _manual_pass_state(folder, manifest_ns):
    marker = os.path.join(folder, "manual_override.json")
    if not os.path.isfile(marker):
        return "none"
    try:
        with open(marker, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("manifest_ns") != manifest_ns:
            return "none"  # 后续自动重生成已经覆盖了手工替换记录
        roles = data.get("roles") or {}
        if not roles:
            return "none"
        for role in MANUAL_PASS_ROLES:
            entry = roles.get(role)
            if not entry:
                return "partial"
            name = entry.get("file", "")
            if os.path.basename(name) != name or not name.startswith(role + "."):
                return "partial"
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                return "partial"
            st = os.stat(path)
            if not st.st_size or st.st_size != entry.get("size") or st.st_mtime_ns != entry.get("mtime_ns"):
                return "partial"
        return "complete"
    except (OSError, ValueError, TypeError, AttributeError):
        return "partial"


def _pass_manifest_issue(folder):
    """只拒绝有 manifest 的旧/坏自动生成 pass；手工上传的结构图仍可使用。"""
    path = os.path.join(folder, "pass_manifest.json")
    if not os.path.isfile(path):
        return ""
    manual = _manual_pass_state(folder, os.stat(path).st_mtime_ns)
    if manual == "complete":
        return ""
    if manual == "partial":
        return "当前机位混有旧自动结构图；请补齐手动白模、深度、法线三通道，或重新自动生成"
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("pass_format_version") != PASS_FORMAT_VERSION:
            return "结构图使用旧版深度编码，请重新生成当前机位"
        depth = meta.get("depth_encoding") or {}
        if (depth.get("encoding") != "near_white_far_dark_bg_black_v2" or
                depth.get("background") != 0.0 or
                int(depth.get("foreground_pixels", 0)) <= 0 or
                int(depth.get("pixels", 0)) <= 0):
            return "深度通道无有效结构，请重新生成当前机位"
        sig = meta.get("source_signature")
        if sig:
            preset = view_preset(os.path.basename(folder))
            if preset and sig.get("view") != [preset["azimuth"], preset["elevation"]]:
                return "机位参数已更新，当前结构图过期，请重新生成"
            src = os.path.join(MODELS_DIR, sig.get("rel", ""))
            if os.path.commonpath((os.path.abspath(MODELS_DIR), os.path.abspath(src))) != os.path.abspath(MODELS_DIR):
                return "结构图模型来源非法"
            if not os.path.isfile(src):
                return "结构图对应的原模型已不存在，请重新生成"
            st = os.stat(src)
            if st.st_size != sig.get("size") or st.st_mtime_ns != sig.get("mtime_ns"):
                return "模型已更新，当前机位结构图过期，请重新生成"
        return ""
    except (OSError, ValueError, TypeError, KeyError):
        return "结构图清单损坏，请重新生成当前机位"


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
    issue = _pass_manifest_issue(folder)
    if issue:
        return False, issue
    return True, ""


# =========================================================
# 模型缩略图 · 上传后立刻给一张预览
# 解决「导入完了主画面还是空白、不知道到底读进来没有」。
# 与正式结构图**共用相机方位 / 取景算法 / 轴向**（见 blender_pass.py 的 --thumb），
# 所以缩略图里能看到的部位，正式机位一定也在画面内。
# =========================================================
THUMB_DIR = os.path.join(ASSETS, "_缩略图")
THUMB_VIEW = "3q4_left"            # 比正视图更有立体感，适合当预览
THUMB_W, THUMB_H = 616, 376        # 正式图 1232×752 的一半，比例保持一致
# 网页 3D 预览用的 GLB（由 Blender 从导入后的网格导出，保留部件结构）。
# 网页只读这个已三角化、已验证的文件，原始 STEP/3DM 不直接喂浏览器。
PREVIEW_DIR = os.path.join(ASSETS, "_预览模型")
_thumb_lock = threading.Lock()
_thumb_state = {"status": "idle", "sku": "", "message": "",
                "started_at": None, "finished_at": None}


def thumb_path(sku):
    return os.path.join(THUMB_DIR, safe_file(sku) + ".png")


def glb_path(sku):
    return os.path.join(PREVIEW_DIR, safe_file(sku) + ".glb")


def glb_is_fresh(sku, model_path):
    """预览模型存在、非空，且比模型文件新。"""
    g = glb_path(sku)
    try:
        if not os.path.isfile(g) or os.path.getsize(g) == 0:
            return False
        if model_path and os.path.isfile(model_path):
            return os.path.getmtime(g) >= os.path.getmtime(model_path)
        return True
    except OSError:
        return False


def parts_index(sku, view=""):
    """读某个 SKU 的部件索引（pass_index → 物体名），供 3D 预览里点选部件用。

    来源是结构图产物里的 `pass_manifest.json` —— 那是 Blender 出 pass 时
    **按物体名排序**生成的（见 blender_pass.py 的 assign_pass_index），
    索引与 objectid.png 的颜色编号一致，所以点选结果能和掩膜对上。

    ⚠️ 部件名是**源文件里带的**：Rhino 导出的 .3dm 常全是「物体.001」，
    STEP 往往带编号（如 102990008）。名不直观是数据本身的问题，不是 bug ——
    所以界面要把「名字 + 编号 + 面数」一起显示，让用户靠高亮认出是哪个部件。
    """
    views = []
    sku_dir = os.path.join(PASSES_DIR, sku) if sku else ""
    if os.path.isdir(sku_dir):
        views = sorted(d for d in os.listdir(sku_dir)
                       if os.path.isdir(os.path.join(sku_dir, d)) and not d.startswith("_"))
    # 优先用指定机位；否则找**第一个真的有 pass_manifest.json 的机位**。
    # ★ 不能只看目录是否存在 —— 空目录（例如只出过 thumb、没出 pass）会把结果带偏，
    #   表现为「明明有结构图却说没有部件索引」。
    cands = ([view] if view else []) + [v for v in views if v != view]
    man, use = None, ""
    for v in cands:
        p = os.path.join(PASSES_DIR, sku, v, "pass_manifest.json")
        if os.path.isfile(p):
            man, use = p, v
            break
    if not man:
        return {"sku": sku, "view": "", "count": 0, "parts": {},
                "note": "还没有任何机位出过结构图（没有 pass_manifest.json），无法给出部件索引"}
    try:
        with open(man, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        return {"sku": sku, "view": use, "count": 0, "parts": {},
                "note": "读取失败：%s" % exc}
    parts = data.get("objectid_map") or {}
    return {"sku": sku, "view": use, "count": len(parts),
            "resolution": data.get("resolution"),
            "parts": parts}


# 跨机位 CMF：用模型文件内容和 Blender 网格名锚定分配，机位内的 object ID 只用来投影。
CMF_SCHEME_DIR = os.path.join(DATA, "cmf_schemes")
CMF_SCHEME_LOCK = threading.Lock()
_MODEL_HASH_CACHE = {}


def _cmf_model(sku):
    model = next((m for m in scan_models() if m["sku"] == sku), None)
    if not model:
        raise ValueError("没有找到该产品的源白模，不能保存跨机位材质方案")
    path = os.path.abspath(model["path"])
    if os.path.commonpath((os.path.realpath(MODELS_DIR), os.path.realpath(path))) != os.path.realpath(MODELS_DIR):
        raise ValueError("模型路径不在白模投放区内")
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime_ns)
    digest = _MODEL_HASH_CACHE.get(key)
    if not digest:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        digest = h.hexdigest()
        _MODEL_HASH_CACHE.clear()
        _MODEL_HASH_CACHE[key] = digest
    return model, digest


def _cmf_scheme_path(sku):
    if not sku or safe_file(sku) != sku:
        raise ValueError("产品编号无效")
    os.makedirs(CMF_SCHEME_DIR, exist_ok=True)
    return os.path.join(CMF_SCHEME_DIR, sku + ".json")


def load_cmf_scheme(sku):
    path = _cmf_scheme_path(sku)
    model, fingerprint = _cmf_model(sku)
    stored = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            stored = json.load(f)
        if not isinstance(stored, dict):
            raise ValueError("材质方案文件格式无效")
        if not isinstance(stored.get("assignments"), dict):
            raise ValueError("材质方案的部件分配格式无效")
    return {"sku": sku, "model": model["rel"], "fingerprint": fingerprint,
            "version": int(stored.get("version") or 0),
            "assignments": stored.get("assignments") or {},
            "stale": bool(stored and stored.get("fingerprint") != fingerprint)}


def save_cmf_assignment(sku, view, part_id, cmf_id, label, color):
    return save_cmf_assignments(sku, view, [{"part": part_id, "label": label}], cmf_id, color)


def save_cmf_assignments(sku, view, parts, cmf_id, color):
    """一次校验、一次写入，避免批量选区只保存一部分。"""
    if not view or not isinstance(parts, list) or not 1 <= len(parts) <= 500:
        raise ValueError("请在当前 3D 视角选择 1–500 个部件")
    index = parts_index(sku, view)
    if index["view"] != view:
        raise ValueError("当前机位的部件索引不存在，请先补齐该视角结构图")
    issue = _pass_manifest_issue(os.path.join(PASSES_DIR, sku, view))
    if issue:
        raise ValueError("结构图已过期：" + issue)
    presets = {p["id"]: p for p in load_cmf_presets()["presets"]}
    if cmf_id not in presets:
        raise ValueError("材质预设不存在")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color or "")):
        raise ValueError("颜色须为 #RRGGBB")
    checked = {}
    for part in parts:
        if not isinstance(part, dict) or not re.fullmatch(r"\d+", str(part.get("part") or "")):
            raise ValueError("选区里有无效部件编号")
        name = index["parts"].get(str(part["part"]))
        if not name:
            raise ValueError("选区里有部件缺少稳定名称或索引；请先补齐该视角结构图")
        label = str(part.get("label") or name).strip()
        if not label or len(label) > 40 or any(ord(c) < 32 for c in label):
            raise ValueError("部位名称须为 1–40 个可见字符")
        checked[name] = label
    with CMF_SCHEME_LOCK:
        scheme = load_cmf_scheme(sku)
        if scheme["stale"]:
            raise ValueError("源模型已改变；请先重新核对并建立材质方案")
        assignments = dict(scheme["assignments"])
        if len(set(assignments) | set(checked)) > 5000:
            raise ValueError("部件分配已达上限")
        for name, label in checked.items():
            assignments[name] = {"label": label, "cmf": cmf_id, "color": color.upper()}
        result = {"sku": sku, "model": scheme["model"],
                  "fingerprint": scheme["fingerprint"], "version": scheme["version"] + 1,
                  "assignments": assignments}
        path = _cmf_scheme_path(sku)
        tmp = path + "." + uuid.uuid4().hex + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return {**result, "stale": False}


def reset_cmf_scheme(sku):
    """显式重新建方案；旧版先移入同目录备份，旧任务版本随即失效。"""
    with CMF_SCHEME_LOCK:
        scheme = load_cmf_scheme(sku)
        path = _cmf_scheme_path(sku)
        if os.path.isfile(path):
            backup = path + ".backup-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            shutil.copy2(path, backup)
        result = {"sku": sku, "model": scheme["model"],
                  "fingerprint": scheme["fingerprint"], "version": scheme["version"] + 1,
                  "assignments": {}}
        tmp = path + "." + uuid.uuid4().hex + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return {**result, "stale": False}


def remove_cmf_assignment(sku, view, part_id):
    index = parts_index(sku, view)
    if index["view"] != view or str(part_id) not in index["parts"]:
        raise ValueError("当前机位找不到这个部件，请重新选择")
    name = index["parts"][str(part_id)]
    with CMF_SCHEME_LOCK:
        scheme = load_cmf_scheme(sku)
        if scheme["stale"]:
            raise ValueError("源模型已改变，请先重新建立材质方案")
        assignments = dict(scheme["assignments"])
        if name not in assignments:
            return scheme
        del assignments[name]
        result = {"sku": sku, "model": scheme["model"],
                  "fingerprint": scheme["fingerprint"], "version": scheme["version"] + 1,
                  "assignments": assignments}
        path = _cmf_scheme_path(sku)
        tmp = path + "." + uuid.uuid4().hex + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return {**result, "stale": False}


def validate_cmf_task(task, payload):
    """提交时验证任务快照；不让旧方案或错机位偷偷生效。"""
    meta = payload.get("_meta") or {}
    ref = meta.get("cmf_scheme")
    if not ref:
        return
    if not isinstance(ref, dict):
        raise RuntimeError("材质方案任务标记无效，请重新建立任务")
    sku, view = str(task.get("sku") or ""), str(task.get("view") or "")
    scheme = load_cmf_scheme(sku)
    if (scheme["stale"] or ref.get("version") != scheme["version"]
            or ref.get("fingerprint") != scheme["fingerprint"]):
        raise RuntimeError("材质方案或源模型在任务建立后已改变，请重新建立这一批任务")
    if not scheme["assignments"]:
        raise RuntimeError("材质方案为空，请重新建立任务")
    index = parts_index(sku, view)
    if index["view"] != view:
        raise RuntimeError("当前机位缺少部件映射，不能保证材质归属")
    names = set(index["parts"].values())
    missing = set(scheme["assignments"]) - names
    if missing:
        raise RuntimeError("当前机位无法映射 %d 个材质部位，请补齐结构图并重新核对方案" % len(missing))
    if _pass_manifest_issue(os.path.join(PASSES_DIR, sku, view)):
        raise RuntimeError("材质方案所用结构图已过期，请重新生成")
    if not os.path.isfile(os.path.join(PASSES_DIR, sku, view, "objectid.png")):
        raise RuntimeError("当前机位缺少对象 ID 图，无法准确定位材质部位；请补齐结构图")
    presets = {p["id"]: p for p in load_cmf_presets()["presets"]}
    groups = {}
    for value in scheme["assignments"].values():
        preset = presets.get(value.get("cmf"))
        if not preset:
            raise RuntimeError("材质方案包含已删除的预设，请重新选择")
        if preset["ai_editable"] is False:
            raise RuntimeError("部位“%s”的“%s”仅支持真渲染；当前 AI 出图不能保证此材质" %
                               (value.get("label") or "未命名", preset["name"]))
        key = (value["label"], preset["id"], value["color"])
        groups[key] = groups.get(key, 0) + 1
    if len(groups) > 32:
        raise RuntimeError("材质方案包含超过 32 个不同部位组合，请合并同类部件后再出图")
    lines = ["%s: %s, exact color %s, %s (%d mesh%s)" %
             (label, presets[pid]["prompt"], color, presets[pid]["process"], count,
              "es" if count != 1 else "")
             for (label, pid, color), count in sorted(groups.items())]
    payload["positive"] = (payload.get("positive") or "") + " Same physical product and part assignments across all views. " + "; ".join(lines) + ". Do not swap materials between parts."
    meta["cmf_scheme_applied"] = {"version": scheme["version"], "parts": len(scheme["assignments"])}


def make_cmf_guide(sku, view, meta):
    """为千问构造同机位的确定性配色参考；原白模与 pass 一律不改。"""
    scheme = load_cmf_scheme(sku)
    color = str(meta.get("body_color") or "")
    background = {"white": "#FFFFFF", "dark": "#25292E"}.get(meta.get("style"), "#F3F5F6")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise RuntimeError("主体颜色无效，无法建立多材质配色参考")
    folder = os.path.join(PASSES_DIR, sku, view)
    clay, oid, manifest = (os.path.join(folder, name) for name in
                           ("clay.png", "objectid.png", "pass_manifest.json"))
    if any(not os.path.isfile(path) for path in (clay, oid, manifest)):
        raise RuntimeError("当前机位缺少白模/对象 ID/结构清单，无法建立多材质参考")
    source = ["guide-v2-lines-clean-bg", scheme["fingerprint"], str(scheme["version"]), color.upper(), background]
    for path in (clay, oid, manifest):
        st = os.stat(path)
        source.extend((str(st.st_size), str(st.st_mtime_ns)))
    digest = hashlib.sha256("|".join(source).encode("utf-8")).hexdigest()[:16]
    rel = "_部件/%s/%s/guides/%s_cmf_guide.png" % (safe_file(sku), safe_file(view), digest)
    dest = os.path.join(ASSETS, *rel.split("/"))
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return rel
    tool = os.path.join(ROOT, "scripts", "cmf_guide.py")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + "." + uuid.uuid4().hex + ".png"
    try:
        proc = subprocess.run([sys.executable, tool, "--clay", clay, "--objectid", oid,
                               "--manifest", manifest, "--scheme", _cmf_scheme_path(sku),
                               "--default-color", color, "--background-color", background, "--out", tmp],
                              capture_output=True, text=True, errors="replace", timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("多材质配色参考生成超时") from exc
    if proc.returncode or not os.path.isfile(tmp) or not os.path.getsize(tmp):
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise RuntimeError("多材质配色参考生成失败：%s" %
                           (proc.stderr or proc.stdout or "请检查 numpy/Pillow 与结构图")[-350:])
    os.replace(tmp, dest)
    return rel


# 局部重绘掩膜的隔离工作区（大纲 P0-3）：只写这里，绝不碰源 CAD/旧 pass/候选图
PART_MASK_DIR = os.path.join(ASSETS, "_部件")
OBJECTID_TOOL = os.path.join(ROOT, "scripts", "objectid_mask.py")
# 大纲 §2 P1（2026-09-29）：ROI 局部重绘与确定性合成。
# 两者同样以**子进程**方式调用，numpy/PIL 由运行本服务的 Python 提供
# （与 objectid_mask.py 同一约定），控制台本体仍然零第三方依赖。
ROI_TOOL = os.path.join(ROOT, "scripts", "roi_crop.py")
COMPOSITE_TOOL = os.path.join(ROOT, "scripts", "composite_masked.py")


def prepare_roi(sku, view, part_id, base_rel, mask_rel, depth_rel="", normal_rel="",
                scale=1.0, pad_ratio=0.12):
    """把局部重绘的输入裁到同一 ROI（按部件尺度留边）。

    返回 (info, error)。info.roi 是闭区间，与 composite_masked.py 的 --bbox 同一口径；
    info.files 是裁剪后各图的**相对 assets 路径**，可直接交给 comfy_upload()。
    产物写 assets/_部件/<SKU>/<机位>/roi_<part>/，不碰源 CAD、旧 pass 与已有候选图。
    """
    if not os.path.isfile(ROI_TOOL):
        return None, "缺少 scripts/roi_crop.py"
    base_abs = _asset_path(base_rel or "")
    mask_abs = _asset_path(mask_rel or "")
    if not base_abs:
        return None, "局部重绘底图不可用：%s" % (base_rel or "(空)")
    if not mask_abs:
        return None, "局部重绘掩膜不可用：%s" % (mask_rel or "(空)")
    dest_dir = os.path.join(PART_MASK_DIR, safe_file(sku), safe_file(view),
                            "roi_%s" % safe_file(str(part_id)))
    os.makedirs(dest_dir, exist_ok=True)
    cmd = [sys.executable, ROI_TOOL, "--base", base_abs, "--mask", mask_abs,
           "--out-dir", dest_dir, "--auto-bbox",
           "--scale", str(scale), "--pad-ratio", str(pad_ratio), "--json"]
    for role, rel in (("depth", depth_rel), ("normal", normal_rel)):
        p = _asset_path(rel) if rel else None
        if p:
            cmd += ["--" + role, p]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=180)
    except subprocess.TimeoutExpired:
        return None, "ROI 裁剪超时"
    if proc.returncode != 0:
        tail = (proc.stdout + "\n" + proc.stderr).strip()[-300:]
        return None, "ROI 裁剪失败：%s" % (tail or "未知错误")
    info = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                info = json.loads(line)
                break
            except ValueError:
                continue
    if not info:
        return None, "ROI 裁剪没有返回结果"
    files = {}
    for role, path in (info.get("files") or {}).items():
        rel = os.path.relpath(path, ASSETS).replace("\\", "/")
        if _asset_path(rel):
            files[role] = rel
    if "base" not in files or "mask" not in files:
        return None, "ROI 裁剪产物不完整"
    info["files"] = files
    info["src"] = {"base": base_rel, "mask": mask_rel,
                   "depth": depth_rel, "normal": normal_rel}
    return info, None


def _output_path(rel):
    """解析 outputs/ 下的相对路径（相对 ROOT）。

    ★ 注意与 _asset_path() 的区别：后者只认 assets/（投放区）下的素材，
      而**产物**在 outputs/ 下，用它去解析产物必然返回 None —— 2026-09-29 踩过：
      ROI 合成报「gen/base/mask 缺失」，其实产物好好的，是解析函数用错了。
    """
    if not rel:
        return None
    p = os.path.abspath(os.path.join(ROOT, str(rel).replace("\\", "/")))
    root = os.path.abspath(OUTPUTS_DIR)
    if (p == root or p.startswith(root + os.sep)) and os.path.isfile(p):
        return p
    return None


def list_candidates(sku, view):
    """列出某机位已有的候选图，供局部编辑选底图（大纲 §2 P1「候选底图版本链」）。

    大纲要求在已有产品图的基础上做局部编辑，而不是每次都从白模起 ——
    白模当底图只算实验模式（未选区域仍是白模，不等于整机换材）。
    这里按时间倒序列出全部候选，用户可任选一张作为下一次的底图，
    改坏了就退回更早的一张，这就是链路的价值。
    `*_raw.png`（ROI 合成前的 AI 原样留档）不列为候选底图。
    """
    if not sku or not view:
        return []
    ddir = os.path.join(OUTPUTS_DIR, safe_file(sku), safe_file(view))
    if not os.path.isdir(ddir):
        return []
    out = []
    for name in sorted(os.listdir(ddir)):
        if not name.lower().endswith(".png") or name.lower().endswith("_raw.png"):
            continue
        p = os.path.join(ddir, name)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({
            "rel": "outputs/%s/%s/%s" % (safe_file(sku), safe_file(view), name),
            "name": name,
            "bytes": st.st_size,
            "ts": st.st_mtime,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            # 尺寸要给前端看：候选图尺寸常与结构图不同（实测 1536×1024 / 992×608 vs
            # 结构图 1232×752），选底图时用户需要知道这件事
            "size": _png_size(p),
        })
    out.sort(key=lambda r: -r["ts"])
    return out


def stage_base_image(sku, view, rel):
    """把选定的底图复制进部件工作区，返回可被 _asset_path() 解析的相对路径。

    为什么要复制：comfy_upload() 走 _asset_path()，只认 assets/ 下的素材，
    而候选图在 outputs/ 下。复制到隔离工作区既让上传能工作，
    也保证 outputs 里的原始产物不被改写（可回退的前提）。
    """
    rel = str(rel or "").replace("\\", "/")
    src = _output_path(rel) if rel.startswith("outputs/") else _asset_path(rel)
    if not src:
        return None, "找不到底图：%s" % rel
    dest_dir = os.path.join(PART_MASK_DIR, safe_file(sku), safe_file(view), "base")
    os.makedirs(dest_dir, exist_ok=True)
    name = "base_%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), safe_file(os.path.basename(src)))
    dest = os.path.join(dest_dir, name)
    try:
        shutil.copyfile(src, dest)
    except OSError as exc:
        return None, "底图复制失败：%s" % exc
    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        return None, "底图复制后为空"
    return os.path.relpath(dest, ASSETS).replace("\\", "/"), None


def composite_roi_output(gen_rel, roi_info):
    """把 ROI 产物贴回原坐标并做确定性合成（掩膜外逐像素保留原底图）。

    返回 (最终相对路径, 合成信息, error)。原产物先改名为 *_raw.png 留档，
    便于对比「AI 原样 vs 合成后」。
    """
    if not os.path.isfile(COMPOSITE_TOOL):
        return None, None, "缺少 scripts/composite_masked.py"
    gen_abs = _output_path(gen_rel)          # 产物在 outputs/ 下，不能用 _asset_path
    src = (roi_info or {}).get("src") or {}
    base_abs = _asset_path(src.get("base") or "")
    mask_abs = _asset_path(src.get("mask") or "")
    if not gen_abs or not base_abs or not mask_abs:
        miss = [n for n, v in (("gen", gen_abs), ("base", base_abs), ("mask", mask_abs)) if not v]
        return None, None, "合成所需文件缺失：%s" % "、".join(miss)
    roi = roi_info.get("roi") or []
    if len(roi) != 4:
        return None, None, "ROI 信息不完整"
    try:
        shutil.copyfile(gen_abs, os.path.splitext(gen_abs)[0] + "_raw.png")
    except OSError as exc:
        return None, None, "保留原始产物失败：%s" % exc
    cmd = [sys.executable, COMPOSITE_TOOL, "--base", base_abs, "--mask", mask_abs,
           "--gen", gen_abs, "--out", gen_abs, "--json",
           "--bbox"] + [str(int(v)) for v in roi]
    feather = roi_info.get("feather")
    if feather:
        cmd += ["--feather", str(feather)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=180)
    except subprocess.TimeoutExpired:
        return None, None, "合成超时"
    info = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                info = json.loads(line)
                break
            except ValueError:
                continue
    if proc.returncode != 0 or not info or not info.get("ok"):
        tail = (proc.stdout + "\n" + proc.stderr).strip()[-300:]
        return None, info, "合成未通过自检：%s" % (tail or "未知错误")
    return gen_rel, info, None


def part_mask(sku, view, part, dilate=4):
    """为指定部件生成局部重绘掩膜（大纲 P0-3 掩膜接口）。

    校验链：objectid.png 与 pass_manifest.json 存在 → 部件号在索引里 → CLI 导出成功。
    用子进程跑 scripts/objectid_mask.py（同解释器），保持控制台零第三方依赖的约定；
    该工具读 16 位 objectid 需要 numpy（PIL 解 16 位会降位毁掉 ID），缺失时报可读错误。
    """
    if not sku or not view:
        return {"error": "缺少 sku 或 view"}
    try:
        part_id = int(part)
    except (TypeError, ValueError):
        return {"error": "部件号无效：%r" % part}
    oid = os.path.join(PASSES_DIR, sku, view, "objectid.png")
    man = os.path.join(PASSES_DIR, sku, view, "pass_manifest.json")
    if not os.path.isfile(oid) or not os.path.isfile(man):
        return {"error": "该机位还没有 objectid.png / pass_manifest.json，请先出结构图"}
    try:
        with open(man, "r", encoding="utf-8", errors="replace") as f:
            mapping = json.load(f).get("objectid_map") or {}
    except (OSError, ValueError) as exc:
        return {"error": "读取 pass_manifest.json 失败：%s" % exc}
    if str(part_id) not in mapping:
        return {"error": "部件 #%d 不在该机位的部件索引里（索引共 %d 项）"
                         % (part_id, len(mapping))}
    if not os.path.isfile(OBJECTID_TOOL):
        return {"error": "缺少 scripts/objectid_mask.py"}
    dest_dir = os.path.join(PART_MASK_DIR, safe_file(sku), safe_file(view))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "mask_%d.png" % part_id)
    d = max(0, min(int(dilate or 0), 32))
    try:
        proc = subprocess.run(
            [sys.executable, OBJECTID_TOOL, oid,
             "--part", str(part_id), "--dilate", str(d), "--out", dest],
            capture_output=True, text=True, errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        return {"error": "掩膜生成超时"}
    if proc.returncode != 0:
        tail = (proc.stdout + "\n" + proc.stderr).strip()[-300:]
        return {"error": "掩膜生成失败：%s" % (tail or "未知错误")}
    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        return {"error": "掩膜文件未产出"}
    info = {}
    m = re.search(r"部件 #\d+（?[^）]*）?：(\d+) 像素", proc.stdout or "")
    if m:
        info["pixels"] = int(m.group(1))
    m = re.search(r"包围盒 x (-?\d+)\.\.(-?\d+) y (-?\d+)\.\.(-?\d+)", proc.stdout or "")
    if m:
        info["bbox"] = [int(m.group(i)) for i in (1, 2, 3, 4)]
    rel = os.path.relpath(dest, ASSETS).replace("\\", "/")
    return {"ok": True, "rel": rel, "part": part_id,
            "name": mapping.get(str(part_id), ""), "dilate": d, **info}


def thumb_is_fresh(sku, model_path):
    """缩略图存在、非空，且**比模型文件新**，才算可用。

    比模型旧就说明模型换过了，得重出 —— 否则会拿旧预览糊弄用户。
    """
    t = thumb_path(sku)
    try:
        if not os.path.isfile(t) or os.path.getsize(t) == 0:
            return False
        if model_path and os.path.isfile(model_path):
            return os.path.getmtime(t) >= os.path.getmtime(model_path)
        return True
    except OSError:
        return False


def thumb_status():
    with _thumb_lock:
        return dict(_thumb_state)


def start_thumb(sku, model_rel=""):
    """后台用 Blender 出一张缩略图。

    与「出结构图」互斥：两个 Blender 同时跑会抢显存，小任务应该让路。
    """
    global _thumb_state
    model = next((m for m in scan_models() if m["sku"] == sku and
                  (not model_rel or m["rel"] == model_rel)), None)
    if not model:
        raise ValueError("投放区里没有 %s 的白模文件" % sku)
    src = os.path.abspath(model["path"])
    if os.path.splitext(src)[1].lower() not in PASS_MODEL_EXTS:
        raise ValueError("这个格式不能生成预览图；支持 BLEND/GLB/GLTF/OBJ/STL/FBX/STEP/STP/3DM")
    exe = blender_executable()
    if not exe:
        raise ValueError("未找到 Blender，无法生成预览图")
    if not os.path.isfile(BLENDER_SCRIPT):
        raise ValueError("缺少 scripts/blender_pass.py")
    if thumb_is_fresh(sku, src) and glb_is_fresh(sku, src):
        return {"ok": True, "skipped": True, "reason": "预览已是最新"}

    with _thumb_lock:
        if _thumb_state["status"] == "running":
            return {"ok": True, "skipped": True, "reason": "已有缩略图任务在跑"}
        if _pass_state["status"] == "running":
            return {"ok": True, "skipped": True, "reason": "结构图任务占用中，稍后再出预览"}
        _thumb_state = {"status": "running", "sku": sku, "message": "正在生成预览图…",
                        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "finished_at": None}

    def worker():
        global _thumb_state
        dest = thumb_path(sku)
        tmp = dest + "." + uuid.uuid4().hex + ".part.png"
        glb = glb_path(sku)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.makedirs(os.path.dirname(glb), exist_ok=True)
            args = [exe, "-b", "-P", BLENDER_SCRIPT, "--",
                    "--model", src, "--sku", sku, "--view", THUMB_VIEW,
                    "--width", str(THUMB_W), "--height", str(THUMB_H),
                    "--samples", "32",          # 预览不需要高采样
                    "--thumb", tmp,
                    "--export-glb", glb]        # 顺带导 GLB，给网页 3D 预览用
            proc = subprocess.run(args, capture_output=True, text=True,
                                  errors="replace", timeout=900)
            ok = (proc.returncode == 0 and os.path.isfile(tmp)
                  and os.path.getsize(tmp) > 0)
            if ok:
                os.replace(tmp, dest)       # 原子发布，避免半成品被前端读到
                tail = ""
            else:
                tail = (proc.stdout + "\n" + proc.stderr).strip()[-800:]
            with _thumb_lock:
                _thumb_state = {
                    "status": "done" if ok else "failed", "sku": sku,
                    "message": "预览图已生成" if ok else (tail or "Blender 执行失败"),
                    "started_at": _thumb_state.get("started_at"),
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        except Exception as exc:
            with _thumb_lock:
                _thumb_state = {"status": "failed", "sku": sku, "message": str(exc),
                                "started_at": _thumb_state.get("started_at"),
                                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "status": "running"}


def pass_status():
    with _pass_lock:
        return dict(_pass_state)


def _resolve_pass_model(sku, model_rel=""):
    """校验 SKU/白模/Blender 可用性，返回 (模型绝对路径, blender.exe)。单机位与批量共用。"""
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
    return src, exe


def _run_pass_once(sku, view, src, exe):
    """同步跑一个机位并校验产物，返回 (ok, reason)。单机位与批量队列共用。"""
    render_src = src
    # .stp/.step 优先原样交给 Blender（STEPper 直接读），STEPper 缺失且有 FreeCAD 才转缓存 STL
    if os.path.splitext(src)[1].lower() in (".stp", ".step") and not blender_has_stepper():
        render_src = convert_step(src)
    args = [exe, "-b", "-P", BLENDER_SCRIPT, "--",
            "--model", render_src, "--sku", sku, "--view", view]
    # ★ 大纲 P0-1：方位角/仰角由服务端机位表**显式**下发 —— 三份定义里 server 是权威，
    #   blender_pass.py 的内部表退化为回退/自检。
    preset = view_preset(view)
    if preset:
        args += ["--azimuth", str(preset["azimuth"]),
                 "--elevation", str(preset["elevation"])]
    started_ns = time.time_ns()
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              errors="replace", timeout=1800)
    except subprocess.TimeoutExpired:
        return False, "生成超过 30 分钟，请检查模型与 Blender 日志"
    tail = (proc.stdout + "\n" + proc.stderr).strip()[-1500:]
    ok = proc.returncode == 0
    reason = ""
    if ok:
        folder = os.path.join(PASSES_DIR, sku, view)
        for name in PASS_REQUIRED:
            path = os.path.join(folder, name)
            if not os.path.isfile(path) or os.stat(path).st_mtime_ns < started_ns:
                return False, "%s 未由本次结构图任务重新生成，请查看 Blender 日志" % name
        manifest = os.path.join(PASSES_DIR, sku, view, "pass_manifest.json")
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                meta = json.load(f)
            st = os.stat(src)
            meta["source_signature"] = {
                "rel": os.path.relpath(src, MODELS_DIR).replace("\\", "/"),
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "view": [preset["azimuth"], preset["elevation"]] if preset else None,
            }
            tmp = manifest + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp, manifest)
        except (OSError, ValueError, TypeError) as exc:
            return False, "结构图清单无法记录模型来源：%s" % exc
        # 退出码 0 不等于产物可用：逐项校验通道齐全、体积非零、尺寸一致
        ok, reason = verify_pass_outputs(sku, view)
    if not ok and not reason:
        reason = tail or "Blender 执行失败"
    return ok, reason


def start_pass(sku, view, model_rel=""):
    """后台用 Blender 给某个 SKU 的某个机位出结构 pass（clay/alpha/depth/normal/objectid）。"""
    global _pass_state
    if view not in VIEW_KEYS:
        raise ValueError("不支持的机位：%s" % view)
    src, exe = _resolve_pass_model(sku, model_rel)

    if qwen_task_running():
        raise ValueError("实验引擎（Qwen）任务正在运行。8GB 显存放不下两个 GPU 作业，"
                         "请等它完成再出结构图。")
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
            ok, reason = _run_pass_once(sku, view, src, exe)
            with _pass_lock:
                _pass_state = {"status": "done" if ok else "failed",
                               "sku": sku, "view": view,
                               "message": ("结构图已生成（clay / 深度 / 法线 三通道已校验）" if ok
                                           else (reason or "Blender 执行失败")),
                               "returncode": 0 if ok else 1,
                               "started_at": _pass_state.get("started_at"),
                               "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        except Exception as exc:
            with _pass_lock:
                _pass_state = {"status": "failed", "sku": sku, "view": view,
                               "message": str(exc), "returncode": None,
                               "started_at": _pass_state.get("started_at"),
                               "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    threading.Thread(target=worker, daemon=True).start()


def start_pass_batch(sku, model_rel="", views=None):
    """批量出结构图：**顺序**执行每个机位（大纲 P0-1）。

    8GB 显卡上同时开多个 Blender 会抢显存，所以这里是一个后台线程逐个跑，
    每个机位独立出图 + 独立 verify_pass_outputs()；部分失败不影响其余机位，
    结束后 batch.done/batch.failed 里能看清哪个成了哪个败。
    """
    global _pass_state
    views = [v for v in (views or []) if v]
    if not views:
        raise ValueError("没有指定机位")
    bad = [v for v in views if v not in VIEW_KEYS]
    if bad:
        raise ValueError("不支持的机位：%s" % ", ".join(bad))
    if len(views) != len(set(views)):
        raise ValueError("机位列表有重复")
    src, exe = _resolve_pass_model(sku, model_rel)

    if qwen_task_running():
        raise ValueError("实验引擎（Qwen）任务正在运行。8GB 显存放不下两个 GPU 作业，"
                         "请等它完成再出结构图。")
    total = len(views)
    views_label = "批量(%s)" % "、".join(views)
    with _pass_lock:
        if _pass_state["status"] == "running":
            raise ValueError("已有结构图任务在运行，请等它完成")
        _pass_state = {"status": "running", "sku": sku, "view": views_label,
                       "message": "准备批量生成 %d 个机位的结构图…" % total,
                       "returncode": None,
                       "batch": {"total": total, "index": 0, "done": [], "failed": []},
                       "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "finished_at": None}

    def worker():
        global _pass_state
        results = []
        try:
            for i, view in enumerate(views):
                with _pass_lock:
                    if not isinstance(_pass_state.get("batch"), dict):
                        _pass_state["batch"] = {"total": total, "index": 0, "done": [], "failed": []}
                    _pass_state["batch"]["index"] = i
                    _pass_state["message"] = "正在生成第 %d/%d 个机位：%s" % (i + 1, total, view)
                try:
                    ok, reason = _run_pass_once(sku, view, src, exe)
                except Exception as exc:
                    ok, reason = False, str(exc)
                results.append({"view": view, "ok": ok, "reason": reason})
            with _pass_lock:
                failed = [r for r in results if not r["ok"]]
                _pass_state = {
                    "status": "done" if not failed else "failed",
                    "sku": sku, "view": views_label,
                    "message": ("%d 个机位结构图全部生成并校验通过" % total) if not failed else
                               ("完成 %d/%d 个机位；失败：%s" % (
                                   total - len(failed), total,
                                   "；".join("%s（%s）" % (r["view"], (r["reason"] or "失败")[:90])
                                             for r in failed))),
                    "returncode": 0 if not failed else 1,
                    "batch": {"total": total, "index": total,
                              "done": [r["view"] for r in results if r["ok"]],
                              "failed": failed},
                    "started_at": _pass_state.get("started_at"),
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        except Exception as exc:
            with _pass_lock:
                _pass_state = {"status": "failed", "sku": sku, "view": views_label,
                               "message": str(exc), "returncode": None,
                               "batch": {"total": total, "index": len(results),
                                         "done": [r["view"] for r in results if r["ok"]],
                                         "failed": results},
                               "started_at": _pass_state.get("started_at"),
                               "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    threading.Thread(target=worker, daemon=True).start()


def guarded_submit(tid):
    """受控提交：结构约束模式缺深度图时**拒绝自动降级**为纯文生图（避免"以为锁了形其实没锁"）。"""
    t = task_by_id(tid)
    if not t:
        raise ValueError("任务不存在：#%s" % tid)
    payload = json.loads(t.get("payload") or "{}")
    # 实验引擎（Qwen）有自己的校验口径（见 _submit_qwen）：输入可以是产品图，
    # 也可以是该机位的白模截图 clay.png。这里先放行，避免被 SDXL 的
    # 「必须 source/ 开头」误伤（v3.5）。
    if ((payload.get("_meta") or {}).get("engine_id") or "sdxl_controlled") != "sdxl_controlled":
        return comfy_submit(tid)
    mode = (payload.get("_meta") or {}).get("mode")
    if mode == "controlled" and not _pass_exists(payload.get("depth_img")):
        raise RuntimeError("缺少当前机位的深度图，已阻止自动降级为纯文生图。请先生成/上传结构图。")
    if mode == "controlled":
        depth_path = _asset_path(payload.get("depth_img"))
        if depth_path and os.path.commonpath((os.path.abspath(PASSES_DIR), os.path.abspath(depth_path))) == os.path.abspath(PASSES_DIR):
            issue = _pass_manifest_issue(os.path.dirname(depth_path))
            if issue:
                raise RuntimeError(issue)
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

    # 会随开发改动的静态资源。图片/字体一般不变，不在此列。
    _CACHE_EXTS = (".html", ".js", ".css")

    def send_head(self):
        """静态资源补协商缓存头。

        SimpleHTTPRequestHandler 默认只发 Last-Modified，浏览器对这类响应会做
        「启发式缓存」——改完 app.js，用户界面还在跑旧版本，表现成「明明修好了，
        界面还是老样子」。这里补 no-cache：**仍走 If-Modified-Since 协商**
        （没改照样 304 省流量），只是不允许不询问就直接拿缓存。
        """
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")   # 访问 / 时补全，否则 isfile 判否、首页永远没缓存头
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in self._CACHE_EXTS:
            self._negotiated_cache = True
        return super().send_head()

    def end_headers(self):
        # 注入点必须在这里：send_head 内部就是靠调 end_headers 落盘的。
        # send_json / serve_output 自己带了 no-store，不走上面的分支。
        if getattr(self, "_negotiated_cache", False):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self._negotiated_cache = False
        super().end_headers()

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

    def serve_thumb(self, sku):
        """返回某 SKU 的缩略图。还没有就 404 —— 前端据此显示占位而不是破图。"""
        if not sku:
            return self.send_json({"error": "缺少 sku"}, 400)
        path = thumb_path(sku)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return self.send_json({"error": "还没有预览图"}, 404)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            return self.send_json({"error": "读取预览图失败：%s" % exc}, 500)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        # 缩略图会随模型更新，用协商缓存（改了立刻能看到新的，没改走 304）
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(data)

    def serve_glb(self, sku):
        """返回某 SKU 的预览模型（GLB）。还没有就 404。"""
        if not sku:
            return self.send_json({"error": "缺少 sku"}, 400)
        path = glb_path(sku)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return self.send_json({"error": "还没有预览模型"}, 404)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            return self.send_json({"error": "读取预览模型失败：%s" % exc}, 500)
        self.send_response(200)
        self.send_header("Content-Type", "model/gltf-binary")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
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
            if kind == "pass" and meta.get("role") in MANUAL_PASS_ROLES:
                _record_manual_pass(os.path.dirname(dest), meta["role"], dest)
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
            # 顺手起一个缩略图任务，让用户马上能看到「确实读进来了」。
            # 失败不影响上传结果 —— 预览只是锦上添花，不该拖累主流程。
            try:
                start_thumb(str(meta.get("sku") or ""),
                            os.path.relpath(dest, ASSETS).replace("\\", "/"))
            except Exception:
                pass
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
            if p == "/api/views":
                # 机位表（大纲 P0-1）：前端视角下拉与六视图按钮都从这里读，
                # 不再各自硬编码一份
                return self.send_json({
                    "presets": VIEW_PRESETS,
                    "renderable": VIEW_KEYS,
                    "six": [p["key"] for p in VIEW_PRESETS
                            if p.get("group") == "six" and p.get("renderable", True)],
                })
            if p == "/api/cmf":
                # 整机、部件与参数卡共用的唯一材质来源
                try:
                    return self.send_json(load_cmf_presets())
                except (OSError, ValueError) as exc:
                    return self.send_json({"presets": [], "error": str(exc)}, 500)
            if p == "/api/designs":
                # 大纲 §4：设计语言 / 布光预设（只读）。文件坏了返回空表而不是 500 ——
                # 没有设计预设时出图照常，不应因此挡住主流程。
                return self.send_json(load_design_presets())
            if p == "/api/candidates":
                # 大纲 §2 P1：候选底图版本链。局部编辑从这里挑一张已有成图当底图。
                sku_ = q.get("sku", [""])[0]
                view_ = q.get("view", [""])[0]
                return self.send_json({"sku": sku_, "view": view_,
                                       "items": list_candidates(sku_, view_)})
            if p == "/api/partcmf":
                # 大纲 §3 P1：按部件 CMF 分配。按机位分开存 —— 切机位不串位。
                sku_ = q.get("sku", [""])[0]
                view_ = q.get("view", [""])[0]
                table = load_part_cmf(sku_)
                return self.send_json({"sku": sku_, "view": view_,
                                       "items": (table.get(view_) or {}) if view_ else {},
                                       "table": table})
            if p == "/api/cmf/scheme":
                try:
                    return self.send_json(load_cmf_scheme(q.get("sku", [""])[0]))
                except (ValueError, OSError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/renderers":
                # 出图引擎注册表（v3.5，只读）：前端下拉、状态文字与禁用规则都读这里。
                # available/reason 由**服务端**探测得出，不依赖浏览器本地状态。
                return self.send_json(renderers_report())
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
                                       "import3dm": blender_has_import3dm(),
                                       "blender_script": os.path.isfile(BLENDER_SCRIPT),
                                       "project": ROOT, "ui": "2.0"})
            if p == "/api/ui/pass/status":
                return self.send_json(pass_status())
            if p == "/api/ui/thumb/status":
                return self.send_json(thumb_status())
            if p == "/api/model/thumb":
                return self.serve_thumb(q.get("sku", [""])[0])
            if p == "/api/model/glb":
                return self.serve_glb(q.get("sku", [""])[0])
            if p == "/api/model/parts":
                return self.send_json(parts_index(q.get("sku", [""])[0],
                                                  q.get("view", [""])[0]))
            if p == "/api/model/partmask":
                r = part_mask(q.get("sku", [""])[0], q.get("view", [""])[0],
                              q.get("part", [""])[0], q.get("dilate", ["4"])[0])
                return self.send_json(r, 200 if r.get("ok") else 400)
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
            if p == "/api/partcmf":
                # 大纲 §3 P1：保存一条「按部件 CMF」分配（cmf 传空 = 删除该条）
                try:
                    b = body or {}
                    table = save_part_cmf(b.get("sku"), b.get("view"), b.get("part"),
                                          b.get("cmf"), b.get("color") or "")
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                return self.send_json({"ok": True, "table": table})
            if p == "/api/cmf/scheme":
                try:
                    b = body or {}
                    if b.get("action") == "reset":
                        return self.send_json({"ok": True, **reset_cmf_scheme(b.get("sku"))})
                    if b.get("action") == "remove":
                        return self.send_json({"ok": True, **remove_cmf_assignment(
                            b.get("sku"), b.get("view"), b.get("part"))})
                    if b.get("action") == "assign_many":
                        return self.send_json({"ok": True, **save_cmf_assignments(
                            b.get("sku"), b.get("view"), b.get("parts"), b.get("cmf"), b.get("color"))})
                    return self.send_json({"ok": True, **save_cmf_assignment(
                        b.get("sku"), b.get("view"), b.get("part"), b.get("cmf"),
                        b.get("label"), b.get("color"))})
                except (ValueError, OSError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/cmf/scheme/check":
                try:
                    b = body or {}
                    views = b.get("views") or []
                    if not isinstance(views, list) or not views or len(views) > 10:
                        raise ValueError("请选择 1–10 个有效机位")
                    for view in views:
                        validate_cmf_task({"sku": b.get("sku"), "view": view},
                                          {"positive": "", "_meta": {"cmf_scheme": {
                                              "version": b.get("version"),
                                              "fingerprint": b.get("fingerprint")}}})
                    return self.send_json({"ok": True, "views": views})
                except (ValueError, RuntimeError, OSError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
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
                # R1 复审指出：这里原来无条件直连 comfy_submit()，等于留了一条
                # 「绕过 guarded_submit 结构图/模式校验」的旁路，而网页链路也在用它。
                # 现在默认走受控提交；实验脚本若确需旁路，必须显式写 ?unsafe=1 ——
                # 让旁路成为「可审计的显式选择」，而不是默认行为。
                try:
                    tid = int((body or {}).get("id"))
                    unsafe = q.get("unsafe", ["0"])[0] in ("1", "true", "yes")
                    return self.send_json(comfy_submit(tid) if unsafe else guarded_submit(tid))
                except (ValueError, RuntimeError, TypeError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/ui/pass/start":
                try:
                    start_pass(str((body or {}).get("sku", "")), str((body or {}).get("view", "")),
                               str((body or {}).get("model", "")))
                    return self.send_json({"ok": True, "status": "running"})
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/ui/pass/batch":
                # 大纲 P0-1：一次提交多个机位，后端**顺序**执行（避免多 Blender 抢显存）
                try:
                    views = (body or {}).get("views") or []
                    if isinstance(views, str):
                        views = [v.strip() for v in views.split(",") if v.strip()]
                    start_pass_batch(str((body or {}).get("sku", "")),
                                     str((body or {}).get("model", "")),
                                     [str(v) for v in views])
                    return self.send_json({"ok": True, "status": "running"})
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/ui/thumb/start":
                try:
                    return self.send_json(start_thumb(str((body or {}).get("sku", "")),
                                                      str((body or {}).get("model", ""))))
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if p == "/api/ui/comfy/submit":
                try:
                    return self.send_json(guarded_submit(int((body or {}).get("id"))))
                except (ValueError, RuntimeError, TypeError) as exc:
                    # RuntimeError 是 guarded_submit 的受控拒绝（缺深度图等），
                    # 属于用户可修正的输入问题 → 400，不是 500。
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
