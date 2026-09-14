"""Select a persisted WeKeep job, fetch invoices, and export once complete."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from shipment_job_store import ShipmentJobStore
from wekeep_tracking_service import (apply_manual_tracking_number, export_tracking_workbook,
                                     fetch_wekeep_tracking_rows, manual_tracking_candidate_indexes,
                                     reconcile_tracking_numbers)
from wekeep_upload_file import ORDER_KIND_LABELS


class TrackingWorker(QThread):
    succeeded = Signal(str, list)
    failed = Signal(str)

    def __init__(self, job_id: str, orders: list[dict], registered_date: date, order_kind: str, parent=None) -> None:
        super().__init__(parent)
        self.job_id, self.orders = job_id, orders
        self.registered_date, self.order_kind = registered_date, order_kind

    def run(self) -> None:
        try:
            lookup_kind = "b2b" if self.order_kind == "b2b_buying" else self.order_kind
            remote = fetch_wekeep_tracking_rows(self.registered_date, lookup_kind)
            self.succeeded.emit(self.job_id, reconcile_tracking_numbers(self.orders, remote))
        except Exception as exc:
            self.failed.emit(str(exc))


class ManualTrackingDialog(QDialog):
    """Review the selected order and every invoice target before manual entry."""

    def __init__(self, rows: list[dict], selected_index: int, parent=None) -> None:
        super().__init__(parent)
        self.rows = rows
        self.selected_index = selected_index
        self.candidate_indexes = manual_tracking_candidate_indexes(rows, selected_index)
        self.setWindowTitle("송장번호 직접 입력")
        self.resize(1180, 620)
        selected = rows[selected_index]

        title = QLabel("송장번호 직접 입력"); title.setObjectName("dialogTitle")
        guide = QLabel("선택한 주문과 합포장 적용 대상을 확인한 후 송장번호를 입력하세요.")
        guide.setObjectName("dialogGuide")
        summary = QGridLayout(); summary.setHorizontalSpacing(14); summary.setVerticalSpacing(7)
        fields = [
            ("주문번호", selected.get("order_number", "")), ("우편번호", selected.get("zipcode", "")),
            ("수령인", selected.get("recipient", "")), ("주소", selected.get("address", "")),
            ("전화번호", selected.get("phone", "")), ("상품명", selected.get("product_name", "")),
        ]
        for position, (label, value) in enumerate(fields):
            row, pair = divmod(position, 2); column = pair * 2
            label_widget = QLabel(label); label_widget.setStyleSheet("font-weight: 700;")
            value_widget = QLabel(str(value or "-")); value_widget.setWordWrap(True)
            summary.addWidget(label_widget, row, column); summary.addWidget(value_widget, row, column + 1)
        summary.setColumnStretch(1, 1); summary.setColumnStretch(3, 1)

        order_count = len({str(rows[index].get("order_number") or index) for index in self.candidate_indexes})
        section = QLabel(f"합포장 적용 대상 {order_count}건"); section.setObjectName("sectionTitle")
        warning = QLabel("아래에서 체크한 주문에 같은 송장번호가 적용됩니다. 주문정보를 확인하고 적용 대상을 조정할 수 있습니다.")
        warning.setWordWrap(True)
        warning.setStyleSheet("background:#fff4e8;color:#b45309;padding:9px;border:1px solid #fdba74;border-radius:5px;")
        self.target_table = QTableWidget(len(self.candidate_indexes), 7)
        self.target_table.setHorizontalHeaderLabels(["적용", "주문번호", "수령인", "전화번호", "우편번호", "주소", "상품명"])
        self.target_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.target_table.verticalHeader().setVisible(False); self.target_table.setAlternatingRowColors(True)
        self.target_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.target_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.target_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for table_row, source_index in enumerate(self.candidate_indexes):
            row = rows[source_index]
            check = QTableWidgetItem(""); check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked); check.setData(Qt.ItemDataRole.UserRole, source_index)
            self.target_table.setItem(table_row, 0, check)
            values = [row.get("order_number", ""), row.get("recipient", ""), row.get("phone", ""),
                      row.get("zipcode", ""), row.get("address", ""), row.get("product_name", "")]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value or "")); item.setToolTip(str(value or ""))
                self.target_table.setItem(table_row, column, item)

        input_row = QHBoxLayout(); input_row.addWidget(QLabel("송장번호"))
        self.tracking_input = QLineEdit(); self.tracking_input.setPlaceholderText("숫자 8~20자리 입력")
        self.tracking_input.setText(str(selected.get("tracking_number") or "")); input_row.addWidget(self.tracking_input, 1)
        self.apply_summary = QLabel("")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("확인 후 적용")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(self.validate_and_accept); self.buttons.rejected.connect(self.reject)
        self.target_table.itemChanged.connect(self.refresh_apply_summary)
        self.tracking_input.textChanged.connect(self.refresh_apply_summary)

        layout = QVBoxLayout(self); layout.addWidget(title); layout.addWidget(guide); layout.addLayout(summary)
        layout.addWidget(section); layout.addWidget(warning); layout.addWidget(self.target_table, 1)
        layout.addLayout(input_row); layout.addWidget(self.apply_summary); layout.addWidget(self.buttons)
        self.refresh_apply_summary()

    def selected_target_indexes(self) -> list[int]:
        return [
            int(self.target_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(self.target_table.rowCount())
            if self.target_table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]

    def refresh_apply_summary(self, *_args) -> None:
        order_count = len({str(self.rows[index].get("order_number") or index) for index in self.selected_target_indexes()})
        number = self.tracking_input.text().strip() or "미입력"
        self.apply_summary.setText(f"입력 송장번호: {number} · 적용 주문 {order_count}건")

    def validate_and_accept(self) -> None:
        if not self.selected_target_indexes():
            QMessageBox.warning(self, "적용 대상 확인", "송장번호를 적용할 주문을 한 건 이상 선택해 주세요."); return
        try:
            apply_manual_tracking_number(
                self.rows, self.selected_index, self.tracking_input.text(), self.selected_target_indexes(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "송장번호 입력 확인", str(exc)); return
        self.accept()


class WeKeepTrackingDialog(QDialog):
    def __init__(self, orders: list[dict] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.store = ShipmentJobStore(); self.jobs = []; self.visible_jobs = []
        self.selected_job = None; self.results = []; self.worker = None
        self.setWindowTitle("위킵 송장번호 가져오기"); self.resize(1220, 760)
        title = QLabel("송장번호 가져오기"); title.setObjectName("dialogTitle")
        guide = QLabel("이전에 위킵에 등록한 출고 작업을 선택해 송장번호를 조회합니다. 모든 송장이 확인되면 최종 Excel을 한 번 저장합니다.")
        guide.setObjectName("dialogGuide"); guide.setWordWrap(True)
        self.start_date = QDateEdit(QDate.currentDate().addDays(-30)); self.start_date.setCalendarPopup(True); self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date = QDateEdit(QDate.currentDate()); self.end_date.setCalendarPopup(True); self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.search = QLineEdit(); self.search.setPlaceholderText("파일명·수령인·주문번호 검색")
        self.search_button = QPushButton("조회")
        filters = QHBoxLayout()
        for widget in (QLabel("출고 작업일"), self.start_date, QLabel("~"), self.end_date, self.search, self.search_button): filters.addWidget(widget)
        filters.setStretch(4, 1)
        self.job_table = QTableWidget(0, 7)
        self.job_table.setHorizontalHeaderLabels(["선택", "출고일", "작업명", "판매처", "주문", "송장 확인", "상태"])
        self.job_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.job_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.job_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection); self.job_table.verticalHeader().setVisible(False)
        self.summary = QLabel("조회할 출고 작업을 선택해 주세요."); self.summary.setObjectName("dialogSummary")
        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(["상태", "주문번호", "수령인", "상품명", "송장번호", "확인 내용"])
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.result_table.verticalHeader().setVisible(False)
        self.fetch_button = QPushButton("선택 작업 송장 재조회"); self.fetch_button.setObjectName("primaryButton"); self.fetch_button.setEnabled(False)
        self.retry_button = QPushButton("미등록 확인·재등록 허용"); self.retry_button.setEnabled(False)
        self.manual_button = QPushButton("선택 주문 송장 직접 입력"); self.manual_button.setEnabled(False)
        self.save_button = QPushButton("최종 Excel 저장"); self.save_button.setEnabled(False)
        self.close_button = QPushButton("닫기")
        buttons = QHBoxLayout(); buttons.addStretch(1); buttons.addWidget(self.close_button); buttons.addWidget(self.retry_button); buttons.addWidget(self.manual_button); buttons.addWidget(self.save_button); buttons.addWidget(self.fetch_button)
        layout = QVBoxLayout(self); layout.addWidget(title); layout.addWidget(guide); layout.addLayout(filters); layout.addWidget(self.job_table, 1)
        layout.addWidget(self.summary); layout.addWidget(self.result_table, 2); layout.addLayout(buttons)
        self.search_button.clicked.connect(self.load_jobs); self.search.returnPressed.connect(self.load_jobs)
        self.start_date.dateChanged.connect(self.load_jobs); self.end_date.dateChanged.connect(self.load_jobs)
        self.job_table.itemSelectionChanged.connect(self.select_job); self.fetch_button.clicked.connect(self.fetch_tracking)
        self.result_table.itemSelectionChanged.connect(self.update_manual_button)
        self.retry_button.clicked.connect(self.allow_retry)
        self.manual_button.clicked.connect(self.enter_tracking_manually)
        self.save_button.clicked.connect(self.save_excel); self.close_button.clicked.connect(self.accept)
        self.load_jobs()

    @staticmethod
    def _job_date(job: dict) -> date:
        try: return datetime.fromisoformat(str(job.get("created_at", "")).replace("Z", "+00:00")).date()
        except ValueError: return date.today()

    @staticmethod
    def _payload_rows(job: dict) -> list[dict]:
        payload = job.get("payload") or {}
        return list(payload.get("export_rows") or payload.get("rows") or [])

    def load_jobs(self) -> None:
        selected_id = str((self.selected_job or {}).get("id") or "")
        self.jobs = self.store.list_recent(limit=200, include_payload=True)
        start, end, query = self.start_date.date().toPython(), self.end_date.date().toPython(), self.search.text().strip().casefold()
        self.visible_jobs = []
        for job in self.jobs:
            payload, rows = job.get("payload") or {}, self._payload_rows(job)
            searchable = " ".join([str(payload.get("source_name") or ""), *(str(row.get(key) or "") for row in rows for key in ("order_number", "recipient", "channel"))]).casefold()
            if start <= self._job_date(job) <= end and (not query or query in searchable): self.visible_jobs.append(job)
        self.job_table.setRowCount(len(self.visible_jobs)); select_index = -1
        for index, job in enumerate(self.visible_jobs):
            rows, payload = self._payload_rows(job), job.get("payload") or {}
            order_count = len({str(row.get("order_number") or row_index) for row_index, row in enumerate(rows)})
            matched, total = int(job.get("matched_count") or 0), int(job.get("tracking_total_count") or order_count)
            status = "등록 확인 필요" if job.get("state") == "unknown" else ("확인 완료" if total and matched == total else (f"{max(total-matched, 0)}건 발급 대기" if matched else "조회 전"))
            values = ["○", self._job_date(job).isoformat(), payload.get("source_name") or f"작업 {job['id'][:8]}",
                      ORDER_KIND_LABELS.get(str(job.get("order_kind")), str(job.get("order_kind", ""))), f"{order_count}건", f"{matched} / {total}", status]
            for column, value in enumerate(values): self.job_table.setItem(index, column, QTableWidgetItem(str(value)))
            if job["id"] == selected_id: select_index = index
        self.job_table.resizeColumnsToContents()
        if self.visible_jobs: self.job_table.selectRow(select_index if select_index >= 0 else 0)
        else:
            self.selected_job = None; self.results = []; self.result_table.setRowCount(0)
            self.summary.setText("조건에 맞는 위킵 출고 작업이 없습니다."); self.fetch_button.setEnabled(False); self.retry_button.setEnabled(False); self.manual_button.setEnabled(False); self.save_button.setEnabled(False)

    def select_job(self) -> None:
        index = self.job_table.currentRow()
        if not 0 <= index < len(self.visible_jobs): return
        self.selected_job = self.visible_jobs[index]; self.results = self.store.load_tracking_results(self.selected_job["id"])
        uncertain = self.selected_job.get("state") == "unknown"
        self.fetch_button.setText("위킵 등록 여부 확인" if uncertain else "선택 작업 송장 재조회")
        not_found = bool(self.results) and any(row.get("tracking_match_state") not in {"matched", "pending"} for row in self.results)
        self.fetch_button.setEnabled(True); self.retry_button.setEnabled(uncertain and not_found); self.show_results()

    def update_manual_button(self) -> None:
        self.manual_button.setEnabled(bool(self.selected_job and 0 <= self.result_table.currentRow() < len(self.results)))

    def show_results(self) -> None:
        grouped = {}
        for index, row in enumerate(self.results):
            grouped.setdefault(str(row.get("order_number") or index), []).append(row)
        matched = sum(all(row.get("tracking_match_state") == "matched" for row in rows) for rows in grouped.values())
        pending = sum(any(row.get("tracking_match_state") in {"pending", "not_found"} for row in rows) for rows in grouped.values())
        review = len(grouped) - matched - pending
        name = str(((self.selected_job or {}).get("payload") or {}).get("source_name") or "선택 작업")
        self.summary.setText(f"{name} · 확인 {matched:,} · 발급 대기 {pending:,} · 검토 {review:,}")
        self.save_button.setEnabled(bool(self.results) and matched == len(grouped))
        self.result_table.setRowCount(len(self.results))
        labels = {"matched": "확인 완료", "pending": "발급 대기", "review": "검토 필요", "not_found": "조회 안 됨"}
        colors = {"matched": "#d9ead3", "pending": "#fff2cc", "review": "#fce5cd", "not_found": "#f4cccc"}
        for row_index, row in enumerate(self.results):
            state = str(row.get("tracking_match_state") or "review")
            values = [labels.get(state, state), row.get("order_number", ""), row.get("recipient", ""),
                      row.get("product_name", ""), row.get("tracking_number", ""), row.get("tracking_match_reason", "")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setBackground(QColor(colors.get(state, "#fce5cd"))); self.result_table.setItem(row_index, column, item)
        self.result_table.resizeColumnsToContents()
        self.update_manual_button()

    def enter_tracking_manually(self) -> None:
        row_index = self.result_table.currentRow()
        if not self.selected_job or not 0 <= row_index < len(self.results):
            return
        dialog = ManualTrackingDialog(self.results, row_index, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.results = apply_manual_tracking_number(
                self.results, row_index, dialog.tracking_input.text(), dialog.selected_target_indexes(),
            )
            self.store.save_tracking_results(self.selected_job["id"], self.results)
        except ValueError as exc:
            QMessageBox.warning(self, "송장번호 입력 확인", str(exc)); return
        self.show_results(); self.load_jobs()

    def fetch_tracking(self) -> None:
        if not self.selected_job: return
        self.fetch_button.setEnabled(False); self.save_button.setEnabled(False); self.close_button.setEnabled(False)
        self.summary.setText("위킵 주문과 송장번호 조회 중...")
        self.worker = TrackingWorker(self.selected_job["id"], self._payload_rows(self.selected_job), self._job_date(self.selected_job), str(self.selected_job["order_kind"]), self)
        self.worker.succeeded.connect(self.on_succeeded); self.worker.failed.connect(self.on_failed); self.worker.start()

    def on_succeeded(self, job_id: str, rows: list[dict]) -> None:
        previous = self.store.load_tracking_results(job_id)
        for index, row in enumerate(rows):
            if index < len(previous) and previous[index].get("tracking_match_state") == "matched" and row.get("tracking_match_state") != "matched": rows[index] = previous[index]
        self.results = rows; self.store.save_tracking_results(job_id, rows)
        if self.selected_job and self.selected_job.get("state") == "unknown":
            remote_found = bool(rows) and all(row.get("tracking_match_state") in {"matched", "pending"} for row in rows)
            if remote_found:
                self.store.transition(job_id, "completed", detail="위킵 주문 목록 재확인 완료")
                self.selected_job["state"] = "completed"
                self.retry_button.setEnabled(False)
            else:
                self.retry_button.setEnabled(True)
        self.fetch_button.setEnabled(True); self.close_button.setEnabled(True); self.show_results(); self.load_jobs()

    def on_failed(self, message: str) -> None:
        self.fetch_button.setEnabled(True); self.close_button.setEnabled(True); self.summary.setText("송장 조회 실패")
        QMessageBox.critical(self, "위킵 송장 조회 실패", message)

    def allow_retry(self) -> None:
        if not self.selected_job or self.selected_job.get("state") != "unknown":
            return
        answer = QMessageBox.question(
            self, "재등록 허용",
            "조회 결과 위킵에 등록되지 않은 주문임을 확인하셨습니까?\n\n"
            "확인 후 재등록을 허용하면 같은 출고 작업을 다시 위킵에 전송할 수 있습니다. 위킵에 이미 존재하는 주문이면 중복 등록될 수 있습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.transition(self.selected_job["id"], "failed", detail="작업자 확인: 위킵 미등록, 재등록 허용")
        self.selected_job = None; self.results = []; self.retry_button.setEnabled(False)
        self.load_jobs()
        QMessageBox.information(self, "재등록 허용 완료", "해당 미확인 작업의 중복 차단을 해제했습니다. 원본 주문 파일을 다시 불러와 위킵 반영을 진행하세요.")

    def save_excel(self) -> None:
        if not self.selected_job or not self.results or any(row.get("tracking_match_state") != "matched" for row in self.results):
            QMessageBox.information(self, "최종 Excel 저장 대기", "모든 주문의 송장번호가 확인된 뒤 최종 Excel을 저장할 수 있습니다."); return
        payload = self.selected_job.get("payload") or {}; source = Path(str(payload.get("source_name") or "위킵_택배출고")).stem
        file_path, _ = QFileDialog.getSaveFileName(self, "최종 송장 Excel 저장", f"{source}_송장완료.xlsx", "Excel 파일 (*.xlsx)")
        if not file_path: return
        if not file_path.lower().endswith(".xlsx"): file_path += ".xlsx"
        try:
            export_tracking_workbook(self.results, file_path, dict(payload.get("output_profile") or {"id": "default_b2c"}))
            self.store.mark_tracking_exported(self.selected_job["id"]); os.startfile(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "최종 Excel 저장 실패", str(exc)); return
        QMessageBox.information(self, "최종 Excel 저장 완료", f"전체 주문과 송장번호가 포함된 파일을 저장했습니다.\n\n{file_path}")

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "송장 조회 중", "조회가 끝날 때까지 창을 닫을 수 없습니다."); event.ignore(); return
        super().closeEvent(event)
