"""Preview REQM orders before opening the corresponding WeKeep registration panel."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
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
from wekeep_order_automation import save_pending_payload
from wekeep_upload_file import ORDER_KIND_LABELS, create_wekeep_upload


PENDING_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "wekeep_orders"


class WeKeepTransferDialog(QDialog):
    def __init__(self, orders: list[dict], current_mode: str, parent=None):
        super().__init__(parent)
        self.orders = orders
        self.current_mode = current_mode
        self.rows: list[dict] = []
        self.setWindowTitle("위킵 주문 반영 미리보기")
        self.resize(1380, 680)

        title = QLabel("위킵 주문 반영 미리보기")
        title.setStyleSheet("font-size:22px;font-weight:900")
        guide = QLabel(
            "REQM 매칭과 위킵 SKU를 검증한 뒤 해당 판매처의 주문등록 화면을 엽니다. "
            "위킵의 최종 저장 버튼은 자동으로 누르지 않습니다."
        )
        guide.setWordWrap(True)
        self.kind = QComboBox()
        self.kind.addItem("B2C 일반주문", "b2c")
        self.kind.addItem("B2C 사입형", "b2c_buying")
        self.kind.addItem("B2B 일반주문", "b2b")
        self.kind.addItem("B2B 사입형", "b2b_buying")
        self.kind.setCurrentIndex(1 if current_mode == "duty_free" else 0)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight:800;padding:8px")

        top = QHBoxLayout()
        top.addWidget(QLabel("위킵 등록 유형"))
        top.addWidget(self.kind)
        top.addStretch(1)
        top.addWidget(self.summary)

        headers = ["상태", "주문번호", "수령인", "원본 상품", "내부 품목코드", "위킵 SKU", "바코드", "수량", "확인 내용"]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        self.open_button = QPushButton("업로드 파일 생성 · 위킵에 첨부")
        self.open_button.setObjectName("primaryButton")
        close_button = QPushButton("닫기")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        buttons.addWidget(self.open_button)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(guide)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

        self.kind.currentIndexChanged.connect(self.refresh)
        self.open_button.clicked.connect(self.open_wekeep)
        close_button.clicked.connect(self.accept)
        self.refresh()

    def refresh(self) -> None:
        self.rows = prepare_wekeep_orders(
            self.orders,
            order_kind=str(self.kind.currentData()),
            mappings=load_wekeep_sku_mappings(),
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
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        order_kind = str(self.kind.currentData())
        try:
            upload_path = create_wekeep_upload(self.rows, order_kind)
        except Exception as exc:
            QMessageBox.critical(self, "위킵 파일 생성 실패", str(exc))
            return
        path = PENDING_DIR / f"pending_{datetime.now():%Y%m%d_%H%M%S}.json"
        save_pending_payload(path, {
            "version": 2,
            "order_kind": order_kind,
            "upload_path": str(upload_path),
            "rows": self.rows,
        })
        subprocess.Popen([sys.executable, "--wekeep-order-preview", str(path)])
        QMessageBox.information(
            self,
            "위킵 파일 첨부",
            f"{ORDER_KIND_LABELS[order_kind]} 공식 양식을 생성해 위킵에 자동 첨부합니다.\n"
            "열린 화면의 내용을 확인한 뒤 최종 '저장'은 작업자가 눌러 주세요.",
        )
