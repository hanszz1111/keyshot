#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B 实验脚本的方法学契约（2026-10-08）

为什么值得单测：`scripts/qwen_ab_experiment.py` 的全部价值在于**一次只变一个变量**。
arm 之间多出一个变量的差异肉眼看不出来，但会让整轮实验的结论不可归因 ——
这正是本项目反复踩到的那一类缺陷（「写了但没生效」「改了但分不清是哪一处」）。
所以把「相邻臂只差一个字段」钉成断言。

只依赖标准库：脚本本身与 server.py 顶层都只用标准库（PIL 在函数内延迟导入），
因此托管 Python 即可运行，不需要 numpy。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import qwen_ab_experiment as A  # noqa: E402


def diff_fields(x, y):
    """返回两个 arm 之间**不同**的字段名集合。"""
    return {k for k in ("variant", "cfg", "guard", "negative", "clip", "shift", "cache", "unet", "steps", "lora")
            if getattr(x, k) != getattr(y, k)}


class ArmComparabilityTest(unittest.TestCase):
    def test_prompt_preset_decomposes_into_two_single_variable_steps(self):
        """A→B0 只动文案；B0→B 只动护栏。

        v3.29 一次改了两件事（文案变短 + 新增正向护栏）。只比 A/B 的话，
        「无差异」无法区分是哪一件在起作用，所以必须能把两步拆开。
        """
        arms = {a.key: a for a in A.preset_arms("prompt")}
        self.assertEqual(set(arms), {"A", "B0", "B"})
        self.assertEqual(diff_fields(arms["A"], arms["B0"]), {"variant"})
        self.assertEqual(diff_fields(arms["B0"], arms["B"]), {"guard"})

    def test_prompt2_matches_the_written_plan(self):
        """prompt2 是方案原文的两臂版（旧 vs 新），保留以便只跑 8 张。"""
        arms = {a.key: a for a in A.preset_arms("prompt2")}
        self.assertEqual(set(arms), {"A", "B"})
        self.assertEqual(arms["A"].variant, "legacy")
        self.assertFalse(arms["A"].guard)
        self.assertEqual(arms["B"].variant, "new")
        self.assertTrue(arms["B"].guard)

    def test_cfg_preset_isolates_cfg_and_negative(self):
        """四条臂，相邻两条只差一个变量。

        C0→C1 只动负面词（CFG=1.0）—— 这是**决定性对照**：若官方「CFG=1 时负面
        分支不参与生成」成立，两张图应当几乎完全一致。
        C1→C2 只动 CFG。
        C2→C3 只动负面词（CFG=1.5）—— 若负面词在 CFG>1 生效，这里应非零。
        提示词必须全程一致（都用 new 基础版、都不加护栏），否则 CFG 不是唯一变量。
        """
        arms = {a.key: a for a in A.preset_arms("cfg")}
        self.assertEqual(set(arms), {"C0", "C1", "C2", "C3"})
        self.assertEqual(diff_fields(arms["C0"], arms["C1"]), {"negative"},
                         "C0→C1 必须只差负面词，才能证明 CFG=1 下它是否生效")
        self.assertEqual(diff_fields(arms["C1"], arms["C2"]), {"cfg"})
        self.assertEqual(diff_fields(arms["C2"], arms["C3"]), {"negative"})
        self.assertEqual(arms["C1"].cfg, arms["C0"].cfg,
                         "C0/C1 必须在同一 CFG 下比较")
        self.assertEqual(arms["C2"].cfg, arms["C3"].cfg,
                         "C2/C3 必须在同一 CFG 下比较")
        for a in arms.values():
            self.assertEqual(a.variant, "new")
            self.assertFalse(a.guard, "CFG 实验里不允许带护栏，否则与 CFG 混淆")

    def test_clip_preset_is_a_clean_2x2(self):
        """文本编码器 × 提示词 的 2×2。

        要能同时回答两个问题：
          - 只换 CLIP（同提示词）会怎样        → 看 clip 维度
          - 同一 CLIP 下换提示词影响多大      → 看 variant 维度
        并且四条臂必须同 CFG、同护栏设置，否则交互项会被污染。
        """
        arms = {a.key: a for a in A.preset_arms("clip")}
        self.assertEqual(set(arms), {"W4A8-A", "W4A8-B0", "INT8-A", "INT8-B0"})
        # 只换 CLIP：同提示词、其余全同
        self.assertEqual(diff_fields(arms["W4A8-A"], arms["INT8-A"]), {"clip"})
        self.assertEqual(diff_fields(arms["W4A8-B0"], arms["INT8-B0"]), {"clip"})
        # 只换提示词：同 CLIP、其余全同
        self.assertEqual(diff_fields(arms["W4A8-A"], arms["W4A8-B0"]), {"variant"})
        self.assertEqual(diff_fields(arms["INT8-A"], arms["INT8-B0"]), {"variant"})
        # 交互项要干净：CFG 与护栏必须四条一致
        for a in arms.values():
            self.assertEqual(a.cfg, 1.0)
            self.assertFalse(a.guard, "加了护栏就没法把差异归因到文案本身")
            self.assertTrue(a.negative)
        self.assertEqual({a.variant for a in arms.values()}, {"legacy", "new"})

    def test_clip_preset_names_real_files(self):
        """臂里写的必须是真实的权重文件名，不能是占位串。"""
        for a in A.preset_arms("clip"):
            self.assertTrue(a.clip and a.clip.endswith(".safetensors"),
                            "每条臂都必须指定 .safetensors 文件名：%s" % a.key)

    def test_shift_preset_changes_only_shift(self):
        """P2：只比内置 shift 与显式 3.1，不得同时动别的东西（方案明确要求）。"""
        arms = {a.key: a for a in A.preset_arms("shift")}
        self.assertEqual(set(arms), {"S-builtin", "S-3.1"})
        self.assertIsNone(arms["S-builtin"].shift, "基线臂不应插 ModelSamplingAuraFlow")
        self.assertEqual(arms["S-3.1"].shift, 3.1)
        self.assertEqual(diff_fields(arms["S-builtin"], arms["S-3.1"]), {"shift"})
        for a in arms.values():
            self.assertEqual(a.variant, "new")
            self.assertEqual(a.cfg, 1.0)
            self.assertFalse(a.guard)
            self.assertIsNone(a.clip, "P2 不允许同时换文本编码器")
            self.assertIsNone(a.cache)

    def test_cache_preset_changes_only_cache(self):
        """P3：只比 QwenImage21Cache 关闭 / CPU / CPU+INT8。"""
        arms = {a.key: a for a in A.preset_arms("cache")}
        self.assertEqual(set(arms), {"K-off", "K-cpu", "K-cpu8"})
        self.assertIsNone(arms["K-off"].cache)
        self.assertEqual(arms["K-cpu"].cache, ("cpu", "default"))
        self.assertEqual(arms["K-cpu8"].cache, ("cpu", "int8"))
        self.assertEqual(diff_fields(arms["K-off"], arms["K-cpu"]), {"cache"})
        self.assertEqual(diff_fields(arms["K-cpu"], arms["K-cpu8"]), {"cache"})
        for a in arms.values():
            self.assertEqual(a.cfg, 1.0)
            self.assertIsNone(a.shift, "P3 不允许同时改 shift")
            self.assertIsNone(a.clip)

    def test_patch_classes_reports_what_will_be_inserted(self):
        """前置校验靠这个函数决定要查哪些节点，漏了就会跑到一半才失败。"""
        self.assertEqual(A._patch_classes(A.Arm("x", "x", "new", 1.0, False, True)), [])
        self.assertEqual(A._patch_classes(A.Arm("x", "x", "new", 1.0, False, True, shift=3.1)),
                         ["ModelSamplingAuraFlow"])
        self.assertEqual(A._patch_classes(A.Arm("x", "x", "new", 1.0, False, True,
                                                cache=("cpu", "int8"))),
                         ["QwenImage21Cache"])

    def test_viggle_preset_pairs_model_with_its_step_count(self):
        """P5：Viggle 6 步模型与步数是**配套**的。

        该模型是为 6 步蒸馏的，拿它跑 25 步没有意义；因此
        「基线 25 步 vs viggle 6 步」虽然是两处改动，但它们是同一件事。
        另加一条「viggle 模型跑 25 步」用于把「换模型」与「减步数」分开诊断。
        """
        arms = {a.key: a for a in A.preset_arms("viggle")}
        self.assertEqual(set(arms), {"V-base25", "V-viggle6", "V-viggle25"})
        b, v6, v25 = arms["V-base25"], arms["V-viggle6"], arms["V-viggle25"]
        self.assertIsNone(b.unet, "基线臂不该换主模型")
        self.assertIsNone(b.steps, "基线臂步数应跟随命令行（25）")
        self.assertEqual(v6.unet, "Qwen-Image-2.1-viggle-turbo-v0.3-6step-int8_convrot.safetensors")
        self.assertEqual(v6.steps, 6)
        self.assertEqual(v25.unet, v6.unet, "诊断臂必须用同一个模型，只差步数")
        self.assertEqual(v25.steps, 25)
        # 「换模型」单独看：v6 与 v25 只差 steps
        self.assertEqual(diff_fields(v6, v25), {"steps"})
        # 其余维度必须一致，否则归因不干净
        for a in arms.values():
            self.assertEqual((a.variant, a.cfg, a.guard, a.negative), ("new", 1.0, False, True))
            self.assertIsNone(a.clip)
            self.assertIsNone(a.shift)
            self.assertIsNone(a.cache)

    def test_all_presets_have_unique_keys(self):
        for name in ("prompt", "prompt2", "cfg", "clip", "shift", "shiftx", "cache", "viggle", "lora"):
            keys = [a.key for a in A.preset_arms(name)]
            self.assertEqual(len(keys), len(set(keys)), "预设 %s 的臂代号必须唯一" % name)

    def test_unknown_preset_fails_loudly(self):
        with self.assertRaises(ValueError):
            A.preset_arms("no_such_preset")


class PromptTextTest(unittest.TestCase):
    def ctx(self):
        return {
            "sku": "样例", "color": "#3a4148", "input_kind": "cmf_guide",
            "material": {"id": "plastic_fine_matte", "prompt": "fine-grain matte ABS plastic",
                         "process": "注塑模具细砂纹",
                         "texture": {"kind": "fine_grain", "scale": "fine",
                                     "direction": "isotropic"}},
        }

    def build(self, variant, linked, guard_arm=False, input_kind="cmf_guide"):
        arm = A.Arm("T", "测试", variant, 1.0, guard=guard_arm, negative=True)
        ctx = self.ctx()
        ctx["input_kind"] = input_kind
        return A.build_positive(arm, ctx, "3q4_left" if linked else "front", linked)

    def test_new_variant_uses_edit_instruction(self):
        text = self.build("new", linked=False)
        self.assertIn("Edit <image1> into a high-quality product photograph", text)
        self.assertNotIn("Professional product photograph of", text)

    def test_legacy_variant_uses_photograph_instruction(self):
        text = self.build("legacy", linked=False)
        self.assertIn("Professional product photograph of", text)

    def test_linked_view_mentions_second_reference_in_both_variants(self):
        for variant in ("legacy", "new"):
            text = self.build(variant, linked=True)
            self.assertIn("<image2>", text, "关联机位必须说明第二参考的作用（%s）" % variant)
            self.assertIn("<image1>", text)

    def test_new_linked_clause_forbids_copying_the_anchor_camera(self):
        """v3.29 的重点之一：第二参考只给身份/CMF，不许把主视图相机带过来。"""
        text = self.build("new", linked=True)
        self.assertIn("keep <image1>'s view", text)

    def test_anchor_view_never_mentions_second_reference(self):
        for variant in ("legacy", "new"):
            self.assertNotIn("<image2>", self.build(variant, linked=False))

    def test_frozen_light_and_style_are_shared_by_both_variants(self):
        """灯光与背景文字是**冻结项**，两版必须逐字相同，否则 A/B 混入第三个变量。"""
        for variant in ("legacy", "new"):
            text = self.build(variant, linked=False)
            self.assertIn(A.LIGHT_TEXT, text)
            self.assertIn(A.STYLE_TEXT, text)

    def test_product_base_tail_replaces_clay_tail(self):
        pb = self.build("new", linked=False, input_kind="product_base")
        self.assertIn("already shows assigned physical materials", pb)
        clay = self.build("new", linked=False, input_kind="cmf_guide")
        self.assertIn("existing parting lines", clay)


class NegativeSourceTest(unittest.TestCase):
    def test_negative_text_comes_from_production_sources(self):
        """负面词必须从 app.js 的 NEGATIVE 与设计库的 negative_common 取，
        不能抄一份写死 —— 否则生产改了词，实验结论会指向一个不存在的提示词。"""
        text = A.production_negative_text()
        self.assertIn("blurry, low quality", text)
        import server as S
        for item in S.load_design_presets().get("negative_common") or []:
            self.assertIn(item, text, "负面词缺少共用约束：%s" % item)

    def test_negative_has_no_duplicates(self):
        text = A.production_negative_text()
        items = [x.strip() for x in text.split(",") if x.strip()]
        self.assertEqual(len(items), len(set(items)), "负面词不应重复出现")


if __name__ == "__main__":
    unittest.main()
