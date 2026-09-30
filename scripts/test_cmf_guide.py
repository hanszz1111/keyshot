#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线测试 CMF 对象 ID 配色图；运行环境需安装 numpy/Pillow。"""
import json
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

# 同 cmf_guide.py：嵌入式 Python（ComfyUI python_embeded 带 _pth）不会把脚本目录
# 放进 sys.path，这里显式补上，否则 `from cmf_guide import ...` 会 ModuleNotFoundError。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cmf_guide import make_guide  # noqa: E402


class CmfGuideTest(unittest.TestCase):
    def test_part_colours_follow_ids_and_background_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            clay = os.path.join(folder, "clay.png")
            oid = os.path.join(folder, "objectid.png")
            manifest = os.path.join(folder, "pass_manifest.json")
            scheme = os.path.join(folder, "scheme.json")
            out = os.path.join(folder, "guide.png")
            pixels = np.full((2, 3, 4), 255, dtype=np.uint8)
            pixels[0, 0] = [20, 30, 40, 0]
            Image.fromarray(pixels, "RGBA").save(clay)
            ids = np.array([[0, 1, 2], [1, 2, 2]], dtype=np.uint16)
            Image.fromarray(ids).save(oid)
            with open(manifest, "w", encoding="utf-8") as f:
                json.dump({"objectid_map": {"1": "FrontShell", "2": "Grip"}}, f)
            with open(scheme, "w", encoding="utf-8") as f:
                json.dump({"assignments": {"Grip": {"color": "#00A000"}}}, f)
            result = make_guide(clay, oid, manifest, scheme, "#A00000", out)
            rendered = np.asarray(Image.open(out).convert("RGBA"))
            self.assertEqual(result["parts"], 1)
            self.assertEqual(rendered[0, 0].tolist(), pixels[0, 0].tolist())
            self.assertGreater(int(rendered[0, 1, 0]), int(rendered[0, 1, 1]))
            self.assertGreater(int(rendered[0, 2, 1]), int(rendered[0, 2, 0]))
            self.assertEqual(rendered[..., 3].tolist(), pixels[..., 3].tolist())

    def test_missing_mapping_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            clay = os.path.join(folder, "clay.png")
            oid = os.path.join(folder, "objectid.png")
            manifest = os.path.join(folder, "pass_manifest.json")
            scheme = os.path.join(folder, "scheme.json")
            out = os.path.join(folder, "guide.png")
            Image.new("RGBA", (1, 1), "white").save(clay)
            Image.fromarray(np.array([[1]], dtype=np.uint16)).save(oid)
            with open(manifest, "w", encoding="utf-8") as f:
                json.dump({"objectid_map": {"1": "FrontShell"}}, f)
            with open(scheme, "w", encoding="utf-8") as f:
                json.dump({"assignments": {"MissingGrip": {"color": "#00A000"}}}, f)
            with self.assertRaisesRegex(ValueError, "不在当前机位"):
                make_guide(clay, oid, manifest, scheme, "#A00000", out)


if __name__ == "__main__":
    unittest.main()
