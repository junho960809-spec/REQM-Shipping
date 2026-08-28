from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from ecount_credential_store import delete_api_key, save_api_key
from integration_credential_store import (
    delete_integration_credentials,
    load_integration_credentials,
    save_integration_credentials,
)


class IntegrationAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("연동 계정 관리")
        self.setMinimumWidth(620)
        self.setObjectName("integrationAccounts")
        self.setStyleSheet("""
            QDialog#integrationAccounts { background:#f4f7fb;color:#172f52;font-family:'맑은 고딕';font-size:13px; }
            QFrame#accountCard { background:white;border:1px solid #d9e3ee;border-radius:14px; }
            QLabel#title { font-size:24px;font-weight:900;color:#10294a; }
            QLabel#section { font-size:17px;font-weight:900;color:#17365d;padding-bottom:5px; }
            QLabel#hint { color:#718096; }
            QLineEdit { background:white;border:1px solid #cbd8e6;border-radius:8px;padding:9px; }
            QPushButton { background:white;color:#29476b;border:1px solid #c8d6e5;border-radius:9px;padding:10px 16px;font-weight:800; }
            QPushButton#primary { background:#087f78;color:white;border:0; }
            QPushButton#danger { color:#c2410c;border-color:#fdba74;background:#fff7ed; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel("연동 계정 관리"); title.setObjectName("title")
        hint = QLabel("한 번 저장하면 이카운트와 인쇄 발주 기능에서 자동으로 사용합니다."); hint.setObjectName("hint")
        layout.addWidget(title); layout.addWidget(hint)

        self.ecount_user_id = QLineEdit()
        self.ecount_password = self.secret_field("이카운트 로그인 비밀번호")
        self.ecount_api_key = self.secret_field("이카운트 API 인증키")
        layout.addWidget(self.card("이카운트 ERP", (
            ("사용자 ID", self.ecount_user_id),
            ("비밀번호", self.ecount_password),
            ("API 인증키", self.ecount_api_key),
        )))

        self.print_board_user_id = QLineEdit()
        self.print_board_password = self.secret_field("인쇄 게시판 비밀번호")
        layout.addWidget(self.card("인쇄 발주 게시판", (
            ("게시판 ID", self.print_board_user_id),
            ("게시판 비밀번호", self.print_board_password),
        )))

        security = QLabel("모든 값은 현재 Windows 사용자만 해독할 수 있도록 암호화해 저장합니다.")
        security.setObjectName("hint"); security.setWordWrap(True); layout.addWidget(security)
        actions = QHBoxLayout()
        delete_button = QPushButton("저장정보 삭제"); delete_button.setObjectName("danger")
        close_button = QPushButton("닫기")
        save_button = QPushButton("저장"); save_button.setObjectName("primary")
        actions.addWidget(delete_button); actions.addStretch(1); actions.addWidget(close_button); actions.addWidget(save_button)
        layout.addLayout(actions)
        delete_button.clicked.connect(self.delete_saved)
        close_button.clicked.connect(self.reject)
        save_button.clicked.connect(self.save)
        self.load_saved()

    @staticmethod
    def secret_field(placeholder: str) -> QLineEdit:
        field = QLineEdit(); field.setEchoMode(QLineEdit.EchoMode.Password); field.setPlaceholderText(placeholder)
        return field

    @staticmethod
    def card(title: str, rows) -> QFrame:
        frame = QFrame(); frame.setObjectName("accountCard")
        box = QVBoxLayout(frame); box.setContentsMargins(18, 16, 18, 16)
        heading = QLabel(title); heading.setObjectName("section"); box.addWidget(heading)
        form = QFormLayout(); form.setSpacing(10)
        for label, widget in rows: form.addRow(label, widget)
        box.addLayout(form)
        return frame

    def values(self) -> dict[str, str]:
        return {
            "ecount_user_id": self.ecount_user_id.text().strip(),
            "ecount_password": self.ecount_password.text(),
            "ecount_api_key": self.ecount_api_key.text().strip(),
            "print_board_user_id": self.print_board_user_id.text().strip(),
            "print_board_password": self.print_board_password.text(),
        }

    def load_saved(self) -> None:
        values = load_integration_credentials()
        for field, value in values.items():
            getattr(self, field).setText(value)

    def save(self) -> None:
        try:
            values = self.values()
            save_integration_credentials(values)
            save_api_key(values["ecount_user_id"], values["ecount_api_key"])
        except Exception as exc:
            QMessageBox.warning(self, "연동 계정 저장 실패", str(exc)); return
        QMessageBox.information(self, "연동 계정 저장", "연동 계정을 안전하게 저장했습니다.")
        self.accept()

    def delete_saved(self) -> None:
        if QMessageBox.question(self, "저장정보 삭제", "저장된 연동 계정을 모두 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        ecount_user_id = self.ecount_user_id.text().strip()
        delete_integration_credentials()
        if ecount_user_id:
            delete_api_key(ecount_user_id)
        for field in (
            self.ecount_user_id, self.ecount_password, self.ecount_api_key,
            self.print_board_user_id, self.print_board_password,
        ):
            field.clear()
        QMessageBox.information(self, "저장정보 삭제", "저장된 연동 계정을 삭제했습니다.")
