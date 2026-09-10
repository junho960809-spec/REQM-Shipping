"""Preview REQM orders before opening the corresponding WeKeep registration panel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from wekeep_sku_store import load_wekeep_sku_mappings, prepare_wekeep_orders, readiness_counts
from shipment_job_store import ShipmentJobStore
from wekeep_order_automation import run_wekeep_job
from wekeep_upload_file import ORDER_KIND_LABELS
from ui.texts import text


class WeKeepSubmissionWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str, str)

    def __init__(self, job_id: str, db_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.job_id = job_id
        self.db_path = db_path

    def run(self) -> None:
        try:
            self.succeeded.emit(run_wekeep_job(self.job_id, self.db_path))
        except Exception as exc:
            self.failed.emit(self.job_id, str(exc))


class WeKeepTransferDialog(QDialog):
    def __init__(self, orders: list[dict], current_mode: str, parent=None):
        super().__init__(parent)
        self.orders = orders
        self.current_mode = current_mode
        self.catalog_items = list(getattr(parent, "catalog", {}).get("items", []) or [])
        self.rows: list[dict] = []
        self.job_store = ShipmentJobStore()
        self.submission_worker: WeKeepSubmissionWorker | None = None
        self.setObjectName("wekeepPreview")
        self.setWindowTitle(text("wekeep.preview.window_title"))
        self.resize(1380, 680)

        title = QLabel(text("wekeep.preview.title"))
        title.setObjectName("dialogTitle")
        guide = QLabel(
            text("wekeep.preview.guide")
        )
        guide.setObjectName("dialogGuide")
        guide.setWordWrap(True)
        self.kind = QComboBox()
        self.kind.addItem("B2C 일반주문", "b2c")
        self.kind.addItem("B2C 사입형", "b2c_buying")
        self.kind.addItem("B2B 일반주문", "b2b")
        self.kind.addItem("B2B 사입형", "b2b_buying")
        self.kind.setCurrentIndex(1 if current_mode == "duty_free" else 0)
        self.summary = QLabel()
        self.summary.setObjectName("dialogSummary")

        top = QHBoxLayout()
        top.addWidget(QLabel(text("wekeep.preview.kind")))
        top.addWidget(self.kind)
        top.addStretch(1)
        top.addWidget(self.summary)

        headers = [
            "상태", "주문번호", "수령인", "원본 상품", "변환 상품명",
            "위킵 등록 상품명", "내부 품목코드", "위킵 SKU", "바코드", "수량", "확인 내용",
        ]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        self.open_button = QPushButton(text("wekeep.preview.submit"))
        self.open_button.setObjectName("primaryButton")
        self.close_button = QPushButton(text("common.close"))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.open_button)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(guide)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

        self.kind.currentIndexChanged.connect(self.refresh)
        self.open_button.clicked.connect(self.open_wekeep)
        self.close_button.clicked.connect(self.accept)
        self.refresh()

    def refresh(self) -> None:
        self.rows = prepare_wekeep_orders(
            self.orders,
            order_kind=str(self.kind.currentData()),
            mappings=load_wekeep_sku_mappings(),
            items=self.catalog_items,
        )
        counts = readiness_counts(self.rows)
        self.summary.setText(f"전체 {counts['total']:,}행 · 준비 {counts['ready']:,} · 검토 필요 {counts['review']:,}")
        self.open_button.setEnabled(bool(self.rows) and counts["review"] == 0)
        self.table.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            ready = row.get("state") == "ready"
            values = [
                "준비 완료" if ready else "검토 필요",
                row.get("order_number", ""),
                row.get("recipient", ""),
                row.get("source_product_name", ""),
                row.get("standard_product_name", "") or row.get("converted_product_name", ""),
                row.get("wekeep_product_name", ""),
                row.get("item_code", ""),
                row.get("sku_no", ""),
                row.get("customer_barcode", ""),
                row.get("quantity", ""),
                row.get("reason", ""),
            ]
            color = QColor("#d9ead3") if ready else QColor("#fce5cd")
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setBackground(color)
                item.setToolTip(str(value))
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()

    def open_wekeep(self) -> None:
        counts = readiness_counts(self.rows)
        if not self.rows or counts["review"]:
            QMessageBox.warning(self, "위킵 반영 보류", "검토 필요 주문을 먼저 수동 매칭해 주세요.")
            return
        order_kind = str(self.kind.currentData())
        total_quantity = sum(int(row.get("quantity") or 0) for row in self.rows)
        answer = QMessageBox.question(
            self,
            "위킵 최종 출고 승인",
            f"{ORDER_KIND_LABELS[order_kind]}\n"
            f"출고 행 {len(self.rows):,}개 · 총 수량 {total_quantity:,}개\n\n"
            "승인하면 백그라운드에서 위킵의 최종 등록 버튼까지 실행합니다.\n"
            "주문번호, 수령인, 주소와 수량을 모두 확인했습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            job = self.job_store.create(self.rows, order_kind)
        except Exception as exc:
            QMessageBox.critical(self, "위킵 출고 작업 생성 실패", str(exc))
            return
        self.kind.setEnabled(False)
        self.close_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.open_button.setText(text("wekeep.preview.working"))
        self.summary.setText(f"작업 {job['id'][:8]} · 백그라운드 등록 진행 중")
        self.submission_worker = WeKeepSubmissionWorker(job["id"], self.job_store.path, self)
        self.submission_worker.succeeded.connect(self.on_submission_succeeded)
        self.submission_worker.failed.connect(self.on_submission_failed)
        self.submission_worker.start()

    def on_submission_succeeded(self, job: dict) -> None:
        self.kind.setEnabled(True)
        self.close_button.setEnabled(True)
        self.open_button.setText(text("wekeep.preview.submit"))
        if job["state"] == "completed":
            self.summary.setText(f"작업 {job['id'][:8]} · 위킵 등록 완료")
            QMessageBox.information(self, "위킵 출고 완료", "위킵의 성공 응답을 확인하고 출고 이력을 저장했습니다.")
            return
        self.summary.setText(f"작업 {job['id'][:8]} · 등록 결과 확인 필요")
        QMessageBox.warning(
            self, "위킵 등록 결과 확인 필요",
            "최종 등록 요청은 전송됐지만 위킵의 성공 응답을 명확히 확인하지 못했습니다.\n"
            "중복 출고 방지를 위해 자동 재시도하지 않습니다.",
        )

    def on_submission_failed(self, job_id: str, message: str) -> None:
        self.kind.setEnabled(True)
        self.close_button.setEnabled(True)
        self.open_button.setText(text("wekeep.preview.submit"))
        job = self.job_store.get(job_id)
        self.open_button.setEnabled(job["state"] == "failed")
        self.summary.setText(f"작업 {job_id[:8]} · {job['state']}")
        QMessageBox.critical(self, "위킵 출고 실패", message)

    def closeEvent(self, event) -> None:
        if self.submission_worker is not None and self.submission_worker.isRunning():
            QMessageBox.information(self, "위킵 등록 진행 중", "등록 결과를 확인할 때까지 창을 닫을 수 없습니다.")
            event.ignore()
            return
        super().closeEvent(event)
