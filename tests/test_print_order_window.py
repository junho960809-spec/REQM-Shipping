import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from print_order_window import PrintOrderWindow
from print_order_analyzer import AnalysisResult


class PrintOrderWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_has_four_workflow_pages_and_web_submit_is_disabled(self):
        window = PrintOrderWindow()
        try:
            self.assertEqual(window.menu.count(), 4)
            self.assertEqual(window.stack.count(), 4)
            window.open_preview()
            self.assertEqual(window.menu.currentRow(), 1)
            self.assertIn("고려기프트", window.preview_title.text())
        finally:
            window.close()

    def test_gender_field_is_removed_and_clipboard_image_can_be_attached(self):
        window = PrintOrderWindow()
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

    def test_web_registration_is_enabled_but_requires_runtime_credentials(self):
        window = PrintOrderWindow()
        try:
            window.ai_file.set_file(__file__)
            window.preview_file.set_file(__file__)
            self.assertTrue(window.web_submit_button.isEnabled())
            with patch("print_order_window.QMessageBox.information") as notice:
                window.submit_to_web()
            notice.assert_called_once()
            self.assertEqual(window.menu.currentRow(), 3)
            self.assertIsNone(window.web_worker)
            self.assertEqual(window.order_payload()["packaging"], "선물포장")
        finally:
            window.close()

    def test_analysis_result_populates_common_order_fields(self):
        window = PrintOrderWindow()
        try:
            result = AnalysisResult(
                "이미지 OCR", "고려기프트",
                {"recipient":"홍길동","contact":"010-1234-5678","address":"서울 영등포구","request_date":"2026-09-01","product":"Q1500 그레이","quantity":"300개","printing":"전면 인쇄","packaging":"선물포장","delivery":"택배"},
                {"recipient":70,"contact":70,"address":70,"request_date":70,"product":70,"quantity":70,"printing":70,"packaging":70,"delivery":70},
                "원문",
            )
            window.apply_analysis(result)
            self.assertEqual(window.customer.currentText(), "고려기프트")
            self.assertEqual(window.quantity.text(), "300")
            self.assertEqual(window.request_date.date().toString("yyyy-MM-dd"), "2026-09-01")
            self.assertIn("홍길동", window.contact.text())
        finally:
            window.close()

    def test_db_product_name_and_automatic_note_are_applied(self):
        items = [{"item_code": "A530734", "standard_name": "소문 듀얼 도킹형 보조배터리 5000mAh", "is_active": True}]
        window = PrintOrderWindow(catalog_items=items)
        try:
            self.assertEqual(window.note.toPlainText(), "인쇄 X  포장 O")
            window.ai_file.set_file(__file__)
            self.assertEqual(window.note.toPlainText(), "인쇄 O  포장 O")
            window.packaging.setCurrentText("기본패키지")
            self.assertEqual(window.note.toPlainText(), "인쇄 O  포장 X")
            self.assertEqual(window.database_product_name("OCR 품명", "A530734"), items[0]["standard_name"])
            self.assertLessEqual(window.order_source.maximumHeight(), 145)
            self.assertLessEqual(window.ai_file.maximumHeight(), 125)
            self.assertLessEqual(window.preview_file.maximumHeight(), 155)
            self.assertEqual(window.order_source.parentWidget().width(), 340)
        finally:
            window.close()

    def test_source_view_opens_original_file_in_default_viewer(self):
        window = PrintOrderWindow()
        try:
            window.order_source.set_file(__file__)
            with patch("print_order_window.QDesktopServices.openUrl", return_value=True) as open_url:
                window.show_source_file()
            open_url.assert_called_once()
            self.assertTrue(open_url.call_args.args[0].isLocalFile())
            self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()).resolve(), Path(__file__).resolve())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
