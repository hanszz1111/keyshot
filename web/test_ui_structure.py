"""Static guardrails for the single active workbench page."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


class WorkbenchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.details = []
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "details":
            self.details.append(attrs.get("id", ""))
        if tag in {"div", "details", "section", "main", "aside"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in {"div", "details", "section", "main", "aside"}:
            if not self.stack or self.stack[-1] != tag:
                self.errors.append(f"unexpected closing {tag}")
            else:
                self.stack.pop()


class WorkbenchStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
        cls.parser = WorkbenchParser()
        cls.parser.feed(cls.page)

    def test_unique_ids_and_balanced_layout(self):
        self.assertEqual(len(self.parser.ids), len(set(self.parser.ids)))
        self.assertEqual([], self.parser.errors)
        self.assertEqual([], self.parser.stack)

    def test_primary_controls_remain_present(self):
        for control in ("productSelect", "materialSelect", "viewSelect", "countSelect", "sizeSelect", "qualitySelect", "generateButton", "renderProgress"):
            with self.subTest(control=control):
                self.assertIn(control, self.parser.ids)

    def test_advanced_controls_remain_available(self):
        for control in ("chooseRefButton", "qwenBaseSelect", "qwenSeed", "passSelectedButton", "passSixButton"):
            with self.subTest(control=control):
                self.assertIn(control, self.parser.ids)
        self.assertIn("qwenAdvancedSettings", self.parser.details)


if __name__ == "__main__":
    unittest.main()
