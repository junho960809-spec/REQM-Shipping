import tempfile
import unittest
from datetime import date
from pathlib import Path

from openpyxl import Workbook

from ecount_sales_sync import parse_ecount_sales_excel, previous_inventory_week
from weekly_inventory_supabase import prepare_records


class EcountSalesSyncTest(unittest.TestCase):
    def test_previous_inventory_week(self):
        self.assertEqual(
            previous_inventory_week(date(2026, 8, 28)),
            (date(2026, 8, 21), date(2026, 8, 27)),
        )
        self.assertEqual(
            previous_inventory_week(date(2026, 8, 27)),
            (date(2026, 8, 21), date(2026, 8, 27)),
        )

    def test_parse_download_and_prepare_supabase_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sales.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["회사"])
            sheet.append(["일자", "거래처코드", "거래처명", "품목코드", "품목명", "수량", "공급가액", "부가세", "합계"])
            sheet.append(["20260827", "AC008712", "샵N", "ITEM-1", "[리큐엠] 상품", "2", "1000", "100", "1100"])
            sheet.append(["총합계", "", "", "", "", "2", "1000", "100", "1100"])
            workbook.save(path)
            workbook.close()

            rows = parse_ecount_sales_excel(path, date(2026, 8, 21), date(2026, 8, 27))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][10], "ITEM-1")
            self.assertEqual(rows[0][12:16], [2.0, 1000, 100, 1100])
            records = prepare_records(rows)
            self.assertEqual(records[0]["sale_date"], "2026-08-27")
            self.assertEqual(records[0]["category"], "리큐엠")


if __name__ == "__main__":
    unittest.main()
