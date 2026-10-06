"""真材质底图的版本、机位和缓存契约（不依赖 Blender/GPU）。"""
import json
import os
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import server as S  # noqa: E402


class ProductBaseSpecTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.assets = os.path.join(self.tmp.name, "assets")
        self.passes = os.path.join(self.assets, "passes")
        folder = os.path.join(self.passes, "Demo", "front")
        os.makedirs(folder)
        with open(os.path.join(folder, "pass_manifest.json"), "w", encoding="utf-8") as stream:
            json.dump({"objectid_map": {"1": "shell", "2": "grip"},
                       "resolution": [1232, 752],
                       "camera": {"azimuth": 0, "elevation": 8, "fit": 1.18, "ortho": False}}, stream)
        self.presets = os.path.join(self.tmp.name, "cmf_presets.json")
        with open(self.presets, "w", encoding="utf-8") as stream:
            json.dump({"presets": [{"id": "plastic_fine_matte"}, {"id": "rubber_matte"}]}, stream)
        self.scheme = {"sku": "Demo", "model": "Demo.glb", "fingerprint": "model-sha",
                       "version": 3, "stale": False,
                       "assignments": {"grip": {"cmf": "rubber_matte", "color": "#222222"}}}
        for name, value in (("ASSETS", self.assets), ("PASSES_DIR", self.passes),
                            ("PRODUCT_BASE_DIR", os.path.join(self.assets, "_成品底图")),
                            ("CMF_PRESETS_PATH", self.presets)):
            patcher = patch.object(S, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (("load_cmf_scheme", lambda sku: self.scheme),
                            ("load_cmf_presets", lambda: {"presets": [
                                {"id": "plastic_fine_matte"}, {"id": "rubber_matte"}]}),
                            ("verify_pass_outputs", lambda sku, view: (True, ""))):
            patcher = patch.object(S, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_same_spec_is_stable_and_scheme_change_invalidates_it(self):
        first = S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")
        again = S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")
        self.assertEqual(first["rel"], again["rel"])
        self.assertEqual(first["resolution"], [1232, 752])
        self.assertTrue(S.qwen_input_ok(first["rel"]))
        self.scheme = {**self.scheme, "version": 4}
        changed = S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")
        self.assertNotEqual(first["rel"], changed["rel"])

    def test_invalid_mapping_and_missing_image_are_rejected(self):
        spec = S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")
        self.assertFalse(S.product_base_fresh(spec))
        self.scheme = {**self.scheme, "assignments": {"not_in_model": {"cmf": "rubber_matte", "color": "#222222"}}}
        with self.assertRaisesRegex(ValueError, "网格映射"):
            S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")

    def test_cached_png_must_match_camera_resolution(self):
        spec = S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")
        os.makedirs(os.path.dirname(spec["path"]), exist_ok=True)
        with open(spec["path"], "wb") as stream:
            stream.write(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 640, 640))
        self.assertFalse(S.product_base_fresh(spec))
        with open(spec["path"], "wb") as stream:
            stream.write(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1232, 752))
        self.assertTrue(S.product_base_fresh(spec))

    def test_blender_command_uses_manifest_camera_and_cpu(self):
        spec = S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")
        captured = {}

        def fake_run(args, **_kwargs):
            captured["args"] = args
            path = args[args.index("--product-render") + 1]
            with open(path, "wb") as stream:
                stream.write(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1232, 752))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with patch.object(S.subprocess, "run", side_effect=fake_run):
            S._run_product_base_once(spec, os.path.join(self.tmp.name, "Demo.glb"), "blender.exe")
        args = captured["args"]
        self.assertIn("--no-gpu", args)
        self.assertEqual(args[args.index("--azimuth") + 1], "0")
        self.assertEqual(args[args.index("--elevation") + 1], "8")
        self.assertEqual(args[args.index("--width") + 1], "1232")
        self.assertTrue(S.product_base_fresh(spec))

    def test_scheme_change_during_render_discards_result(self):
        spec = S.product_base_spec("Demo", "front", "plastic_fine_matte", "#AABBCC", "studio")

        def fake_run(args, **_kwargs):
            path = args[args.index("--product-render") + 1]
            with open(path, "wb") as stream:
                stream.write(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1232, 752))
            self.scheme = {**self.scheme, "version": 4}
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with patch.object(S.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "已丢弃过期底图"):
                S._run_product_base_once(spec, os.path.join(self.tmp.name, "Demo.glb"), "blender.exe")
        self.assertFalse(os.path.isfile(spec["path"]))

    def _two_specs(self):
        folder = os.path.join(self.passes, "Demo", "back")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "pass_manifest.json"), "w", encoding="utf-8") as stream:
            json.dump({"objectid_map": {"1": "shell", "2": "grip"},
                       "resolution": [1232, 752],
                       "camera": {"azimuth": 180, "elevation": 8, "fit": 1.18, "ortho": False}}, stream)
        return [S.product_base_spec("Demo", view, "plastic_fine_matte", "#AABBCC", "studio")
                for view in ("front", "back")]

    def test_two_views_share_scene_and_one_blender_process(self):
        specs = self._two_specs()
        self.assertEqual(specs[0]["scene_id"], specs[1]["scene_id"])
        calls = []

        class FakeProcess:
            def wait(self, timeout=None):
                return 0
            def poll(self):
                return 0

        def fake_popen(args, **_kwargs):
            calls.append(args)
            with open(args[args.index("--product-batch") + 1], encoding="utf-8") as stream:
                batch = json.load(stream)
            self.assertEqual([item["view"] for item in batch["views"]], ["front", "back"])
            for item in batch["views"]:
                with open(item["output"], "wb") as stream:
                    stream.write(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1232, 752))
            return FakeProcess()

        with patch.object(S.subprocess, "Popen", side_effect=fake_popen):
            S._run_product_base_scene(specs, os.path.join(self.tmp.name, "Demo.glb"), "blender.exe")
        self.assertEqual(len(calls), 1)
        self.assertIn("--no-gpu", calls[0])
        self.assertTrue(all(S.product_base_fresh(spec) for spec in specs))
        rel = S._write_product_scene_report(specs)
        self.assertEqual(S.latest_product_scene("Demo")["report"], rel)
        self.scheme = {**self.scheme, "version": 4}
        self.assertEqual(S.latest_product_scene("Demo"), {})

    def test_mixed_scene_is_rejected_before_blender(self):
        specs = self._two_specs()
        bad = {**specs[1], "scene_id": "deadbeefdeadbeef"}
        with patch.object(S.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "共享同一模型"):
                S._run_product_base_scene([specs[0], bad], "Demo.glb", "blender.exe")
            popen.assert_not_called()

    def test_batch_rejects_changed_cmf_without_publishing(self):
        specs = self._two_specs()

        class FakeProcess:
            def wait(self, timeout=None):
                return 0
            def poll(self):
                return 0

        def fake_popen(args, **_kwargs):
            with open(args[args.index("--product-batch") + 1], encoding="utf-8") as stream:
                batch = json.load(stream)
            for item in batch["views"]:
                with open(item["output"], "wb") as stream:
                    stream.write(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1232, 752))
            self.scheme = {**self.scheme, "version": 4}
            return FakeProcess()

        with patch.object(S.subprocess, "Popen", side_effect=fake_popen):
            with self.assertRaisesRegex(RuntimeError, "已丢弃"):
                S._run_product_base_scene(specs, os.path.join(self.tmp.name, "Demo.glb"), "blender.exe")
        self.assertFalse(any(os.path.isfile(spec["path"]) for spec in specs))


if __name__ == "__main__":
    unittest.main()
