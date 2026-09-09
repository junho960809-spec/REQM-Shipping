"""Standalone visual preview that never connects to production services."""
from __future__ import annotations

import json
import os
import sys

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.texts import DEFAULT_TEXTS, TEXT_OVERRIDE_PATH, reload_texts, text
from ui.theme import CUSTOM_THEME_PATH, load_theme


class UiPreviewWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(text("preview.title"))
        self.resize(1040, 720)

        root = QWidget()
        root.setObjectName("mainContainer")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        self.title = QLabel(text("app.title"))
        self.title.setObjectName("appTitle")
        self.subtitle = QLabel(text("app.subtitle"))
        self.subtitle.setObjectName("appSubtitle")
        self.guide = QLabel(text("preview.guide"))
        self.guide.setObjectName("dialogGuide")
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.guide)

        card = QFrame()
        card.setProperty("role", "card")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(QLabel("입력 요소와 버튼"))
        self.email_field = QLineEdit()
        self.email_field.setPlaceholderText(text("login.email_placeholder"))
        actions = QHBoxLayout()
        self.primary_button = QPushButton(text("wekeep.preview.submit"))
        self.primary_button.setProperty("variant", "primary")
        normal = QPushButton(text("common.close"))
        danger = QPushButton("위험 작업")
        danger.setProperty("variant", "danger")
        actions.addWidget(self.primary_button)
        actions.addWidget(normal)
        actions.addWidget(danger)
        actions.addStretch(1)
        card_layout.addWidget(self.email_field)
        card_layout.addLayout(actions)
        layout.addWidget(card)

        status = QLabel("샘플 상태 · 준비 완료 3건 · 검토 필요 1건")
        status.setProperty("role", "status")
        layout.addWidget(status)

        table = QTableWidget(3, 5)
        table.setHorizontalHeaderLabels(["상태", "주문번호", "수령인", "상품", "수량"])
        samples = [
            ("준비 완료", "ORDER-001", "홍길동", "샘플 상품 A", "2"),
            ("검토 필요", "ORDER-002", "김민지", "샘플 상품 B", "1"),
            ("등록 완료", "ORDER-003", "이서준", "샘플 상품 C", "3"),
        ]
        for row_index, row in enumerate(samples):
            for column_index, value in enumerate(row):
                table.setItem(row_index, column_index, QTableWidgetItem(value))
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)

        controls = QHBoxLayout()
        create_button = QPushButton(text("preview.create_files"))
        open_button = QPushButton(text("preview.open_folder"))
        reload_button = QPushButton(text("preview.reload"))
        reload_button.setProperty("variant", "primary")
        create_button.clicked.connect(self.create_edit_files)
        open_button.clicked.connect(self.open_edit_folder)
        reload_button.clicked.connect(self.reload_preview)
        controls.addWidget(create_button)
        controls.addWidget(open_button)
        controls.addStretch(1)
        controls.addWidget(reload_button)
        layout.addLayout(controls)
        self.setCentralWidget(root)

    def create_edit_files(self) -> None:
        TEXT_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not TEXT_OVERRIDE_PATH.exists():
            editable = {
                "app.title": DEFAULT_TEXTS["app.title"],
                "app.subtitle": DEFAULT_TEXTS["app.subtitle"],
                "wekeep.preview.title": DEFAULT_TEXTS["wekeep.preview.title"],
                "wekeep.preview.submit": DEFAULT_TEXTS["wekeep.preview.submit"],
            }
            TEXT_OVERRIDE_PATH.write_text(json.dumps(editable, ensure_ascii=False, indent=2), encoding="utf-8")
        if not CUSTOM_THEME_PATH.exists():
            CUSTOM_THEME_PATH.write_text(
                "/* 기본 테마 뒤에 적용되는 사용자 스타일입니다. */\n"
                "/* 예: QPushButton[variant=\"primary\"] { background: #153f38; } */\n",
                encoding="utf-8",
            )
        os.startfile(TEXT_OVERRIDE_PATH.parent)
        QMessageBox.information(
            self,
            text("preview.files_ready_title"),
            text("preview.files_ready", folder=TEXT_OVERRIDE_PATH.parent),
        )

    @staticmethod
    def open_edit_folder() -> None:
        TEXT_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
        os.startfile(TEXT_OVERRIDE_PATH.parent)

    def reload_preview(self) -> None:
        reload_texts()
        QApplication.instance().setStyleSheet(load_theme())
        self.setWindowTitle(text("preview.title"))
        self.title.setText(text("app.title"))
        self.subtitle.setText(text("app.subtitle"))
        self.guide.setText(text("preview.guide"))
        self.email_field.setPlaceholderText(text("login.email_placeholder"))
        self.primary_button.setText(text("wekeep.preview.submit"))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("REQM UI Preview")
    app.setStyleSheet(load_theme())
    window = UiPreviewWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
