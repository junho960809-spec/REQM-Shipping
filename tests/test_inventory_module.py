import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from inventory_module import InventoryRow, export_inventory_workbook, import_wekeep_rows


class InventoryModuleTests(unittest.TestCase):
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
