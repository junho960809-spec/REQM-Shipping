from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QThread, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from as_daily_export import export_as_daily
from as_site_client import AsSiteClient, load_as_credentials, save_as_credentials


SETTINGS_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "as_daily_settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class FetchWorker(QThread):
    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, user_id: str, password: str, start: str, end: str, receipt_type: str, status: str) -> None:
        super().__init__()
        self.args = user_id, password, start, end, receipt_type, status

    def run(self) -> None:
        try:
            user_id, password, start, end, receipt_type, status = self.args
            client = AsSiteClient(user_id, password)
            client.login()
            self.loaded.emit(client.fetch_records(start, end, receipt_type, status))
        except Exception as exc:
            self.failed.emit(str(exc))


class AsCredentialDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AS 사이트 계정 설정")
        user_id, _ = load_as_credentials()
        self.user_id = QLineEdit(user_id)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        save = QPushButton("저장")
        save.clicked.connect(self.accept)
        form = QFormLayout(self)
        form.addRow("아이디", self.user_id)
        form.addRow("비밀번호", self.password)
        form.addRow(save)

    def accept(self) -> None:
        try:
            save_as_credentials(self.user_id.text(), self.password.text())
        except Exception as exc:
            QMessageBox.warning(self, "저장 실패", str(exc))
            return
        super().accept()


class AsDailyDialog(QDialog):
    HEADERS = ["상태", "접수일", "유형", "이름", "우편번호", "주소", "연락처", "생산년월", "상품명", "수량", "사유"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AS 일일 현황")
        self.resize(1180, 720)
        self.records: list[dict] = []
        self.worker = None
        self.last_fetch_at = 0.0
        self.fetch_started_at = 0.0
        self.auto_refresh_pending = False
        self.settings = load_settings()
        if not self.settings.get("template_path"):
            candidates = [
                Path.home() / "OneDrive" / "Desktop" / "일일 처리 현황_ 테스트.xlsx",
                Path.home() / "Desktop" / "일일 처리 현황_ 테스트.xlsx",
            ]
            detected = next((path for path in candidates if path.is_file()), None)
            if detected:
                self.settings["template_path"] = str(detected)
                save_settings(self.settings)
        today = QDate.currentDate()
        self.start_date = QDateEdit(today)
        self.end_date = QDateEdit(today)
        for widget in (self.start_date, self.end_date):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
        self.receipt_type = QComboBox()
        self.receipt_type.addItem("전체", "")
        self.receipt_type.addItem("교환 출고", "T")
        self.receipt_type.addItem("반품 입고", "R")
        self.status = QComboBox()
        for label, value in [("전체", ""), ("접수", "1"), ("입고", "2"), ("검수", "3"), ("발송", "4"), ("완료", "5")]:
            self.status.addItem(label, value)
        self.fetch_button = QPushButton("AS 사이트에서 불러오기")
        self.fetch_button.clicked.connect(self.fetch)
        self.account_button = QPushButton("사이트 계정 설정")
        self.account_button.clicked.connect(self.configure_account)
        self.template_button = QPushButton("엑셀 양식 선택")
        self.template_button.clicked.connect(self.choose_template)
        self.excel_button = QPushButton("엑셀 열기")
        self.excel_button.setEnabled(False)
        self.excel_button.clicked.connect(self.open_excel)
        self.summary = QLabel("조회 전 · AS 사이트 연결 준비")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((90, 95, 75, 90, 85, 280, 125, 95, 150, 65, 190)):
            self.table.setColumnWidth(column, width)

        filters = QHBoxLayout()
        for label, widget in [("시작일", self.start_date), ("종료일", self.end_date), ("접수 유형", self.receipt_type), ("진행상황", self.status)]:
            filters.addWidget(QLabel(label))
            filters.addWidget(widget)
        filters.addStretch(1)
        filters.addWidget(self.account_button)
        filters.addWidget(self.fetch_button)
        actions = QHBoxLayout()
        actions.addWidget(self.summary)
        actions.addStretch(1)
        actions.addWidget(self.template_button)
        actions.addWidget(self.excel_button)
        layout = QVBoxLayout(self)
        title = QLabel("AS 일일 현황")
        title.setStyleSheet("font-size: 24px; font-weight: 900;")
        layout.addWidget(title)
        layout.addLayout(filters)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)

    def configure_account(self) -> None:
        AsCredentialDialog(self).exec()

    def choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "일일 처리 현황 엑셀 양식 선택", self.settings.get("template_path", ""), "Excel (*.xlsx)")
        if path:
            self.settings["template_path"] = path
            save_settings(self.settings)
            self.summary.setText(f"엑셀 양식 · {Path(path).name}")

    def fetch(self, automatic: bool = False) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        user_id, password = load_as_credentials()
        if not user_id or not password:
            if automatic:
                return
            if AsCredentialDialog(self).exec() != QDialog.DialogCode.Accepted:
                return
            user_id, password = load_as_credentials()
        self.fetch_button.setEnabled(False)
        self.summary.setText("AS 사이트 자동 최신화 중…" if automatic else "AS 사이트 조회 중…")
        self.fetch_started_at = time.monotonic()
        self.worker = FetchWorker(user_id, password, self.start_date.date().toString("yyyy-MM-dd"), self.end_date.date().toString("yyyy-MM-dd"), str(self.receipt_type.currentData()), str(self.status.currentData()))
        self.worker.loaded.connect(self.show_records)
        self.worker.failed.connect(self.show_error)
        self.worker.start()

    def show_records(self, records: list) -> None:
        self.records = records
        self.last_fetch_at = time.monotonic()
        self.auto_refresh_pending = False
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(records))
        try:
            for row, record in enumerate(records):
                product = " ".join(part for part in (record.get("product", ""), record.get("color", "")) if part).strip()
                values = ["반영 예정" if record.get("type") in {"교환", "반품"} else "확인 필요", record.get("receipt_date", ""), record.get("type", ""),
                          record.get("name", ""), record.get("postcode", ""), record.get("address", ""), record.get("phone", ""),
                          record.get("manufacture", ""), product, record.get("quantity", ""), record.get("reason", "")]
                for column, value in enumerate(values):
                    self.table.setItem(row, column, QTableWidgetItem(str(value)))
        finally:
            self.table.setUpdatesEnabled(True)
        self.summary.setText(f"최신 조회 {len(records):,}건 · 교환 {sum(r.get('type') == '교환' for r in records):,}건 · 반품 {sum(r.get('type') == '반품' for r in records):,}건 · 프로그램 복귀 시 자동 갱신")
        self.fetch_button.setEnabled(True)
        self.excel_button.setEnabled(bool(records))

    def show_error(self, message: str) -> None:
        self.auto_refresh_pending = False
        self.fetch_button.setEnabled(True)
        self.summary.setText("조회 실패")
        QMessageBox.critical(self, "AS 사이트 조회 실패", message)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() != QEvent.Type.ActivationChange or not self.isActiveWindow() or not self.records:
            return
        # Excel·브라우저 작업 후 프로그램으로 돌아왔을 때만 한 번 갱신한다.
        # 조회 직후 발생하는 포커스 이벤트와 연속 활성화 이벤트는 무시한다.
        if time.monotonic() - max(self.last_fetch_at, self.fetch_started_at) < 5:
            return
        if self.auto_refresh_pending or (self.worker is not None and self.worker.isRunning()):
            return
        self.auto_refresh_pending = True
        QTimer.singleShot(250, lambda: self.fetch(automatic=True))

    def open_excel(self) -> None:
        default_name = f"일일 처리 현황_{self.start_date.date().toString('yyyyMMdd')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "AS 일일 현황 엑셀 저장", str(Path.home() / "Desktop" / default_name), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_as_daily(self.records, path, self.settings.get("template_path", ""))
            os.startfile(path)
        except Exception as exc:
            QMessageBox.critical(self, "엑셀 생성 실패", str(exc))
