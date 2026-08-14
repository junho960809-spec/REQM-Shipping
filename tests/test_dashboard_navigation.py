from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from main import (
    InventoryPreviewDialog,
    MainWindow,
    MiniWidgetDialog,
    calendar_event_from_remote,
    calendar_event_payload,
    create_app_icon,
)


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

    def test_calendar_event_converts_between_local_and_shared_schema(self) -> None:
        local = {
            "id": "event-1", "date": "2026-08-20", "title": "공용 일정",
            "info": "사용자 공유 정보", "file_paths": ["C:/local/file.xlsx"],
            "attachments": [],
        }
        payload = calendar_event_payload(local)
        restored = calendar_event_from_remote(payload, local["file_paths"])

        self.assertEqual(payload["event_date"], "2026-08-20")
        self.assertEqual(restored, local)

    def test_shared_calendar_uploads_attachment_and_saves_storage_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "일정.xlsx")
            with open(source, "wb") as stream:
                stream.write(b"calendar attachment")
            storage_bucket = Mock()
            self.window.supabase_client = Mock()
            self.window.supabase_client.storage.from_.return_value = storage_bucket
            table_query = Mock()
            table_query.upsert.return_value = table_query
            table_query.execute.return_value = Mock(data=[])
            self.window.supabase_client.table.return_value = table_query
            self.window.catalog = {"calendar_shared_available": True, "calendar_events": []}
            event = {
                "id": "event-1", "date": "2026-08-20", "title": "공용 일정",
                "info": "첨부 포함", "file_paths": [source], "attachments": [],
            }
            self.window.calendar_events = [event]

            with patch("main.save_calendar_events"):
                self.window.save_calendar_event_record(event)

            storage_bucket.upload.assert_called_once()
            self.assertEqual(event["file_paths"], [])
            self.assertEqual(event["attachments"][0]["name"], "일정.xlsx")

    def test_main_window_stays_on_top_and_has_taskbar_icon(self) -> None:
        icon = create_app_icon()
        QApplication.setWindowIcon(icon)
        self.window.setWindowIcon(icon)

        self.assertTrue(self.window.windowFlags() & self.window.windowFlags().WindowStaysOnTopHint)
        self.assertFalse(self.window.windowIcon().isNull())

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
            "recipient": "원본 수령인", "phone": "010-1111-2222", "zipcode": "12345",
            "address": "원본 파일 주소 10",
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
            patch("main.load_orders", return_value=([order], {"product_name": 0, "quantity": 1})),
            patch("main.load_locations", return_value=[location]),
            patch("main.find_reference_mapping", return_value={"item_code": "A001"}),
        ):
            self.window.load_order_file("롯데면세점.xlsx", "auto")

        self.assertEqual(self.window.current_mode, "duty_free")
        self.assertEqual(self.window.current_orders[0]["internal_item_code"], "A001")
        self.assertEqual(self.window.current_orders[0]["address"], "원본 파일 주소 10")
        self.assertEqual(self.window.current_orders[0]["recipient"], "원본 수령인")
        self.assertEqual(self.window.selected_location_name, "")
        self.assertEqual(self.window.export_button.text(), "출고 변환")
        self.assertTrue(self.window.export_button.isEnabled())

        self.window.apply_location()
        self.assertEqual(self.window.current_orders[0]["address"], "서울시 테스트로 1")
        self.assertEqual(self.window.current_orders[0]["recipient"], "담당자")
        self.assertEqual(self.window.selected_location_name, "롯데 출고지")
        self.assertNotIn("면세점 출고", [button.text() for button in self.window.dashboard_cards])

    def test_regular_shipping_file_is_not_misclassified_by_marketplace_name(self) -> None:
        order = {
            "channel": "현대홈쇼핑", "order_number": "ORDER-1",
            "product_name": "테스트 품목", "quantity": "1",
            "recipient": "홍길동", "phone": "010-1234-5678",
            "zipcode": "12345", "address": "서울시 원본 주소 1",
            "source_format": "일반 택배",
        }
        columns = {
            "channel": 0, "order_number": 1, "product_name": 2, "quantity": 3,
            "recipient": 4, "phone": 5, "zipcode": 6, "address1": 7,
        }
        sparse_order = {
            "channel": "현대면세점", "product_name": "테스트 품목", "quantity": "1",
            "recipient": "", "phone": "", "zipcode": "", "address": "",
        }
        self.window.matcher = Mock()
        self.window.matcher.match.return_value = {
            "status": "exact", "matched_product": "테스트 품목", "components": "A001",
        }
        self.window.mark_duplicates = Mock()
        with (
            patch("main.load_duty_free", return_value=None),
            patch("main.load_simple_duty_free", return_value=([sparse_order], "현대면세점")),
            patch("main.load_orders", return_value=([order], columns)),
        ):
            self.window.load_order_file("현대홈쇼핑_일반출고.xlsx", "auto")

        self.assertEqual(self.window.current_mode, "parcel")
        self.assertEqual(self.window.current_orders[0]["recipient"], "홍길동")
        self.assertEqual(self.window.current_orders[0]["phone"], "010-1234-5678")
        self.assertEqual(self.window.current_orders[0]["address"], "서울시 원본 주소 1")

    def test_mini_widget_has_two_compact_function_buttons(self) -> None:
        widget = MiniWidgetDialog(self.window)
        self.assertEqual(
            [button.property("widgetTarget") for button in widget.action_buttons],
            ["shipping", "calendar"],
        )
        self.assertEqual((widget.width(), widget.height()), (498, 500))
        self.assertEqual([button.text() for button in widget.action_buttons], ["📦  출고", "📅  일정"])
        self.assertEqual(
            widget.inventory_results.selectionMode(),
            widget.inventory_results.SelectionMode.NoSelection,
        )
        self.assertEqual(widget.inventory_results.height(), 226)
        self.assertTrue(widget.event_summary.isHidden())
        widget.close()

    def test_mini_widget_supports_quick_inventory_search(self) -> None:
        self.window.inventory_rows.extend([
            {"code": "MINT-4", "name": "민트 관련 품목 4", "headquarters_stock": 1, "wekeep_stock": 2, "safety": 0},
            {"code": "MINT-5", "name": "민트 관련 품목 5", "headquarters_stock": 1, "wekeep_stock": 2, "safety": 0},
        ])
        widget = MiniWidgetDialog(self.window)
        widget.inventory_search_input.setText("민트")
        self.assertEqual(widget.inventory_results.count(), 5)
        self.assertIn("위킵 20", widget.inventory_results.item(0).text())
        widget.inventory_search_input.setText("없는품목")
        self.assertEqual(widget.inventory_results.count(), 1)
        self.assertIn("검색 결과가 없습니다", widget.inventory_results.item(0).text())
        widget.close()

    def test_inventory_safety_stock_cell_saves_immediately(self) -> None:
        self.window.save_inventory_safety_stock = Mock(return_value=True)
        dialog = InventoryPreviewDialog(self.window)

        safety_item = dialog.table.item(0, 5)
        safety_item.setText("42")

        self.window.save_inventory_safety_stock.assert_called_once_with("QP1000C-BL", 42.0)
        dialog.close()

    def test_saving_safety_stock_updates_database_catalog_and_shared_rows(self) -> None:
        query = Mock()
        query.update.return_value = query
        query.eq.return_value = query
        query.execute.return_value = Mock(data=[])
        self.window.supabase_client = Mock()
        self.window.supabase_client.table.return_value = query
        self.window.catalog = {
            "items": [{"item_code": "QP1000C-BL", "standard_name": "QP1000C 블루", "safety_stock": 30}]
        }

        saved = self.window.save_inventory_safety_stock("QP1000C-BL", 42)

        self.assertTrue(saved)
        query.update.assert_called_once_with({"safety_stock": 42})
        self.assertEqual(self.window.catalog["items"][0]["safety_stock"], 42)
        self.assertEqual(self.window.inventory_rows[0]["safety"], 42)

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

    def test_double_clicking_empty_calendar_date_opens_new_event_dialog(self) -> None:
        selected_date = self.window.calendar_widget.selectedDate()
        self.window.calendar_events = []
        dialog = Mock()
        dialog.exec.return_value = QDialog.DialogCode.Accepted
        dialog.values.return_value = {
            "id": "new-event", "date": selected_date.toString("yyyy-MM-dd"),
            "title": "신규 일정", "info": "입력 정보", "file_paths": [],
        }
        with (
            patch("main.CalendarEventDialog", return_value=dialog) as opened,
            patch("main.save_calendar_events"),
        ):
            self.window.open_calendar_date(selected_date)

        opened.assert_called_once_with(default_date=selected_date, parent=self.window)
        self.assertEqual(self.window.calendar_events[0]["info"], "입력 정보")

    def test_double_clicking_scheduled_date_opens_saved_information(self) -> None:
        selected_date = self.window.calendar_widget.selectedDate()
        event = {
            "id": "saved-event", "date": selected_date.toString("yyyy-MM-dd"),
            "title": "기존 일정", "info": "저장된 정보", "file_paths": [],
        }
        self.window.calendar_events = [event]
        with patch.object(self.window, "open_calendar_event_row") as opened:
            self.window.open_calendar_date(selected_date)

        opened.assert_called_once_with(event)


if __name__ == "__main__":
    unittest.main()
