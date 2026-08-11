from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from main import DutyFreeShippingDialog, MainWindow, MiniWidgetDialog


class DashboardNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()

    def test_cards_are_ordered_shipping_duty_free_warehouse(self) -> None:
        self.assertEqual(
            [button.text() for button in self.window.dashboard_cards],
            ["📦  출고 파일 변환", "🏬  면세점 출고", "↔  창고이동"],
        )

    def test_shipping_card_opens_shipping_workspace(self) -> None:
        self.window.dashboard_cards[0].click()
        self.assertIs(self.window.page_stack.currentWidget(), self.window.work_page)

    def test_duty_free_card_opens_compact_dialog(self) -> None:
        dialog = DutyFreeShippingDialog(None, [], self.window)
        self.assertEqual((dialog.width(), dialog.height()), (760, 560))
        dialog.close()
        with patch.object(DutyFreeShippingDialog, "exec", return_value=0) as opened:
            self.window.dashboard_cards[1].click()
        opened.assert_called_once()

    def test_duty_free_transfer_uses_loaded_orders(self) -> None:
        dialog = DutyFreeShippingDialog(
            None, [], self.window, catalog_items=[{"item_code": "A001"}],
            ecount_config={"source_warehouse": "100", "target_warehouse": "300"},
            completed_requests=set(), is_admin=True,
        )
        dialog.orders = [{
            "channel": "롯데면세점", "quantity": "2", "status": "exact", "components": "A001",
        }]
        dialog.apply_selected_location()
        self.assertTrue(dialog.transfer_button.isEnabled())
        with patch("main.EcountTransferDialog") as transfer_class:
            transfer = transfer_class.return_value
            transfer.exec.return_value = QDialog.DialogCode.Accepted
            transfer.transfer_scope = "롯데면세점"
            transfer.items = [{"item_code": "A001", "quantity": "2"}]
            dialog.open_warehouse_transfer()
        self.assertIs(transfer_class.call_args.args[0], dialog.orders)
        self.assertEqual(transfer_class.call_args.args[1], [{"item_code": "A001"}])
        self.assertIn("창고이동 완료", dialog.status.text())
        dialog.close()

    def test_warehouse_card_routes_to_transfer_when_orders_exist(self) -> None:
        self.window.current_orders = [{"channel": "롯데면세점", "quantity": "1"}]
        self.window.open_ecount_transfer = Mock()
        self.window.dashboard_cards[2].click()
        self.window.open_ecount_transfer.assert_called_once_with()

    def test_mini_widget_has_four_function_buttons_in_requested_order(self) -> None:
        widget = MiniWidgetDialog(self.window)
        self.assertEqual(
            [button.property("widgetTarget") for button in widget.action_buttons],
            ["shipping", "duty_free", "warehouse", "calendar"],
        )
        widget.close()

    def test_mini_widget_buttons_route_to_each_function(self) -> None:
        widget = MiniWidgetDialog(self.window)
        widget.close = Mock()
        self.window.show_shipping_workspace = Mock()
        self.window.show_dashboard = Mock()
        self.window.open_duty_free_shipping = Mock()
        self.window.open_dashboard_warehouse_transfer = Mock()

        widget.open_target("shipping")
        self.window.show_shipping_workspace.assert_called_once_with()

        widget.open_target("duty_free")
        self.window.open_duty_free_shipping.assert_called_once_with()

        widget.open_target("warehouse")
        self.window.open_dashboard_warehouse_transfer.assert_called_once_with()

        widget.open_target("calendar")
        self.assertEqual(self.window.show_dashboard.call_count, 3)
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
