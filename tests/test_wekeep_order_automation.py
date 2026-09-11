from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shipment_job_store import ShipmentJobStore
from wekeep_order_automation import (
    ConfirmedSubmissionFailure,
    load_pending_payload,
    ensure_authenticated,
    open_registration_panel,
    save_pending_payload,
    submit_registration,
    run_wekeep_job,
)


class FakeLocator:
    def __init__(self, calls: list, name: str, page=None) -> None:
        self.calls = calls
        self.name = name
        self.page = page

    def click(self) -> None:
        self.calls.append(("click", self.name))

    def set_input_files(self, path: str) -> None:
        self.calls.append(("files", self.name, path))

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def inner_text(self) -> str:
        return self.page.body_text if self.name == "body" else ""

    def all_inner_texts(self) -> list[str]:
        return list(self.page.alert_messages) if "role='alert'" in self.name else []

    def get_by_role(self, role: str, **kwargs):
        self.calls.append(("scoped_role", self.name, role, kwargs))
        return FakeLocator(self.calls, f"{self.name}::{kwargs['name']}", self.page)

    def fill(self, value: str) -> None:
        self.calls.append(("fill", self.name, value))

    def check(self) -> None:
        self.calls.append(("check", self.name))


class FakePage:
    def __init__(self) -> None:
        self.calls: list = []
        self.body_text = "주식회사 리큐엠(B2C) 주식회사 리큐엠(사입형B2C) 주식회사 리큐엠(B2B)"
        self.alert_messages: list[str] = []
        self.url = "https://fbw.wekeep.co.kr/fbw/login"

    def get_by_role(self, role: str, **kwargs) -> FakeLocator:
        self.calls.append(("role", role, kwargs))
        return FakeLocator(self.calls, kwargs["name"], self)

    def locator(self, selector: str) -> FakeLocator:
        self.calls.append(("locator", selector))
        locator = FakeLocator(self.calls, selector, self)
        if selector in ("#orderExcelPopup", "#shipmentOrderExcelPopup"):
            locator.inner_text = lambda: self.body_text
        return locator

    def wait_for_timeout(self, value: int) -> None:
        self.calls.append(("wait", value))

    def goto(self, url: str, **kwargs) -> None:
        self.calls.append(("goto", url))
        self.url = url


class WeKeepOrderAutomationTests(unittest.TestCase):
    @staticmethod
    def _prepared_rows() -> list[dict]:
        return [{
            "state": "ready", "order_number": "O-1", "channel": "와이즐리",
            "item_code": "A", "sku_no": "SKU-A", "wekeep_product_name": "제품",
            "quantity": 1, "recipient": "홍길동", "phone": "010-1234-5678",
            "zipcode": "01234", "address": "서울",
        }]

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

    def test_submits_only_exact_route_button_and_requires_success_response(self) -> None:
        page = FakePage()
        page.body_text = "주식회사 리큐엠(B2C) 주문이 등록되었습니다. 주문번호: WK-123"

        result = submit_registration(page, "b2c")

        self.assertIn(("click", "#orderExcelPopup::저장"), page.calls)
        self.assertEqual(result, {"state": "completed", "provider_reference": "WK-123"})

    def test_refuses_to_submit_when_popup_seller_does_not_match_route(self) -> None:
        page = FakePage()
        page.body_text = "주식회사 리큐엠(B2B)"

        with self.assertRaisesRegex(RuntimeError, "판매처가 일치하지 않습니다"):
            submit_registration(page, "b2c")

        self.assertFalse(any(call[0] == "click" and "저장" in call[1] for call in page.calls))

    def test_unconfirmed_response_is_never_reported_as_success(self) -> None:
        page = FakePage()
        page.body_text = "주식회사 리큐엠(사입형B2C) 주문 목록"

        self.assertEqual(submit_registration(page, "b2c_buying")["state"], "unknown")

    def test_explicit_duplicate_alert_is_a_confirmed_failure(self) -> None:
        page = FakePage()
        page.body_text = "주식회사 리큐엠(B2C)"
        page.alert_messages = ["이미 등록된 중복 주문입니다."]
        with self.assertRaises(ConfirmedSubmissionFailure):
            submit_registration(page, "b2c")

    def test_saved_credentials_can_log_in_without_showing_browser(self) -> None:
        page = FakePage()

        ensure_authenticated(page, "wekeep-user", "wekeep-secret")

        self.assertIn(("fill", 'input[name="j_username"]', "wekeep-user"), page.calls)
        self.assertIn(("fill", 'input[name="j_password"]', "wekeep-secret"), page.calls)
        self.assertIn(("click", 'input[type="submit"][value="시작하기"]'), page.calls)

    def test_headless_job_is_completed_only_after_submit_confirmation(self) -> None:
        class PlaywrightManager:
            def __enter__(self):
                return object()

            def __exit__(self, *_args):
                return False

        with tempfile.TemporaryDirectory() as folder:
            store = ShipmentJobStore(Path(folder) / "jobs.sqlite3")
            job = store.create(self._prepared_rows(), "b2c")
            page = Mock(url="https://fbw.wekeep.co.kr/fbw/admin/v2/order/list.do")
            context = Mock(pages=[page])

            def confirmed(_page, _kind, *, on_submitted=None):
                on_submitted()
                return {"state": "completed", "provider_reference": "WK-123"}

            with patch("playwright.sync_api.sync_playwright", return_value=PlaywrightManager()), patch(
                "wekeep_order_automation.launch_wekeep_context", return_value=context
            ), patch("wekeep_order_automation.create_wekeep_upload"), patch(
                "wekeep_order_automation.load_integration_credentials",
                return_value={"wekeep_user_id": "user", "wekeep_password": "secret"},
            ), patch("wekeep_order_automation.ensure_authenticated"), patch(
                "wekeep_order_automation.open_registration_panel"
            ), patch("wekeep_order_automation.submit_registration", side_effect=confirmed):
                completed = run_wekeep_job(job["id"], store.path)

            self.assertEqual(completed["state"], "completed")
            self.assertEqual(completed["provider_reference"], "WK-123")

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
