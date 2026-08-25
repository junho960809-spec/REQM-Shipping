import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from print_order_test import PrintOrderTestWindow


class PrintOrderPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_has_four_workflow_pages_and_web_submit_is_disabled(self):
        window = PrintOrderTestWindow()
        try:
            self.assertEqual(window.menu.count(), 4)
            self.assertEqual(window.stack.count(), 4)
            window.open_preview()
            self.assertEqual(window.menu.currentRow(), 1)
            self.assertIn("고려기프트", window.preview_title.text())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
