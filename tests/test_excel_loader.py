from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from excel_loader import load_orders


class ExcelLoaderTests(unittest.TestCase):
    def test_recipient_mobile_number_is_preferred_over_empty_phone_number(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "eri_orders.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([
            "MALL", "주문번호", "상품명", "주문수량", "수령인명",
            "우편번호", "주소", "수령인전화번호", "수령인핸드폰번호",
            "업체명", "모델명",
        ])
        sheet.append([
            "M", "ORDER-1", "REQM 상품", 1, "홍길동",
            "01234", "서울시 중구 테스트로 1", "--", "010-4966-0448",
            "004_(주)리큐엠", "Q1500",
        ])
        workbook.save(path)
        workbook.close()

        orders, columns = load_orders(str(path))

        self.assertEqual(orders[0]["source_format"], "판매처 직접파일 · 이알아이")
        self.assertEqual(orders[0]["phone"], "010-4966-0448")
        self.assertEqual(columns["phone"], 8)


if __name__ == "__main__":
    unittest.main()
