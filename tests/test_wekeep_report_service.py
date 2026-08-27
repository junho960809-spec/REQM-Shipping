from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import wekeep_report_service as service


class FakeChromium:
    def __init__(self, available_channels: set[str]) -> None:
        self.available_channels = available_channels
        self.calls: list[str] = []

    def launch_persistent_context(self, *args, **kwargs):
        channel = kwargs["channel"]
        self.calls.append(channel)
        if channel not in self.available_channels:
            raise RuntimeError(f"{channel} unavailable")
        return f"{channel}-context"


class FakePlaywright:
    def __init__(self, available_channels: set[str]) -> None:
        self.chromium = FakeChromium(available_channels)


class FakeLocator:
    def fill(self, value: str) -> None:
        self.value = value

    def click(self) -> None:
        pass


class FakePage:
    url = service.INVENTORY_URL

    def __init__(self) -> None:
        self.wait_args: list[tuple[str, int]] = []

    def goto(self, *args, **kwargs) -> None:
        pass

    def wait_for_timeout(self, *args, **kwargs) -> None:
        pass

    def locator(self, *args, **kwargs) -> FakeLocator:
        return FakeLocator()

    def wait_for_function(self, expression: str, *, arg: str, timeout: int) -> None:
        self.wait_args.append((arg, timeout))

    def evaluate(self, expression: str) -> list[dict]:
        return [{"code": "QP1000C1-Carrot", "name": "캐롯", "stock": 14}]


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.pages = [page]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class WeKeepReportServiceTests(unittest.TestCase):
    def test_browser_prefers_chrome_when_both_browsers_exist(self) -> None:
        playwright = FakePlaywright({"chrome", "msedge"})

        context = service.launch_wekeep_context(playwright, headless=True)

        self.assertEqual(context, "chrome-context")
        self.assertEqual(playwright.chromium.calls, ["chrome"])

    def test_browser_falls_back_to_edge_when_chrome_is_missing(self) -> None:
        playwright = FakePlaywright({"msedge"})

        context = service.launch_wekeep_context(playwright, headless=False)

        self.assertEqual(context, "msedge-context")
        self.assertEqual(playwright.chromium.calls, ["chrome", "msedge"])

    def test_missing_browsers_reports_actionable_diagnostics(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Google Chrome 또는 Microsoft Edge") as raised:
            service.launch_wekeep_context(FakePlaywright(set()), headless=True)

        self.assertIn("chrome unavailable", str(raised.exception))
        self.assertIn("msedge unavailable", str(raised.exception))

    def test_save_config_deduplicates_items_and_normalizes_values(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder) / "wekeep_report.json"
            with patch.object(service, "REQM_DIR", Path(folder)), patch.object(service, "CONFIG_PATH", config_path):
                service.save_config([
                    {"item_code": "QP1000C", "item_name": "캐롯", "wekeep_code": " QP1000C1-Carrot ", "threshold": -4},
                    {"item_code": "qp1000c", "item_name": "중복", "wekeep_code": "other", "threshold": 10},
                ], "15:00")

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schedule_time"], "15:00")
            self.assertEqual(saved["selected_items"], [{
                "item_code": "QP1000C", "item_name": "캐롯",
                "wekeep_code": "QP1000C1-Carrot", "threshold": 0,
            }])

    def test_inventory_lookup_waits_for_the_requested_code(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        with patch.object(service, "launch_wekeep_context", return_value=context):
            rows = service.collect_inventory_rows(object(), ["QP1000C1-Carrot"], headless=True)

        self.assertEqual(rows[0]["stock"], 14)
        self.assertEqual(page.wait_args, [("QP1000C1-Carrot", 10_000)])
        self.assertTrue(context.closed)


if __name__ == "__main__":
    unittest.main()
