from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QMessageBox

from main import (
    InventoryPreviewDialog,
    InventoryMiniWidget,
    PrintOrderMiniWidget,
    CalendarMiniWidget,
    MainWindow,
    MiniWidgetDialog,
    StartupLoginDialog,
    calendar_event_from_remote,
    calendar_event_payload,
    create_app_icon,
    repair_shortcuts_on_startup,
    update_shortcuts_powershell,
)
from cs_dialog import CsManagementDialog, MarketplaceSelectionDialog, OperatorMemoEditor
from integration_account_dialog import IntegrationAccountDialog
from print_order_window import PrintOrderWindow


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

    def test_dashboard_replaces_work_cards_with_closed_mall_launcher(self) -> None:
        self.assertEqual(self.window.dashboard_cards, [])
        self.assertEqual(self.window.dashboard_status_cards, [])
        self.assertEqual(
            [button.text() for button in self.window.dashboard_nav_buttons],
            ["▦  폐쇄몰 접속", "▣  출고 관리", "▤  송장 관리", "▥  재고 관리", "▦  주간 재고조사", "▣  인쇄 발주", "▣  CS 관리", "🛠  AS 관리"],
        )

    def test_phone_authenticated_closed_malls_are_registered(self) -> None:
        phone_sites = {
            site["name"] for site in self.window.closed_mall_launcher.sites
            if site["auth_type"] == "phone"
        }
        self.assertEqual(phone_sites, {"이알아이", "삼성쇼핑몰", "한섬", "SSF", "마켓컬리", "핫트랙스(교보문고)"})

    def test_wisely_order_button_uses_short_label(self) -> None:
        self.assertEqual(self.window.wisely_mail_button.text(), "와이즐리 주문")

    def test_startup_login_uses_restored_card_design(self) -> None:
        with patch("main.load_program_login", return_value=("saved@example.com", "saved-secret")):
            dialog = StartupLoginDialog()
        self.assertEqual(dialog.size().width(), 520)
        self.assertIsNotNone(dialog.findChild(QFrame, "loginBrandCard"))
        self.assertIsNotNone(dialog.findChild(QFrame, "loginFormCard"))
        self.assertEqual(dialog.email.placeholderText(), "프로그램 계정 이메일")
        self.assertEqual(dialog.email.text(), "saved@example.com")
        self.assertEqual(dialog.password.text(), "saved-secret")
        self.assertTrue(dialog.remember_login.isChecked())
        dialog.close()

    def test_dashboard_cards_fit_their_title_in_compact_buttons(self) -> None:
        for button in self.window.dashboard_cards:
            expected_width = button.fontMetrics().horizontalAdvance(button.text()) + 64
            self.assertEqual(button.height(), 68)
            self.assertEqual(button.width(), expected_width)
            self.assertLess(button.width(), 300)

    def test_closed_mall_launcher_shows_four_sites_per_row(self) -> None:
        layout = self.window.dashboard_cards_layout
        self.assertEqual(layout.getItemPosition(0)[:2], (0, 0))
        self.assertEqual(layout.getItemPosition(3)[:2], (0, 3))
        self.assertEqual(layout.getItemPosition(4)[:2], (1, 0))

    def test_release_spec_includes_all_runtime_assets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        spec = (root / "REQM.spec").read_text(encoding="utf-8")
        self.assertIn("assets/app_icon.png", spec)
        self.assertIn('icon="assets/app_icon.ico"', spec)
        self.assertIn("assets/direct_conversion_reference.xlsx", spec)
        self.assertIn("assets/weekly_inventory_template.xlsx", spec)
        self.assertIn("assets/windows_ocr.ps1", spec)
        self.assertEqual([path.name for path in root.glob("*.spec")], ["REQM.spec"])

    def test_shared_wekeep_sku_migration_has_rls_and_admin_write_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sql = (root / "supabase" / "migrations" / "20260911_wekeep_sku_mappings.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("create table if not exists public.wekeep_sku_mappings", sql)
        self.assertIn("enable row level security", sql)
        self.assertIn("authenticated users read wekeep sku mappings", sql)
        self.assertIn("admins write wekeep sku mappings", sql)
        self.assertIn("unique index", sql)

    def test_removed_marketplace_automation_is_not_in_production_root(self) -> None:
        root = Path(__file__).resolve().parents[1]
        legacy_modules = (
            "marketplace_29cm_executor.py",
            "marketplace_automation_settings.py",
            "marketplace_bridge_server.py",
            "marketplace_catalog_store.py",
            "marketplace_option_store.py",
        )
        self.assertFalse(any((root / name).exists() for name in legacy_modules))
        extension_dir = root / "extensions" / "reqm-marketplace-bridge"
        self.assertFalse(extension_dir.exists() and any(extension_dir.iterdir()))

    def test_startup_login_is_independent_from_hidden_main_window(self) -> None:
        dialog = Mock()
        dialog.exec.return_value = QDialog.DialogCode.Rejected
        with patch("main.StartupLoginDialog", return_value=dialog) as opened:
            self.assertFalse(self.window.require_startup_login())
        opened.assert_called_once_with(None)

    def test_updater_corrects_reqm_shortcuts_and_creates_desktop_shortcut(self) -> None:
        script = update_shortcuts_powershell()

        self.assertIn("GetFolderPath('Desktop')", script)
        self.assertIn("GetFolderPath('StartMenu')", script)
        self.assertIn("User Pinned\\TaskBar", script)
        self.assertIn("$shortcut.TargetPath = $target", script)
        self.assertIn("Join-Path $desktopPath 'REQM.lnk'", script)
        self.assertIn("Shortcut corrected:", script)

    def test_updated_app_repairs_shortcuts_once_on_first_start(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch("main.subprocess.Popen") as launched:
            repair_dir = os.path.join(folder, "updates")

            started = repair_shortcuts_on_startup(
                current_exe=os.path.join(folder, "REQM.exe"),
                app_version="1.0.63",
                base_dir=os.path.abspath(repair_dir),
            )

            self.assertTrue(started)
            launched.assert_called_once()
            script_path = os.path.join(repair_dir, "repair_reqm_shortcuts_1.0.63.ps1")
            self.assertTrue(os.path.exists(script_path))
            with open(script_path, encoding="utf-8-sig") as stream:
                script = stream.read()
            self.assertIn("Startup shortcut repair:", script)
            self.assertIn("shortcut_repaired_1.0.63.txt", script)

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
        self.window.dashboard_nav_buttons[1].click()
        self.assertIs(self.window.page_stack.currentWidget(), self.window.work_page)

    def test_shipping_analysis_table_reads_from_order_to_conversion(self) -> None:
        headers = [self.window.table.horizontalHeaderItem(index).text() for index in range(self.window.table.columnCount())]
        self.assertEqual(headers[:11], [
            "수령인", "주문번호", "판매처", "원본 상품명", "원본 옵션", "주문수량", "→",
            "변환 상품명", "출고 품목코드·수량", "상태", "판정 이유",
        ])
        self.window.populate_table([{
            "recipient": "홍길동", "order_number": "O-1", "channel": "테스트몰",
            "product_name": "원본 세트", "options": "화이트", "quantity": "1",
            "matched_product": "본품 / 케이스", "components": "MAIN×1 + CASE×1",
            "status": "exact", "reason": "정확 일치",
        }])
        self.assertEqual(self.window.table.item(0, 0).text(), "홍길동")
        self.assertEqual(self.window.table.item(0, 3).text(), "원본 세트")
        self.assertEqual(self.window.table.item(0, 6).text(), "→")
        self.assertEqual(self.window.table.item(0, 7).text(), "본품\n케이스")
        self.assertEqual(self.window.table.item(0, 8).text(), "MAIN×1\nCASE×1")
        self.assertEqual(self.window.table.item(0, 9).text(), "정확")

    def test_inventory_card_opens_preview_dialog(self) -> None:
        self.window.dashboard_nav_buttons[3].click()
        self.assertIsInstance(self.window.page_stack.currentWidget(), InventoryPreviewDialog)
        self.assertIs(self.window.page_stack.currentWidget(), self.window.embedded_pages["inventory"])

    def test_weekly_inventory_card_opens_dialog(self) -> None:
        self.window.dashboard_nav_buttons[4].click()
        self.assertIs(self.window.page_stack.currentWidget(), self.window.embedded_pages["weekly_inventory"])

    def test_print_order_card_opens_management_window(self) -> None:
        self.window.dashboard_nav_buttons[5].click()
        self.assertIsInstance(self.window.page_stack.currentWidget(), PrintOrderWindow)
        self.assertIs(self.window.page_stack.currentWidget(), self.window.embedded_pages["print_order"])

    def test_cs_card_opens_shared_draft_workspace(self) -> None:
        self.window.dashboard_nav_buttons[6].click()
        self.assertIsInstance(self.window.page_stack.currentWidget(), CsManagementDialog)
        self.assertIs(self.window.page_stack.currentWidget(), self.window.embedded_pages["cs"])

    def test_cs_dialog_keeps_naver_actions_disabled_before_api_connection(self) -> None:
        dialog = CsManagementDialog()
        self.assertFalse(dialog.sync_button.isEnabled())
        self.assertTrue(dialog.convert_button.isEnabled())
        self.assertFalse(dialog.send_button.isEnabled())
        dialog.close()

    def test_marketplace_popup_lists_current_and_future_sales_channels(self) -> None:
        dialog = MarketplaceSelectionDialog("naver")
        labels = [dialog.market_list.item(index).text() for index in range(dialog.market_list.count())]
        self.assertTrue(any("네이버 스마트스토어" in label for label in labels))
        self.assertTrue(any("쿠팡" in label for label in labels))
        self.assertTrue(any("11번가" in label for label in labels))
        self.assertTrue(any("전체 판매처" in label for label in labels))
        dialog.close()

    def test_cs_dialog_sample_can_be_converted_without_naver_credentials(self) -> None:
        dialog = CsManagementDialog()
        dialog.load_sample_cases()
        self.assertEqual(dialog.current_case["product_model"], "QP1000C")
        dialog.convert_note()
        self.assertIn("사용과 충전을 즉시 중단", dialog.draft.toPlainText())
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.close()

    def test_operator_memo_editor_separates_customer_and_internal_content(self) -> None:
        editor = OperatorMemoEditor()
        editor.customer_guidance.setPlainText("베이지 색상으로 교환 가능합니다.")
        editor.customer_requests.setPlainText("제품 사진을 첨부해 주세요.")
        editor.processing_results.setPlainText("교환 재고를 확보했습니다.")
        editor.internal_notes.setPlainText("물류팀 확인 완료")
        saved = editor.toPlainText()
        self.assertIn("고객 안내: 베이지", saved)
        self.assertIn("고객 요청: 제품 사진", saved)
        self.assertIn("처리 결과: 교환 재고", saved)
        self.assertIn("내부 메모: 물류팀", saved)
        editor.close()

    def test_operator_memo_editor_loads_legacy_unlabelled_note_as_internal(self) -> None:
        editor = OperatorMemoEditor()
        editor.setPlainText("예전에 저장한 형식 없는 작업자 메모")
        self.assertEqual(editor.internal_notes.toPlainText(), "예전에 저장한 형식 없는 작업자 메모")
        self.assertFalse(editor.customer_guidance.toPlainText())
        editor.close()

    def test_separated_customer_guidance_is_added_to_generated_draft(self) -> None:
        dialog = CsManagementDialog()
        dialog.load_sample_cases()
        dialog.operator_note.clear()
        dialog.operator_note.customer_guidance.setPlainText("회수 접수 후 베이지 색상으로 교환 가능합니다.")
        dialog.operator_note.internal_notes.setPlainText("물류팀 재고 확인 완료")
        dialog.convert_note()
        answer = dialog.draft.toPlainText()
        self.assertIn("베이지 색상으로 교환", answer)
        self.assertNotIn("물류팀", answer)
        dialog.close()

    def test_cs_dialog_automatically_generates_draft_from_question(self) -> None:
        dialog = CsManagementDialog()
        dialog.load_sample_cases()
        self.assertIn("사용과 충전을 즉시 중단", dialog.draft.toPlainText())
        self.assertIn("안전_팽창", dialog.analysis_summary.text())
        self.assertIn("긴급 안전", dialog.analysis_summary.text())
        self.assertIn("즉시 사용 중단", dialog.reply_basis.toPlainText())
        self.assertIn("수동 전송 모드", dialog.manual_send_notice.text())
        self.assertEqual(dialog.send_button.text(), "검토 완료 후 수동 전송")
        dialog.close()

    def test_cs_dialog_splits_order_context_into_readable_fields(self) -> None:
        dialog = CsManagementDialog()
        dialog.inquiry_list.clear()
        case = {
            "_sample": True,
            "id": "sample-order",
            "channel": "order_inquiry",
            "question": "배송 상태를 알려주세요",
            "product_order_id": "202609250001",
            "product_model": "QPD330",
            "category": "리큐엠 QPD330 / 옵션: 블랙 / 주문상태: 배송 중 / 수량: 2",
        }
        dialog.inquiry_list.addItem("주문 문의")
        dialog.inquiry_list.item(0).setData(Qt.ItemDataRole.UserRole, case)
        dialog.inquiry_list.setCurrentRow(0)
        context = dialog.order_context.toPlainText()
        self.assertIn("상품명: 리큐엠 QPD330", context)
        self.assertIn("옵션: 블랙", context)
        self.assertIn("주문상태: 배송 중", context)
        self.assertIn("수량: 2", context)
        dialog.close()

    def test_cs_dialog_applies_worker_edited_answer_for_matching_case(self) -> None:
        dialog = CsManagementDialog()
        dialog.repository.find_reusable_answer = Mock(return_value={"final_answer": "검수된 공용 답변"})
        dialog.load_sample_cases()
        self.assertEqual(dialog.draft.toPlainText(), "검수된 공용 답변")
        self.assertIn("작업자가 수정한 답변", dialog.draft_source.text())
        dialog.close()

    def test_cs_dialog_sends_saved_product_qna_and_marks_it_complete(self) -> None:
        dialog = CsManagementDialog()
        dialog.naver_client = Mock()
        dialog.repository = Mock()
        dialog.repository.list_cases.return_value = []
        dialog.current_case = {
            "id": "case-1", "external_id": "42", "channel": "product_qna",
        }
        dialog.current_draft_id = "draft-1"
        dialog.draft.setPlainText("고객 안내 답변")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning"):
            dialog.send_to_naver()
        dialog.naver_client.answer_product_qna.assert_called_once_with("42", "고객 안내 답변")
        dialog.repository.mark_sent.assert_called_once_with(
            case_id="case-1", draft_id="draft-1", external_id="42",
        )
        dialog.close()

    def test_cs_dialog_syncs_product_and_order_inquiries_together(self) -> None:
        dialog = CsManagementDialog()
        dialog.naver_client = Mock()
        dialog.naver_client.product_qnas.return_value = [{
            "questionId": 42, "question": "충전이 안 됩니다", "productId": 100,
            "productName": "리큐엠 QP1000C", "createDate": "2026-09-25T09:00:00+09:00",
        }]
        dialog.naver_client.customer_inquiry_search_period.return_value = ("2026-08-26", "2026-09-25")
        dialog.naver_client.customer_inquiries.return_value = [{
            "inquiryNo": 77, "title": "배송 문의", "inquiryContent": "언제 출고되나요?",
            "productOrderIdList": "202609250001", "productNo": 200,
            "productName": "리큐엠 QPD330", "productOrderOption": "블랙",
            "inquiryRegistrationDateTime": "2026-09-25T10:00:00+09:00",
        }]
        dialog.naver_client.product_orders.return_value = [{"productOrder": {
            "productOrderId": "202609250001", "productName": "리큐엠 QPD330",
            "productOption": "블랙", "productOrderStatus": "DELIVERED", "remainQuantity": 1,
        }}]
        dialog.repository = Mock()
        dialog.repository.upsert_cases.return_value = 2
        dialog.repository.list_cases.return_value = []
        with patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning"):
            dialog.sync_naver_inquiries()
        cases = dialog.repository.upsert_cases.call_args.args[0]
        self.assertEqual([case["channel"] for case in cases], ["product_qna", "order_inquiry"])
        self.assertEqual(cases[1]["product_order_id"], "202609250001")
        self.assertEqual(cases[1]["product_model"], "QPD330")
        self.assertEqual(cases[1]["question"], "배송 문의\n\n언제 출고되나요?")
        self.assertIn("주문상태: 배송 완료", cases[1]["category"])
        dialog.close()

    def test_cs_dialog_sends_saved_order_inquiry_and_marks_it_complete(self) -> None:
        dialog = CsManagementDialog()
        dialog.naver_client = Mock()
        dialog.repository = Mock()
        dialog.repository.list_cases.return_value = []
        dialog.current_case = {"id": "case-2", "external_id": "77", "channel": "order_inquiry"}
        dialog.current_draft_id = "draft-2"
        dialog.draft.setPlainText("주문 고객 안내 답변")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning"):
            dialog.send_to_naver()
        dialog.naver_client.answer_customer_inquiry.assert_called_once_with("77", "주문 고객 안내 답변")
        dialog.repository.mark_sent.assert_called_once_with(
            case_id="case-2", draft_id="draft-2", external_id="77",
        )
        dialog.close()

    def test_naver_connection_test_requires_both_credentials(self) -> None:
        with patch("integration_account_dialog.load_integration_credentials", return_value={
            "ecount_user_id": "", "ecount_password": "", "ecount_api_key": "",
            "print_board_user_id": "", "print_board_password": "",
            "webmail_user_id": "", "webmail_password": "",
            "wekeep_user_id": "", "wekeep_password": "",
        }), patch("integration_account_dialog.load_naver_credentials", return_value={
            "client_id": "", "client_secret": "",
        }), patch.object(QMessageBox, "information") as message:
            dialog = IntegrationAccountDialog()
            dialog.test_naver_connection()
        message.assert_called_once()
        self.assertIn("모두 입력", message.call_args.args[2])
        dialog.close()

    def test_naver_connection_test_queries_unanswered_qna(self) -> None:
        with patch("integration_account_dialog.load_integration_credentials", return_value={
            "ecount_user_id": "", "ecount_password": "", "ecount_api_key": "",
            "print_board_user_id": "", "print_board_password": "",
            "webmail_user_id": "", "webmail_password": "",
            "wekeep_user_id": "", "wekeep_password": "",
        }), patch("integration_account_dialog.load_naver_credentials", return_value={
            "client_id": "", "client_secret": "",
        }), patch("integration_account_dialog.NaverCommerceClient") as client_class, \
                patch("integration_account_dialog.save_naver_credentials") as save_naver, \
                patch.object(QMessageBox, "information") as message:
            client_class.return_value.product_qnas.return_value = [{"questionId": 1}]
            dialog = IntegrationAccountDialog()
            dialog.naver_client_id.setText("client")
            dialog.naver_client_secret.setText("secret")
            dialog.test_naver_connection()
        client_class.return_value.product_qnas.assert_called_once_with(answered=False, page=1, size=10)
        save_naver.assert_called_once_with("client", "secret")
        self.assertIn("1건", message.call_args.args[2])
        dialog.close()

    def test_dashboard_integration_account_button_opens_dialog(self) -> None:
        with patch("main.IntegrationAccountDialog") as dialog_class:
            self.window.dashboard_accounts_button.click()
        dialog_class.assert_called_once_with(self.window)
        dialog_class.return_value.exec.assert_called_once()

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

    def test_inventory_mini_widget_is_an_independent_window(self) -> None:
        widget = InventoryMiniWidget(self.window)
        self.assertEqual(widget.windowTitle(), "재고 위젯")
        self.assertEqual((widget.width(), widget.height()), (650, 500))
        widget.resize(760, 610)
        self.assertEqual((widget.width(), widget.height()), (760, 610))
        self.assertEqual(
            widget.inventory_results.selectionMode(),
            widget.inventory_results.SelectionMode.NoSelection,
        )
        widget.close()

    def test_mini_widget_saves_user_selected_size(self) -> None:
        with patch("main.save_widget_position") as save_geometry:
            widget = CalendarMiniWidget(self.window)
            widget.show(); self.app.processEvents()
            widget.resize(540, 640); self.app.processEvents()
            widget.close()
        save_geometry.assert_called_with("calendar", widget.x(), widget.y(), 540, 640)

    def test_print_and_calendar_widgets_are_separate_windows(self) -> None:
        print_widget = PrintOrderMiniWidget(self.window)
        calendar_widget = CalendarMiniWidget(self.window)
        self.assertEqual(print_widget.windowTitle(), "인쇄 발주 위젯")
        self.assertEqual(calendar_widget.windowTitle(), "일정 위젯")
        self.assertEqual(list(print_widget.status_labels), ["신규 접수", "인쇄 진행", "패킹 진행", "출고 대기"])
        self.assertEqual(calendar_widget.today_events.count(), 1)
        print_widget.close(); calendar_widget.close()

    def test_dashboard_opens_all_three_independent_widgets(self) -> None:
        with patch("main.save_widget_position"):
            self.window.open_mini_widget()
            self.assertEqual(set(self.window.mini_widgets), {"inventory", "print_order", "calendar"})
            self.assertEqual(
                {widget.windowTitle() for widget in self.window.mini_widgets.values()},
                {"재고 위젯", "인쇄 발주 위젯", "일정 위젯"},
            )
            for widget in self.window.mini_widgets.values():
                self.assertTrue(widget.windowFlags() & widget.windowFlags().WindowStaysOnTopHint)
                widget.close()

    def test_mini_widget_supports_quick_inventory_search(self) -> None:
        self.window.inventory_rows.extend([
            {"code": "MINT-4", "name": "민트 관련 품목 4", "headquarters_stock": 1, "wekeep_stock": 2, "safety": 0},
            {"code": "MINT-5", "name": "민트 관련 품목 5", "headquarters_stock": 1, "wekeep_stock": 2, "safety": 0},
        ])
        widget = InventoryMiniWidget(self.window)
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

    def test_independent_widget_buttons_route_to_each_function(self) -> None:
        widget = InventoryMiniWidget(self.window)
        self.window.open_inventory_preview = Mock()
        self.window.show_dashboard = Mock()
        widget.open_target("inventory")
        self.window.open_inventory_preview.assert_called_once_with()
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
