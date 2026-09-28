#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""objectid 掩膜工具 —— 读结构图产物里的部件 ID，导出某个部件的掩膜。

背景（2026-09-28 修正）：
    IndexOB 直连 File Output 时，**原始 ID 数值**（1.0, 2.0, … 2530.0）
    会被 PNG 16 位钳制到 0–1，导致所有 ID **饱和成 65535** ——
    产物只剩 0 / 65535 两个值，等于只是一张前景掩膜。
    现在 blender_pass.py 在输出前先除以 65535，读回来乘 65535 即得真实部件号。

用法：
    # 列出各部件及其像素占比
    python objectid_mask.py assets/passes/<SKU>/<机位>/objectid.png --list

    # 导出某个部件的掩膜（黑白 PNG，白=该部件）
    python objectid_mask.py <objectid.png> --part 1781 --out mask.png

    # 按名字查部件号（名字来自 pass_manifest.json 的 objectid_map）
    python objectid_mask.py <objectid.png> --name 物体.2527 --out mask.png
"""
import argparse
import json
import os
import struct
import sys
import zlib

import numpy as np
from PIL import Image

ID_SCALE = 65535.0          # 与 blender_pass.py 的 DIVIDE 常量一致


def read_png_raw(path):
    """自己解 PNG：PIL 对 16 位 RGB(A) 会降位成 8 位，把 ID 信息毁掉。"""
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG 文件：%s" % path)
    pos, idat = 8, b""
    w = h = bd = ct = None
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        typ = d[pos + 4:pos + 8]
        body = d[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", body[:10])
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    bpp = channels * (bd // 8)
    stride = w * bpp
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    i = 0
    for y in range(h):
        f = raw[i]
        i += 1
        line = np.frombuffer(raw[i:i + stride], dtype=np.uint8).astype(np.int32).copy()
        i += stride
        if f == 1:                       # Sub
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif f == 2:                     # Up
            line = (line + prev.astype(np.int32)) & 0xFF
        elif f == 3:                     # Average
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + int(prev[x])) >> 1)) & 0xFF
        elif f == 4:                     # Paeth
            for x in range(stride):
                a = int(line[x - bpp]) if x >= bpp else 0
                b = int(prev[x])
                c = int(prev[x - bpp]) if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        out[y] = line.astype(np.uint8)
        prev = out[y]
    return w, h, bd, ct, out


def read_ids(path):
    """读 objectid.png，返回 (width, height, uint16 ID 数组)。"""
    w, h, bd, ct, raw = read_png_raw(path)
    arr = raw.reshape(h, w, -1)
    if bd == 16:
        ids = (arr[..., 0].astype(np.uint32) << 8) | arr[..., 1].astype(np.uint32)
        # 输出前除以了 65535，这里乘回来（四舍五入消掉量化误差）
        ids = np.rint(ids / ID_SCALE * ID_SCALE).astype(np.uint16)
    else:
        ids = arr[..., 0].astype(np.uint16)
    return w, h, ids


def load_name_map(png_path):
    """从同目录的 pass_manifest.json 读 「部件号 → 名字」。"""
    man = os.path.join(os.path.dirname(os.path.abspath(png_path)), "pass_manifest.json")
    if not os.path.isfile(man):
        return {}
    try:
        with open(man, "r", encoding="utf-8", errors="replace") as f:
            return (json.load(f).get("objectid_map") or {})
    except (OSError, ValueError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="objectid_mask.py",
                                 description="读 objectid.png 的部件 ID 并导出部件掩膜")
    ap.add_argument("png", help="objectid.png 路径")
    ap.add_argument("--list", action="store_true", help="列出所有部件及像素占比")
    ap.add_argument("--top", type=int, default=25, help="--list 时最多显示多少个（按面积降序）")
    ap.add_argument("--part", type=int, help="要导出的部件号")
    ap.add_argument("--name", help="按名字导出（用 pass_manifest 的 objectid_map 反查）")
    ap.add_argument("--out", help="掩膜输出路径（白=该部件，黑=其余）")
    ap.add_argument("--dilate", type=int, default=0, help="掩膜外扩像素（给 inpaint 留边）")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.png):
        print("找不到文件：%s" % args.png)
        return 2
    w, h, ids = read_ids(args.png)
    uniq, counts = np.unique(ids, return_counts=True)
    total = ids.size
    names = load_name_map(args.png)
    print("图像 %dx%d，非零部件 %d 个（ID 范围 %d..%d）"
          % (w, h, int((uniq > 0).sum()), int(uniq.min()), int(uniq.max())))

    if not names:
        print("提示：同目录没有 pass_manifest.json，无法给出部件名")

    target = args.part
    if args.name:
        for idx, nm in names.items():
            if nm == args.name:
                target = int(idx)
                break
        if target is None:
            print("按名字找不到部件：%s" % args.name)
            return 3

    if args.list or target is None:
        order = np.argsort(-counts)
        print()
        print("%-8s %-26s %10s  %s" % ("部件号", "名字", "像素", "占比"))
        shown = 0
        for k in order:
            pid = int(uniq[k])
            if pid == 0:
                continue
            if shown >= args.top:
                print("  …（其余 %d 个略）" % max(0, int((uniq > 0).sum()) - shown))
                break
            print("%-8d %-26s %10d  %.3f%%"
                  % (pid, names.get(str(pid), "(未在 manifest 中)"),
                     int(counts[k]), 100.0 * counts[k] / total))
            shown += 1
        return 0

    mask = (ids == target)
    if not mask.any():
        print("部件 #%d 在该图里没有像素" % target)
        return 4
    if args.dilate > 0:
        m = mask.copy()
        for _ in range(args.dilate):
            p = np.pad(m, 1, constant_values=False)
            m = (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
                 | p[1:-1, 1:-1] | p[:-2, :-2] | p[:-2, 2:] | p[2:, :-2] | p[2:, 2:])
        mask = m
    out = (mask.astype(np.uint8) * 255)
    ys, xs = np.nonzero(mask)
    print("部件 #%d（%s）：%d 像素，占 %.3f%%，包围盒 x %d..%d y %d..%d"
          % (target, names.get(str(target), "?"), int(mask.sum()),
             100.0 * mask.sum() / total, xs.min(), xs.max(), ys.min(), ys.max()))
    if args.out:
        Image.fromarray(out, mode="L").save(args.out)
        print("已写出掩膜：%s" % args.out)
    else:
        print("（未给 --out，不写文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
