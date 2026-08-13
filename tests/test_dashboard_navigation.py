from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from main import InventoryPreviewDialog, MainWindow, MiniWidgetDialog


class DashboardNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()

    def test_dashboard_has_shipping_and_inventory_cards(self) -> None:
        self.assertEqual(
            [button.text() for button in self.window.dashboard_cards],
            ["📦  출고 파일 변환", "▤  재고 조회"],
        )

    def test_shipping_card_opens_shipping_workspace(self) -> None:
        self.window.dashboard_cards[0].click()
        self.assertIs(self.window.page_stack.currentWidget(), self.window.work_page)

    def test_inventory_card_opens_preview_dialog(self) -> None:
        with patch.object(InventoryPreviewDialog, "exec", return_value=0) as opened:
            self.window.dashboard_cards[1].click()
        opened.assert_called_once()

    def test_inventory_preview_is_not_connected_yet(self) -> None:
        dialog = InventoryPreviewDialog(self.window)
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertFalse(dialog.search_button.isEnabled())
        self.assertIn("연동 전 샘플", dialog.table.item(0, 7).text())
        dialog.close()

    def test_sparse_duty_free_file_uses_unified_shipping_workspace(self) -> None:
        order = {
            "channel": "롯데면세점", "product_name": "테스트 품목", "quantity": "2",
            "ref_no": "REF-1", "sku_no": "SKU-1", "match_method": "name_or_code",
        }
        location = {
            "id": "lotte", "name": "롯데 출고지", "channel": "롯데면세점",
            "recipient": "담당자", "phone": "010-0000-0000", "zipcode": "00000",
            "address": "서울시 테스트로 1", "message": "면세점 출고",
        }
        self.window.matcher = Mock()
        self.window.matcher.match.return_value = {
            "status": "exact", "matched_product": "테스트 품목", "components": "A001",
        }
        self.window.mark_duplicates = Mock()
        with (
            patch("main.load_duty_free", return_value=None),
            patch("main.load_simple_duty_free", return_value=([order], "롯데면세점")),
            patch("main.load_locations", return_value=[location]),
            patch("main.find_reference_mapping", return_value={"item_code": "A001"}),
        ):
            self.window.load_order_file("롯데면세점.xlsx", "auto")

        self.assertEqual(self.window.current_mode, "duty_free")
        self.assertEqual(self.window.current_orders[0]["internal_item_code"], "A001")
        self.assertEqual(self.window.current_orders[0]["address"], "서울시 테스트로 1")
        self.assertEqual(self.window.selected_location_name, "롯데 출고지")
        self.assertNotIn("면세점 출고", [button.text() for button in self.window.dashboard_cards])

    def test_mini_widget_has_three_unified_function_buttons(self) -> None:
        widget = MiniWidgetDialog(self.window)
        self.assertEqual(
            [button.property("widgetTarget") for button in widget.action_buttons],
            ["shipping", "warehouse", "calendar"],
        )
        widget.close()

    def test_mini_widget_buttons_route_to_each_function(self) -> None:
        widget = MiniWidgetDialog(self.window)
        widget.close = Mock()
        self.window.show_shipping_workspace = Mock()
        self.window.show_dashboard = Mock()
        self.window.open_dashboard_warehouse_transfer = Mock()

        widget.open_target("shipping")
        self.window.show_shipping_workspace.assert_called_once_with()

        widget.open_target("warehouse")
        self.window.open_dashboard_warehouse_transfer.assert_called_once_with()

        widget.open_target("calendar")
        self.assertEqual(self.window.show_dashboard.call_count, 2)
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
