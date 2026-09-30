"""确定性 CMF 引导图：背景、分区与结构线离线回归。"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import cmf_guide  # noqa: E402


class CmfGuideTest(unittest.TestCase):
    def test_clean_background_and_part_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            ids = np.zeros((8, 8), dtype=np.uint16)
            ids[1:7, 1:4] = 1
            ids[1:7, 4:7] = 2
            clay = np.zeros((8, 8, 4), dtype=np.uint8)
            clay[ids != 0] = (220, 220, 220, 255)
            clay_path = os.path.join(folder, "clay.png")
            manifest = os.path.join(folder, "manifest.json")
            scheme = os.path.join(folder, "scheme.json")
            result = os.path.join(folder, "guide.png")
            Image.fromarray(clay, "RGBA").save(clay_path)
            with open(manifest, "w", encoding="utf-8") as stream:
                json.dump({"objectid_map": {"1": "shell", "2": "grip"}}, stream)
            with open(scheme, "w", encoding="utf-8") as stream:
                json.dump({"assignments": {"grip": {"color": "#FF0000"}}}, stream)
            with patch.object(cmf_guide, "read_ids", return_value=(8, 8, ids)):
                info = cmf_guide.make_guide(clay_path, "unused.png", manifest, scheme,
                                            "#0000FF", result)
            output = np.asarray(Image.open(result).convert("RGBA"))
            self.assertFalse(info["normal_used"])
            self.assertEqual(output[0, 0].tolist(), [243, 245, 246, 255])
            self.assertGreater(int(output[3, 2, 2]), int(output[3, 2, 0]))
            self.assertGreater(int(output[3, 5, 0]), int(output[3, 5, 2]))
            self.assertLess(int(output[3, 4, 0]), int(output[3, 5, 0]))

    def test_overexposed_clay_uses_normal_shading_and_detects_fold(self):
        with tempfile.TemporaryDirectory() as folder:
            ids = np.ones((8, 8), dtype=np.uint16)
            clay = np.full((8, 8, 4), 255, dtype=np.uint8)
            normals = np.zeros((8, 8, 3), dtype=np.uint8)
            normals[:, :4] = (128, 128, 255)  # 正面
            normals[:, 4:] = (255, 128, 128)  # 侧面，构成清晰折线
            clay_path = os.path.join(folder, "clay.png")
            normal_path = os.path.join(folder, "normal.png")
            manifest = os.path.join(folder, "manifest.json")
            result = os.path.join(folder, "guide.png")
            Image.fromarray(clay, "RGBA").save(clay_path)
            Image.fromarray(normals, "RGB").save(normal_path)
            with open(manifest, "w", encoding="utf-8") as stream:
                json.dump({"objectid_map": {"1": "shell"}}, stream)
            with patch.object(cmf_guide, "read_ids", return_value=(8, 8, ids)):
                info = cmf_guide.make_guide(clay_path, "unused.png", manifest,
                                            os.path.join(folder, "missing.json"),
                                            "#C0C0C0", result, normal_path=normal_path)
            output = np.asarray(Image.open(result).convert("RGBA"))
            self.assertTrue(info["normal_used"])
            self.assertEqual(info["clipped_foreground_pct"], 100.0)
            self.assertGreater(int(output[3, 2, 0]), int(output[3, 6, 0]))
            self.assertLess(int(output[3, 4, 0]), int(output[3, 6, 0]))

    def test_normal_size_mismatch_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            clay = np.full((4, 4, 4), 255, dtype=np.uint8)
            clay_path = os.path.join(folder, "clay.png")
            normal_path = os.path.join(folder, "normal.png")
            manifest = os.path.join(folder, "manifest.json")
            Image.fromarray(clay, "RGBA").save(clay_path)
            Image.fromarray(np.zeros((2, 2, 3), dtype=np.uint8), "RGB").save(normal_path)
            with open(manifest, "w", encoding="utf-8") as stream:
                json.dump({"objectid_map": {}}, stream)
            with patch.object(cmf_guide, "read_ids", return_value=(4, 4, np.ones((4, 4), dtype=np.uint16))):
                with self.assertRaisesRegex(ValueError, "法线与白模尺寸不一致"):
                    cmf_guide.make_guide(clay_path, "unused.png", manifest,
                                         os.path.join(folder, "missing.json"),
                                         "#C0C0C0", os.path.join(folder, "guide.png"),
                                         normal_path=normal_path)


if __name__ == "__main__":
    unittest.main()
