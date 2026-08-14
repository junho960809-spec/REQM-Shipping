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
        self.window.inventory_rows = [dict(row) for row in InventoryPreviewDialog.SAMPLE_ROWS]
        self.window.inventory_last_checked = "2026-08-14 10:00:00"
        self.window.refresh_inventory = Mock()

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

    def test_inventory_preview_uses_shared_live_inventory_rows(self) -> None:
        dialog = InventoryPreviewDialog(self.window)
        self.assertEqual(dialog.table.rowCount(), 4)
        self.assertTrue(dialog.search_button.isEnabled())
        self.assertEqual(dialog.table.columnCount(), 7)
        self.assertEqual(dialog.table.item(0, 6).text(), "2026-08-14 10:00:00")
        dialog.close()

    def test_inventory_filters_out_of_stock_and_highlights_safety_threshold(self) -> None:
        dialog = InventoryPreviewDialog(self.window)
        dialog.set_filter("out")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).text(), "품절")
        dialog.set_filter("all")
        safety_rows = [
            row for row in range(dialog.table.rowCount())
            if dialog.table.item(row, 0).text() == "안전재고 도달"
        ]
        self.assertEqual(len(safety_rows), 1)
        self.assertEqual(dialog.table.item(safety_rows[0], 4).text(), dialog.table.item(safety_rows[0], 5).text())
        dialog.close()

    def test_inventory_approximate_search_accepts_partial_name_and_code(self) -> None:
        dialog = InventoryPreviewDialog(self.window)
        dialog.search_input.setText("실리콘민트")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 1).text(), "QP1000C-MT")
        dialog.search_input.setText("qp500")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).text(), "품절")
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

    def test_mini_widget_has_two_compact_function_buttons(self) -> None:
        widget = MiniWidgetDialog(self.window)
        self.assertEqual(
            [button.property("widgetTarget") for button in widget.action_buttons],
            ["shipping", "calendar"],
        )
        self.assertEqual((widget.width(), widget.height()), (380, 500))
        self.assertEqual([button.text() for button in widget.action_buttons], ["📦  출고", "📅  일정"])
        self.assertEqual(
            widget.inventory_results.selectionMode(),
            widget.inventory_results.SelectionMode.NoSelection,
        )
        self.assertEqual(widget.inventory_results.height(), 226)
        self.assertTrue(widget.event_summary.isHidden())
        widget.close()

    def test_mini_widget_supports_quick_inventory_search(self) -> None:
        widget = MiniWidgetDialog(self.window)
        widget.inventory_search_input.setText("민트")
        self.assertEqual(widget.inventory_results.count(), 3)
        self.assertIn("위킵 20", widget.inventory_results.item(0).text())
        widget.inventory_search_input.setText("없는품목")
        self.assertEqual(widget.inventory_results.count(), 1)
        self.assertIn("검색 결과가 없습니다", widget.inventory_results.item(0).text())
        widget.close()

    def test_mini_widget_buttons_route_to_each_function(self) -> None:
        widget = MiniWidgetDialog(self.window)
        widget.close = Mock()
        self.window.show_shipping_workspace = Mock()
        self.window.show_dashboard = Mock()

        widget.open_target("shipping")
        self.window.show_shipping_workspace.assert_called_once_with()

        widget.open_target("calendar")
        self.assertEqual(self.window.show_dashboard.call_count, 1)
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
