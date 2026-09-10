from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from wekeep_tracking_service import export_tracking_workbook, reconcile_tracking_numbers


class WeKeepTrackingServiceTests(unittest.TestCase):
    @staticmethod
    def _orders() -> list[dict]:
        return [
            {"order_number": "O-1", "channel": "셀메이트", "product_name": "본품", "quantity": 1,
             "recipient": "홍길동", "phone": "010-1234-5678", "zipcode": "01234",
             "address": "서울시 테스트로 1", "message": "문 앞", "serial_number": "S-1"},
            {"order_number": "O-1", "channel": "셀메이트", "product_name": "옵션", "quantity": 1,
             "recipient": "홍길동", "phone": "010-1234-5678", "zipcode": "01234",
             "address": "서울시 테스트로 1", "message": "문 앞", "serial_number": "S-2"},
        ]

    def test_exact_order_and_recipient_fill_same_invoice_on_set_rows(self) -> None:
        results = reconcile_tracking_numbers(self._orders(), [{
            "order_number": "O-1", "recipient": "홍길동", "tracking_number": "5409-8333-2747",
        }])
        self.assertEqual([row["tracking_number"] for row in results], ["540983332747"] * 2)
        self.assertTrue(all(row["tracking_match_state"] == "matched" for row in results))

    def test_recipient_mismatch_never_fills_invoice(self) -> None:
        result = reconcile_tracking_numbers(self._orders()[:1], [{
            "order_number": "O-1", "recipient": "다른사람", "tracking_number": "540983332747",
        }])[0]
        self.assertEqual(result["tracking_match_state"], "review")
        self.assertEqual(result["tracking_number"], "")

    def test_phone_and_address_are_checked_when_wekeep_exposes_them(self) -> None:
        remote = {"order_number": "O-1", "recipient": "홍길동", "phone": "01012345678",
                  "address": "부산시 다른로 2", "tracking_number": "540983332747"}
        result = reconcile_tracking_numbers(self._orders()[:1], [remote])[0]
        self.assertEqual(result["tracking_match_state"], "review")

    def test_pending_missing_and_multiple_invoices_stay_blank(self) -> None:
        for remote, expected in [
            ([{"order_number": "O-1", "recipient": "홍길동", "tracking_number": "-"}], "pending"),
            ([], "not_found"),
            ([{"order_number": "O-1", "recipient": "홍길동", "tracking_number": "11111111", "additional_tracking": "22222222"}], "review"),
        ]:
            with self.subTest(expected=expected):
                result = reconcile_tracking_numbers(self._orders()[:1], remote)[0]
                self.assertEqual(result["tracking_match_state"], expected)
                self.assertEqual(result["tracking_number"], "")

    def test_export_preserves_11_column_layout_and_writes_invoice_as_text(self) -> None:
        rows = reconcile_tracking_numbers(self._orders(), [{
            "order_number": "O-1", "recipient": "홍길동", "tracking_number": "540983332747",
        }])
        with tempfile.TemporaryDirectory() as folder:
            path = export_tracking_workbook(rows, Path(folder) / "tracking.xlsx")
            workbook = load_workbook(path, data_only=True)
            try:
                sheet = workbook.active
                self.assertEqual(sheet.max_column, 11)
                self.assertEqual([cell.value for cell in sheet[1]], [
                    "주문번호", "판매처", "상품명", "수량", "수령자", "핸드폰", "우편번호",
                    "주소", "배송메세지", "송장번호", "일련번호",
                ])
                self.assertEqual([sheet.cell(row, 10).value for row in (2, 3)], ["540983332747"] * 2)
                self.assertEqual([sheet.cell(row, 11).value for row in (2, 3)], ["S-1", "S-2"])
            finally:
                workbook.close()


if __name__ == "__main__":
    unittest.main()
