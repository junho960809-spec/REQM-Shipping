from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from cs_repository import CsRepository, DraftConflictError
from cs_service import transform_operator_note
from naver_commerce_client import NaverCommerceClient, NaverCommerceError
from naver_credential_store import load_naver_credentials


class CsManagementDialog(QDialog):
    """First-stage shared CS workspace; Naver transport is connected later."""

    def __init__(self, parent=None, *, supabase_client=None) -> None:
        super().__init__(parent)
        self.supabase_client = supabase_client
        self.repository = CsRepository(supabase_client)
        credentials = load_naver_credentials()
        self.naver_client = (
            NaverCommerceClient(credentials["client_id"], credentials["client_secret"])
            if credentials["client_id"] and credentials["client_secret"]
            else None
        )
        self.current_case: dict | None = None
        self.current_draft_version = 0
        self.current_policy_refs: list[str] = []
        self.setWindowTitle("CS 관리")
        self.resize(1180, 720)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("CS 관리")
        title.setObjectName("sectionTitle")
        guide = QLabel("네이버 문의를 확인하고 작업자 메모를 고객용 답변 초안으로 정리합니다.")
        guide.setObjectName("appSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(guide)
        header.addLayout(title_box)
        header.addStretch(1)
        self.sync_button = QPushButton("문의 동기화")
        self.sync_button.setEnabled(False)
        self.sync_button.setToolTip("Supabase와 네이버 커머스 API 인증정보가 필요합니다.")
        header.addWidget(self.sync_button)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_inquiry_list())
        splitter.addWidget(self._build_inquiry_detail())
        splitter.addWidget(self._build_draft_panel())
        splitter.setSizes([270, 420, 390])
        layout.addWidget(splitter, 1)
        self.convert_button.clicked.connect(self.convert_note)
        self.save_button.clicked.connect(self.save_shared_draft)
        self.inquiry_list.currentRowChanged.connect(self.select_case)
        self.convert_button.setEnabled(True)
        if self.supabase_client is not None:
            self.load_cases()
        if self.supabase_client is not None and self.naver_client is not None:
            self.sync_button.setEnabled(True)
            self.sync_button.clicked.connect(self.sync_naver_qnas)

    def _build_inquiry_list(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("주문번호·제품 검색")
        self.status_filter = QComboBox()
        self.status_filter.addItem("미답변", "unanswered")
        self.status_filter.addItem("처리 중", "in_progress")
        self.status_filter.addItem("완료", "completed")
        filters.addWidget(self.search, 1)
        filters.addWidget(self.status_filter)
        layout.addLayout(filters)
        self.inquiry_list = QListWidget()
        self.inquiry_list.addItem("네이버 문의 동기화 전")
        layout.addWidget(self.inquiry_list, 1)
        return panel

    def _build_inquiry_detail(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("고객 문의"))
        self.question = QTextEdit()
        self.question.setReadOnly(True)
        self.question.setPlainText("제품 문의를 동기화하면 고객 질문과 주문 정보가 표시됩니다.")
        layout.addWidget(self.question, 1)
        layout.addWidget(QLabel("연결된 주문·상품 정보"))
        self.order_context = QTextEdit()
        self.order_context.setReadOnly(True)
        self.order_context.setPlainText("주문번호\n제품 모델\n배송 상태")
        layout.addWidget(self.order_context, 1)
        return panel

    def _build_draft_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("작업자 메모"))
        self.operator_note = QTextEdit()
        self.operator_note.setPlaceholderText("예: 팽창 / 즉시 사용 중단 / 주문번호와 사진 요청 / 새상품 교환")
        layout.addWidget(self.operator_note)
        self.convert_button = QPushButton("고객용 초안으로 변환")
        layout.addWidget(self.convert_button)
        layout.addWidget(QLabel("공용 답변 초안"))
        self.draft = QTextEdit()
        self.draft.setPlaceholderText("변환된 초안은 Supabase에 저장되어 다른 작업자와 공유됩니다.")
        layout.addWidget(self.draft, 1)
        actions = QHBoxLayout()
        self.save_button = QPushButton("초안 저장")
        self.send_button = QPushButton("승인 후 네이버 전송")
        self.save_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.save_button.setToolTip("CS 공용 테이블 적용 후 사용할 수 있습니다.")
        self.send_button.setToolTip("네이버 커머스 API 연결 전에는 전송할 수 없습니다.")
        actions.addWidget(self.save_button)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)
        return panel

    def load_cases(self) -> None:
        try:
            cases = self.repository.list_cases(self.status_filter.currentData() or "unanswered")
        except Exception as exc:
            QMessageBox.warning(self, "문의 불러오기 실패", str(exc))
            return
        self.inquiry_list.clear()
        for case in cases:
            label = f"{case.get('question') or '문의 내용 없음'} · {case.get('product_model') or '모델 미확인'}"
            self.inquiry_list.addItem(label)
            self.inquiry_list.item(self.inquiry_list.count() - 1).setData(Qt.ItemDataRole.UserRole, case)
        if cases:
            self.inquiry_list.setCurrentRow(0)
        else:
            self.inquiry_list.addItem("현재 미답변 문의가 없습니다.")

    @staticmethod
    def _model_from_product_name(product_name: str) -> str:
        upper = product_name.upper()
        models = ("QP1000A", "QP2000A", "QPD250", "QPD365", "QP1000C", "QP2000C", "QPD330", "QPD365-N")
        return next((model for model in models if model in upper), "")

    def sync_naver_qnas(self) -> None:
        if self.naver_client is None:
            return
        self.sync_button.setEnabled(False)
        try:
            qnas = self.naver_client.product_qnas(answered=False, page=1, size=100)
            cases = []
            for row in qnas:
                product_name = str(row.get("productName") or "")
                cases.append({
                    "channel": "product_qna",
                    "external_id": str(row.get("questionId") or ""),
                    "question": str(row.get("question") or ""),
                    "product_no": str(row.get("productId") or ""),
                    "product_model": self._model_from_product_name(product_name),
                    "category": "",
                    "risk_level": "normal",
                    "status": "unanswered",
                    "source_created_at": row.get("createDate"),
                })
            cases = [case for case in cases if case["external_id"]]
            saved = self.repository.upsert_cases(cases)
            self.load_cases()
            QMessageBox.information(self, "문의 동기화", f"미답변 상품 Q&A {saved}건을 동기화했습니다.")
        except NaverCommerceError as exc:
            trace = f"\nTrace ID: {exc.trace_id}" if exc.trace_id else ""
            QMessageBox.warning(self, "네이버 문의 동기화 실패", f"{exc}{trace}")
        except Exception as exc:
            QMessageBox.warning(self, "문의 동기화 실패", str(exc))
        finally:
            self.sync_button.setEnabled(True)

    def select_case(self, row: int) -> None:
        item = self.inquiry_list.item(row)
        case = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(case, dict):
            self.current_case = None
            self.save_button.setEnabled(False)
            return
        self.current_case = case
        self.question.setPlainText(str(case.get("question") or ""))
        self.order_context.setPlainText(
            f"주문번호: {case.get('product_order_id') or '미확인'}\n"
            f"제품 모델: {case.get('product_model') or '미확인'}\n"
            f"채널: {case.get('channel') or '미확인'}"
        )
        latest = self.repository.latest_draft(str(case.get("id") or ""))
        self.current_draft_version = int(latest.get("version") or 0) if latest else 0
        self.operator_note.setPlainText(str(latest.get("operator_note") or "") if latest else "")
        self.draft.setPlainText(str(latest.get("final_answer") or "") if latest else "")
        self.save_button.setEnabled(True)

    def convert_note(self) -> None:
        try:
            result = transform_operator_note(
                question=self.question.toPlainText(),
                operator_note=self.operator_note.toPlainText(),
                product_model=str((self.current_case or {}).get("product_model") or ""),
            )
        except ValueError as exc:
            QMessageBox.information(self, "작업자 메모 확인", str(exc))
            return
        self.draft.setPlainText(result.text)
        self.current_policy_refs = list(result.policy_refs)

    def save_shared_draft(self) -> None:
        if not self.current_case:
            return
        try:
            saved = self.repository.save_draft(
                case_id=str(self.current_case["id"]),
                operator_note=self.operator_note.toPlainText(),
                generated_draft=self.draft.toPlainText(),
                knowledge_refs=self.current_policy_refs,
                expected_version=self.current_draft_version,
            )
        except DraftConflictError as exc:
            QMessageBox.warning(self, "초안 수정 충돌", str(exc))
            self.select_case(self.inquiry_list.currentRow())
            return
        except Exception as exc:
            QMessageBox.warning(self, "초안 저장 실패", str(exc))
            return
        self.current_draft_version = int(saved.get("version") or self.current_draft_version + 1)
        QMessageBox.information(self, "초안 저장", "공용 초안을 저장했습니다.")
