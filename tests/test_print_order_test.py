import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QColor
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

    def test_gender_field_is_removed_and_clipboard_image_can_be_attached(self):
        window = PrintOrderTestWindow()
        try:
            self.assertFalse(hasattr(window, "gender"))
            image = QImage(20, 20, QImage.Format.Format_ARGB32)
            image.fill(QColor("#0d9488"))
            QApplication.clipboard().setImage(image)
            window.preview_file.paste_clipboard_image()
            self.assertTrue(window.preview_file.path.endswith(".png"))
            self.assertTrue(Path(window.preview_file.path).exists())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
