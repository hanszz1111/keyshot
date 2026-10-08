"""千问高级参数仅接受经过实测/限定的组合。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import server as S  # noqa: E402


class QwenParametersTest(unittest.TestCase):
    def test_defaults_and_experimental_cfg(self):
        defaults = {"steps": 25, "cfg": 1.0}
        self.assertEqual(S.qwen_sampling_params({}, defaults), (25, 1.0))
        self.assertEqual(S.qwen_sampling_params({"steps": 40, "cfg": 1.5}, defaults), (40, 1.5))

    def test_rejects_out_of_range_and_unvalidated_cfg(self):
        defaults = {"steps": 25, "cfg": 1.0}
        for payload in ({"steps": 51}, {"steps": 7}, {"steps": "25.5"},
                        {"cfg": 3}, {"cfg": "nan"}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                S.qwen_sampling_params(payload, defaults)


if __name__ == "__main__":
    unittest.main()
