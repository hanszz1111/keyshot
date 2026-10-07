"""Qwen CFG=1 提示词保形约束。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import server as S  # noqa: E402


class QwenPromptTest(unittest.TestCase):
    def test_cfg_one_moves_essential_constraints_to_positive(self):
        payload = {"positive": "Edit the product lighting.",
                   "negative": "extra holes, dirty background", "_meta": {}}
        S.prepare_qwen_prompt(payload, {"cfg": 1.0})
        self.assertIn("holes, controls, seams", payload["positive"])
        self.assertIn("material and colour", payload["positive"])
        self.assertIn("without stray objects", payload["positive"])
        self.assertEqual(payload["negative"], "extra holes, dirty background")
        self.assertFalse(payload["_meta"]["qwen_negative_active"])

    def test_higher_cfg_keeps_prompt_unchanged_for_ab_test(self):
        payload = {"positive": "Edit the product lighting.", "negative": "extra holes"}
        S.prepare_qwen_prompt(payload, {"cfg": 1.5})
        self.assertEqual(payload["positive"], "Edit the product lighting.")
        self.assertNotIn("_meta", payload)


if __name__ == "__main__":
    unittest.main()
