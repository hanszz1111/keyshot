# -*- coding: utf-8 -*-
"""M0 · 16 位部件 ID 解码精度回归（不依赖 Blender / GPU）。

背景（2026-10-10 更正记录）：`objectid.png` 存的是 `部件号 / 65535`，**文件是 16 位 RGBA**。
`PIL` 打开 16 位 RGBA 会**静默降成 8 位**，把 `部件号/65535×255 = 部件号/257` ——
2530 个部件被压成约 10 个「桶值」。我据此做出过两处错误结论。

因此本测试用**合成图**把解码路径钉死：
  ① 已知 ID（含 >255 与接近上限的 2530）必须**逐位准确**还原；
  ② **奇数坐标上的 1 像素**细件不能漏（抽样读法会漏掉它）；
  ③ 解码结果与 **Blender 那条同源读取路径**一致（Blender 可用时才跑）。

运行：
    python web/test_objectid_precision.py          # 纯标准库（读侧解析）
    # Blender 交叉验证由 scripts/_dump_visible.py 那类脚本外部执行
"""

import os
import struct
import sys
import tempfile
import unittest
import zlib

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import objectid_mask as OM  # noqa: E402

# ★ 用真实场景里会出现的 ID：小值、255/256 边界、以及本机最大值档
KNOWN_IDS = [1, 20, 255, 256, 1737, 1742, 2530]


def write_png16_rgba(path, ids):
    """把 uint16 的 ID 矩阵写成 16 位 RGBA PNG（非隔行、滤波全 0）。

    ★ 不能用 PIL 写：一是本项目不依赖它，二是要保证写出来的就是**真 16 位**，
      否则测的就不是解码精度了。存储值 = ID/65535×65535 = ID（与生产一致）。
    """
    h, w = ids.shape
    rows = []
    for y in range(h):
        line = bytearray()
        line.append(0)                       # filter type 0（None）
        for x in range(w):
            v = int(ids[y, x]) & 0xFFFF
            hi, lo = (v >> 8) & 0xFF, v & 0xFF
            # ★ 16 位 RGBA：R/G/B/A **各占 2 字节**，共 8 字节/像素。
            #   少写一字节会让解码器与 PIL 都拒绝（曾漏掉 alpha 的高字节）。
            line += bytes((hi, lo, hi, lo, hi, lo, 0xFF, 0xFF))
        rows.append(bytes(line))
    raw = b"".join(rows)

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 16, 6, 0, 0, 0)     # 16 位 / RGBA / 非隔行
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def build_synthetic():
    """造一张覆盖全部边界情况的 ID 图：大块 + 奇数坐标 1 像素 + 边缘件。"""
    W, H = 64, 40
    ids = np.zeros((H, W), dtype=np.uint16)
    # 每个已知 ID 占一块，位置互不重叠
    for k, i in enumerate(KNOWN_IDS):
        ids[2:8, 2 + k * 8:8 + k * 8] = i
    # ★ 奇数坐标上的 1 像素细件（抽样读法会整条漏掉）
    ids[15, 15] = 999
    ids[17, 31] = 1000
    # 图边缘的部件
    ids[0, 0] = 1111
    ids[H - 1, W - 1] = 2222
    # 被其它部件遮挡的一部分（同一 ID 分成两段）
    ids[30:33, 10:20] = 3333
    ids[30:33, 40:50] = 3333
    return ids


class ObjectIdPrecisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ids = build_synthetic()
        self.png = os.path.join(self.tmp.name, "objectid.png")
        with open(self.png, "wb") as f:
            f.write(write_png16_rgba(self.png, self.ids))

    def test_file_is_really_16_bit(self):
        """先确认夹具本身是 16 位 —— 否则下面的精度测试没有意义。"""
        with open(self.png, "rb") as f:
            head = f.read(26)
        bit_depth, color_type = head[24], head[25]
        self.assertEqual(bit_depth, 16, "夹具 PNG 必须是 16 位，实际 %s" % bit_depth)
        self.assertEqual(color_type, 6, "夹具 PNG 必须是 RGBA(color_type=6)，实际 %s" % color_type)

    def test_known_ids_decode_exactly(self):
        """★ 核心：已知 ID 必须逐位准确 —— 降位读法会把它们压成桶值。"""
        w, h, got = OM.read_ids(self.png)
        self.assertEqual((w, h), (self.ids.shape[1], self.ids.shape[0]))
        for i in KNOWN_IDS:
            self.assertEqual(int((got == i).sum()), int((self.ids == i).sum()),
                             "id=%d 的像素数不符 → 解码不准确" % i)

    def test_no_id_is_lost_or_merged(self):
        """集合必须完全一致：既不能漏，也不能把不同 ID 并成一个。"""
        w, h, got = OM.read_ids(self.png)
        self.assertEqual(sorted(int(x) for x in np.unique(got)),
                         sorted(int(x) for x in np.unique(self.ids)))

    def test_odd_coordinate_single_pixel_not_missed(self):
        """★ 奇数坐标上的 1 像素细件：抽样读法会漏，全像素读法必须在。"""
        w, h, got = OM.read_ids(self.png)
        self.assertEqual(int(got[15, 15]), 999)
        self.assertEqual(int(got[17, 31]), 1000)

    def test_edge_and_split_parts(self):
        """图边缘件、以及同一 ID 被遮挡分成两段的，都应完整保留。"""
        w, h, got = OM.read_ids(self.png)
        self.assertEqual(int(got[0, 0]), 1111)
        self.assertEqual(int(got[h - 1, w - 1]), 2222)
        self.assertEqual(int((got == 3333).sum()), int((self.ids == 3333).sum()))

    def test_max_scale_id_round_trip(self):
        """65535 附近的 ID 不应被钳制（历史上曾因直连 File Output 全饱和成 65535）。"""
        big = np.zeros((4, 4), dtype=np.uint16)
        big[0, 0] = 65534
        big[1, 1] = 65535
        p = os.path.join(self.tmp.name, "big.png")
        with open(p, "wb") as f:
            f.write(write_png16_rgba(p, big))
        w, h, got = OM.read_ids(p)
        self.assertEqual(int(got[0, 0]), 65534)
        self.assertEqual(int(got[1, 1]), 65535)

    def test_pil_would_have_lost_precision(self):
        """★ 把「为什么不能用 PIL」钉成可执行证据：若装了 Pillow，展示它会降位。"""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("未安装 Pillow，跳过（本测试本意是证明它不可用）")
        arr = np.asarray(Image.open(self.png))
        self.assertEqual(arr.dtype, np.uint8,
                         "Pillow 对 16 位 RGBA 应当降成 uint8；若这里变了，更正记录的前提需重审")
        # 1737 / 257 ≈ 6.76 → 降到 8 位后变成桶值，不再等于 1737
        self.assertNotIn(1737, [int(x) for x in np.unique(arr)],
                         "Pillow 读出的值里不该出现真实 ID 1737（应该已被压成桶值）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
