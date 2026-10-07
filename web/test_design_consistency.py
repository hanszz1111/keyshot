"""设计语言快照：同一系列不会悄悄混入修改后的预设。"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import server as S  # noqa: E402


class DesignConsistencyTest(unittest.TestCase):
    def test_signature_is_stable_and_rejects_changed_preset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "designs.json")
            data = {"negative_common": ["extra holes"], "presets": [{
                "id": "studio", "name": "影棚", "prompt": "soft key light",
                "negative": ["dirty background"], "render_style": "white",
                "render_light": "soft"}]}
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
            with patch.object(S, "DESIGN_PRESETS_PATH", path):
                signature = S.load_design_presets()["presets"][0]["signature"]
                self.assertEqual(signature, S.load_design_presets()["presets"][0]["signature"])
                payload = {"positive": "product", "negative": "blur",
                           "_meta": {"design": "studio", "design_signature": signature}}
                self.assertEqual(S.apply_design(payload)[1], None)
                self.assertIn("soft key light", payload["positive"])
                data["presets"][0]["prompt"] = "hard red light"
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump(data, stream)
                old = {"positive": "product", "negative": "blur",
                       "_meta": {"design": "studio", "design_signature": signature}}
                self.assertIn("已修改", S.apply_design(old)[1])
                self.assertEqual(old["positive"], "product")


if __name__ == "__main__":
    unittest.main()
