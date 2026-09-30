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
                cmf_guide.make_guide(clay_path, "unused.png", manifest, scheme,
                                     "#0000FF", result)
            output = np.asarray(Image.open(result).convert("RGBA"))
            self.assertEqual(output[0, 0].tolist(), [243, 245, 246, 255])
            self.assertGreater(int(output[3, 2, 2]), int(output[3, 2, 0]))
            self.assertGreater(int(output[3, 5, 0]), int(output[3, 5, 2]))
            self.assertLess(int(output[3, 4, 0]), int(output[3, 5, 0]))


if __name__ == "__main__":
    unittest.main()
