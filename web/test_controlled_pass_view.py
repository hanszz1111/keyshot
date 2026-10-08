"""受控出图不得混用其他机位的单面深度图。"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import server as S  # noqa: E402


def png_header(width, height):
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" +
            width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")


class ControlledPassViewTest(unittest.TestCase):
    def test_rejects_other_view_and_stretched_canvas(self):
        with tempfile.TemporaryDirectory() as assets:
            root = os.path.join(assets, "passes")
            with patch.object(S, "PASSES_DIR", root), patch.object(S, "ASSETS", assets):
                self.check_bundle(root)

    def check_bundle(self, root):
        for view in ("front", "3q4_left"):
            folder = os.path.join(root, "sample", view)
            os.makedirs(folder)
            for role in ("depth", "normal"):
                with open(os.path.join(folder, role + ".png"), "wb") as stream:
                    stream.write(png_header(1200, 800))
        task = {"sku": "sample", "view": "3q4_left"}
        payload = {"depth_img": "sample/front/depth.png", "width": 1200, "height": 800}
        with self.assertRaisesRegex(RuntimeError, "不属于当前产品"):
            S.validate_controlled_pass_bundle(task, payload)
        payload["depth_img"] = "sample/3q4_left/depth.png"
        payload["normal_img"] = "sample/3q4_left/normal.png"
        S.validate_controlled_pass_bundle(task, payload)
        payload["width"] = 1024
        payload["height"] = 1024
        with self.assertRaisesRegex(RuntimeError, "画幅"):
            S.validate_controlled_pass_bundle(task, payload)


if __name__ == "__main__":
    unittest.main()
