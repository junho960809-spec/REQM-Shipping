from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)


SAMPLE_ORDERS = [
    ["고려기프트", "일체형 듀얼", "300", "2026-08-26", "검토 전"],
    ["한양대학교", "Q1500 그레이", "300", "2026-09-01", "등록 완료"],
]


class FileDropBox(QFrame):
    def __init__(self, title: str, extensions: str, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.path = ""
        self.setObjectName("dropBox")
        layout = QVBoxLayout(self)
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

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.set_file(urls[0].toLocalFile())


class PrintOrderTestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
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
        version = QLabel("TEST · 웹 등록 비활성화")
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
        self.product = QComboBox(); self.product.setEditable(True); self.product.addItems(["Q1500 그레이", "Q1500 화이트", "일체형 듀얼"])
        self.quantity = QLineEdit("300"); self.printing = QLineEdit("전면 / 로고 1도 인쇄")
        self.device = QLineEdit("Q1500"); self.packaging = QComboBox(); self.packaging.addItems(["선물포장","기본패키지","벌크","OEM포장"])
        self.gender = QComboBox(); self.gender.addItems(["없음","포함"])
        self.address = QLineEdit("서울 영등포구 양산로 43")
        self.delivery = QComboBox(); self.delivery.addItems(["택배","퀵 선불","퀵 착불","기타"])
        self.contact = QLineEdit("홍길동 / 010-0000-0000")
        self.request_date = QDateEdit(QDate.currentDate().addDays(7)); self.request_date.setCalendarPopup(True); self.request_date.setDisplayFormat("yyyy-MM-dd")
        self.note = QTextEdit("시안 확인 후 생산 진행 바랍니다."); self.note.setMaximumHeight(72)
        for label, widget in [("발주처",self.customer),("품명",self.product),("총수량",self.quantity),("인쇄내용",self.printing),("기기명",self.device),("포장",self.packaging),("8핀 젠더",self.gender),("주소",self.address),("배송",self.delivery),("담당자·연락처",self.contact),("출고요청일",self.request_date),("비고",self.note)]: form.addRow(label,widget)
        form_box.addLayout(form)
        files = QVBoxLayout(); self.ai_file=FileDropBox("AI 원본 파일","Adobe Illustrator · .ai"); self.preview_file=FileDropBox("시안 이미지","PNG · JPG · PDF")
        files.addWidget(self.ai_file); files.addWidget(self.preview_file)
        auto = QPushButton("발주서에서 자동 채우기"); auto.setObjectName("primary"); auto.clicked.connect(self.apply_sample)
        files.addWidget(auto)
        body.addWidget(form_card,2); body.addLayout(files,1); layout.addLayout(body,1)
        actions=QHBoxLayout(); self.validation=QLabel("필수항목 12개 중 10개 확인 · 첨부파일 2개 필요"); self.validation.setObjectName("muted")
        check=QPushButton("누락 검사"); check.clicked.connect(self.validate_order)
        preview=QPushButton("등록 미리보기"); preview.setObjectName("primary"); preview.clicked.connect(self.open_preview)
        actions.addWidget(self.validation); actions.addStretch(1); actions.addWidget(check); actions.addWidget(preview); layout.addLayout(actions)
        return page

    def build_preview_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(28,22,28,22)
        self.page_header("등록 미리보기", "웹 게시판에 입력될 내용을 확인합니다. 테스트 버전은 실제 등록하지 않습니다.",layout)
        card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card)
        self.preview_title=QLabel("고려기프트 · Q1500 그레이 · 300개"); self.preview_title.setStyleSheet("font-size:20px;font-weight:900")
        self.preview_text=QLabel(); self.preview_text.setWordWrap(True); self.preview_text.setStyleSheet("font-size:14px;line-height:1.7;padding:15px")
        box.addWidget(self.preview_title); box.addWidget(self.preview_text); box.addStretch(1)
        warning=QLabel("안전장치: 작성완료 버튼을 누르기 전 사용자 확인을 한 번 더 받습니다."); warning.setStyleSheet("background:#fff7ed;color:#9a3412;padding:13px;border-radius:8px")
        box.addWidget(warning); disabled=QPushButton("웹 등록 (테스트 비활성화)"); disabled.setEnabled(False); box.addWidget(disabled)
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
        table=QTableWidget(3,5); table.setHorizontalHeaderLabels(["거래처","기본 주소","담당자","기본 배송","최근 사용 품목"]); table.horizontalHeader().setStretchLastSection(True)
        rows=[["고려기프트","서울 영등포구","김담당","택배","일체형 듀얼"],["한양대학교","서울 성동구","박담당","퀵 선불","Q1500 그레이"],["신규 거래처","미등록","미등록","택배","-"]]
        for r,row in enumerate(rows):
            for c,v in enumerate(row): table.setItem(r,c,QTableWidgetItem(v))
        layout.addWidget(table,1); return page

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
            f"포장: {self.packaging.currentText()}    |    젠더: {self.gender.currentText()}\n\n"
            f"인쇄내용: {self.printing.text()}    |    기기명: {self.device.text()}\n\n"
            f"주소: {self.address.text()}\n배송: {self.delivery.currentText()}    |    출고요청일: {self.request_date.date().toString('yyyy-MM-dd')}\n\n"
            f"담당자: {self.contact.text()}\n비고: {self.note.toPlainText()}\n\n"
            f"AI 파일: {Path(self.ai_file.path).name if self.ai_file.path else '미연결'}\n시안 이미지: {Path(self.preview_file.path).name if self.preview_file.path else '미연결'}"
        )

    def open_preview(self):
        self.update_preview(); self.menu.setCurrentRow(1)


def main():
    app=QApplication(sys.argv)
    window=PrintOrderTestWindow(); window.show()
    if "--screenshots" in sys.argv:
        index=sys.argv.index("--screenshots")
        output=Path(sys.argv[index+1]); output.mkdir(parents=True,exist_ok=True)
        def capture():
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
