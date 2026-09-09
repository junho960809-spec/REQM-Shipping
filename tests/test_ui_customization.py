from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ui.texts import DEFAULT_TEXTS, reload_texts, text
from ui.theme import load_theme


class UiCustomizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        reload_texts(Path("__missing_ui_texts__.json"))

    def test_known_text_can_be_overridden_without_changing_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "texts.json"
            path.write_text(json.dumps({"app.title": "새 출고 화면", "unknown.key": "무시"}), encoding="utf-8")
            loaded = reload_texts(path)

        self.assertEqual(text("app.title"), "새 출고 화면")
        self.assertEqual(DEFAULT_TEXTS["app.title"], "REQM 출고 관리")
        self.assertNotIn("unknown.key", loaded)

    def test_unknown_text_key_fails_fast(self) -> None:
        with self.assertRaises(KeyError):
            text("business.order_kind")

    def test_custom_qss_is_appended_after_base_theme(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "custom.qss"
            path.write_text("QPushButton { background: magenta; }", encoding="utf-8")
            theme = load_theme(path)

        self.assertIn("QMainWindow", theme)
        self.assertTrue(theme.rstrip().endswith("QPushButton { background: magenta; }"))

    def test_release_spec_packages_base_theme(self) -> None:
        spec = (Path(__file__).resolve().parents[1] / "REQM.spec").read_text(encoding="utf-8")
        self.assertIn('("ui/styles/theme.qss", "ui/styles")', spec)


if __name__ == "__main__":
    unittest.main()
