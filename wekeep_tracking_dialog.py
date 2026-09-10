"""Dialog for fetching and exporting WeKeep tracking numbers."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QDateEdit, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from wekeep_tracking_service import export_tracking_workbook, fetch_wekeep_tracking_rows, reconcile_tracking_numbers


class TrackingWorker(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, orders: list[dict], registered_date: date, order_kind: str, parent=None) -> None:
        super().__init__(parent)
        self.orders, self.registered_date, self.order_kind = orders, registered_date, order_kind

    def run(self) -> None:
        try:
            self.succeeded.emit(reconcile_tracking_numbers(self.orders, fetch_wekeep_tracking_rows(self.registered_date, self.order_kind)))
        except Exception as exc:
            self.failed.emit(str(exc))


class WeKeepTrackingDialog(QDialog):
    def __init__(self, orders: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.orders = [dict(row) for row in orders]
        self.results: list[dict] = []
        self.worker: TrackingWorker | None = None
        self.setWindowTitle("위킵 송장번호 가져오기")
        self.resize(1120, 650)
        title = QLabel("위킵 송장번호 가져오기"); title.setObjectName("dialogTitle")
        guide = QLabel("위킵 등록일과 판매처를 선택하면 백그라운드로 주문을 조회합니다. 확인된 송장만 기존 택배출고 양식 J열에 입력합니다.")
        guide.setObjectName("dialogGuide"); guide.setWordWrap(True)
        self.date_edit = QDateEdit(QDate.currentDate()); self.date_edit.setCalendarPopup(True); self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.kind = QComboBox()
        for label, value in (("B2C", "b2c"), ("B2C 사입형", "b2c_buying"), ("B2B", "b2b")):
            self.kind.addItem(label, value)
        self.fetch_button = QPushButton("송장번호 가져오기"); self.fetch_button.setObjectName("primaryButton")
        self.save_button = QPushButton("송장 입력 Excel 저장"); self.save_button.setEnabled(False)
        self.close_button = QPushButton("닫기")
        self.summary = QLabel("조회할 위킵 등록일을 선택해 주세요."); self.summary.setObjectName("dialogSummary")
        controls = QHBoxLayout()
        for widget in (QLabel("위킵 등록일"), self.date_edit, QLabel("판매처"), self.kind, self.fetch_button): controls.addWidget(widget)
        controls.addStretch(1); controls.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["상태", "주문번호", "수령인", "상품명", "송장번호", "확인 내용"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        buttons = QHBoxLayout(); buttons.addStretch(1); buttons.addWidget(self.close_button); buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self); layout.addWidget(title); layout.addWidget(guide); layout.addLayout(controls); layout.addWidget(self.table, 1); layout.addLayout(buttons)
        self.fetch_button.clicked.connect(self.fetch_tracking); self.save_button.clicked.connect(self.save_excel); self.close_button.clicked.connect(self.accept)

    def fetch_tracking(self) -> None:
        self.fetch_button.setEnabled(False); self.save_button.setEnabled(False); self.close_button.setEnabled(False)
        self.summary.setText("위킵 주문과 송장번호 조회 중...")
        selected = self.date_edit.date()
        self.worker = TrackingWorker(self.orders, date(selected.year(), selected.month(), selected.day()), str(self.kind.currentData()), self)
        self.worker.succeeded.connect(self.on_succeeded); self.worker.failed.connect(self.on_failed); self.worker.start()

    def on_succeeded(self, rows: list[dict]) -> None:
        self.results = rows; self.fetch_button.setEnabled(True); self.close_button.setEnabled(True)
        matched = sum(row.get("tracking_match_state") == "matched" for row in rows)
        pending = sum(row.get("tracking_match_state") == "pending" for row in rows)
        review = len(rows) - matched - pending
        self.summary.setText(f"확인 {matched:,} · 발급 대기 {pending:,} · 검토 {review:,}"); self.save_button.setEnabled(matched > 0)
        self.table.setRowCount(len(rows))
        labels = {"matched": "확인 완료", "pending": "발급 대기", "review": "검토 필요", "not_found": "조회 안 됨"}
        colors = {"matched": "#d9ead3", "pending": "#fff2cc", "review": "#fce5cd", "not_found": "#f4cccc"}
        for row_index, row in enumerate(rows):
            state = str(row.get("tracking_match_state") or "review")
            values = [labels.get(state, state), row.get("order_number", ""), row.get("recipient", ""), row.get("product_name", ""), row.get("tracking_number", ""), row.get("tracking_match_reason", "")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setBackground(QColor(colors.get(state, "#fce5cd"))); item.setToolTip(str(value)); self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()

    def on_failed(self, message: str) -> None:
        self.fetch_button.setEnabled(True); self.close_button.setEnabled(True); self.summary.setText("송장 조회 실패")
        QMessageBox.critical(self, "위킵 송장 조회 실패", message)

    def save_excel(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(self, "송장 입력 파일 저장", "위킵_택배출고_송장완료.xlsx", "Excel 파일 (*.xlsx)")
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            export_tracking_workbook(self.results, file_path)
        except Exception as exc:
            QMessageBox.critical(self, "송장 Excel 저장 실패", str(exc))
            return
        QMessageBox.information(self, "송장 Excel 저장 완료", f"확인된 송장번호를 기존 택배출고 양식에 입력했습니다.\n\n{file_path}")

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "송장 조회 중", "조회가 끝날 때까지 창을 닫을 수 없습니다.")
            event.ignore()
            return
        super().closeEvent(event)
