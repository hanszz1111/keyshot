#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""千问 A/B 受控实验批处理（2026-10-08）

对应方案：`docs/Qwen-Image-2.1-工业产品精度与画质优化方案-20261007.md` §四 P0
——「用同一输入、同一种子、同一参数」做**单变量**对照。

设计原则（每一条都对应一次真实踩坑）：

1. **不动生产**。不修改 `web/server.py` / `web/app.js`，不写控制台任务库
   （`config/tasks.db`）。本脚本直接与 ComfyUI 8190 对话，产物落
   `outputs/_AB实验/<stamp>/`（`outputs/` 已在 .gitignore 内）。
2. **复用生产代码构造工作流**：导入 `web/server.py`，调用 `load_qwen_workflow()` /
   `fill_qwen_workflow()` / `validate_cmf_task()` / `prepare_qwen_prompt()` /
   `comfy_upload()`。这样节点接线与线上完全一致，避免「实验用了一套自己写的
   接线，结论不能推广」。
3. **一次只变一个变量**。其余全部冻结并写进事实卡；每条 arm 的提示词全文
   落库，便于日后逐字复算。
4. **盲评友好**：网格图默认用代号（A/B/C）标注，代号→arm 的映射单独存
   `盲评对照.json`，避免「看到名字就偏心」。
5. **幂等**：已存在的结果直接复用，`--force` 才重跑；中断后可续跑。

用法（★ 必须用带 numpy 的解释器，因为要走 CMF 引导图）：

    set PY=F:\\AI-Renderer\\packs\\ComfyUI_windows_portable\\python_embeded\\python.exe
    %PY% scripts/qwen_ab_experiment.py --plan                 # 只看计划，不跑
    %PY% scripts/qwen_ab_experiment.py --preset smoke         # 2 张冒烟
    %PY% scripts/qwen_ab_experiment.py --preset prompt        # A/B-1 提示词 8 张
    %PY% scripts/qwen_ab_experiment.py --preset cfg           # CFG/负面词 12 张
"""

import argparse
import hashlib
import itertools
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# ★ 与 scripts/cmf_guide.py 同一个坑：嵌入式 Python 的 _pth 不会把脚本目录
#   放进 sys.path；这里显式加 web/ 才能 import server。
sys.path.insert(0, os.path.join(ROOT, "web"))
import server as S  # noqa: E402

ENGINE_ID = "qwen21_edit_local"
# 冻结的生产常量（取自 app.js 的 STYLE.studio / LIGHT.soft；两版提示词共用，非变量）
LIGHT_TEXT = "large softbox studio lighting, soft contact shadows"
STYLE_TEXT = "clean light-gray gradient studio background"
# 机位英文名（取自 app.js 的 VIEW_EN）
VIEW_EN = {
    "front": "front view", "back": "rear view",
    "3q4_left": "left three-quarter view", "3q4_right": "right three-quarter view",
    "side": "right side view", "side_left": "left side view",
    "top": "top-down view", "bottom": "bottom-up view",
    "detail_keypad": "keypad detail view", "detail_window": "transparent window detail view",
}

# ── 提示词两版 ──────────────────────────────────────────────────────────────
# 逐字取自对应版本的 web/app.js `buildPayload()`（千问分支），出处 commit 见下。
# 硬编码而非运行时读 app.js：app.js 会继续演进，而实验必须能复算当时用的文案。
#   legacy = v3.29 之前                 commit 796ad94
#   new    = v3.29 起（短指令 + 护栏）  commit c5998a2
PROMPT_VARIANTS = {
    "legacy": {
        "origin": "796ad94 (v3.29 之前)",
        "lead": "Professional product photograph of {sku}, {view_en}.",
        "linked": (
            "<image1> is the target camera and geometry, including any supplied deterministic "
            "CMF colour zones: preserve its silhouette, part count, openings, hole positions and "
            "visible sides. <image2> is the same product from another angle: transfer ONLY product "
            "identity, material placement, exact colours, texture and design language. Do not copy "
            "<image2>'s camera angle or geometry over <image1>."
        ),
        "anchor": (
            "Use the input image as the target camera and geometry; if it contains deterministic "
            "CMF colour zones, preserve their part boundaries. Preserve silhouette, part count, "
            "openings, hole positions and visible sides."
        ),
        "identity": (
            "One physical industrial product. Main body {material}, exact colour {color}, "
            "{kind} texture at {scale} scale in {direction} direction, process {process}. "
            "Keep this CMF assignment on the same physical surfaces across all camera views; "
            "never swap materials or colours between parts."
        ),
        "tail_clay": (
            "Treat the dark structural lines and colour-zone boundaries in <image1> as fixed "
            "product geometry and parting lines. Keep each line in its original location; do not "
            "add or remove seams. Photorealistic material response and sharp focus. Do not invent "
            "controls, seams, text or logos."
        ),
        "tail_pbr": (
            "<image1> is a CAD-geometry render with assigned physical materials. Preserve its "
            "product silhouette, holes, actual part boundaries and material placement; only refine "
            "plausible surface micro-detail and lighting. Never redesign the product or move a "
            "material to another part."
        ),
    },
    "new": {
        "origin": "c5998a2 (v3.29 起)",
        "lead": "Edit <image1> into a high-quality product photograph of {sku}, {view_en}.",
        "linked": (
            "<image1> fixes the target camera and geometry. <image2> shows the same product from "
            "another angle and is only a reference for product identity and CMF; keep <image1>'s view."
        ),
        "anchor": "<image1> fixes the target camera, geometry and visible part boundaries.",
        "identity": (
            "One physical industrial product. Main body: {material}, colour {color}, "
            "{kind} texture at {scale} scale in {direction} direction, process {process}. "
            "Apply this CMF to the same physical surfaces in every view."
        ),
        "tail_clay": (
            "Treat the structural lines and colour-zone boundaries in <image1> as existing parting "
            "lines. Render realistic material response and sharp focus."
        ),
        "tail_pbr": (
            "<image1> already shows assigned physical materials; refine only plausible surface "
            "micro-detail and lighting."
        ),
    },
}


class Arm(object):
    """一条实验臂 = 一组完全确定的参数。"""

    def __init__(self, key, label, variant, cfg, guard, negative, clip=None):
        self.key = key
        self.label = label
        self.variant = variant      # "legacy" | "new"
        self.cfg = cfg
        self.guard = guard          # 是否调用 prepare_qwen_prompt（CFG=1 的正向护栏）
        self.negative = negative    # 是否保留负面提示词
        self.clip = clip            # 文本编码器文件名；None = 用生产默认

    def to_dict(self):
        return {"key": self.key, "label": self.label, "variant": self.variant,
                "cfg": self.cfg, "guard": self.guard, "negative": self.negative,
                "clip": self.clip or "（生产默认）"}


def preset_arms(name):
    """实验预设。相邻两条之间**只差一个变量**，这是可比性的前提。"""
    if name == "prompt":
        # A/B-1：提示词对照（CFG、种子、输入全部不动）。
        # ★ 这里比方案原文多一条 B0：v3.29 一次改了两件事（文案变短 + 新增正向护栏），
        #   只比 A/B 的话「无差异」无法区分是哪一件在起作用。加 B0 后
        #   A→B0 只动文案、B0→B 只动护栏，两步各自单变量。
        return [
            Arm("A", "A · 旧提示词（长，v3.29 前）", "legacy", 1.0, guard=False, negative=True),
            Arm("B0", "B0 · 新提示词（短指令，无护栏）", "new", 1.0, guard=False, negative=True),
            Arm("B", "B · 新提示词（短指令 + CFG=1 护栏）", "new", 1.0, guard=True, negative=True),
        ]
    if name == "prompt2":
        # 与方案原文完全一致的两臂版（旧 vs 新），供只想要 8 张时使用
        return [
            Arm("A", "A · 旧提示词（长，v3.29 前）", "legacy", 1.0, guard=False, negative=True),
            Arm("B", "B · 新提示词（短指令 + CFG=1 护栏）", "new", 1.0, guard=True, negative=True),
        ]
    if name == "clip":
        # ★ 2×2 交互设计：文本编码器 × 提示词。
        #   假设：项目用的是 4bit 文本编码器（w4a8），而社区工作流与官方模板都用 INT8。
        #   如果 4bit 削弱了指令跟随，那么「换提示词」在 INT8 下应当比在 w4a8 下**更能撬动画面**。
        #   四条臂一律 CFG=1、不加护栏、负面词全开 —— 使「提示词」这一维只剩文案差异。
        arms = []
        for key, clip_file, clip_label in (
                ("W4A8", "qwen3vl_8b_w4a8.safetensors", "W4A8·4bit（项目现状）"),
                ("INT8", "qwen3vl_8b_int8_convrot.safetensors", "INT8·官方模板默认")):
            arms.append(Arm(key + "-A", clip_label + " + 旧长提示",
                            "legacy", 1.0, guard=False, negative=True, clip=clip_file))
            arms.append(Arm(key + "-B0", clip_label + " + 新短提示",
                            "new", 1.0, guard=False, negative=True, clip=clip_file))
        return arms
    if name == "cfg":
        # 四条臂，相邻两条只差一个变量。提示词一律用 new 的**基础版**（不加护栏），
        # 否则护栏会与 CFG 混淆。
        #   C0→C1 只动负面词（都在 CFG=1.0）—— ★ 决定性对照：
        #         官方说明 CFG=1 时负面分支不参与生成，那么 C0 与 C1 应当**几乎完全一致**。
        #   C1→C2 只动 CFG。
        #   C2→C3 只动负面词（都在 CFG=1.5）—— 若负面词在 CFG>1 真的生效，这里应非零。
        return [
            Arm("C0", "C0 · CFG1.0 无负面词（决定性对照）", "new", 1.0, guard=False, negative=False),
            Arm("C1", "C1 · CFG1.0 带负面词（按官方说明不生效）", "new", 1.0, guard=False, negative=True),
            Arm("C2", "C2 · CFG1.5 带负面词（应生效）", "new", 1.5, guard=False, negative=True),
            Arm("C3", "C3 · CFG1.5 无负面词（对照基线）", "new", 1.5, guard=False, negative=False),
        ]
    if name == "smoke":
        return preset_arms("prompt")
    raise ValueError("未知预设：%s" % name)


def build_positive(arm, ctx, view, linked):
    """按 app.js 的拼接顺序复现千问正向提示词（含生产同款的 CMF 区块）。"""
    v = PROMPT_VARIANTS[arm.variant]
    m = ctx["material"]
    parts = [
        v["lead"].format(sku=ctx["sku"], view_en=VIEW_EN.get(view, view)),
        v["linked"] if linked else v["anchor"],
        v["identity"].format(material=m["prompt"], color=ctx["color"],
                             kind=m["texture"]["kind"], scale=m["texture"]["scale"],
                             direction=m["texture"]["direction"], process=m["process"]),
        LIGHT_TEXT + ".",
        STYLE_TEXT + ".",
        v["tail_pbr"] if ctx["input_kind"] == "product_base" else v["tail_clay"],
    ]
    return " ".join(x for x in parts if x)


def production_negative_text():
    """按生产口径拼负面提示词：app.js 的 NEGATIVE 常量 + 设计库的 negative_common。

    ★ 从**真实来源**取而不是抄一份写死：负面词一旦在生产里变了，实验要能跟着变，
      否则「实验结论」会指向一个已经不存在的提示词。NEGATIVE 在 app.js 里没有
      导出，这里按常量声明处解析。
    """
    app_js = os.path.join(ROOT, "web", "app.js")
    with open(app_js, "r", encoding="utf-8") as f:
        src = f.read()
    marker = 'const NEGATIVE = "'
    start = src.index(marker) + len(marker)
    end = src.index('";', start)
    base = src[start:end]
    common = [str(x) for x in (S.load_design_presets().get("negative_common") or [])]
    return ", ".join([base] + [c for c in common if c and c not in base])


def upload_file(abs_path, host):
    """把**任意本地文件**传到 ComfyUI `/upload/image`，返回它在 input 下的文件名。

    ★ 为什么不用 `S.comfy_upload()`：那个函数走 `_asset_path()`，而它只认 `assets/`
      下的素材。第二参考（锚点产物）在 `outputs/` 下，`_asset_path()` 解析不了 ——
      实测直接抛「找不到素材」。服务端生产链路是靠 `stage_base_image()` 先搬到
      可解析的位置绕开的；实验脚本直接上传更直白，也少一次复制。
    """
    name = os.path.basename(abs_path)
    with open(abs_path, "rb") as f:
        blob = f.read()
    boundary = "----rendererab" + hashlib.md5(blob[:4096] + name.encode("utf-8")).hexdigest()
    head = ("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n" % (boundary, name)).encode("utf-8")
    tail = ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    req = urllib.request.Request(host + "/upload/image", data=head + blob + tail, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    with S._urlopen(req, timeout=90) as r:
        res = json.loads(r.read().decode("utf-8"))
    sub = res.get("subfolder") or ""
    return (sub + "/" + res["name"]) if sub else res["name"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_of(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


# ── 输入图准备 ──────────────────────────────────────────────────────────────

def resolve_input(ctx, view):
    """返回该机位的输入图 rel（相对 assets/，口径与 _asset_path 一致）。"""
    if ctx["input_kind"] == "product_base":
        spec = S.product_base_spec(ctx["sku"], view, ctx["material"]["id"], ctx["color"], "studio")
        return spec["rel"]
    if ctx["input_kind"] == "clay":
        return "%s/%s/clay.png" % (ctx["sku"], view)
    # cmf_guide：生产在 input_kind=clay 时实际送的图（服务端 make_cmf_guide 生成）
    return S.make_cmf_guide(ctx["sku"], view, {"body_color": ctx["color"], "style": "studio"})


def path_of_rel(rel):
    """把「assets 相对路径」或「项目根相对路径」都解析成真实文件路径。

    ★ 两套口径都存在：输入图是 assets 相对（`_部件/...`），而实验产物在项目根的
      `outputs/...`。`_asset_path()` 只认前者，所以这里要兜一层。
    """
    p = S._asset_path(rel)
    if p and os.path.isfile(p):
        return p
    p = os.path.join(ROOT, str(rel).replace("/", os.sep))
    if os.path.isfile(p):
        return p
    raise RuntimeError("输入图不存在：%s" % rel)


# ── 单格运行 ────────────────────────────────────────────────────────────────

def run_cell(arm, view, seed, ctx, outdir, force=False):
    cell_dir = os.path.join(outdir, arm.key)
    os.makedirs(cell_dir, exist_ok=True)
    dst = os.path.join(cell_dir, "%s_s%d.png" % (view, seed))

    # ★ 先把参数与提示词算出来，**再**判断缓存。
    #   否则重跑时「缓存命中」的格子会丢掉 prompt/cfg/negative 记录，
    #   导致最新的事实卡反而比首跑更不完整（实测踩到）。
    linked = view in ctx["linked_views"]
    positive = build_positive(arm, ctx, view, linked)
    payload = {
        "positive": positive,
        "negative": ctx["negative_text"] if arm.negative else "",
        "seed": int(seed),
        "resolution": ctx["resolution"],
        "steps": ctx["steps"],
        "cfg": arm.cfg,
        "_meta": {"ab_experiment": ctx["experiment"], "ab_arm": arm.key},
    }
    # 与生产同序：先并 CMF 部位清单，再加护栏
    S.validate_cmf_task({"sku": ctx["sku"], "view": view}, payload)
    if arm.guard:
        S.prepare_qwen_prompt(payload, {"cfg": arm.cfg})

    wf = S.load_qwen_workflow()
    wf["5"]["inputs"]["images.image_1"] = ["4", 0]
    # ★ 文本编码器覆盖（QWEN_SLOTS 里有 "clip_name" → 节点 2，且在 weight_files 之后应用，
    #   所以在这里塞进 payload 可以覆盖 render_defaults 里的默认权重）
    if arm.clip:
        payload["clip_name"] = arm.clip
    applied, skipped = S.fill_qwen_workflow(
        wf, payload, S.qwen_edit_cfg(), S.engine_cfg(ENGINE_ID)[1])

    record = {
        "arm": arm.key, "view": view, "seed": seed,
        "linked": linked,
        "second_ref": ({"rel": ctx["second_ref"], "sha256": ctx["second_ref_sha256"]}
                       if linked else {}),
        "input_rel": ctx["input_rel"][view],
        "clip_name": wf["2"]["inputs"]["clip_name"] if "2" in wf else "",
        "unet_name": wf["1"]["inputs"]["unet_name"] if "1" in wf else "",
        "prompt": wf["5"]["inputs"]["prompt"],
        "negative": wf["5"]["inputs"].get("negative_prompt", ""),
        "cfg": wf["6"]["inputs"]["cfg"], "steps": wf["6"]["inputs"]["steps"],
        "resolution": wf["5"]["inputs"]["resolution"],
        "sampler": wf["6"]["inputs"]["sampler_name"],
        "scheduler": wf["6"]["inputs"]["scheduler"],
        "negative_active": float(wf["6"]["inputs"]["cfg"]) > 1.0,
        "node5_latent_from": wf["6"]["inputs"]["latent_image"],
        "applied": applied, "skipped": skipped,
    }

    if os.path.isfile(dst) and os.path.getsize(dst) > 0 and not force:
        record.update({"status": "cached", "file": rel_of(dst), "seconds": 0,
                       "sha256": sha256_file(dst)})
        return record

    host = ctx["host"]
    wf["4"]["inputs"]["image"] = S.comfy_upload(ctx["input_rel"][view], host)
    if linked:
        ref_abs = os.path.join(ROOT, ctx["second_ref"].replace("/", os.sep))
        wf["9"] = {"class_type": "LoadImage", "inputs": {"image": upload_file(ref_abs, host)}}
        wf["5"]["inputs"]["images.image_2"] = ["9", 0]
        record["second_ref_wired"] = wf["5"]["inputs"]["images.image_2"]

    started = time.time()
    try:
        resp = S.http_json(host + "/prompt",
                           {"prompt": wf, "client_id": "ai-renderer-ab"}, timeout=180)
    except Exception as exc:
        record.update({"status": "submit_failed", "error": str(exc), "seconds": round(time.time() - started, 1)})
        return record
    if resp.get("node_errors"):
        record.update({"status": "node_errors",
                       "error": json.dumps(resp["node_errors"], ensure_ascii=False)[:600],
                       "seconds": round(time.time() - started, 1)})
        return record

    pid = resp.get("prompt_id")
    record["prompt_id"] = pid
    deadline = time.time() + ctx["timeout"]
    imgs, err = [], None
    while time.time() < deadline:
        try:
            hist = S.http_json("%s/history/%s" % (host, pid), timeout=20)
        except Exception as exc:
            err = "轮询失败：%s" % exc
            break
        if pid in hist:
            info = hist[pid]
            status = info.get("status") or {}
            if status.get("status_str") == "error":
                err = json.dumps(status.get("messages", []), ensure_ascii=False)[:600]
                break
            for out in (info.get("outputs") or {}).values():
                imgs.extend(out.get("images") or [])
            if imgs:
                break
        time.sleep(2.0)

    elapsed = round(time.time() - started, 1)
    if err:
        record.update({"status": "exec_error", "error": err, "seconds": elapsed})
        return record
    if not imgs:
        record.update({"status": "timeout_no_output", "seconds": elapsed,
                       "note": "超过 %ss 仍无产物" % ctx["timeout"]})
        return record

    im = imgs[0]
    q = urllib.parse.urlencode({"filename": im.get("filename", ""),
                                "subfolder": im.get("subfolder", "") or "",
                                "type": im.get("type", "output")})
    try:
        with S._urlopen("%s/view?%s" % (host, q), timeout=90) as r:
            data = r.read()
    except Exception as exc:
        record.update({"status": "download_failed", "error": str(exc), "seconds": elapsed})
        return record
    with open(dst, "wb") as f:
        f.write(data)
    record.update({"status": "ok", "file": rel_of(dst), "bytes": len(data),
                   "seconds": elapsed, "comfy_name": im.get("filename"),
                   "sha256": hashlib.sha256(data).hexdigest()})
    return record


# ── 锚点（第二参考）──────────────────────────────────────────────────────────

def ensure_anchor(ctx, outdir):
    """关联机位需要一个**固定**的第二参考，否则 A/B 会多出一个变量。

    这里用生产默认设置（new 变体 + 护栏）为锚点机位生成一次，之后所有 arm
    复用同一个文件，并把它写进事实卡。
    """
    if ctx["second_ref_mode"] == "none":
        return None, None
    if ctx["second_ref_mode"] != "auto":
        p = path_of_rel(ctx["second_ref_mode"])
        return ctx["second_ref_mode"], sha256_file(p)

    anchor_dir = os.path.join(outdir, "_anchor")
    os.makedirs(anchor_dir, exist_ok=True)
    view = ctx["anchor_view"]
    dst = os.path.join(anchor_dir, "%s_anchor.png" % view)
    if not (os.path.isfile(dst) and os.path.getsize(dst) > 0):
        arm = Arm("anchor", "锚点", "new", 1.0, guard=True, negative=True)
        sub = dict(ctx)
        sub["linked_views"] = set()          # 锚点自身只用第一参考
        res = run_cell(arm, view, ctx["seeds"][0], sub, anchor_dir, force=False)
        if res.get("status") not in ("ok", "cached"):
            raise RuntimeError("锚点生成失败：%s" % res.get("error") or res.get("status"))
        got = os.path.join(ROOT, res["file"].replace("/", os.sep))
        if os.path.abspath(got) != os.path.abspath(dst):
            if os.path.isfile(got):
                os.replace(got, dst)
    rel = rel_of(dst)
    return rel, sha256_file(dst)


# ── 对照网格图 ──────────────────────────────────────────────────────────────

def make_contact_sheet(arms, cells, outdir, title):
    """把同一 (机位, 种子) 的各臂并排成一张网格图，代号标注（盲评用）。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    ok = [c for c in cells if c.get("status") in ("ok", "cached") and c.get("file")]
    if not ok:
        return None
    keys = [(c["view"], c["seed"]) for c in ok]
    rows = sorted(set(keys), key=lambda t: (t[0], t[1]))
    by = {(c["view"], c["seed"], c["arm"]): c for c in ok}

    cell_w, pad, label_h, head_h = 460, 10, 26, 34
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        font_small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
        font_head = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
    except Exception:
        font = font_small = font_head = ImageFont.load_default()

    thumbs = {}
    cell_h = None
    for key in rows:
        for arm in arms:
            c = by.get((key[0], key[1], arm.key))
            if not c:
                continue
            p = os.path.join(ROOT, c["file"].replace("/", os.sep))
            im = Image.open(p).convert("RGB")
            ratio = cell_w / float(im.width)
            th = im.resize((cell_w, max(1, int(im.height * ratio))), Image.LANCZOS)
            thumbs[(key[0], key[1], arm.key)] = th
            cell_h = cell_h or th.height
    if not cell_h:
        return None

    W = pad + len(arms) * (cell_w + pad)
    H = head_h + len(rows) * (label_h + cell_h + pad)
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 8), title, fill=(20, 40, 55), font=font_head)
    for ci, arm in enumerate(arms):
        d.text((pad + ci * (cell_w + pad), head_h - 2), "臂 %s" % arm.key,
               fill=(20, 60, 90), font=font)
    y = head_h
    for key in rows:
        d.rectangle([0, y, W, y + label_h], fill=(240, 245, 248))
        d.text((pad, y + 4), "%s · seed %s" % (key[0], key[1]), fill=(30, 50, 65), font=font_small)
        y += label_h
        for ci, arm in enumerate(arms):
            th = thumbs.get((key[0], key[1], arm.key))
            if th is None:
                continue
            sheet.paste(th, (pad + ci * (cell_w + pad), y))
        y += cell_h + pad
    dst = os.path.join(outdir, "对照网格-%s.png" % title.replace(" ", "_"))
    sheet.save(dst)
    return rel_of(dst)


def analyze_differences(arms, cells, outdir):
    """客观差异量化：**臂间差异 vs 种子噪声基线**。

    ★ 为什么必须带基线：只说「A 与 B 的 MAE 是 2.2」没有意义 —— 得知道
      「同一臂只换个种子」会差多少，才能判断 2.2 算大还是算小。
      实测（AI渲染1 / front / 768 / 25 步）：同种子换臂 MAE ≈ 1.7–1.9，
      而同臂换种子 MAE ≈ 8.5–9.2 —— 提示词的效应比采样噪声小 3–8 倍。
      这说明在该配置下「改提示词」几乎不是有效的控制手段。

    ★ 本函数只回答「改了多少像素」，**不回答「变好还是变坏」**。方向必须靠
      人工 0–2 分（方案 §五）；MAE 小不等于没问题（一个孔位的增删是局部大差异，
      会被「差异像素占比」这一列捕捉到）。

    ★★ 必须比**解码后的像素**，不能比文件哈希：ComfyUI 的 SaveImage 会把整个
      提示词写进 PNG 的 `prompt` 元数据，所以两图即使像素完全相同，文件字节也
      不同（实测 CFG=1 下有无负面词：像素 100% 相同，SHA256 却不同）。
      比文件哈希会得出「两者有差异」的**错误结论**。
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return {"skipped": "缺少 numpy/Pillow，请用 ComfyUI 的 python_embeded 运行"}

    def load(cell):
        p = os.path.join(ROOT, cell["file"].replace("/", os.sep))
        if not os.path.isfile(p):
            return None
        return np.asarray(Image.open(p).convert("RGB"))

    ok = {(c["view"], c["seed"], c["arm"]): c
          for c in cells if c.get("status") in ("ok", "cached") and c.get("file")}
    keys = sorted({(v, s) for (v, s, _a) in ok})

    def pair(x, y):
        a, b = load(x), load(y)
        if a is None or b is None:
            return None
        if a.shape != b.shape:
            return {"note": "尺寸不同 %s vs %s" % (a.shape, b.shape)}
        identical = bool(np.array_equal(a, b))
        d = np.abs(a.astype(np.int16) - b.astype(np.int16)).mean(axis=2)
        return {"mae": round(float(d.mean()), 2),
                "diff_ratio": round(float((d > 12).mean() * 100), 1),
                "pixel_identical": identical}

    pairwise = []
    for view, seed in keys:
        for x, y in itertools.combinations([a.key for a in arms], 2):
            r = pair(ok[(view, seed, x)], ok[(view, seed, y)])
            if r:
                pairwise.append(dict(r, view=view, seed=seed, a=x, b=y, kind="臂间"))

    noise = []
    seeds = sorted({s for (_v, s) in keys})
    for view, _seed in keys:
        if len(seeds) < 2:
            break
        for arm in [a.key for a in arms]:
            if (view, seeds[0], arm) in ok and (view, seeds[1], arm) in ok:
                r = pair(ok[(view, seeds[0], arm)], ok[(view, seeds[1], arm)])
                if r:
                    noise.append(dict(r, view=view, seed="%s→%s" % (seeds[0], seeds[1]),
                                      a=arm, b=arm, kind="种子噪声"))

    def avg(items):
        vals = [i["mae"] for i in items if "mae" in i]
        return round(sum(vals) / len(vals), 2) if vals else None

    a_arm, a_noise = avg(pairwise), avg(noise)
    result = {
        "pairwise": pairwise, "seed_noise": noise,
        "avg_arm_effect": a_arm, "avg_seed_noise": a_noise,
        "note": ("MAE 越小表示两图越接近。判读方法：把『臂间』与『种子噪声』比 —— "
                 "臂间若明显小于种子噪声，说明该变量对画面的作用小于随机采样。"
                 "本函数不判断好坏，方向由人工 0–2 分给出。"),
    }
    if a_arm is not None and a_noise:
        result["arm_over_noise"] = round(a_arm / a_noise, 3)
    return result


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(prog="qwen_ab_experiment.py",
                                 description="千问 A/B 受控实验批处理（不写生产任务库）")
    ap.add_argument("--preset", default="prompt",
                    choices=["prompt", "prompt2", "cfg", "clip", "smoke"])
    ap.add_argument("--sku", default="AI渲染1")
    ap.add_argument("--views", default="", help="逗号分隔；默认按预设（prompt*/cfg=front,3q4_left；smoke=front）")
    ap.add_argument("--seeds", default="", help="逗号分隔；smoke 默认 43")
    ap.add_argument("--resolution", type=int, default=768)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--input", dest="input_kind", default="cmf_guide",
                    choices=["cmf_guide", "clay", "product_base"])
    ap.add_argument("--cmf", default="plastic_fine_matte", help="主体 CMF 预设 id")
    ap.add_argument("--color", default="", help="主体颜色，留空取预设默认")
    ap.add_argument("--second-ref", default="auto",
                    help="关联机位的第二参考：auto=现场生成一次并复用 / none / <assets 相对路径>")
    ap.add_argument("--timeout", type=float, default=900, help="单张最长等待秒数")
    ap.add_argument("--outdir", default="", help="留空 = outputs/_AB实验/<时间戳>")
    ap.add_argument("--force", action="store_true", help="重跑已存在的格子")
    ap.add_argument("--plan", action="store_true", help="只打印计划，不提交任何任务")
    args = ap.parse_args(argv)

    # 口径与生产一致（服务端 _submit_qwen 里同样的两条校验），提前挡住无效参数
    _q = S.qwen_edit_cfg()
    if not (_q.get("resolution_min", 512) <= args.resolution <= _q.get("resolution_max", 1536)):
        raise SystemExit("分辨率预算须在 %s–%s" % (_q.get("resolution_min", 512), _q.get("resolution_max", 1536)))
    if args.resolution % 32:
        raise SystemExit("分辨率预算须为 32 的倍数（当前 %d）" % args.resolution)
    if not 8 <= args.steps <= 50:
        raise SystemExit("步数须在 8–50（当前 %d）" % args.steps)

    if args.preset == "smoke":
        views = args.views or "front"
        seeds = [int(x) for x in (args.seeds or "43").split(",") if x.strip()]
    else:
        views = args.views or "front,3q4_left"
        seeds = [int(x) for x in (args.seeds or "43,1234").split(",") if x.strip()]
    views = [v.strip() for v in views.split(",") if v.strip()]

    presets = {p["id"]: p for p in S.load_cmf_presets()["presets"]}
    if args.cmf not in presets:
        raise SystemExit("未知 CMF 预设：%s" % args.cmf)
    material = presets[args.cmf]
    color = args.color or material["color"]

    _eid, ecfg, eerr = S.engine_cfg(ENGINE_ID)
    if eerr:
        raise SystemExit("引擎不可用：%s" % eerr)
    ok, why, detail = S.engine_ready(ENGINE_ID)
    if not ok:
        raise SystemExit("引擎未就绪：%s" % why)

    scheme = S.load_cmf_scheme(args.sku)
    if scheme.get("stale"):
        raise SystemExit("SKU %s 的 CMF 方案已过期，请先在网页重新核对部位" % args.sku)

    arms = preset_arms(args.preset)
    # ★ 前置校验：引用的文本编码器必须真实存在。
    #   否则会跑到第 N 格才由 ComfyUI 报 node_errors，白等一轮。
    for arm in arms:
        if not arm.clip:
            continue
        found = S.comfy_models("CLIPLoader", "clip_name", S.engine_host(ENGINE_ID)) or []
        if arm.clip not in found:
            raise SystemExit("配置引用的文本编码器不存在：%s\n  可用：%s"
                             % (arm.clip, [x for x in found if "qwen" in x.lower()] or found))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # ★ 默认目录**按预设稳定**（不带时间戳）：脚本幂等，重复运行只补缺的格子 ——
    #   这样中断可续跑，「跑完 2 臂后想再加一条臂」也不必重算已有结果。
    #   每次运行另存一份带时间戳的事实卡，避免覆盖历史。
    outdir = os.path.join(ROOT, args.outdir.replace("/", os.sep)) if args.outdir \
        else os.path.join(ROOT, "outputs", "_AB实验", args.preset)
    os.makedirs(outdir, exist_ok=True)

    negative_text = production_negative_text()

    ctx = {
        "experiment": args.preset, "sku": args.sku, "seeds": seeds,
        "resolution": args.resolution, "steps": args.steps,
        "input_kind": args.input_kind, "material": material, "color": color,
        "negative_text": negative_text, "host": detail.get("host") or ecfg.get("comfy_host"),
        "timeout": args.timeout,
        "linked_views": {v for v in views if v != "front"},
        "anchor_view": "front" if "front" in views else views[0],
        "second_ref_mode": args.second_ref, "second_ref": "", "second_ref_sha256": "",
        "input_rel": {},
    }
    for v in views:
        ctx["input_rel"][v] = resolve_input(ctx, v)

    # 事实卡：先把冻结项写下来，即使中途失败也有据可查
    facts = {
        "schema": "qwen-ab-fact-card/v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "preset": args.preset, "stamp": stamp,
        "engine": {"id": ENGINE_ID, "host": ctx["host"],
                   "weight_files": ecfg.get("weight_files")},
        "qwen_defaults": S.qwen_edit_cfg(),
        "frozen": {
            "sku": args.sku, "views": views, "seeds": seeds,
            "resolution_budget": args.resolution, "steps": args.steps,
            "sampler": S.qwen_edit_cfg().get("sampler_name"),
            "scheduler": S.qwen_edit_cfg().get("scheduler"),
            "denoise": S.qwen_edit_cfg().get("denoise"),
            "light_text": LIGHT_TEXT, "style_text": STYLE_TEXT,
            "cmf_preset": material["id"], "color": color,
            "cmf_scheme_version": scheme["version"],
            "cmf_scheme_fingerprint": scheme["fingerprint"],
            "cmf_parts": len(scheme.get("assignments") or {}),
            "input_kind": args.input_kind,
            "negative_text": negative_text,
        },
        "input_images": {},
    }
    for v in views:
        p = path_of_rel(ctx["input_rel"][v])
        facts["input_images"][v] = {"rel": ctx["input_rel"][v],
                                    "sha256": sha256_file(p),
                                    "width_height": list(S._png_size(p) or [])}
    facts["prompt_variants"] = {k: PROMPT_VARIANTS[k] for k in {a.variant for a in arms}}
    facts["arms"] = [a.to_dict() for a in arms]

    print("=" * 78)
    print("千问 A/B 受控实验 · 预设 %s" % args.preset)
    print("=" * 78)
    print("输出目录 : %s" % rel_of(outdir))
    print("引擎     : %s @ %s" % (ENGINE_ID, ctx["host"]))
    print("SKU      : %s（CMF 方案 v%s，%d 个部位）" % (args.sku, scheme["version"], facts["frozen"]["cmf_parts"]))
    print("机位×种子: %s × %s" % (views, seeds))
    print("冻结参数 : %d 像素预算 / %d 步 / CFG 由各臂指定 / 输入=%s"
          % (args.resolution, args.steps, args.input_kind))
    print("主体材质 : %s %s" % (material["name"], color))
    for v in views:
        print("输入图   : %s → %s" % (v, facts["input_images"][v]["rel"]))
    print("臂       :")
    for a in arms:
        print("   %-3s CFG=%-4s 护栏=%-5s 负面词=%-5s 变体=%s"
              % (a.key, a.cfg, a.guard, a.negative, a.variant))
    total = len(arms) * len(views) * len(seeds)
    print("合计     : %d 张" % total)
    print("=" * 78)

    if args.plan:
        # 打印一条臂的完整提示词，方便肉眼核对（不提交）
        a = arms[0]
        for v in views:
            pos = build_positive(a, ctx, v, v in ctx["linked_views"])
            print("\n[臂 %s / %s] 正向提示词（未含 CMF 区块与护栏）：\n%s" % (a.key, v, pos))
        print("\n--plan：未提交任何任务。")
        return 0

    # 关联机位需要固定第二参考
    if ctx["linked_views"]:
        rel, digest = ensure_anchor(ctx, outdir)
        ctx["second_ref"], ctx["second_ref_sha256"] = rel, digest
        facts["second_reference"] = {"rel": rel, "sha256": digest,
                                     "note": "关联机位的第二参考；所有臂复用同一文件以保证单变量"}
        print("第二参考 : %s" % rel)

    cells = []
    done = 0
    for view in views:
        for seed in seeds:
            for arm in arms:
                res = run_cell(arm, view, seed, ctx, outdir, force=args.force)
                cells.append(res)
                done += 1
                mark = {"ok": "OK ", "cached": "缓存"}.get(res.get("status"), "失败")
                extra = res.get("error") or ""
                print("  [%2d/%2d] %-3s %-9s s%-6s %s %ss %s"
                      % (done, total, arm.key, view, seed, mark,
                         res.get("seconds", 0), extra[:110]))

    facts["cells"] = cells
    # ★ 缓存格子的耗时是 0；若直接写盘，重跑会把上一次的真实耗时**抹掉**。
    #   这里从既有事实卡继承历史耗时，并保留每次运行的摘要（只增不减）。
    prior = {}
    prior_path = os.path.join(outdir, "事实卡.json")
    if os.path.isfile(prior_path):
        try:
            with open(prior_path, "r", encoding="utf-8") as f:
                prior = json.load(f)
        except (OSError, ValueError):
            prior = {}
    prev_cells = {(c.get("arm"), c.get("view"), c.get("seed")): c
                  for c in (prior.get("cells") or []) if isinstance(c, dict)}
    for c in cells:
        if c.get("status") == "cached" and not c.get("seconds"):
            old = prev_cells.get((c.get("arm"), c.get("view"), c.get("seed")))
            if old and old.get("seconds"):
                c["seconds"] = old["seconds"]
                c["seconds_source"] = "继承自上一次运行"
    history = list(prior.get("run_history") or [])
    history.append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "ok": sum(1 for c in cells if c.get("status") == "ok"),
        "cached": sum(1 for c in cells if c.get("status") == "cached"),
        "failed": sum(1 for c in cells if c.get("status") not in ("ok", "cached")),
    })
    facts["run_history"] = history
    facts["summary"] = {
        "total": len(cells),
        "ok": sum(1 for c in cells if c.get("status") == "ok"),
        "cached": sum(1 for c in cells if c.get("status") == "cached"),
        "failed": sum(1 for c in cells if c.get("status") not in ("ok", "cached")),
        "total_seconds": round(sum(c.get("seconds") or 0 for c in cells), 1),
    }
    facts["difference_analysis"] = analyze_differences(arms, cells, outdir)
    # 盲评对照：代号 → 臂，与网格图一起给出，但**图上只写代号**
    facts["blind_map"] = {a.key: a.label for a in arms}
    for name in ("事实卡.json", "事实卡-%s.json" % stamp):
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
            json.dump(facts, f, ensure_ascii=False, indent=2)
    with open(os.path.join(outdir, "盲评对照.json"), "w", encoding="utf-8") as f:
        json.dump(facts["blind_map"], f, ensure_ascii=False, indent=2)

    sheet = make_contact_sheet(arms, cells, outdir, "%s-%s" % (args.preset, stamp))
    print("-" * 78)
    print("完成：成功 %d / 缓存 %d / 失败 %d，合计 %ss"
          % (facts["summary"]["ok"], facts["summary"]["cached"],
             facts["summary"]["failed"], facts["summary"]["total_seconds"]))
    da = facts["difference_analysis"]
    if da.get("avg_arm_effect") is not None:
        print("差异量化：臂间 MAE 均值 %.2f ｜ 种子噪声 MAE 均值 %.2f ｜ 臂间/噪声 = %s"
              % (da["avg_arm_effect"], da["avg_seed_noise"], da.get("arm_over_noise")))
        print("          （比值明显小于 1 = 该变量的画面作用小于随机采样；")
        print("            这不判断好坏，方向请按打分表人工评 0–2 分）")
    elif da.get("skipped"):
        print("差异量化：%s" % da["skipped"])
    print("事实卡 : %s" % rel_of(os.path.join(outdir, "事实卡.json")))
    if sheet:
        print("对照网格: %s" % sheet)
    print("打分表 : %s" % rel_of(write_score_sheet(arms, cells, outdir, args.preset)))
    return 0 if facts["summary"]["failed"] == 0 else 1


def write_score_sheet(arms, cells, outdir, preset):
    """生成 0–2 分打分表（方案 §五 的验收口径）。"""
    header = ["臂代号", "机位", "种子", "结构与方向(0-2)", "CMF归属(0-2)",
              "材料可信度(0-2)", "背景光照(0-2)", "视觉主次(0-2)", "失败位置备注"]
    rows = [",".join(header)]
    for c in cells:
        if c.get("status") not in ("ok", "cached"):
            continue
        rows.append(",".join([c["arm"], c["view"], str(c["seed"]), "", "", "", "", "", ""]))
    dst = os.path.join(outdir, "打分表-%s.csv" % preset)
    with open(dst, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(rows) + "\n")
    return dst


if __name__ == "__main__":
    sys.exit(main())
