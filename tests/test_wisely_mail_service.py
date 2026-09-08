from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from wisely_mail_service import attachment_name_for, file_sha256, subject_for


class WiselyMailServiceTests(unittest.TestCase):
    def test_daily_mail_identifiers_are_exact(self) -> None:
        day = date(2026, 9, 8)
        self.assertEqual(subject_for(day), "2026-09-08 리큐엠 주문 발주서 입니다.")
        self.assertEqual(attachment_name_for(day), "orders_2026-09-08_리큐엠.xlsx")

    def test_file_hash_is_stable_for_duplicate_detection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "order.xlsx"
            path.write_bytes(b"same-order")
            first = file_sha256(path)
            second = file_sha256(path)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
