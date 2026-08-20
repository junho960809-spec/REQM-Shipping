import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook, load_workbook
from PySide6.QtWidgets import QApplication

from inventory_module import InventoryDialog, InventoryRow, export_inventory_workbook, import_wekeep_rows


class InventoryModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_entry_rows_follow_reference_workbook_order(self):
        rows = InventoryDialog._initial_rows([{"item_code": "SHOULD-NOT-APPEAR", "item_name": "제외 품목"}])

        self.assertEqual(len(rows), 165)
        self.assertEqual((rows[0].item_code, rows[0].item_name), ("QWC-Q1500GR", "[리큐엠] QWC-Q1500 무선충전기 그레이"))
        self.assertEqual((rows[-1].item_code, rows[-1].item_name), ("QMA-Bubblepad-Cr", "리큐엠 맥세이프 액세서리-버블패드_소프트 크림"))
        self.assertNotIn("SHOULD-NOT-APPEAR", {row.item_code for row in rows})

    def test_entry_table_defaults_to_excel_source_order(self):
        dialog = InventoryDialog([])
        try:
            self.assertEqual(dialog.sort_filter.currentText(), "엑셀 원본 순서")
            self.assertEqual(dialog.entry_table.item(0, 0).text(), "QWC-Q1500GR")
            self.assertEqual(dialog.entry_table.item(dialog.entry_table.rowCount() - 1, 0).text(), "QMA-Bubblepad-Cr")
        finally:
            dialog.close()

    def test_differences(self):
        row = InventoryRow("A", "품목", 10, 7, 5, 8)
        self.assertEqual(row.headquarters_difference, 3)
        self.assertEqual(row.wekeep_difference, -3)
        self.assertEqual(row.total_difference, 0)

    def test_import_wekeep_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "wekeep.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "재고데이터-위킵"
            sheet.append(["상품관리코드", "상품명", "시점재고"])
            sheet.append(["QWC-Q1500GR", "무선충전기 그레이", 536])
            workbook.save(path)
            result = import_wekeep_rows(path)
        self.assertEqual(result["QWC-Q1500GR"], ("무선충전기 그레이", 536))

    def test_export_inventory_workbook(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inventory.xlsx"
            export_inventory_workbook(path, [InventoryRow("A", "품목", 10, 7, 5, 8)])
            workbook = load_workbook(path, data_only=False)
            self.assertEqual(
                workbook.sheetnames,
                ["재고현황", "실재고 전산비교", "재고데이터", "재고데이터-리큐엠", "재고데이터-위킵", "RAWDATA_이카운트"],
            )
            self.assertEqual(workbook["재고현황"]["E3"].value, 3)
            self.assertEqual(workbook["재고현황"]["H3"].value, -3)
            self.assertEqual(workbook["재고현황"]["I3"].value, 0)


if __name__ == "__main__":
    unittest.main()
