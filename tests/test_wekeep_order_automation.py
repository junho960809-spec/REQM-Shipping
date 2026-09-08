from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wekeep_order_automation import load_pending_payload, open_registration_panel, save_pending_payload


class FakeLocator:
    def __init__(self, calls: list, name: str) -> None:
        self.calls = calls
        self.name = name

    def click(self) -> None:
        self.calls.append(("click", self.name))

    def set_input_files(self, path: str) -> None:
        self.calls.append(("files", self.name, path))


class FakePage:
    def __init__(self) -> None:
        self.calls: list = []

    def get_by_role(self, role: str, **kwargs) -> FakeLocator:
        self.calls.append(("role", role, kwargs))
        return FakeLocator(self.calls, kwargs["name"])

    def locator(self, selector: str) -> FakeLocator:
        self.calls.append(("locator", selector))
        return FakeLocator(self.calls, selector)

    def wait_for_timeout(self, value: int) -> None:
        self.calls.append(("wait", value))


class WeKeepOrderAutomationTests(unittest.TestCase):
    def test_opens_verified_b2b_seller_panel(self) -> None:
        page = FakePage()

        open_registration_panel(page, "b2b")

        self.assertIn(("locator", 'button[id^="B2B-"]'), page.calls)
        self.assertIn(("click", 'button[id^="B2B-"]'), page.calls)
        self.assertIn(("click", "#excelOrderBtn"), page.calls)

    def test_opens_distinct_b2b_buying_route(self) -> None:
        page = FakePage()

        open_registration_panel(page, "b2b_buying")

        self.assertIn(("click", 'button[id^="B2B-"]'), page.calls)
        self.assertIn(("click", "#shipmentExcelBtn"), page.calls)

    def test_attaches_file_without_clicking_save(self) -> None:
        page = FakePage()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "upload.xlsx"
            path.write_bytes(b"xlsx")
            open_registration_panel(page, "b2c_buying", path)

        self.assertTrue(any(call[:2] == ("files", "#file_upload_excelPopup_shipment") for call in page.calls))
        self.assertFalse(any("excelFileUpload" in str(call) for call in page.calls))

    def test_load_pending_payload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pending.json"
            path.write_text(json.dumps({"order_kind": "b2b", "rows": []}), encoding="utf-8")
            value = load_pending_payload(path)
        self.assertEqual(value["order_kind"], "b2b")

    def test_invalid_pending_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pending.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "형식"):
                load_pending_payload(path)

    def test_pending_payload_is_encrypted_at_rest(self) -> None:
        payload = {"order_kind": "b2c", "rows": [{"recipient": "홍길동", "state": "ready"}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pending.json"
            save_pending_payload(path, payload)
            stored = path.read_text(encoding="utf-8")
            loaded = load_pending_payload(path)

        self.assertNotIn("홍길동", stored)
        self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
