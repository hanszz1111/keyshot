#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性掩膜合成 —— 只在掩膜（含羽化边）内采用生成图，**边外逐像素保留底图**。

为什么需要它（大纲 §2 P1 / GATE）：
    inpaint 的结果**不能指望模型自觉不改非目标区域**。实测中 AI 会在掩膜外
    留下「呼吸感」重绘（改 1% 像素却动整张图），对刻度、丝印、孔位这类
    必须逐像素还原的地方是硬伤。所以合成必须由程序做，且要做在模型之外。

做法：
    out = base × (1 − α) + gen × α，α 由掩膜经羽化得到。
    掩膜为黑处 α=0 → 严格取底图原始像素（不是「接近」，是同一份字节）。
    脚本末尾会**自检**并打印「掩膜外最大像素差」，非 0 即报错退出。

用法：
    # 生成图与底图同尺寸
    python composite_masked.py --base b.png --mask m.png --gen g.png --out o.png --feather 3

    # 生成图是 ROI 局部产物，需贴回原图坐标（x0 x1 y0 y1，闭区间）
    python composite_masked.py --base b.png --mask m.png --gen g.png --out o.png \
        --bbox 120 480 300 700 --feather 4

依赖 numpy + PIL —— 与 objectid_mask.py 一致，由 ComfyUI 的 python_embeded 提供，
不给控制台本体增加依赖（始终以子进程方式调用）。
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter


def load_rgba(path):
    if not os.path.isfile(path):
        raise SystemExit("找不到文件：%s" % path)
    return Image.open(path).convert("RGBA")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="composite_masked.py",
                                 description="确定性掩膜合成（掩膜外严格保留底图）")
    ap.add_argument("--base", required=True, help="底图（未编辑区域从这里逐像素取）")
    ap.add_argument("--mask", required=True, help="掩膜（白=要采用生成图）")
    ap.add_argument("--gen", required=True, help="生成图（或 ROI 局部产物）")
    ap.add_argument("--out", required=True, help="输出 PNG")
    ap.add_argument("--feather", type=float, default=0.0, help="羽化半径（像素），0=硬边")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "X1", "Y0", "Y1"),
                    help="生成图对应的原图 ROI（闭区间）；给了就把 gen 缩放后贴回该位置")
    ap.add_argument("--json", action="store_true", help="额外输出一行 JSON 结果（给服务端解析）")
    args = ap.parse_args(argv)

    base = load_rgba(args.base)
    mask_src = Image.open(args.mask).convert("L") if os.path.isfile(args.mask) else None
    if mask_src is None:
        raise SystemExit("找不到掩膜：%s" % args.mask)
    gen = load_rgba(args.gen)

    W, H = base.size
    roi = None
    if args.bbox:
        x0, x1, y0, y1 = args.bbox
        if not (0 <= x0 <= x1 < W and 0 <= y0 <= y1 < H):
            raise SystemExit("ROI 越界：x %d..%d y %d..%d（图 %dx%d）" % (x0, x1, y0, y1, W, H))
        rw, rh = x1 - x0 + 1, y1 - y0 + 1
        if gen.size != (rw, rh):
            gen = gen.resize((rw, rh), Image.LANCZOS)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.paste(gen, (x0, y0))
        gen = canvas
        roi = [x0, x1, y0, y1]
    elif gen.size != (W, H):
        gen = gen.resize((W, H), Image.LANCZOS)

    if mask_src.size != (W, H):
        mask_src = mask_src.resize((W, H), Image.NEAREST)

    # 二值化：>127 视为「要重绘」。先二值再羽化，避免把 JPEG 噪声当梯度。
    strict = mask_src.point(lambda v: 255 if v > 127 else 0)
    if args.feather > 0:
        # ★ 羽化必须**限制在掩膜内部**：GaussianBlur 会把 α 扩散到掩膜外一圈，
        #   那一圈的像素就会被生成图混掉 —— 实测差 200/255，正是 GATE 要防的
        #   「非编辑区被改动」。这里把模糊结果乘回二值掩膜，保证掩膜外 α 严格 = 0。
        blurred = strict.filter(ImageFilter.GaussianBlur(args.feather))
        ba = np.asarray(blurred, dtype=np.float32) / 255.0
        sa = np.asarray(strict, dtype=np.float32) / 255.0
        alpha = Image.fromarray(np.rint(ba * sa * 255.0).astype(np.uint8), mode="L")
    else:
        alpha = strict

    out = Image.composite(gen, base, alpha)          # α 白处取 gen，黑处取 base

    # ---- 自检：掩膜外（二值掩膜=0 处）必须与底图逐像素相同 ----
    a = np.asarray(base, dtype=np.int16)
    b = np.asarray(out, dtype=np.int16)
    m = np.asarray(strict, dtype=np.uint8)
    outside = (m == 0)
    max_diff = 0
    outside_px = int(outside.sum())
    if outside_px:
        d = np.abs(a[outside] - b[outside])
        max_diff = int(d.max()) if d.size else 0
    inside_px = int((m > 0).sum())

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    out.save(args.out)

    print("合成完成：%dx%d  掩膜内 %d 像素 / 掩膜外 %d 像素  羽化 %.1f  底图外差异 %s"
          % (W, H, inside_px, outside_px, args.feather, "待检"))
    print("掩膜外最大像素差：%d（必须为 0）" % max_diff)
    if args.json:
        print(json.dumps({"ok": max_diff == 0, "width": W, "height": H,
                          "inside_pixels": inside_px, "outside_pixels": outside_px,
                          "outside_max_diff": max_diff, "feather": args.feather,
                          "roi": roi, "out": os.path.abspath(args.out)},
                         ensure_ascii=False))
    return 0 if max_diff == 0 else 5


if __name__ == "__main__":
    sys.exit(main())
