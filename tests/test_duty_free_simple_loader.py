from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from duty_free_loader import _simple_orders_from_rows, load_simple_duty_free


class DutyFreeSimpleLoaderTests(unittest.TestCase):
    def test_reads_product_and_quantity_from_fixed_pdf_table_shape(self) -> None:
        rows = [
            ["입고내용", "Sku.No", "Ref.No", "상품명", "수량"],
            ["본품", "2731106888", "8809477248685", "실리콘 케이스 라벤더", "10"],
            [None, "2731106889", "8809477248692", "실리콘 케이스 민트", 20],
        ]

        orders = _simple_orders_from_rows(rows, "PDF 1쪽 표 1", "롯데면세점")

        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0]["product_name"], "실리콘 케이스 라벤더")
        self.assertEqual(orders[0]["quantity"], "10")
        self.assertEqual(orders[0]["source_item_code"], "8809477248685")
        self.assertEqual(orders[0]["ref_no"], "8809477248685")
        self.assertEqual(orders[0]["sku_no"], "2731106888")
        self.assertEqual(orders[1]["quantity"], "20")

    def test_loads_sparse_excel_without_recipient_or_address_columns(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "롯데면세점_입고.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["롯데면세점 리큐엠 입고 진행 건"])
        sheet.append(["입고내용", "Sku.No", "Ref.No", "상품명", "수량"])
        sheet.append(["본품", "2731106888", "8809477248685", "20W 고속충전 배터리", 30])
        workbook.save(path)
        workbook.close()

        orders, channel = load_simple_duty_free(str(path))

        self.assertEqual(channel, "롯데면세점")
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["product_name"], "20W 고속충전 배터리")
        self.assertEqual(orders[0]["quantity"], "30")
        self.assertEqual(orders[0]["address"], "")


if __name__ == "__main__":
    unittest.main()
