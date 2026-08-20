from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from weekly_inventory_catalog import WEEKLY_INVENTORY_ITEMS
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass
class InventoryRow:
    item_code: str
    item_name: str
    headquarters_actual: int = 0
    ecount_headquarters: int = 0
    wekeep_actual: int = 0
    ecount_wekeep: int = 0
    reason: str = ""
    action: str = ""
    reviewed: bool = False

    @property
    def headquarters_difference(self) -> int:
        return self.headquarters_actual - self.ecount_headquarters

    @property
    def wekeep_difference(self) -> int:
        return self.wekeep_actual - self.ecount_wekeep

    @property
    def total_difference(self) -> int:
        return self.headquarters_difference + self.wekeep_difference


SAMPLE_ROWS = [
    InventoryRow("QWC-Q1500GR", "[리큐엠] QWC-Q1500 무선충전기 그레이", 8, 7, 536, 540),
    InventoryRow("QWC-Q1500WH", "[리큐엠] QWC-Q1500 무선충전기 화이트", 11, 11, 412, 410),
    InventoryRow("QWC-Q1500-GR-PM", "[리큐엠] QWC-Q1500 무선충전기 그레이-판촉용", 629, 630, 0, 0),
    InventoryRow("QWC-Q1500-WH-PM", "[리큐엠] QWC-Q1500 무선충전기 화이트-판촉용", 63, 60, 0, 0),
    InventoryRow("QWC-Q1500PK", "[리큐엠] QWC-Q1500 무선충전기 핑크", 15, 15, 128, 130),
    InventoryRow("QWC-Q3100S-WH", "[리큐엠] 3in1 무선충전기 Q3100S 화이트", 22, 20, 74, 74),
]


def import_wekeep_rows(path: str | Path) -> dict[str, tuple[str, int]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook["재고데이터-위킵"] if "재고데이터-위킵" in workbook.sheetnames else workbook.active
        values = sheet.iter_rows(values_only=True)
        header = next(values, None)
        if not header:
            raise ValueError("위킵 재고 파일이 비어 있습니다.")
        normalized = [str(value or "").replace(" ", "").lower() for value in header]

        def find_column(*aliases: str) -> int | None:
            for alias in aliases:
                key = alias.replace(" ", "").lower()
                if key in normalized:
                    return normalized.index(key)
            return None

        code_column = find_column("상품관리코드", "품목코드", "상품코드")
        name_column = find_column("상품명", "품목명")
        quantity_column = find_column("시점재고", "재고수량", "현재고", "수량")
        if code_column is None or quantity_column is None:
            raise ValueError("상품관리코드와 시점재고 열을 찾지 못했습니다.")
        result: dict[str, tuple[str, int]] = {}
        for row in values:
            code = str(row[code_column] or "").strip() if code_column < len(row) else ""
            if not code:
                continue
            name = str(row[name_column] or "").strip() if name_column is not None and name_column < len(row) else ""
            raw_quantity = row[quantity_column] if quantity_column < len(row) else 0
            try:
                quantity = int(float(raw_quantity or 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{code}의 시점재고 값이 숫자가 아닙니다.") from exc
            result[code] = (name, quantity)
        return result
    finally:
        workbook.close()


def export_inventory_workbook(path: str | Path, rows: list[InventoryRow]) -> None:
    workbook = Workbook()
    overview = workbook.active
    overview.title = "재고현황"
    comparison = workbook.create_sheet("실재고 전산비교")
    inventory_data = workbook.create_sheet("재고데이터")
    reqm_data = workbook.create_sheet("재고데이터-리큐엠")
    wekeep_data = workbook.create_sheet("재고데이터-위킵")
    raw_ecount = workbook.create_sheet("RAWDATA_이카운트")

    headers = ["품목코드", "품목명", "본사 실재고", "이카운트 본사", "본사 차이", "위킵 재고", "이카운트 위킵", "위킵 차이", "전체 차이", "판정"]
    overview.append(["REQM 주간 재고조사", datetime.now().strftime("%Y-%m-%d %H:%M")])
    overview.append(headers)
    comparison.append(headers + ["차이 원인", "조치 내용", "검토 완료"])
    inventory_data.append(["품목코드", "품목명", "본사창고", "위킵창고", "본사 실재고", "위킵 실재고", "전체 차이"])
    reqm_data.append(["품목코드", "품목명", "01-위킵창고", "01-본사창고", "03-불량창고(본사)"])
    wekeep_data.append(["상품관리코드", "상품명", "시점재고"])
    raw_ecount.append(["구분", "창고", "품목코드", "품목명", "수량", "수집시각"])

    for item in rows:
        base = [
            item.item_code, item.item_name, item.headquarters_actual, item.ecount_headquarters,
            item.headquarters_difference, item.wekeep_actual, item.ecount_wekeep,
            item.wekeep_difference, item.total_difference, "일치" if item.total_difference == 0 else "차이",
        ]
        overview.append(base)
        comparison.append(base + [item.reason, item.action, "완료" if item.reviewed else "미처리"])
        inventory_data.append([item.item_code, item.item_name, item.ecount_headquarters, item.ecount_wekeep, item.headquarters_actual, item.wekeep_actual, item.total_difference])
        reqm_data.append([item.item_code, item.item_name, item.ecount_wekeep, item.ecount_headquarters, 0])
        wekeep_data.append([item.item_code, item.item_name, item.wekeep_actual])
        raw_ecount.append(["현재고", "본사창고", item.item_code, item.item_name, item.ecount_headquarters, datetime.now()])
        raw_ecount.append(["현재고", "위킵창고", item.item_code, item.item_name, item.ecount_wekeep, datetime.now()])

    navy = PatternFill("solid", fgColor="17365D")
    teal = PatternFill("solid", fgColor="0D9488")
    for sheet in workbook.worksheets:
        header_row = 2 if sheet is overview else 1
        for cell in sheet[header_row]:
            cell.fill = navy
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center")
        sheet.freeze_panes = f"A{header_row + 1}"
        sheet.auto_filter.ref = sheet.dimensions
        for column in range(1, sheet.max_column + 1):
            width = max(len(str(sheet.cell(row, column).value or "")) for row in range(1, min(sheet.max_row, 80) + 1))
            sheet.column_dimensions[get_column_letter(column)].width = min(max(width + 3, 11), 42)
    overview["A1"].fill = teal
    overview["A1"].font = Font(color="FFFFFF", bold=True, size=16)
    workbook.save(path)


class InventoryDialog(QDialog):
    HEADERS = ["품목코드", "품목명", "본사 실재고", "이카운트 본사", "본사 차이", "위킵 재고", "이카운트 위킵", "위킵 차이", "전체 차이", "판정"]

    def __init__(self, catalog_items: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("REQM 주간 재고조사")
        self.resize(1480, 900)
        self.rows = self._initial_rows(catalog_items or [])
        self.filtered_indices: list[int] = []
        self.current_review_index: int | None = None
        self._build_ui()
        self.refresh_all()

    @staticmethod
    def _initial_rows(catalog_items: list[dict]) -> list[InventoryRow]:
        return [InventoryRow(item_code=code, item_name=name) for code, name in WEEKLY_INVENTORY_ITEMS]

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QDialog { background:#f5f7fa; color:#172f52; font-family:'맑은 고딕'; font-size:12px; }
            QLabel#title { font-size:26px; font-weight:800; color:#10294a; }
            QLabel#guide { color:#718096; }
            QFrame#card { background:white; border:1px solid #dce4ed; border-radius:12px; }
            QTabWidget::pane { border:0; }
            QTabBar::tab { background:#e9eef5; color:#50627a; padding:12px 24px; margin-right:3px; border-radius:7px; font-weight:700; }
            QTabBar::tab:selected { background:#087f78; color:white; }
            QLineEdit,QComboBox,QSpinBox,QTextEdit { background:white; border:1px solid #cfd9e5; border-radius:7px; padding:7px; }
            QPushButton { background:white; color:#29476b; border:1px solid #cbd7e5; border-radius:8px; padding:9px 15px; font-weight:700; }
            QPushButton:hover { background:#edf6f5; border-color:#0d9488; }
            QPushButton#primary { background:#087f78; color:white; border:none; }
            QPushButton#primary:hover { background:#066b66; }
            QPushButton:disabled { background:#edf0f4; color:#9ca7b5; }
            QTableWidget { background:white; alternate-background-color:white; gridline-color:#e7ebf0; border:1px solid #dbe3ec; }
            QHeaderView::section { background:#17365d; color:white; padding:9px; border:0; border-right:1px solid #365578; font-weight:700; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        header = QHBoxLayout()
        title = QLabel("주간 재고조사")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch(1)
        self.source_status = QLabel("테스트 데이터 · 이카운트 API 연결 전")
        self.source_status.setObjectName("guide")
        header.addWidget(self.source_status)
        root.addLayout(header)
        guide = QLabel("이카운트 전산재고와 본사·위킵 실재고를 비교하고 주간재고조사 Excel을 생성합니다.")
        guide.setObjectName("guide")
        root.addWidget(guide)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._dashboard_tab(), "1  조사 준비")
        self.tabs.addTab(self._entry_tab(), "2  실재고 입력")
        self.tabs.addTab(self._import_tab(), "3  자료 최신화")
        self.tabs.addTab(self._review_tab(), "4  결과 검토")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        root.addWidget(self.tabs, 1)

    def _card(self, title_text: str, body_text: str, button_text: str, callback, enabled: bool = True) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        title = QLabel(title_text)
        title.setStyleSheet("font-size:17px;font-weight:800;color:#17365d")
        body = QLabel(body_text)
        body.setWordWrap(True)
        body.setObjectName("guide")
        button = QPushButton(button_text)
        button.setObjectName("primary" if enabled else "")
        button.setEnabled(enabled)
        button.clicked.connect(callback)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)
        layout.addWidget(button)
        return card

    def _dashboard_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        cards = QHBoxLayout()
        cards.addWidget(self._card("1. 이카운트 최신화", "품목과 본사·위킵 창고의 전산재고를 가져옵니다.", "API 준비 중", lambda: None, False))
        cards.addWidget(self._card("2. 위킵 Excel 불러오기", "상품관리코드와 시점재고를 자동으로 반영합니다.", "Excel 파일 선택", self.load_wekeep))
        cards.addWidget(self._card("3. 본사 실재고 입력", "입력하는 즉시 본사·전체 차이를 다시 계산합니다.", "실재고 입력", lambda: self.tabs.setCurrentIndex(1)))
        cards.addWidget(self._card("4. 결과 Excel 생성", "검토 결과를 주간재고조사 파일로 저장합니다.", "결과 Excel 생성", self.export_result))
        layout.addLayout(cards)
        self.dashboard_status = QLabel()
        self.dashboard_status.setObjectName("guide")
        self.dashboard_status.setStyleSheet("background:white;border:1px solid #dce4ed;border-radius:10px;padding:18px")
        layout.addWidget(self.dashboard_status)
        layout.addStretch(1)
        return widget

    def _entry_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("품목코드 또는 품목명 검색")
        self.status_filter = QComboBox()
        self.status_filter.addItems(["전체", "차이 있음", "일치"])
        self.location_filter = QComboBox()
        self.location_filter.addItems(["전체 위치", "본사 차이", "위킵 차이", "양쪽 차이"])
        self.sort_filter = QComboBox()
        self.sort_filter.addItems(["엑셀 원본 순서", "차이 큰 순", "품목코드 순", "품목명 순"])
        tools.addWidget(self.search, 2)
        tools.addWidget(self.status_filter)
        tools.addWidget(self.location_filter)
        tools.addWidget(self.sort_filter)
        layout.addLayout(tools)
        self.entry_summary = QLabel()
        self.entry_summary.setObjectName("guide")
        layout.addWidget(self.entry_summary)
        self.entry_table = QTableWidget()
        self._prepare_table(self.entry_table, self.HEADERS)
        layout.addWidget(self.entry_table, 1)
        self.search.textChanged.connect(self.refresh_entry_table)
        self.status_filter.currentIndexChanged.connect(self.refresh_entry_table)
        self.location_filter.currentIndexChanged.connect(self.refresh_entry_table)
        self.sort_filter.currentIndexChanged.connect(self.refresh_entry_table)
        self.entry_table.cellChanged.connect(self.on_entry_changed)
        return widget

    def _import_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        ecount = self._card("이카운트 API", "회사·창고 매핑을 확인한 뒤 최신 전산재고를 불러옵니다. 이카운트 재고는 수정하지 않습니다.", "API 연결은 다음 단계", lambda: None, False)
        wekeep = self._card("위킵 Excel", "지원 열: 상품관리코드 / 상품명 / 시점재고\n현재 테스트 단계에서는 Excel 파일을 직접 불러옵니다.", "위킵 Excel 선택", self.load_wekeep)
        layout.addWidget(ecount)
        layout.addWidget(wekeep)
        return widget

    def _review_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        left = QVBoxLayout()
        self.review_table = QTableWidget()
        self._prepare_table(self.review_table, ["품목코드", "품목명", "본사 차이", "위킵 차이", "전체 차이", "처리 상태"])
        self.review_table.cellClicked.connect(self.select_review_row)
        left.addWidget(self.review_table)
        right_card = QFrame()
        right_card.setObjectName("card")
        right = QVBoxLayout(right_card)
        self.review_item = QLabel("차이 품목을 선택하세요")
        self.review_item.setStyleSheet("font-size:16px;font-weight:800")
        self.reason_combo = QComboBox()
        self.reason_combo.addItems(["미확인", "입출고 시점 차이", "전산 등록 오류", "파손·분실", "위킵 반영 지연", "기타"])
        self.action_edit = QTextEdit()
        self.action_edit.setPlaceholderText("조치 내용을 입력하세요")
        self.reviewer_edit = QLineEdit()
        self.reviewer_edit.setPlaceholderText("담당자")
        self.reviewed_check = QCheckBox("검토 완료")
        save_button = QPushButton("선택 품목 저장")
        save_button.clicked.connect(self.save_review)
        export_button = QPushButton("주간재고조사 Excel 생성")
        export_button.setObjectName("primary")
        export_button.clicked.connect(self.export_result)
        form = QFormLayout()
        form.addRow("차이 원인", self.reason_combo)
        form.addRow("조치 내용", self.action_edit)
        form.addRow("담당자", self.reviewer_edit)
        right.addWidget(self.review_item)
        right.addLayout(form)
        right.addWidget(self.reviewed_check)
        right.addWidget(save_button)
        right.addStretch(1)
        right.addWidget(export_button)
        layout.addLayout(left, 2)
        layout.addWidget(right_card, 1)
        return widget

    @staticmethod
    def _prepare_table(table: QTableWidget, headers: list[str]) -> None:
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(False)

    def _visible_indices(self) -> list[int]:
        query = self.search.text().strip().lower() if hasattr(self, "search") else ""
        status = self.status_filter.currentText() if hasattr(self, "status_filter") else "전체"
        location = self.location_filter.currentText() if hasattr(self, "location_filter") else "전체 위치"
        indices = []
        for index, row in enumerate(self.rows):
            if query and query not in f"{row.item_code} {row.item_name}".lower():
                continue
            if status == "차이 있음" and row.total_difference == 0:
                continue
            if status == "일치" and row.total_difference != 0:
                continue
            if location == "본사 차이" and row.headquarters_difference == 0:
                continue
            if location == "위킵 차이" and row.wekeep_difference == 0:
                continue
            if location == "양쪽 차이" and (row.headquarters_difference == 0 or row.wekeep_difference == 0):
                continue
            indices.append(index)
        sort = self.sort_filter.currentText() if hasattr(self, "sort_filter") else "엑셀 원본 순서"
        if sort == "품목코드 순":
            indices.sort(key=lambda i: self.rows[i].item_code)
        elif sort == "품목명 순":
            indices.sort(key=lambda i: self.rows[i].item_name)
        elif sort == "차이 큰 순":
            indices.sort(key=lambda i: (-abs(self.rows[i].total_difference), self.rows[i].item_code))
        return indices

    def refresh_all(self) -> None:
        self.refresh_entry_table()
        self.refresh_review_table()
        self.update_dashboard_status()

    def update_dashboard_status(self) -> None:
        differences = sum(row.total_difference != 0 for row in self.rows)
        reviewed = sum(row.reviewed for row in self.rows if row.total_difference != 0)
        self.dashboard_status.setText(
            f"현재 품목 {len(self.rows):,}개 · 차이 품목 {differences:,}개 · 검토 완료 {reviewed:,}개\n"
            "이카운트 API는 다음 단계에서 연결되며 현재는 화면과 Excel 흐름을 확인하는 테스트 버전입니다."
        )

    def refresh_entry_table(self) -> None:
        self.filtered_indices = self._visible_indices()
        self.entry_table.blockSignals(True)
        self.entry_table.setRowCount(len(self.filtered_indices))
        for table_row, source_index in enumerate(self.filtered_indices):
            row = self.rows[source_index]
            values = [row.item_code, row.item_name, row.headquarters_actual, row.ecount_headquarters, row.headquarters_difference, row.wekeep_actual, row.ecount_wekeep, row.wekeep_difference, row.total_difference, "일치" if row.total_difference == 0 else "차이"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, source_index)
                if column not in (2, 5):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column in (4, 7, 8):
                    item.setFont(FontProxy.bold_font(item.font()))
                    item.setForeground(QColor("#064fbd") if int(value) > 0 else QColor("#d11f2f") if int(value) < 0 else QColor("#536174"))
                    item.setText(f"+{value}" if int(value) > 0 else str(value))
                item.setBackground(QColor("white"))
                self.entry_table.setItem(table_row, column, item)
        self.entry_table.blockSignals(False)
        self.entry_summary.setText(f"전체 {len(self.rows):,}개 중 {len(self.filtered_indices):,}개 표시 · 실재고 입력 즉시 차이가 계산됩니다.")

    def update_entry_row(self, table_row: int, source_index: int) -> None:
        row = self.rows[source_index]
        values = {
            2: row.headquarters_actual,
            4: row.headquarters_difference,
            5: row.wekeep_actual,
            7: row.wekeep_difference,
            8: row.total_difference,
            9: "일치" if row.total_difference == 0 else "차이",
        }
        self.entry_table.blockSignals(True)
        try:
            for column, value in values.items():
                item = self.entry_table.item(table_row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.entry_table.setItem(table_row, column, item)
                item.setData(Qt.ItemDataRole.UserRole, source_index)
                if column in (4, 7, 8):
                    numeric = int(value)
                    item.setText(f"+{numeric}" if numeric > 0 else str(numeric))
                    item.setFont(FontProxy.bold_font(item.font()))
                    item.setForeground(QColor("#064fbd") if numeric > 0 else QColor("#d11f2f") if numeric < 0 else QColor("#536174"))
                else:
                    item.setText(str(value))
                item.setBackground(QColor("white"))
        finally:
            self.entry_table.blockSignals(False)

    def on_entry_changed(self, table_row: int, column: int) -> None:
        if column not in (2, 5) or not (0 <= table_row < len(self.filtered_indices)):
            return
        source_index = self.filtered_indices[table_row]
        try:
            value = int(self.entry_table.item(table_row, column).text().replace(",", "") or 0)
        except ValueError:
            self.refresh_entry_table()
            return
        if column == 2:
            self.rows[source_index].headquarters_actual = value
        else:
            self.rows[source_index].wekeep_actual = value
        filtering_by_difference = self.status_filter.currentText() != "전체" or self.location_filter.currentText() != "전체 위치"
        if self.sort_filter.currentText() == "차이 큰 순" or filtering_by_difference:
            self.refresh_entry_table()
        else:
            self.update_entry_row(table_row, source_index)
        self.update_dashboard_status()

    def on_tab_changed(self, index: int) -> None:
        if index == 3:
            self.refresh_review_table()

    def refresh_review_table(self) -> None:
        indices = [index for index, row in enumerate(self.rows) if row.total_difference != 0]
        indices.sort(key=lambda index: -abs(self.rows[index].total_difference))
        self.review_table.setRowCount(len(indices))
        for table_row, source_index in enumerate(indices):
            row = self.rows[source_index]
            values = [row.item_code, row.item_name, row.headquarters_difference, row.wekeep_difference, row.total_difference, "검토 완료" if row.reviewed else "미처리"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, source_index)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column in (2, 3, 4):
                    numeric = int(value)
                    item.setText(f"+{numeric}" if numeric > 0 else str(numeric))
                    item.setForeground(QColor("#064fbd") if numeric > 0 else QColor("#d11f2f") if numeric < 0 else QColor("#536174"))
                item.setBackground(QColor("white"))
                self.review_table.setItem(table_row, column, item)

    def select_review_row(self, table_row: int, _column: int) -> None:
        item = self.review_table.item(table_row, 0)
        if not item:
            return
        self.current_review_index = int(item.data(Qt.ItemDataRole.UserRole))
        row = self.rows[self.current_review_index]
        self.review_item.setText(f"{row.item_code}\n{row.item_name}")
        reason_index = self.reason_combo.findText(row.reason or "미확인")
        self.reason_combo.setCurrentIndex(max(reason_index, 0))
        self.action_edit.setPlainText(row.action)
        self.reviewed_check.setChecked(row.reviewed)

    def save_review(self) -> None:
        if self.current_review_index is None:
            QMessageBox.information(self, "품목 선택", "왼쪽 표에서 검토할 품목을 선택하세요.")
            return
        row = self.rows[self.current_review_index]
        row.reason = self.reason_combo.currentText()
        row.action = self.action_edit.toPlainText().strip()
        row.reviewed = self.reviewed_check.isChecked()
        self.refresh_all()

    def load_wekeep(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "위킵 재고 Excel 선택", "", "Excel 파일 (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            imported = import_wekeep_rows(path)
        except Exception as exc:
            QMessageBox.critical(self, "위킵 파일 오류", str(exc))
            return
        matched = 0
        for row in self.rows:
            if row.item_code in imported:
                name, quantity = imported[row.item_code]
                row.wekeep_actual = quantity
                if not row.item_name and name:
                    row.item_name = name
                matched += 1
        self.source_status.setText(f"위킵 반영 완료 · {Path(path).name} · {matched:,}개 품목")
        self.refresh_all()
        QMessageBox.information(self, "위킵 재고 반영", f"{len(imported):,}개 행을 읽고 현재 목록의 {matched:,}개 품목에 반영했습니다.")

    def export_result(self) -> None:
        default_name = f"REQM_주간재고조사_{datetime.now():%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "주간재고조사 Excel 저장", default_name, "Excel 파일 (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_inventory_workbook(path, self.rows)
        except Exception as exc:
            QMessageBox.critical(self, "Excel 생성 실패", str(exc))
            return
        QMessageBox.information(self, "Excel 생성 완료", f"주간재고조사 파일을 저장했습니다.\n{path}")


class FontProxy:
    @staticmethod
    def bold_font(font):
        font.setBold(True)
        return font
