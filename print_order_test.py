from __future__ import annotations

import sys
import os
import re
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)
from playwright.sync_api import sync_playwright
from print_order_analyzer import AnalysisResult, analyze_order_document


SAMPLE_ORDERS = [
    ["고려기프트", "일체형 듀얼", "300", "2026-08-26", "검토 전"],
    ["한양대학교", "Q1500 그레이", "300", "2026-09-01", "등록 완료"],
]

ORDER_BOARD_URL = "http://orora.ipdisk.co.kr:8000/apache/gnuboard5/bbs/board.php?bo_table=Order"
ORDER_WRITE_URL = "http://orora.ipdisk.co.kr:8000/apache/gnuboard5/bbs/write.php?bo_table=Order"
CHROME_PATHS = (
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
)


class PrintOrderWebWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, credentials: dict[str, str], order: dict[str, str]):
        super().__init__()
        self.credentials = credentials
        self.order = order

    def run(self):
        try:
            chrome = next((path for path in CHROME_PATHS if path.exists()), None)
            if chrome is None:
                raise RuntimeError("Google Chrome을 찾지 못했습니다.")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                try:
                    page = browser.new_page()
                    page.goto(ORDER_BOARD_URL, wait_until="domcontentloaded", timeout=30_000)
                    if page.locator("#login_id").count():
                        page.locator("#login_id").fill(self.credentials["user_id"])
                        page.locator("#login_pw").fill(self.credentials["password"])
                        page.locator('input[type="submit"]').click()
                        page.wait_for_load_state("domcontentloaded", timeout=30_000)
                    if page.locator("#login_id").count():
                        raise RuntimeError("로그인에 실패했습니다. 아이디와 비밀번호를 확인하세요.")
                    page.goto(ORDER_WRITE_URL, wait_until="domcontentloaded", timeout=30_000)
                    fields = {
                        "wr_subject": "customer", "wr_5": "product", "wr_6": "quantity",
                        "wr_9": "printing", "wr_4": "device", "wr_1": "address",
                        "wr_2": "contact", "wr_10": "request_date", "wr_content": "note",
                    }
                    for field_name, order_key in fields.items():
                        page.locator(f'[name="{field_name}"]').fill(self.order[order_key])
                    page.locator(f'input[name="wr_7"][value="{self.order["packaging"]}"]').check()
                    page.locator('input[name="wr_8"][value="없음"]').check()
                    page.locator(f'input[name="wr_3"][value="{self.order["delivery"]}"]').check()
                    file_inputs = page.locator('input[name="bf_file[]"]')
                    file_inputs.nth(0).set_input_files(self.order["ai_file"])
                    file_inputs.nth(1).set_input_files(self.order["preview_file"])
                    page.locator('#btn_submit[type="submit"]').click()
                    page.wait_for_load_state("domcontentloaded", timeout=30_000)
                    if "write.php" in page.url:
                        raise RuntimeError("웹사이트가 등록 완료 화면으로 이동하지 않았습니다.")
                    self.succeeded.emit(page.url)
                finally:
                    browser.close()
        except Exception as exc:
            self.failed.emit(str(exc))


class PrintOrderAnalysisWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            self.succeeded.emit(analyze_order_document(self.path))
        except Exception as exc:
            self.failed.emit(str(exc))


class FileDropBox(QFrame):
    fileChanged = Signal(str)

    def __init__(self, title: str, extensions: str, accept_clipboard_image: bool = False, file_prefix: str = "시안캡처", parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.path = ""
        self.accept_clipboard_image = accept_clipboard_image
        self.file_prefix = file_prefix
        self.setObjectName("dropBox")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size:15px;font-weight:800;color:#17365d")
        self.status = QLabel(f"{extensions}\n파일을 끌어놓거나 선택하세요")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setObjectName("muted")
        button = QPushButton("파일 선택")
        button.clicked.connect(self.choose_file)
        layout.addWidget(self.title)
        layout.addWidget(self.status, 1)
        layout.addWidget(button)
        if accept_clipboard_image:
            paste = QPushButton("클립보드 이미지 붙여넣기  Ctrl+V")
            paste.setObjectName("primary")
            paste.clicked.connect(self.paste_clipboard_image)
            layout.addWidget(paste)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "첨부파일 선택")
        if path:
            self.set_file(path)

    def set_file(self, path: str):
        self.path = path
        self.status.setText(f"연결 완료\n{Path(path).name}")
        self.setProperty("ready", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.fileChanged.emit(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.set_file(urls[0].toLocalFile())

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self.accept_clipboard_image and event.matches(QKeySequence.StandardKey.Paste):
            self.paste_clipboard_image()
            event.accept()
            return
        super().keyPressEvent(event)

    def paste_clipboard_image(self):
        image = QApplication.clipboard().image()
        if image.isNull():
            self.status.setText("클립보드에 이미지가 없습니다.\n캡처 후 다시 Ctrl+V를 눌러주세요.")
            return
        output_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "print_order_attachments"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.file_prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
        if not image.save(str(path), "PNG"):
            self.status.setText("클립보드 이미지를 저장하지 못했습니다.")
            return
        self.set_file(str(path))


class PrintOrderTestWindow(QMainWindow):
    def __init__(self, parent=None, catalog_items=None):
        super().__init__(parent)
        self.catalog_items = [item for item in (catalog_items or []) if item.get("is_active", True)]
        self.web_worker = None
        self.analysis_worker = None
        self.last_analysis = None
        self.setWindowTitle("REQM · 인쇄 발주 자동화 테스트")
        self.resize(1500, 900)
        self.setStyleSheet("""
            QMainWindow,QWidget { background:#f4f7fb;color:#172f52;font-family:'맑은 고딕';font-size:12px; }
            QFrame#sidebar { background:#102d52;border:0; }
            QFrame#card,QFrame#dropBox { background:white;border:1px solid #d9e3ee;border-radius:12px; }
            QFrame#dropBox[ready="true"] { border:2px solid #0d9488;background:#f0fdfa; }
            QLabel#pageTitle { font-size:25px;font-weight:900;color:#10294a; }
            QLabel#muted { color:#718096; }
            QLabel#step { background:#e7eef6;color:#395473;border-radius:10px;padding:7px 12px;font-weight:700; }
            QLabel#stepDone { background:#dff7f3;color:#087f78;border-radius:10px;padding:7px 12px;font-weight:800; }
            QLineEdit,QComboBox,QDateEdit,QTextEdit { background:white;border:1px solid #cbd8e6;border-radius:7px;padding:8px; }
            QPushButton { background:white;color:#29476b;border:1px solid #c8d6e5;border-radius:8px;padding:9px 14px;font-weight:800; }
            QPushButton:hover { border-color:#0d9488;background:#ecf8f7; }
            QPushButton#primary { background:#087f78;color:white;border:0; }
            QPushButton#danger { background:#fff7ed;color:#c2410c;border:1px solid #fdba74; }
            QListWidget { background:transparent;border:0;color:#dce8f5;font-size:14px;outline:0; }
            QListWidget::item { padding:13px 15px;margin:2px 8px;border-radius:8px; }
            QListWidget::item:selected { background:#087f78;color:white;font-weight:800; }
            QTableWidget { background:white;border:1px solid #d9e3ee;border-radius:10px;gridline-color:#e8edf3; }
            QHeaderView::section { background:#17365d;color:white;padding:9px;border:0;font-weight:800; }
        """)
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)
        side = QVBoxLayout(sidebar)
        brand = QLabel("REQM\nPRINT ORDER")
        brand.setStyleSheet("color:white;font-size:22px;font-weight:900;padding:22px 16px")
        self.menu = QListWidget()
        self.menu.addItems(["새 발주 등록", "등록 미리보기", "진행 현황", "거래처·품목 설정"])
        self.menu.setCurrentRow(0)
        side.addWidget(brand)
        side.addWidget(self.menu, 1)
        version = QLabel("웹 등록 테스트 활성화")
        version.setStyleSheet("color:#9db2ca;padding:20px")
        side.addWidget(version)
        shell.addWidget(sidebar)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_entry_page())
        self.stack.addWidget(self.build_preview_page())
        self.stack.addWidget(self.build_status_page())
        self.stack.addWidget(self.build_settings_page())
        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex)
        shell.addWidget(self.stack, 1)

    def page_header(self, title: str, guide: str, parent_layout: QVBoxLayout):
        label = QLabel(title)
        label.setObjectName("pageTitle")
        hint = QLabel(guide)
        hint.setObjectName("muted")
        parent_layout.addWidget(label)
        parent_layout.addWidget(hint)

    def build_entry_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(28,22,28,22)
        self.page_header("인쇄 발주 등록", "발주 정보를 입력하고 AI·시안 파일을 연결하면 등록 전 누락을 검사합니다.", layout)
        steps = QHBoxLayout()
        for index, text in enumerate(["1  발주 정보", "2  파일 연결", "3  검토", "4  웹 등록"]):
            tag = QLabel(text); tag.setObjectName("stepDone" if index == 0 else "step"); steps.addWidget(tag)
        steps.addStretch(1); layout.addLayout(steps)
        body = QHBoxLayout(); form_card = QFrame(); form_card.setObjectName("card")
        form_box = QVBoxLayout(form_card); form = QFormLayout(); form.setSpacing(12)
        self.customer = QComboBox(); self.customer.setEditable(True); self.customer.addItems(["고려기프트", "한양대학교", "신규 거래처 입력"])
        self.product = QComboBox(); self.product.setEditable(True)
        db_names = list(dict.fromkeys(
            str(item.get("standard_name", "")).strip() for item in self.catalog_items
            if str(item.get("standard_name", "")).strip()
        ))
        self.product.addItems(db_names or ["Q1500 그레이", "Q1500 화이트", "일체형 듀얼"])
        self.quantity = QLineEdit("300"); self.printing = QLineEdit("전면 / 로고 1도 인쇄")
        self.device = QLineEdit("Q1500"); self.packaging = QComboBox(); self.packaging.addItems(["선물포장","기본패키지","벌크","OEM포장"])
        self.address = QLineEdit("서울 영등포구 양산로 43")
        self.delivery = QComboBox(); self.delivery.addItems(["택배","퀵 선불","퀵 착불","기타"])
        self.contact = QLineEdit("홍길동 / 010-0000-0000")
        self.request_date = QDateEdit(QDate.currentDate().addDays(7)); self.request_date.setCalendarPopup(True); self.request_date.setDisplayFormat("yyyy-MM-dd")
        self.note = QTextEdit(); self.note.setMaximumHeight(72)
        for label, widget in [("발주처",self.customer),("품명",self.product),("총수량",self.quantity),("인쇄내용",self.printing),("기기명",self.device),("포장",self.packaging),("주소",self.address),("배송",self.delivery),("담당자·연락처",self.contact),("출고요청일",self.request_date),("비고",self.note)]: form.addRow(label,widget)
        form_box.addLayout(form)
        files_panel = QWidget(); files_panel.setFixedWidth(340)
        files = QVBoxLayout(files_panel); files.setContentsMargins(0, 0, 0, 0); files.setSpacing(8)
        self.order_source = FileDropBox("발주서 가져오기", "이미지 · PDF · Excel · Ctrl+V", accept_clipboard_image=True, file_prefix="발주서캡처")
        self.order_source.setMaximumHeight(145)
        self.analysis_status = QLabel("발주서를 연결하면 자동 분석합니다."); self.analysis_status.setWordWrap(True); self.analysis_status.setObjectName("muted")
        analyze = QPushButton("발주서 분석 및 자동 채우기"); analyze.setObjectName("primary"); analyze.clicked.connect(self.analyze_source)
        raw = QPushButton("분석 원문 보기"); raw.clicked.connect(self.show_analysis_text)
        source_actions = QHBoxLayout(); source_actions.addWidget(analyze, 2); source_actions.addWidget(raw, 1)
        self.ai_file=FileDropBox("AI 원본 파일","Adobe Illustrator · .ai"); self.ai_file.setMaximumHeight(125)
        self.preview_file=FileDropBox("시안 이미지","PNG · JPG · PDF · Ctrl+V", accept_clipboard_image=True); self.preview_file.setMaximumHeight(155)
        files.addWidget(self.order_source); files.addWidget(self.analysis_status); files.addLayout(source_actions)
        files.addWidget(self.ai_file); files.addWidget(self.preview_file); files.addStretch(1)
        self.ai_file.fileChanged.connect(self.update_auto_note)
        self.packaging.currentTextChanged.connect(self.update_auto_note)
        self.update_auto_note()
        body.addWidget(form_card, 1); body.addWidget(files_panel, 0); layout.addLayout(body,1)
        actions=QHBoxLayout(); self.validation=QLabel("필수항목 12개 중 10개 확인 · 첨부파일 2개 필요"); self.validation.setObjectName("muted")
        check=QPushButton("누락 검사"); check.clicked.connect(self.validate_order)
        preview=QPushButton("등록 미리보기"); preview.setObjectName("primary"); preview.clicked.connect(self.open_preview)
        actions.addWidget(self.validation); actions.addStretch(1); actions.addWidget(check); actions.addWidget(preview); layout.addLayout(actions)
        return page

    @staticmethod
    def _match_key(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z가-힣]", "", value).casefold()

    def database_product_name(self, extracted_name: str, extracted_code: str = "") -> str:
        code_key = self._match_key(extracted_code)
        if code_key:
            for item in self.catalog_items:
                if self._match_key(str(item.get("item_code", ""))) == code_key:
                    return str(item.get("standard_name", "")).strip() or extracted_name
        name_key = self._match_key(extracted_name)
        if not name_key:
            return extracted_name
        best_name, best_score = extracted_name, 0.0
        for item in self.catalog_items:
            name = str(item.get("standard_name", "")).strip()
            candidate = self._match_key(name)
            if not candidate:
                continue
            score = 1.0 if name_key in candidate or candidate in name_key else SequenceMatcher(None, name_key, candidate).ratio()
            if score > best_score:
                best_name, best_score = name, score
        return best_name if best_score >= 0.72 else extracted_name

    def update_auto_note(self, *_):
        printing = "O" if getattr(self, "ai_file", None) and self.ai_file.path else "X"
        packaging = "O" if self.packaging.currentText() == "선물포장" else "X"
        self.note.setPlainText(f"인쇄 {printing}  포장 {packaging}")

    def build_preview_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(28,22,28,22)
        self.page_header("등록 미리보기", "웹 게시판에 실제 입력될 내용을 확인한 뒤 최종 등록합니다.",layout)
        card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card)
        self.preview_title=QLabel("고려기프트 · Q1500 그레이 · 300개"); self.preview_title.setStyleSheet("font-size:20px;font-weight:900")
        self.preview_text=QLabel(); self.preview_text.setWordWrap(True); self.preview_text.setStyleSheet("font-size:14px;line-height:1.7;padding:15px")
        box.addWidget(self.preview_title); box.addWidget(self.preview_text); box.addStretch(1)
        warning=QLabel("안전장치: 작성완료 버튼을 누르기 전 사용자 확인을 한 번 더 받습니다."); warning.setStyleSheet("background:#fff7ed;color:#9a3412;padding:13px;border-radius:8px")
        box.addWidget(warning)
        self.web_submit_button=QPushButton("기존 게시판에 등록"); self.web_submit_button.setObjectName("primary")
        self.web_submit_button.clicked.connect(self.submit_to_web); box.addWidget(self.web_submit_button)
        layout.addWidget(card,1); self.update_preview(); return page

    def build_status_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(28,22,28,22)
        self.page_header("인쇄 발주 진행 현황", "등록된 발주와 출고요청일, 현재 처리상태를 한 화면에서 확인합니다.",layout)
        table=QTableWidget(len(SAMPLE_ORDERS),5); table.setHorizontalHeaderLabels(["발주처","품명","수량","출고요청일","상태"])
        table.horizontalHeader().setStretchLastSection(True)
        for r,row in enumerate(SAMPLE_ORDERS):
            for c,value in enumerate(row):
                item=QTableWidgetItem(value)
                if c==4: item.setForeground(QColor("#087f78" if value=="등록 완료" else "#c2410c")); item.setFont(QFont("맑은 고딕",10,QFont.Weight.Bold))
                table.setItem(r,c,item)
        layout.addWidget(table,1); return page

    def build_settings_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(28,22,28,22)
        self.page_header("거래처·품목 자동완성", "반복 발주 시 주소, 담당자, 포장, 배송 방식을 자동으로 채우는 기준정보입니다.",layout)
        login_card=QFrame(); login_card.setObjectName("card"); login_form=QFormLayout(login_card)
        self.web_id=QLineEdit(); self.web_id.setPlaceholderText("사내게시판 아이디")
        self.web_password=QLineEdit(); self.web_password.setEchoMode(QLineEdit.EchoMode.Password); self.web_password.setPlaceholderText("실행 중에만 사용 · 저장하지 않음")
        login_form.addRow("게시판 아이디",self.web_id); login_form.addRow("게시판 비밀번호",self.web_password)
        security=QLabel("HTTP 사이트이므로 계정은 저장하지 않습니다. 프로그램을 다시 열면 재입력해야 합니다."); security.setStyleSheet("color:#c2410c;padding:8px")
        login_form.addRow("",security); layout.addWidget(login_card)
        table=QTableWidget(3,5); table.setHorizontalHeaderLabels(["거래처","기본 주소","담당자","기본 배송","최근 사용 품목"]); table.horizontalHeader().setStretchLastSection(True)
        rows=[["고려기프트","서울 영등포구","김담당","택배","일체형 듀얼"],["한양대학교","서울 성동구","박담당","퀵 선불","Q1500 그레이"],["신규 거래처","미등록","미등록","택배","-"]]
        for r,row in enumerate(rows):
            for c,v in enumerate(row): table.setItem(r,c,QTableWidgetItem(v))
        layout.addWidget(table,1); return page

    def analyze_source(self):
        if not self.order_source.path:
            QMessageBox.information(self, "발주서 선택", "이미지·PDF·Excel 파일을 선택하거나 캡처 이미지를 붙여넣으세요.")
            return
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            return
        self.analysis_status.setText("발주서 내용을 분석하는 중...")
        self.analysis_worker = PrintOrderAnalysisWorker(self.order_source.path)
        self.analysis_worker.succeeded.connect(self.apply_analysis)
        self.analysis_worker.failed.connect(self.analysis_failed)
        self.analysis_worker.finished.connect(self.release_analysis_worker)
        self.analysis_worker.start()

    def apply_analysis(self, result: AnalysisResult):
        self.last_analysis = result
        fields = result.fields
        if result.vendor:
            self.customer.setCurrentText(result.vendor)
        if fields.get("product") or fields.get("item_code"):
            self.product.setCurrentText(self.database_product_name(fields.get("product", ""), fields.get("item_code", "")))
        if fields.get("quantity"):
            numeric = re.sub(r"[^0-9]", "", fields["quantity"])
            if numeric:
                self.quantity.setText(numeric)
        if fields.get("printing"):
            self.printing.setText(fields["printing"])
        recipient_contact = " / ".join(value for value in (fields.get("recipient", ""), fields.get("contact", "")) if value)
        if recipient_contact:
            self.contact.setText(recipient_contact)
        if fields.get("address"):
            self.address.setText(fields["address"])
        for option in ["선물포장", "기본패키지", "벌크", "OEM포장"]:
            if option in fields.get("packaging", ""):
                self.packaging.setCurrentText(option)
                break
        for option in ["퀵 선불", "퀵 착불", "택배", "기타"]:
            if option.replace(" ", "") in fields.get("delivery", "").replace(" ", ""):
                self.delivery.setCurrentText(option)
                break
        raw_date = fields.get("request_date", "")
        date_match = re.search(r"(20\d{2})?\D*(\d{1,2})\D+(\d{1,2})", raw_date)
        if date_match:
            year = int(date_match.group(1) or QDate.currentDate().year())
            parsed = QDate(year, int(date_match.group(2)), int(date_match.group(3)))
            if parsed.isValid():
                self.request_date.setDate(parsed)
        confidence_values = [value for value in result.confidence.values() if value]
        average = round(sum(confidence_values) / len(confidence_values)) if confidence_values else 0
        self.analysis_status.setText(
            f"{result.vendor} · {result.source_type} 분석 완료 · 평균 신뢰도 {average}%\n"
            "자동 입력값을 원본과 비교하고 노란색 항목을 확인하세요."
        )
        widget_map = {
            "product": self.product, "quantity": self.quantity, "printing": self.printing,
            "address": self.address, "contact": self.contact,
        }
        for key, widget in widget_map.items():
            score = result.confidence.get(key, 0)
            widget.setToolTip(f"발주서 분석 신뢰도 {score}%")
            widget.setStyleSheet("background:#fff7d6" if score and score < 85 else "")
        self.validate_order()

    def analysis_failed(self, message: str):
        self.analysis_status.setText("발주서 분석 실패")
        QMessageBox.critical(self, "발주서 분석 실패", message)

    def release_analysis_worker(self):
        worker = self.analysis_worker
        self.analysis_worker = None
        if worker is not None:
            worker.deleteLater()

    def show_analysis_text(self):
        if self.last_analysis is None:
            QMessageBox.information(self, "분석 원문", "먼저 발주서를 분석하세요.")
            return
        dialog = QDialog(self); dialog.setWindowTitle("발주서 분석 원문"); dialog.resize(900, 650)
        layout = QVBoxLayout(dialog); text = QTextEdit(); text.setReadOnly(True); text.setPlainText(self.last_analysis.raw_text)
        layout.addWidget(text); close = QPushButton("닫기"); close.clicked.connect(dialog.accept); layout.addWidget(close)
        dialog.exec()

    def apply_sample(self):
        self.customer.setCurrentText("고려기프트"); self.product.setCurrentText("일체형 듀얼"); self.quantity.setText("300")
        self.printing.setText("전면 / 고려기프트 로고 1도"); self.device.setText("일체형 듀얼"); self.validation.setText("발주서 분석 완료 · 첨부파일을 연결하세요")

    def validate_order(self):
        missing=[]
        for label,widget in [("발주처",self.customer),("품명",self.product),("수량",self.quantity),("인쇄내용",self.printing),("주소",self.address),("담당자",self.contact)]:
            value=widget.currentText() if isinstance(widget,QComboBox) else widget.text()
            if not value.strip(): missing.append(label)
        if not self.ai_file.path: missing.append("AI 파일")
        if not self.preview_file.path: missing.append("시안 이미지")
        self.validation.setText("누락: "+", ".join(missing) if missing else "모든 필수항목과 첨부파일 확인 완료")

    def update_preview(self):
        if not hasattr(self,"preview_text"): return
        self.preview_title.setText(f"{self.customer.currentText()} · {self.product.currentText()} · {self.quantity.text()}개")
        self.preview_text.setText(
            f"포장: {self.packaging.currentText()}\n\n"
            f"인쇄내용: {self.printing.text()}    |    기기명: {self.device.text()}\n\n"
            f"주소: {self.address.text()}\n배송: {self.delivery.currentText()}    |    출고요청일: {self.request_date.date().toString('yyyy-MM-dd')}\n\n"
            f"담당자: {self.contact.text()}\n비고: {self.note.toPlainText()}\n\n"
            f"AI 파일: {Path(self.ai_file.path).name if self.ai_file.path else '미연결'}\n시안 이미지: {Path(self.preview_file.path).name if self.preview_file.path else '미연결'}"
        )

    def open_preview(self):
        self.update_preview(); self.menu.setCurrentRow(1)

    def order_payload(self) -> dict[str, str]:
        return {
            "customer": self.customer.currentText().strip(),
            "product": self.product.currentText().strip(),
            "quantity": self.quantity.text().strip(),
            "packaging": self.packaging.currentText(),
            "printing": self.printing.text().strip(),
            "device": self.device.text().strip(),
            "address": self.address.text().strip(),
            "delivery": self.delivery.currentText(),
            "contact": self.contact.text().strip(),
            "request_date": self.request_date.date().toString("yyyy-MM-dd"),
            "note": self.note.toPlainText().strip(),
            "ai_file": self.ai_file.path,
            "preview_file": self.preview_file.path,
        }

    def submit_to_web(self):
        self.validate_order()
        if not self.ai_file.path or not self.preview_file.path:
            QMessageBox.warning(self, "첨부 확인", "AI 파일과 시안 이미지를 모두 연결하세요.")
            return
        if not self.web_id.text().strip() or not self.web_password.text():
            QMessageBox.information(self, "로그인 정보", "거래처·품목 설정에서 게시판 아이디와 비밀번호를 입력하세요.")
            self.menu.setCurrentRow(3)
            return
        answer = QMessageBox.question(
            self,
            "웹 등록 최종 확인",
            f"{self.customer.currentText()} / {self.product.currentText()} / {self.quantity.text()}개를\n"
            "오로라모바일 인쇄 진행 리스트에 실제 등록합니다. 계속할까요?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.web_worker is not None and self.web_worker.isRunning():
            return
        self.web_submit_button.setEnabled(False)
        self.web_submit_button.setText("웹 등록 중...")
        credentials = {"user_id": self.web_id.text().strip(), "password": self.web_password.text()}
        self.web_worker = PrintOrderWebWorker(credentials, self.order_payload())
        self.web_worker.succeeded.connect(self.on_web_succeeded)
        self.web_worker.failed.connect(self.on_web_failed)
        self.web_worker.finished.connect(self.release_web_worker)
        self.web_worker.start()

    def on_web_succeeded(self, url: str):
        QMessageBox.information(self, "웹 등록 완료", f"인쇄 발주가 등록되었습니다.\n{url}")

    def on_web_failed(self, message: str):
        QMessageBox.critical(self, "웹 등록 실패", message)

    def release_web_worker(self):
        worker = self.web_worker
        self.web_worker = None
        self.web_submit_button.setEnabled(True)
        self.web_submit_button.setText("기존 게시판에 등록")
        if worker is not None:
            worker.deleteLater()


def main():
    app=QApplication(sys.argv)
    window=PrintOrderTestWindow(); window.show()
    if "--screenshots" in sys.argv:
        index=sys.argv.index("--screenshots")
        output=Path(sys.argv[index+1]); output.mkdir(parents=True,exist_ok=True)
        def capture():
            window.order_source.set_file("C:/orders/고려기프트_발주서.pdf")
            window.ai_file.set_file("C:/orders/고려기프트_일체형듀얼_300.ai")
            window.preview_file.set_file("C:/orders/고려기프트_시안.png")
            window.validate_order()
            for page,name in [(0,"01_발주입력.png"),(1,"02_등록미리보기.png"),(2,"03_진행현황.png"),(3,"04_자동완성설정.png")]:
                window.menu.setCurrentRow(page)
                if page==1: window.update_preview()
                app.processEvents()
                window.grab().save(str(output/name))
            app.quit()
        QTimer.singleShot(500,capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
