from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from wekeep_tracking_dialog import ManualTrackingDialog


class ManualTrackingDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def rows() -> list[dict]:
        base = {
            "recipient": "홍길동", "phone": "010-1234-5678", "zipcode": "01234",
            "address": "서울시 테스트로 1", "product_name": "본품",
            "tracking_match_state": "pending", "tracking_number": "",
        }
        return [{**base, "order_number": "O-1"}, {**base, "order_number": "O-2", "product_name": "케이스"}]

    def test_dialog_exposes_full_order_details_and_checked_targets(self) -> None:
        dialog = ManualTrackingDialog(self.rows(), 0)
        try:
            self.assertEqual(dialog.target_table.columnCount(), 7)
            self.assertEqual(
                [dialog.target_table.horizontalHeaderItem(index).text() for index in range(7)],
                ["적용", "주문번호", "수령인", "전화번호", "우편번호", "주소", "상품명"],
            )
            self.assertEqual(dialog.selected_target_indexes(), [0, 1])
            dialog.target_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
            self.assertEqual(dialog.selected_target_indexes(), [0])
            self.assertIn("적용 주문 1건", dialog.apply_summary.text())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
