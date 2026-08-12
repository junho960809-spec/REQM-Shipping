import json
import sys
import hashlib
import os
import shutil
import subprocess
import uuid
import urllib.request
import webbrowser
from datetime import datetime
from urllib.parse import quote
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QAbstractItemView,
    QVBoxLayout,
    QWidget,
)
from supabase import Client, create_client

from excel_loader import COLUMN_ALIASES, load_orders, missing_shipping_columns, suggest_header_row
from matcher import ProductMatcher
from matcher import compact
from matcher import order_source_text
from shipping_export import export_with_format
from duty_free_loader import load_duty_free, load_simple_duty_free, match_barcodes
from duty_free_reference_store import find_reference_mapping
from catalog_import import compare_catalog, load_item_catalog
from location_store import (
    load_locations,
    local_to_remote,
    save_locations,
    sync_remote_locations,
)
from format_store import upsert_format
from output_format_store import delete_output_format, load_output_formats, save_custom_output_format
from direct_suggester import component_payload, components_text, suggest_direct_order
from ecount_dialog import EcountTransferDialog
from ecount_client import load_completed_transfer_requests
from marketplace_option_store import (
    complete_option_action,
    create_option_action,
    load_option_actions,
    load_option_mappings,
    upsert_option_mapping,
)
from marketplace_automation_settings import load_29cm_profile_path, save_29cm_profile_path
from marketplace_29cm_executor import execute_29cm_action, sync_29cm_catalog, open_29cm_login
from marketplace_catalog_store import save_catalog_options, search_catalog_options


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_CONFIG = {
    "supabase_url": "https://jcslohuraqclhryeqxoc.supabase.co",
    "supabase_publishable_key": "sb_publishable_dafbXHpLHVPDhsMwm_B5RA_LgCqlWeg",
    "ecount": {
        "company_code": "304293",
        "user_id": "",
        "zone": "AB",
        "employee_code": "",
        "source_warehouse": "100",
        "target_warehouse": "300",
        "target_channel": "",
        "test_mode": False,
        "remarks": "REQM 출고 창고이동",
    },
}
ADMIN_USER_ID = "c7937d51-1a14-47aa-987e-6254c6c79014"
APP_VERSION = "1.0.42"
UPDATE_BASE_URL = "https://jcslohuraqclhryeqxoc.supabase.co/storage/v1/object/public/reqm-updates"
UPDATE_MANIFEST_URL = f"{UPDATE_BASE_URL}/manifest.json"
RECENT_WORK_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "recent_work.json"
CALENDAR_EVENT_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "calendar_events.json"
WIDGET_SETTINGS_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "widget_settings.json"


class MarketplaceActionHistoryDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("상품 관리 처리 이력")
        self.resize(1000, 440)
        layout = QVBoxLayout(self)
        title = QLabel("품절 처리 · 판매 재개 이력")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "요청 시각", "요청 계정", "처리 계정", "판매처", "상품번호", "옵션번호",
            "내부 품목", "작업", "상태",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        self.refresh()

    def refresh(self) -> None:
        rows = list(reversed(load_option_actions()))
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("requested_at", ""), row.get("requested_by", ""),
                row.get("processed_by", "") or "처리 대기", row.get("marketplace", ""),
                row.get("marketplace_item_no", ""), row.get("marketplace_option_no", ""),
                row.get("internal_item_code", ""),
                "품절 처리" if row.get("action") == "SOLD_OUT" else "판매 재개",
                row.get("status", ""),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))


class MarketplaceOptionDialog(QDialog):
    """판매처 옵션 매핑과 전용 자동화 PC용 요청을 관리한다."""

    def __init__(self, requested_by: str = "", parent=None) -> None:
        super().__init__(parent)
        self.requested_by = requested_by.strip()
        self.setWindowTitle("상품 관리")
        self.resize(960, 620)
        layout = QVBoxLayout(self)
        title = QLabel("상품 관리")
        title.setObjectName("sectionTitle")
        hint = QLabel(
            "로그인 세션은 전용 자동화 PC에만 보관합니다. 이 화면에서는 상품·옵션 매핑과 "
            "품절/판매 재개 요청을 관리합니다."
        )
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

        catalog_actions = QHBoxLayout()
        self.catalog_search = QLineEdit()
        self.catalog_search.setPlaceholderText("29CM 상품명·옵션명·상품번호로 검색")
        self.catalog_search.textChanged.connect(self.refresh_catalog)
        sync_catalog = QPushButton("29CM 목록 동기화")
        sync_catalog.setObjectName("primaryButton")
        sync_catalog.clicked.connect(self.sync_catalog)
        catalog_actions.addWidget(self.catalog_search, 1)
        catalog_actions.addWidget(sync_catalog)
        layout.addLayout(catalog_actions)

        self.catalog_table = QTableWidget(0, 6)
        self.catalog_table.setHorizontalHeaderLabels(["상품명", "옵션명", "재고", "상태", "상품번호", "옵션번호"])
        self.catalog_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.catalog_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.catalog_table.itemSelectionChanged.connect(self.load_selected_catalog_option)
        self.catalog_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.catalog_table.setMaximumHeight(210)
        layout.addWidget(self.catalog_table)

        form = QFormLayout()
        self.marketplace = QComboBox()
        self.marketplace.addItem("29CM")
        self.internal_item = QLineEdit()
        self.internal_option = QLineEdit()
        self.item_no = QLineEdit()
        self.option_no = QLineEdit()
        self.option_name = QLineEdit()
        self.restock_stock = QLineEdit("1")
        self.restock_stock.setPlaceholderText("판매 재개 재고 수량")
        form.addRow("판매처", self.marketplace)
        form.addRow("내부 품목코드", self.internal_item)
        form.addRow("내부 옵션명", self.internal_option)
        form.addRow("판매처 상품번호", self.item_no)
        form.addRow("판매처 옵션번호", self.option_no)
        form.addRow("판매처 옵션명", self.option_name)
        form.addRow("판매 재개 재고", self.restock_stock)
        layout.addLayout(form)

        actions = QHBoxLayout()
        save = QPushButton("매핑 저장")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_mapping)
        open_site = QPushButton("29CM 상품 열기")
        open_site.clicked.connect(self.open_29cm_item)
        profile = QPushButton("REQM_CS 프로필 설정")
        profile.clicked.connect(self.configure_29cm_profile)
        login = QPushButton("29CM 로그인 창 열기")
        login.clicked.connect(self.open_29cm_login)
        history = QPushButton("처리 이력")
        history.clicked.connect(self.open_history)
        sold_out = QPushButton("품절 처리")
        sold_out.clicked.connect(lambda: self.request_action("SOLD_OUT"))
        restock = QPushButton("판매 재개")
        restock.clicked.connect(lambda: self.request_action("RESTOCK"))
        execute = QPushButton("대기 요청 실행")
        execute.setObjectName("primaryButton")
        execute.clicked.connect(self.execute_pending_action)
        actions.addWidget(save)
        actions.addWidget(open_site)
        actions.addWidget(profile)
        actions.addWidget(login)
        actions.addWidget(history)
        actions.addStretch(1)
        actions.addWidget(sold_out)
        actions.addWidget(restock)
        actions.addWidget(execute)
        layout.addLayout(actions)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["판매처", "내부 품목", "내부 옵션", "상품번호", "옵션번호", "옵션명"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_selected_mapping)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def current_mapping(self) -> dict[str, str]:
        return {
            "marketplace": self.marketplace.currentText(),
            "internal_item_code": self.internal_item.text(),
            "internal_option_name": self.internal_option.text(),
            "marketplace_item_no": self.item_no.text(),
            "marketplace_option_no": self.option_no.text(),
            "marketplace_option_name": self.option_name.text(),
        }

    def refresh(self) -> None:
        rows = load_option_mappings()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("marketplace", ""), row.get("internal_item_code", ""),
                row.get("internal_option_name", ""), row.get("marketplace_item_no", ""),
                row.get("marketplace_option_no", ""), row.get("marketplace_option_name", ""),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
        pending = sum(1 for row in load_option_actions() if row.get("status") == "PENDING")
        self.status.setText(f"저장된 옵션 매핑 {len(rows)}개 · 전용 자동화 PC 처리 대기 요청 {pending}건")
        self.refresh_catalog()

    def refresh_catalog(self) -> None:
        if not hasattr(self, "catalog_table"):
            return
        rows = search_catalog_options(self.catalog_search.text(), self.marketplace.currentText())
        self.catalog_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("marketplace_item_name", ""), row.get("marketplace_option_name", ""),
                row.get("stock", ""), row.get("sale_status", ""),
                row.get("marketplace_item_no", ""), row.get("marketplace_option_no", ""),
            ]
            for column, value in enumerate(values):
                self.catalog_table.setItem(row_index, column, QTableWidgetItem(str(value)))

    def load_selected_catalog_option(self) -> None:
        row = self.catalog_table.currentRow()
        if row < 0:
            return
        values = [self.catalog_table.item(row, column).text() if self.catalog_table.item(row, column) else "" for column in range(6)]
        item_name, option_name, _stock, _status, item_no, option_no = values
        self.item_no.setText(item_no)
        self.option_no.setText(option_no)
        self.option_name.setText(option_name)
        if not self.internal_item.text().strip():
            self.internal_item.setText(item_name)
        if not self.internal_option.text().strip():
            self.internal_option.setText(option_name)
        self.status.setText(f"선택됨 · {item_name} / {option_name} (상품번호 {item_no}, 옵션번호 {option_no})")

    def sync_catalog(self) -> None:
        answer = QMessageBox.question(
            self,
            "29CM 목록 동기화",
            "REQM_CS 프로필로 29CM 옵션 재고 화면을 열어 현재 조회 가능한 목록을 가져옵니다.\n"
            "동기화 중에는 해당 REQM_CS Chrome 창을 모두 닫아야 합니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = sync_29cm_catalog(load_29cm_profile_path())
            saved = save_catalog_options(self.marketplace.currentText(), rows)
            self.refresh_catalog()
            self.status.setText(
                f"29CM 옵션 목록 {len(saved)}개를 동기화했습니다. 검색 결과에서 상품과 옵션을 선택해 주세요."
            )
        except Exception as error:
            QMessageBox.critical(self, "29CM 목록 동기화 실패", str(error))
        finally:
            QApplication.restoreOverrideCursor()

    def load_selected_mapping(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        values = [self.table.item(row, column).text() if self.table.item(row, column) else "" for column in range(6)]
        self.marketplace.setCurrentText(values[0])
        self.internal_item.setText(values[1])
        self.internal_option.setText(values[2])
        self.item_no.setText(values[3])
        self.option_no.setText(values[4])
        self.option_name.setText(values[5])

    def save_mapping(self) -> None:
        try:
            upsert_option_mapping(self.current_mapping())
        except ValueError as error:
            QMessageBox.warning(self, "매핑 저장", str(error))
            return
        self.refresh()
        self.status.setText("매핑을 저장했습니다. 실제 처리 전에는 전용 자동화 PC에서 로그인 상태를 확인합니다.")

    def request_action(self, action: str) -> None:
        label = "품절 처리" if action == "SOLD_OUT" else "판매 재개"
        answer = QMessageBox.question(
            self,
            label,
            f"29CM 옵션 {self.option_no.text().strip() or '(미입력)'}에 {label} 요청을 등록합니다.\n"
            "전용 자동화 PC가 처리하기 전에는 판매 상태가 변경되지 않습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            target_stock = "0" if action == "SOLD_OUT" else self.restock_stock.text().strip()
            if action == "RESTOCK" and (not target_stock.isdigit() or int(target_stock) <= 0):
                raise ValueError("판매 재개 재고 수량은 1개 이상 입력해 주세요.")
            create_option_action(self.current_mapping(), action, self.requested_by, target_stock)
        except ValueError as error:
            QMessageBox.warning(self, label, str(error))
            return
        self.refresh()
        self.status.setText(f"{label} 요청을 등록했습니다. 처리 이력에서 요청 계정과 상태를 확인할 수 있습니다.")

    def execute_pending_action(self) -> None:
        mapping = self.current_mapping()
        pending = next(
            (
                row for row in reversed(load_option_actions())
                if row.get("status") == "PENDING"
                and row.get("marketplace") == mapping["marketplace"]
                and row.get("marketplace_item_no") == mapping["marketplace_item_no"]
                and row.get("marketplace_option_no") == mapping["marketplace_option_no"]
            ),
            None,
        )
        if pending is None:
            QMessageBox.information(self, "대기 요청 실행", "이 옵션의 대기 중인 품절 또는 판매 재개 요청이 없습니다.")
            return
        label = "품절 처리" if pending.get("action") == "SOLD_OUT" else f"판매 재개 ({pending.get('target_stock')}개)"
        answer = QMessageBox.question(
            self,
            "29CM 실제 실행 확인",
            f"REQM_CS 프로필로 29CM 옵션 {pending.get('marketplace_option_no')}의 {label}를 실제 실행합니다.\n"
            "판매 상태가 변경되며, 실행 후 재고와 상태를 다시 검증합니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = execute_29cm_action(pending, load_29cm_profile_path())
            complete_option_action(pending["action_id"], "COMPLETED", self.requested_by, details=result)
            self.status.setText(
                f"29CM {label} 완료 · 이전 {result['previous_stock']}개 → {result['target_stock']}개 · "
                f"상태 {result['verified_status']}"
            )
        except Exception as error:
            complete_option_action(pending["action_id"], "FAILED", self.requested_by, str(error))
            QMessageBox.critical(self, "29CM 실행 실패", str(error))
        self.refresh()

    def open_history(self) -> None:
        MarketplaceActionHistoryDialog(self).exec()

    def configure_29cm_profile(self) -> None:
        profile_path, accepted = QInputDialog.getText(
            self,
            "29CM REQM_CS 프로필 경로",
            "Chrome Profile Path",
            text=load_29cm_profile_path(),
        )
        if not accepted:
            return
        try:
            save_29cm_profile_path(profile_path)
            self.status.setText("REQM_CS 프로필 경로를 저장했습니다.")
        except ValueError as error:
            QMessageBox.warning(self, "29CM 프로필", str(error))

    def open_29cm_login(self) -> None:
        try:
            open_29cm_login(load_29cm_profile_path())
            self.status.setText("29CM 로그인 창을 열었습니다. 회사 CS 판매처 계정으로 로그인한 뒤 창을 닫고 목록 동기화를 실행해 주세요.")
        except Exception as error:
            QMessageBox.critical(self, "29CM 로그인 창", str(error))

    def open_29cm_item(self) -> None:
        item_no = self.item_no.text().strip()
        if not item_no:
            QMessageBox.warning(self, "29CM 상품 열기", "판매처 상품번호를 입력해 주세요.")
            return
        webbrowser.open(f"https://partner-item.29cm.co.kr/{quote(item_no)}?from=option-stock")


def load_recent_work() -> list[dict]:
    try:
        data = json.loads(RECENT_WORK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def save_recent_work(rows: list[dict]) -> None:
    RECENT_WORK_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECENT_WORK_PATH.write_text(
        json.dumps(rows[:30], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_calendar_events() -> list[dict]:
    try:
        data = json.loads(CALENDAR_EVENT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def save_calendar_events(rows: list[dict]) -> None:
    CALENDAR_EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_EVENT_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_widget_target() -> str:
    try:
        target = str(json.loads(WIDGET_SETTINGS_PATH.read_text(encoding="utf-8")).get("target", "dashboard"))
        return target if target in {"dashboard", "shipping", "inventory"} else "dashboard"
    except (OSError, ValueError, TypeError):
        return "dashboard"


def save_widget_target(target: str) -> None:
    WIDGET_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WIDGET_SETTINGS_PATH.write_text(
        json.dumps({"target": target}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remove_legacy_transfer_credentials() -> None:
    """Remove the encrypted API key left by the retired warehouse-transfer feature."""
    credential_path = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "credentials.json"
    try:
        credential_path.unlink(missing_ok=True)
    except OSError:
        pass


def version_key(value: str) -> tuple[int, ...]:
    parts = []
    for part in str(value or "0").split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


class UpdateCheckWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            request = urllib.request.Request(UPDATE_MANIFEST_URL, headers={"User-Agent": "REQM-Updater"})
            with urllib.request.urlopen(request, timeout=15) as response:
                manifest = json.loads(response.read().decode("utf-8"))
            for key in ("version", "file", "sha256"):
                if not manifest.get(key):
                    raise ValueError(f"업데이트 정보에 {key} 값이 없습니다.")
            if not manifest.get("chunks") and not manifest.get("file"):
                raise ValueError("업데이트 파일 정보가 없습니다.")
            self.succeeded.emit(manifest)
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    succeeded = Signal(str, object)
    failed = Signal(str)

    def __init__(self, manifest: dict):
        super().__init__()
        self.manifest = manifest

    def run(self) -> None:
        try:
            update_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "updates"
            update_dir.mkdir(parents=True, exist_ok=True)
            file_name = Path(str(self.manifest["file"])).name
            target = update_dir / f"{self.manifest['version']}_{file_name}"
            digest = hashlib.sha256()
            remote_parts = self.manifest.get("chunks") or [file_name]
            with target.open("wb") as output:
                for remote_name in remote_parts:
                    safe_name = Path(str(remote_name)).name
                    url = f"{UPDATE_BASE_URL}/{quote(safe_name)}"
                    request = urllib.request.Request(url, headers={"User-Agent": "REQM-Updater"})
                    with urllib.request.urlopen(request, timeout=60) as response:
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            output.write(chunk)
                            digest.update(chunk)
            expected = str(self.manifest["sha256"]).strip().lower()
            if digest.hexdigest().lower() != expected:
                target.unlink(missing_ok=True)
                raise ValueError("다운로드 파일의 보안 해시가 일치하지 않습니다.")
            self.succeeded.emit(str(target), self.manifest)
        except Exception as exc:
            self.failed.emit(str(exc))


class ItemManagerDialog(QDialog):
    """관리자 전용 표준 품목 관리 화면."""
    def __init__(self, client: Client, items: list[dict], barcodes: list[dict], parent=None):
        super().__init__(parent)
        self.client, self.items, self.barcodes = client, items, barcodes
        self.setWindowTitle("DB 품목 관리 · 관리자")
        self.resize(900, 560)
        self.search = QLineEdit()
        self.search.setPlaceholderText("품목코드 또는 품목명 검색")
        self.grid = QTableWidget(0, 6)
        self.grid.setHorizontalHeaderLabels(["품목코드", "표준 품목명", "모델", "색상", "형태", "사용"])
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        import_btn = QPushButton("엑셀 품목 가져오기")
        import_btn.setObjectName("primaryButton")
        add_btn, edit_btn, active_btn = QPushButton("신규 품목"), QPushButton("선택 수정"), QPushButton("사용/중지 전환")
        delete_btn = QPushButton("삭제")
        buttons = QHBoxLayout()
        for button in (import_btn, add_btn, edit_btn, active_btn, delete_btn): buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("표준 품목(items) 관리 — 변경 내용은 Supabase에 즉시 저장됩니다."))
        layout.addWidget(self.search); layout.addWidget(self.grid); layout.addLayout(buttons)
        self.search.textChanged.connect(self.refresh)
        import_btn.clicked.connect(self.import_catalog)
        add_btn.clicked.connect(self.add_item); edit_btn.clicked.connect(self.edit_item); active_btn.clicked.connect(self.toggle_active)
        delete_btn.clicked.connect(self.delete_items)
        self.refresh()

    def import_catalog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "품목코드·품목명·바코드 파일 선택",
            "",
            "Excel 파일 (*.xlsx *.xlsm)",
        )
        if not path:
            return
        try:
            records = load_item_catalog(path)
            result = compare_catalog(records, self.items, self.barcodes)
        except Exception as exc:
            QMessageBox.critical(self, "파일 분석 실패", str(exc))
            return

        conflicts = result["barcode_conflicts"]
        conflict_note = ""
        if conflicts:
            examples = ", ".join(
                f"{row['barcode']} ({row['item_code']}↔{row['db_item_code']})"
                for row in conflicts[:3]
            )
            conflict_note = f"\n바코드 충돌 {len(conflicts):,}개: {examples}\n충돌 항목은 등록하지 않습니다."
        message = (
            f"파일 품목: {len(records):,}개\n"
            f"신규 품목: {len(result['new_items']):,}개\n"
            f"DB에 이미 있는 품목: {len(result['existing_items']):,}개\n"
            f"이름이 다른 기존 품목: {len(result['renamed_items']):,}개 (DB 이름 유지)\n"
            f"신규 바코드: {len(result['new_barcodes']):,}개\n"
            f"DB에 이미 있는 바코드: {len(result['existing_barcodes']):,}개"
            f"{conflict_note}\n\n신규 품목과 충돌 없는 신규 바코드만 DB에 등록할까요?"
        )
        answer = QMessageBox.question(
            self,
            "가져오기 미리보기",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        item_payload = [
            {
                "item_code": row["item_code"],
                "standard_name": row["standard_name"],
                "model": "",
                "color": "",
                "form": "",
                "is_active": True,
                "review_status": "confirmed",
            }
            for row in result["new_items"]
        ]
        barcode_payload = [
            {"item_code": row["item_code"], "barcode": row["barcode"], "is_active": True}
            for row in result["new_barcodes"]
        ]
        try:
            if item_payload:
                response = self.client.table("items").insert(item_payload).execute()
                self.items.extend(response.data or item_payload)
            if barcode_payload:
                response = self.client.table("item_barcodes").insert(barcode_payload).execute()
                self.barcodes.extend(response.data or barcode_payload)
            self.refresh()
            QMessageBox.information(
                self,
                "가져오기 완료",
                f"신규 품목 {len(item_payload):,}개와 신규 바코드 {len(barcode_payload):,}개를 등록했습니다.",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "DB 등록 실패",
                "일부 품목이 먼저 등록되었을 수 있습니다. DB를 다시 불러온 뒤 재시도하세요.\n\n" + str(exc),
            )

    def refresh(self) -> None:
        word = self.search.text().strip().lower()
        rows = [r for r in self.items if word in f"{r.get('item_code','')} {r.get('standard_name','')}".lower()]
        self.grid.setRowCount(len(rows))
        self.grid_rows = rows
        for i, row in enumerate(rows):
            values = [row.get("item_code", ""), row.get("standard_name", ""), row.get("model", ""), row.get("color", ""), row.get("form", ""), "사용" if row.get("is_active", True) else "중지"]
            for j, value in enumerate(values): self.grid.setItem(i, j, QTableWidgetItem(str(value or "")))

    def selected(self) -> dict | None:
        row = self.grid.currentRow()
        return self.grid_rows[row] if 0 <= row < len(self.grid_rows) else None

    def ask_fields(self, original=None) -> dict | None:
        original = original or {}
        result = {}
        for key, label in (("item_code", "품목코드"), ("standard_name", "표준 품목명"), ("model", "모델"), ("color", "색상"), ("form", "형태")):
            value, ok = QInputDialog.getText(self, "품목 정보", label, text=str(original.get(key, "") or ""))
            if not ok: return None
            result[key] = value.strip()
        if not result["item_code"] or not result["standard_name"]:
            QMessageBox.warning(self, "필수값", "품목코드와 표준 품목명은 필수입니다."); return None
        result["is_active"] = original.get("is_active", True)
        result["review_status"] = original.get("review_status", "confirmed")
        return result

    def add_item(self) -> None:
        data = self.ask_fields()
        if data:
            try: self.client.table("items").insert(data).execute(); self.items.append(data); self.refresh()
            except Exception as exc: QMessageBox.critical(self, "저장 실패", str(exc))

    def edit_item(self) -> None:
        row = self.selected()
        if not row: QMessageBox.information(self, "선택", "수정할 품목을 선택하세요."); return
        data = self.ask_fields(row)
        if data:
            try:
                self.client.table("items").update(data).eq("item_code", row["item_code"]).execute(); row.update(data); self.refresh()
            except Exception as exc: QMessageBox.critical(self, "수정 실패", str(exc))

    def toggle_active(self) -> None:
        row = self.selected()
        if not row: return
        value = not row.get("is_active", True)
        try: self.client.table("items").update({"is_active": value}).eq("item_code", row["item_code"]).execute(); row["is_active"] = value; self.refresh()
        except Exception as exc: QMessageBox.critical(self, "변경 실패", str(exc))

    def delete_items(self) -> None:
        selected_indexes = self.grid.selectionModel().selectedRows()
        selected_rows = sorted({index.row() for index in selected_indexes})
        candidates = [self.grid_rows[index] for index in selected_rows if 0 <= index < len(self.grid_rows)]
        if not candidates:
            QMessageBox.information(self, "삭제할 품목 선택", "삭제할 품목을 선택하세요.\n여러 품목은 Ctrl 또는 Shift를 누른 채 선택할 수 있습니다.")
            return
        lines = "\n".join(
            f"• {row.get('item_code', '')} | {row.get('standard_name', '')}"
            for row in candidates[:20]
        )
        if len(candidates) > 20:
            lines += f"\n• 외 {len(candidates) - 20:,}개"
        answer = QMessageBox.question(
            self,
            "DB 품목 삭제 확인",
            f"선택한 {len(candidates):,}개 품목과 연결 바코드·상품 구성 정보를 DB에서 삭제합니다.\n\n"
            f"{lines}\n\n삭제 후 복구할 수 없습니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        codes = [str(row.get("item_code", "")) for row in candidates if row.get("item_code")]
        try:
            aliases = self.client.table("item_aliases").select("source_channel,normalized_source,components").execute().data or []
            related_aliases = [
                alias for alias in aliases
                if alias.get("normalized_source") and any(
                    str(component.get("item_code", "")) in codes
                    for component in (alias.get("components") or [])
                )
            ]
            for alias in related_aliases:
                self.client.table("item_aliases").delete().eq(
                    "source_channel", str(alias.get("source_channel", ""))
                ).eq(
                    "normalized_source", str(alias.get("normalized_source", ""))
                ).execute()
            self.client.table("item_barcodes").delete().in_("item_code", codes).execute()
            self.client.table("product_components").delete().in_("item_code", codes).execute()
            self.client.table("items").delete().in_("item_code", codes).execute()
            self.items[:] = [row for row in self.items if str(row.get("item_code", "")) not in codes]
            self.barcodes[:] = [row for row in self.barcodes if str(row.get("item_code", "")) not in codes]
            self.refresh()
            QMessageBox.information(self, "삭제 완료", f"선택한 DB 품목 {len(codes):,}개를 삭제했습니다.")
        except Exception as exc:
            QMessageBox.critical(self, "DB 삭제 실패", f"삭제 도중 오류가 발생했습니다. DB를 다시 불러와 확인하세요.\n\n{exc}")


class DutyLocationDialog(QDialog):
    """Local reusable duty-free shipping destination address book."""
    FIELD_LABELS = (
        ("name", "출고지 이름"),
        ("channel", "면세점 구분"),
        ("recipient", "수령인/담당자"),
        ("phone", "연락처"),
        ("zipcode", "우편번호"),
        ("address", "주소"),
        ("message", "배송 메모"),
    )

    def __init__(self, locations: list[dict[str, str]], parent=None, client=None):
        super().__init__(parent)
        self.locations = [dict(row) for row in locations]
        self.client = client
        self.current_id = ""
        self.setWindowTitle("면세점 출고지 정보 관리")
        self.resize(780, 520)
        self.list_widget = QListWidget()
        self.fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        for key, label in self.FIELD_LABELS:
            edit = QLineEdit()
            if key == "channel":
                edit.setPlaceholderText("예: 롯데면세점, 시티면세점 T2 606매장")
            elif key == "address":
                edit.setPlaceholderText("기본 주소와 상세 주소를 함께 입력")
            self.fields[key] = edit
            form.addRow(label, edit)

        new_button = QPushButton("새 출고지")
        sync_button = QPushButton("DB 주소 동기화")
        sync_button.setEnabled(self.client is not None)
        save_button = QPushButton("저장")
        save_button.setObjectName("primaryButton")
        delete_button = QPushButton("삭제")
        close_button = QPushButton("완료")
        buttons = QHBoxLayout()
        for button in (new_button, sync_button, save_button, delete_button, close_button):
            buttons.addWidget(button)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addStretch(1)
        right.addLayout(buttons)
        body = QHBoxLayout()
        body.addWidget(self.list_widget, 2)
        body.addLayout(right, 3)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("자주 사용하는 면세점·터미널·매장별 출고지를 등록하세요."))
        layout.addLayout(body)

        self.list_widget.currentRowChanged.connect(self.load_selected)
        new_button.clicked.connect(self.new_location)
        sync_button.clicked.connect(self.sync_from_database)
        save_button.clicked.connect(self.save_current)
        delete_button.clicked.connect(self.delete_current)
        close_button.clicked.connect(self.accept)
        self.refresh_list()
        if self.locations:
            self.list_widget.setCurrentRow(0)

    def refresh_list(self, selected_id: str = "") -> None:
        self.list_widget.clear()
        selected_row = -1
        for index, row in enumerate(self.locations):
            label = row.get("name", "")
            if row.get("channel"):
                label += f" · {row['channel']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row.get("id", ""))
            self.list_widget.addItem(item)
            if selected_id and row.get("id") == selected_id:
                selected_row = index
        if selected_row >= 0:
            self.list_widget.setCurrentRow(selected_row)

    def load_selected(self, index: int) -> None:
        if not (0 <= index < len(self.locations)):
            return
        row = self.locations[index]
        self.current_id = row.get("id", "")
        for key, edit in self.fields.items():
            edit.setText(row.get(key, ""))

    def new_location(self) -> None:
        self.current_id = ""
        self.list_widget.clearSelection()
        self.list_widget.setCurrentRow(-1)
        for edit in self.fields.values():
            edit.clear()
        self.fields["name"].setFocus()

    def save_current(self) -> None:
        data = {key: edit.text().strip() for key, edit in self.fields.items()}
        if not data["name"] or not data["address"]:
            QMessageBox.warning(self, "필수 정보", "출고지 이름과 주소는 반드시 입력하세요.")
            return
        data["id"] = self.current_id or str(uuid.uuid4())
        index = next((i for i, row in enumerate(self.locations) if row.get("id") == data["id"]), -1)
        if index >= 0:
            self.locations[index] = data
        else:
            self.locations.append(data)
        self.current_id = data["id"]
        save_locations(self.locations)
        if self.client is not None:
            try:
                self.client.table("duty_free_locations").upsert(
                    local_to_remote(data), on_conflict="location_id"
                ).execute()
            except Exception as exc:
                QMessageBox.warning(
                    self, "DB 동기화 안내",
                    f"PC 주소록에는 저장했지만 DB 동기화에 실패했습니다.\n{exc}",
                )
        self.refresh_list(self.current_id)
        QMessageBox.information(self, "저장 완료", f"'{data['name']}' 출고지를 저장했습니다.")

    def delete_current(self) -> None:
        index = next((i for i, row in enumerate(self.locations) if row.get("id") == self.current_id), -1)
        if index < 0:
            return
        answer = QMessageBox.question(
            self, "출고지 삭제", f"'{self.locations[index].get('name', '')}' 출고지를 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        deleted = self.locations.pop(index)
        self.current_id = ""
        save_locations(self.locations)
        if self.client is not None:
            try:
                self.client.table("duty_free_locations").update({"is_active": False}).eq(
                    "location_id", deleted.get("id", "")
                ).execute()
            except Exception as exc:
                QMessageBox.warning(
                    self, "DB 동기화 안내",
                    f"PC 주소록에서는 삭제했지만 DB 동기화에 실패했습니다.\n{exc}",
                )
        self.refresh_list()
        self.new_location()

    def sync_from_database(self) -> None:
        if self.client is None:
            return
        try:
            response = self.client.table("duty_free_locations").select("*").execute()
            self.locations, added = sync_remote_locations(list(response.data or []))
        except Exception as exc:
            QMessageBox.warning(self, "주소 동기화 실패", str(exc))
            return
        self.refresh_list(self.current_id)
        QMessageBox.information(
            self, "주소 동기화 완료",
            f"DB 주소록을 불러왔습니다. 신규 복구 {added:,}건 · 전체 {len(self.locations):,}건",
        )


class AccountSettingsDialog(QDialog):
    """로그인 입력란을 메인 화면 대신 작은 설정 창에서 관리한다."""
    def __init__(self, email: str, password: str, logged_in: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정 · 로그인 계정")
        self.setMinimumWidth(430)
        self.email_edit = QLineEdit(email)
        self.password_edit = QLineEdit(password)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        status = QLabel("현재 로그인된 계정입니다." if logged_in else "로그인에 사용할 계정을 입력하세요.")
        status.setWordWrap(True)
        form = QFormLayout()
        form.addRow("이메일", self.email_edit)
        form.addRow("비밀번호", self.password_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("적용")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(status)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def credentials(self) -> tuple[str, str]:
        return self.email_edit.text().strip(), self.password_edit.text()


class FileFormatDialog(QDialog):
    """One-time mapping wizard for an unknown seller spreadsheet format."""
    FIELD_LABELS = (
        ("order_number", "주문번호 *"),
        ("product_name", "상품명 *"),
        ("quantity", "수량 *"),
        ("recipient", "수령인 *"),
        ("option1", "상품옵션"),
        ("option2", "추가 옵션"),
        ("model", "모델명"),
        ("channel", "판매처"),
        ("phone", "연락처 *"),
        ("zipcode", "우편번호 *"),
        ("address1", "주소 *"),
        ("address2", "상세주소"),
        ("message", "배송메세지"),
        ("serial_number", "일련번호"),
    )
    REQUIRED_KEYS = {
        "order_number", "product_name", "quantity", "recipient", "phone", "zipcode", "address1",
    }

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.profile: dict = {}
        row_index, headers = suggest_header_row(file_path)
        self.header_row = row_index
        self.headers = [header for header in headers if header]
        self.setWindowTitle("새 주문 파일 양식 등록")
        self.resize(650, 650)
        self.name_edit = QLineEdit(Path(file_path).stem)
        self.combos: dict[str, QComboBox] = {}
        form = QFormLayout()
        form.addRow("양식 이름 *", self.name_edit)
        for key, label in self.FIELD_LABELS:
            combo = QComboBox()
            combo.addItem("(사용 안 함)", "")
            for header in self.headers:
                combo.addItem(header, header)
            aliases = {"".join(alias.lower().split()) for alias in COLUMN_ALIASES.get(key, [])}
            selected = next(
                (index for index, header in enumerate(self.headers, start=1)
                 if "".join(header.lower().split()) in aliases),
                0,
            )
            combo.setCurrentIndex(selected)
            self.combos[key] = combo
            form.addRow(label, combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("양식 저장 후 불러오기")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"처음 보는 주문 파일입니다. {self.header_row + 1}행을 제목 행으로 분석했습니다.\n"
            "각 항목에 해당하는 원본 열을 한 번만 확인하면 다음 파일부터 자동 인식합니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        name = self.name_edit.text().strip()
        mapping = {key: str(combo.currentData() or "") for key, combo in self.combos.items()}
        missing = [key for key in self.REQUIRED_KEYS if not mapping.get(key)]
        if not name or missing:
            QMessageBox.warning(self, "필수 연결", "양식 이름과 별표(*) 항목을 모두 연결하세요.")
            return
        self.profile = {
            "id": str(uuid.uuid4()),
            "name": f"판매처 직접파일 · {name}",
            "mapping": mapping,
        }
        upsert_format(self.profile)
        super().accept()


class OutputFormatDialog(QDialog):
    """Register an Excel file as a reusable shipping output template."""
    FIELD_LABELS = (
        ("order_number", "주문번호"),
        ("channel", "판매처"),
        ("product_name", "상품명 *"),
        ("options", "옵션명"),
        ("quantity", "수량 *"),
        ("recipient", "수령자 *"),
        ("phone", "핸드폰 *"),
        ("zipcode", "우편번호 *"),
        ("address", "주소 *"),
        ("message", "배송메세지"),
        ("serial_number", "일련번호"),
    )
    REQUIRED_KEYS = {"product_name", "quantity", "recipient", "phone", "zipcode", "address"}

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.profile: dict = {}
        self.file_path = file_path
        self.header_row, headers = suggest_header_row(file_path)
        self.headers = [header for header in headers if header]
        self.setWindowTitle("새 출력 양식 등록")
        self.resize(620, 620)
        self.name_edit = QLineEdit(Path(file_path).stem)
        self.combos: dict[str, QComboBox] = {}
        aliases = {
            "order_number": ["주문번호"],
            "channel": ["판매처", "판매처명"],
            "product_name": ["상품명", "품목명"],
            "options": ["옵션명", "옵션", "상품옵션"],
            "quantity": ["수량", "주문수량"],
            "recipient": ["수령자", "수령인", "수취인"],
            "phone": ["핸드폰", "휴대폰", "연락처"],
            "zipcode": ["우편번호"],
            "address": ["주소", "수령자주소"],
            "message": ["배송메세지", "배송메시지"],
            "serial_number": ["일련번호"],
        }
        form = QFormLayout()
        form.addRow("양식 이름 *", self.name_edit)
        for key, label in self.FIELD_LABELS:
            combo = QComboBox()
            combo.addItem("(사용 안 함)", "")
            for header in self.headers:
                combo.addItem(header, header)
            normalized = {"".join(value.lower().split()) for value in aliases.get(key, [])}
            selected = next(
                (index for index, header in enumerate(self.headers, start=1)
                 if "".join(header.lower().split()) in normalized),
                0,
            )
            combo.setCurrentIndex(selected)
            self.combos[key] = combo
            form.addRow(label, combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("출력 양식 저장")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"{self.header_row + 1}행을 제목 행으로 찾았습니다. 변환 결과를 넣을 열을 연결하세요.\n"
            "등록한 양식은 다음 실행에서도 다시 선택할 수 있습니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        name = self.name_edit.text().strip()
        selected = {key: str(combo.currentData() or "") for key, combo in self.combos.items()}
        missing = [key for key in self.REQUIRED_KEYS if not selected.get(key)]
        if not name or missing:
            QMessageBox.warning(self, "필수 연결", "양식 이름과 별표(*) 항목을 모두 연결하세요.")
            return
        mapping = {key: header for key, header in selected.items() if header}
        self.profile = save_custom_output_format(name, self.file_path, self.header_row, mapping)
        super().accept()


class OutputFormatManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("출력 양식 관리")
        self.resize(560, 410)
        self.list_widget = QListWidget()
        add_button = QPushButton("Excel 양식 추가")
        delete_button = QPushButton("선택 양식 삭제")
        close_button = QPushButton("완료")
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(delete_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        intro = QLabel("변환 결과로 사용할 Excel 양식을 등록하고 관리합니다. 기본 제공 양식은 삭제할 수 없습니다.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self.list_widget)
        layout.addLayout(buttons)
        add_button.clicked.connect(self.add_format)
        delete_button.clicked.connect(self.delete_selected)
        close_button.clicked.connect(self.accept)
        self.refresh()

    def refresh(self, selected_id: str = "") -> None:
        self.formats = load_output_formats()
        self.list_widget.clear()
        for index, profile in enumerate(self.formats):
            label = profile["name"] + (" · 기본 제공" if profile.get("builtin") else " · 사용자 등록")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, profile["id"])
            self.list_widget.addItem(item)
            if profile["id"] == selected_id:
                self.list_widget.setCurrentRow(index)

    def add_format(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "출력 Excel 양식 선택", "", "Excel 파일 (*.xlsx)")
        if not path:
            return
        dialog = OutputFormatDialog(path, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(dialog.profile.get("id", ""))

    def delete_selected(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        profile_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        profile = next((row for row in self.formats if row.get("id") == profile_id), None)
        if not profile or profile.get("builtin"):
            QMessageBox.information(self, "기본 양식", "기본 제공 출력 양식은 삭제할 수 없습니다.")
            return
        delete_output_format(profile_id)
        self.refresh()


class DirectSuggestionDialog(QDialog):
    def __init__(self, orders: list[dict], items: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("판매상품 자동 추천 · 일괄 확인")
        self.resize(1180, 650)
        self.entries: list[dict] = []
        seen: set[str] = set()
        for order in orders:
            if order.get("status") not in {"missing", "ambiguous"}:
                continue
            key = compact(order_source_text(order))
            if not key or key in seen:
                continue
            seen.add(key)
            self.entries.append({"key": key, "order": order, "suggestion": suggest_direct_order(order, items)})

        auto_count = sum(entry["suggestion"]["status"] == "auto" for entry in self.entries)
        review_count = len(self.entries) - auto_count
        info = QLabel(
            f"고유 미등록 조합 {len(self.entries):,}개 · 자동확정 가능 {auto_count:,}개 · 확인 필요 {review_count:,}개\n"
            "모델·색상·옵션 후보가 하나로 확실한 항목만 일괄 확정됩니다. 확인 필요 항목은 저장하지 않습니다."
        )
        info.setWordWrap(True)
        self.table = QTableWidget(len(self.entries), 5)
        self.table.setHorizontalHeaderLabels(["판정", "모델", "판매처 상품·옵션", "추천 DB 품목", "추천 근거"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row_index, entry in enumerate(self.entries):
            order, suggestion = entry["order"], entry["suggestion"]
            values = [
                "자동확정" if suggestion["status"] == "auto" else "확인 필요",
                order.get("model", ""),
                " / ".join(filter(None, [order.get("product_name", ""), order.get("options", "")])),
                components_text(suggestion["components"]),
                suggestion["reason"],
            ]
            color = QColor("#d9ead3") if suggestion["status"] == "auto" else QColor("#fce5cd")
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setBackground(color)
                self.table.setItem(row_index, column, item)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(f"자동 추천 {auto_count:,}개 일괄 확정")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("나중에 확인")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(auto_count > 0)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

    def confirmed_entries(self) -> list[dict]:
        return [entry for entry in self.entries if entry["suggestion"]["status"] == "auto"]

    def review_entries(self) -> list[dict]:
        return [entry for entry in self.entries if entry["suggestion"]["status"] != "auto"]


class CorrectionDialog(QDialog):
    def __init__(self, order: dict[str, str], items: list[dict], parent=None):
        super().__init__(parent)
        self.items = items
        self.selected: list[tuple[dict, int]] = []
        self.setWindowTitle("출고 품목 수동 수정")
        self.resize(850, 560)

        source = QLabel(
            f"원본 상품: {order.get('product_name', '')}\n"
            f"옵션: {order.get('options', '')}\n"
            f"현재 재고매칭: {order.get('matched_name', '')}"
        )
        source.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("품목코드, 품목명, 모델, 색상 검색")
        self.candidates = QListWidget()
        self.chosen = QListWidget()
        self.scope = QComboBox()
        self.scope.addItem("이 행만 수정", "row")
        self.scope.addItem("현재 파일의 같은 상품 모두 수정", "same")
        self.scope.addItem("같은 상품 전체 수정 + Supabase 별칭 저장", "database")
        add_button = QPushButton("선택 품목 추가 →")
        remove_button = QPushButton("선택 구성품 제거")

        lists = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("DB 품목 검색 결과"))
        left.addWidget(self.candidates)
        left.addWidget(add_button)
        right = QVBoxLayout()
        right.addWidget(QLabel("적용할 출고 구성품"))
        right.addWidget(self.chosen)
        right.addWidget(remove_button)
        lists.addLayout(left)
        lists.addLayout(right)

        form = QFormLayout()
        form.addRow("적용 범위", self.scope)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(source)
        layout.addWidget(self.search)
        layout.addLayout(lists)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self.refresh_candidates)
        add_button.clicked.connect(self.add_item)
        self.candidates.itemDoubleClicked.connect(lambda *_: self.add_item())
        remove_button.clicked.connect(self.remove_item)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        self.refresh_candidates()

    def refresh_candidates(self) -> None:
        keyword = self.search.text().strip().lower()
        self.candidates.clear()
        shown = 0
        for item in self.items:
            text = " | ".join(
                str(item.get(key, "")) for key in ("item_code", "standard_name", "model", "color", "form")
            )
            if keyword and keyword not in text.lower():
                continue
            widget_item = QListWidgetItem(text)
            widget_item.setData(256, item)
            self.candidates.addItem(widget_item)
            shown += 1
            if shown >= 300:
                break

    def add_item(self) -> None:
        current = self.candidates.currentItem()
        if current is None:
            QMessageBox.information(self, "품목 선택", "추가할 품목을 먼저 선택하세요.")
            return
        item = current.data(256)
        quantity, ok = QInputDialog.getInt(self, "구성 수량", "이 품목의 세트 구성 수량", 1, 1, 999)
        if not ok:
            return
        self.selected.append((item, quantity))
        self.refresh_chosen()

    def remove_item(self) -> None:
        row = self.chosen.currentRow()
        if row >= 0:
            self.selected.pop(row)
            self.refresh_chosen()

    def refresh_chosen(self) -> None:
        self.chosen.clear()
        for item, quantity in self.selected:
            self.chosen.addItem(f"{item.get('item_code', '')} × {quantity} | {item.get('standard_name', '')}")

    def validate_and_accept(self) -> None:
        if not self.selected:
            QMessageBox.warning(self, "구성품 확인", "출고할 품목을 한 개 이상 추가하세요.")
            return
        self.accept()

    def result_data(self) -> tuple[str, str, str, list[dict]]:
        names = " / ".join(str(item.get("standard_name", "")) for item, _ in self.selected)
        components = " + ".join(f"{item.get('item_code', '')}×{qty}" for item, qty in self.selected)
        component_data = [
            {"item_code": item.get("item_code", ""), "standard_name": item.get("standard_name", ""), "quantity": qty}
            for item, qty in self.selected
        ]
        return names, components, str(self.scope.currentData()), component_data


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config.update({key: value for key, value in loaded.items() if key != "ecount"})
    config["ecount"].update(loaded.get("ecount") or {})
    return config


def fetch_all_rows(client: Client, table: str, page_size: int = 1000) -> list[dict]:
    """Load a Supabase table without silently truncating rows at the API page limit."""
    rows: list[dict] = []
    start = 0
    while True:
        response = (
            client.table(table)
            .select("*")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


class LoginWorker(QThread):
    succeeded = Signal(int, object)
    failed = Signal(str)

    def __init__(self, email: str, password: str):
        super().__init__()
        self.email = email
        self.password = password

    def run(self) -> None:
        try:
            config = load_config()
            client: Client = create_client(
                config["supabase_url"], config["supabase_publishable_key"]
            )
            auth_result = client.auth.sign_in_with_password(
                {"email": self.email, "password": self.password}
            )
            items = fetch_all_rows(client, "items")
            products = fetch_all_rows(client, "registered_products")
            components = fetch_all_rows(client, "product_components")
            barcodes = fetch_all_rows(client, "item_barcodes")
            duty_locations = fetch_all_rows(client, "duty_free_locations")
            try:
                aliases = fetch_all_rows(client, "item_aliases")
            except Exception:
                aliases = []
            try:
                role_rows = fetch_all_rows(client, "app_user_roles")
                app_role = next((r.get("role") for r in role_rows if str(r.get("user_id")) == str(auth_result.user.id)), "viewer")
            except Exception:
                app_role = "admin" if str(auth_result.user.id) == ADMIN_USER_ID else "viewer"
            self.succeeded.emit(
                len(items),
                {"items": items, "products": products, "components": components, "barcodes": barcodes,
                 "duty_locations": duty_locations, "aliases": aliases, "client": client,
                 "auth_user_id": str(auth_result.user.id), "app_role": app_role},
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class StartupLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.catalog = None
        self.item_count = 0
        self.setObjectName("startupLogin")
        self.setWindowTitle("REQM 로그인")
        self.setFixedSize(470, 330)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 28)
        layout.setSpacing(13)
        title = QLabel("REQM 로그인")
        title.setObjectName("dashboardTitle")
        subtitle = QLabel("등록된 프로그램 계정으로 로그인해 주세요.")
        subtitle.setObjectName("dashboardHint")
        self.email = QLineEdit()
        self.email.setPlaceholderText("이메일")
        self.password = QLineEdit()
        self.password.setPlaceholderText("비밀번호")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.message = QLabel("로그인 후 물류 대시보드를 사용할 수 있습니다.")
        self.message.setObjectName("dashboardHint")
        self.message.setWordWrap(True)
        self.login_button = QPushButton("로그인")
        self.login_button.setObjectName("primaryButton")
        self.login_button.setFixedHeight(46)
        cancel_button = QPushButton("종료")
        cancel_button.clicked.connect(self.reject)
        self.login_button.clicked.connect(self.start_login)
        self.email.returnPressed.connect(self.start_login)
        self.password.returnPressed.connect(self.start_login)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        layout.addWidget(self.email)
        layout.addWidget(self.password)
        layout.addWidget(self.message)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.login_button, 1)
        layout.addLayout(buttons)

    def start_login(self) -> None:
        email = self.email.text().strip()
        password = self.password.text()
        if not email or not password:
            self.message.setText("이메일과 비밀번호를 모두 입력해 주세요.")
            return
        self.login_button.setEnabled(False)
        self.email.setEnabled(False)
        self.password.setEnabled(False)
        self.message.setText("로그인 및 품목 DB 확인 중...")
        self.worker = LoginWorker(email, password)
        self.worker.succeeded.connect(self.login_succeeded)
        self.worker.failed.connect(self.login_failed)
        self.worker.start()

    def login_succeeded(self, count: int, catalog: dict) -> None:
        self.item_count = count
        self.catalog = catalog
        self.accept()

    def login_failed(self, message: str) -> None:
        self.login_button.setEnabled(True)
        self.email.setEnabled(True)
        self.password.setEnabled(True)
        self.password.clear()
        self.password.setFocus()
        self.message.setText(f"로그인에 실패했습니다. 계정 정보를 확인해 주세요.\n{message}")

    def reject(self) -> None:
        if self.worker and self.worker.isRunning():
            self.message.setText("로그인 확인이 끝날 때까지 잠시 기다려 주세요.")
            return
        super().reject()


class FileDropZone(QFrame):
    filesDropped = Signal(list)

    def __init__(self, parent=None, label_text: str = "엑셀 또는 PDF 파일을 여기에 드래그 앤 드롭하세요", allowed_suffixes: set[str] | None = None):
        super().__init__(parent)
        self.allowed_suffixes = allowed_suffixes or {".xls", ".xlsx", ".pdf"}
        self.setAcceptDrops(True)
        self.setMinimumHeight(76)
        self.setStyleSheet(
            "QFrame { border: 2px dashed #48bdb7; border-radius: 20px; "
            "background: #e9f8f6; color: #172321; }"
        )
        layout = QVBoxLayout(self)
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

    def dragEnterEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if paths and all(Path(path).suffix.lower() in self.allowed_suffixes for path in paths):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.filesDropped.emit(paths)
        event.acceptProposedAction()


class DutyFreeShippingDialog(QDialog):
    """Dedicated sparse PDF/Excel to duty-free shipping conversion workflow."""

    def __init__(
        self, matcher: ProductMatcher | None, locations: list[dict[str, str]],
        parent=None, client=None, catalog_items=None, ecount_config=None,
        completed_requests=None, is_admin=False,
    ):
        super().__init__(parent)
        self.matcher = matcher
        self.locations = [dict(row) for row in locations]
        self.client = client
        self.catalog_items = list(catalog_items or [])
        self.ecount_config = dict(ecount_config or {})
        self.completed_requests = completed_requests if completed_requests is not None else set()
        self.is_admin = is_admin
        self.orders: list[dict[str, str]] = []
        self.source_path = ""
        self.detected_channel = "면세점"
        self.setWindowTitle("면세점 출고")
        self.resize(760, 560)
        self.setMinimumSize(680, 500)

        title = QLabel("면세점 출고")
        title.setObjectName("appTitle")
        hint = QLabel("PDF 또는 Excel의 고정 표에서 품목명과 수량을 읽고 저장된 출고지를 자동으로 적용합니다.")
        hint.setObjectName("appSubtitle")

        self.file_label = QLabel("입력 파일을 선택하거나 아래 영역에 끌어다 놓으세요.")
        self.file_label.setWordWrap(True)
        choose_button = QPushButton("PDF / Excel 선택")
        choose_button.setObjectName("fileButton")
        choose_button.clicked.connect(self.select_file)
        self.drop_zone = FileDropZone(
            label_text="📄  면세점 입고 파일을 여기에 드래그 앤 드롭",
            allowed_suffixes={".pdf", ".xls", ".xlsx"},
        )
        self.drop_zone.setFixedHeight(60)
        self.drop_zone.filesDropped.connect(self.load_dropped_files)

        file_card = QFrame()
        file_card.setObjectName("fileCard")
        file_layout = QVBoxLayout(file_card)
        file_header = QHBoxLayout()
        file_header.addWidget(QLabel("입력 파일  ·  PDF / Excel"))
        file_header.addStretch(1)
        file_header.addWidget(choose_button)
        file_layout.addLayout(file_header)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(self.drop_zone)

        self.location_combo = QComboBox()
        self.location_combo.setMinimumWidth(220)
        self.location_combo.currentIndexChanged.connect(self.apply_selected_location)
        location_manage_button = QPushButton("출고지 정보 관리")
        location_manage_button.clicked.connect(self.manage_locations)
        location_row = QHBoxLayout()
        location_row.addWidget(QLabel("📍  저장된 면세점 출고지"))
        location_row.addWidget(self.location_combo)
        location_row.addWidget(location_manage_button)
        location_row.addStretch(1)

        self.status = QLabel("파일을 불러오면 품목명·수량·출고지 결과를 먼저 보여드립니다.")
        self.status.setObjectName("statusCard")
        self.status.setWordWrap(True)

        self.table = QTableWidget()
        headers = ["상태", "품목명", "수량", "적용 출고지"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.output_format_combo = QComboBox()
        for profile in load_output_formats():
            self.output_format_combo.addItem(str(profile.get("name", "출고 양식")), str(profile.get("id", "")))
        output_manage_button = QPushButton("출력 양식 관리")
        output_manage_button.clicked.connect(self.manage_output_formats)
        self.export_button = QPushButton("출고용 Excel 변환")
        self.export_button.setObjectName("exportButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_file)
        self.transfer_button = QPushButton("이카운트 창고이동")
        self.transfer_button.setEnabled(False)
        self.transfer_button.clicked.connect(self.open_warehouse_transfer)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.accept)
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("변환 출력 양식"))
        format_row.addWidget(self.output_format_combo)
        format_row.addWidget(output_manage_button)
        format_row.addStretch(1)
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(close_button)
        action_row.addWidget(self.transfer_button)
        action_row.addWidget(self.export_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(file_card)
        layout.addLayout(location_row)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)
        layout.addLayout(format_row)
        layout.addLayout(action_row)
        self.refresh_locations()

    def refresh_locations(self, selected_id: str = "") -> None:
        self.locations = load_locations() or self.locations
        previous_id = selected_id or str(self.location_combo.currentData() or "")
        self.location_combo.blockSignals(True)
        self.location_combo.clear()
        if not self.locations:
            self.location_combo.addItem("저장된 출고지가 없습니다", "")
        else:
            for row in self.locations:
                self.location_combo.addItem(row.get("name", "면세점 출고지"), row.get("id", ""))
            selected_index = self.location_combo.findData(previous_id)
            self.location_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.location_combo.blockSignals(False)
        self.apply_selected_location()

    def selected_location(self) -> dict[str, str] | None:
        location_id = str(self.location_combo.currentData() or "")
        return next((row for row in self.locations if row.get("id") == location_id), None)

    def manage_locations(self) -> None:
        selected_id = str(self.location_combo.currentData() or "")
        dialog = DutyLocationDialog(self.locations, self, client=self.client)
        dialog.exec()
        self.locations = load_locations()
        self.refresh_locations(selected_id)

    def manage_output_formats(self) -> None:
        selected_id = str(self.output_format_combo.currentData() or "default_b2c")
        dialog = OutputFormatManagerDialog(self)
        dialog.exec()
        self.output_format_combo.clear()
        selected_index = 0
        for index, profile in enumerate(load_output_formats()):
            self.output_format_combo.addItem(str(profile.get("name", "출고 양식")), str(profile.get("id", "")))
            if str(profile.get("id", "")) == selected_id:
                selected_index = index
        self.output_format_combo.setCurrentIndex(selected_index)

    def select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "면세점 입고 파일 선택", "", "면세점 입력 파일 (*.pdf *.xls *.xlsx)"
        )
        if path:
            self.load_document(path)

    def load_dropped_files(self, paths: list[str]) -> None:
        if not paths:
            return
        if len(paths) > 1:
            QMessageBox.information(self, "파일 한 개씩 처리", "첫 번째 파일만 불러옵니다.")
        self.load_document(paths[0])

    def load_document(self, path: str) -> None:
        try:
            orders, channel = load_simple_duty_free(path)
            for order in orders:
                order["order_number"] = Path(path).stem
                reference_mapping = find_reference_mapping(channel, order.get("ref_no", ""))
                if reference_mapping:
                    order["internal_item_code"] = reference_mapping.get("item_code", "")
                if self.matcher is not None:
                    order.update(self.matcher.match(order))
                else:
                    order.update(
                        {
                            "status": "exact",
                            "matched_product": order.get("product_name", ""),
                            "components": order.get("source_item_code", ""),
                            "reason": "면세점 고정 표 인식",
                        }
                    )
        except Exception as exc:
            QMessageBox.critical(self, "면세점 파일 분석 실패", str(exc))
            return
        self.orders = orders
        self.source_path = path
        self.detected_channel = channel
        self.file_label.setText(f"{Path(path).name}  ·  {len(orders):,}개 품목 인식")
        self.apply_selected_location()

    def apply_selected_location(self) -> None:
        location = self.selected_location()
        if location:
            for order in self.orders:
                order["channel"] = location.get("channel") or self.detected_channel
                order["recipient"] = location.get("recipient", "")
                order["phone"] = location.get("phone", "")
                order["zipcode"] = location.get("zipcode", "")
                order["address"] = location.get("address", "")
                order["message"] = location.get("message", "")
        else:
            for order in self.orders:
                for key in ("recipient", "phone", "zipcode", "address", "message"):
                    order[key] = ""
        self.populate_table()
        ready = bool(self.orders and location and location.get("address"))
        self.export_button.setEnabled(ready)
        self.transfer_button.setEnabled(bool(self.orders))
        if self.orders:
            if ready:
                self.status.setText(
                    f"{self.detected_channel} · {len(self.orders):,}개 품목 · "
                    f"'{location.get('name', '')}' 출고지 자동 적용 완료"
                )
            else:
                self.status.setText(
                    f"{self.detected_channel} · {len(self.orders):,}개 품목 인식 완료 · 저장된 출고지를 선택하거나 등록하세요."
                )

    def populate_table(self) -> None:
        labels = {
            "exact": "정확", "similar": "유사", "alias": "별칭적용", "manual": "수동확정",
            "ambiguous": "확인필요", "missing": "미등록", "barcode_error": "바코드오류",
        }
        colors = {
            "exact": QColor("#d9ead3"), "similar": QColor("#fff2cc"),
            "alias": QColor("#d9d2e9"), "manual": QColor("#cfe2f3"),
            "ambiguous": QColor("#fce5cd"), "missing": QColor("#f4cccc"),
            "barcode_error": QColor("#e06666"),
        }
        location = self.selected_location() or {}
        location_text = ""
        if location:
            location_text = f"{location.get('name', '')} · {location.get('address', '')}".strip(" ·")
        self.table.setRowCount(len(self.orders))
        for row_index, order in enumerate(self.orders):
            status = str(order.get("status", ""))
            values = [
                labels.get(status, status),
                order.get("product_name", ""),
                order.get("quantity", ""),
                location_text,
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setBackground(colors.get(status, QColor("white")))
                if column_index == 3:
                    item.setToolTip(location_text)
                self.table.setItem(row_index, column_index, item)

    def export_file(self) -> None:
        location = self.selected_location()
        if not self.orders or not location or not location.get("address"):
            QMessageBox.warning(self, "변환 준비 필요", "파일과 저장된 면세점 출고지를 먼저 선택하세요.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "면세점 출고 파일 저장", "면세점_출고.xlsx", "Excel 파일 (*.xlsx)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            selected_id = str(self.output_format_combo.currentData() or "default_b2c")
            formats = load_output_formats()
            profile = next((row for row in formats if str(row.get("id")) == selected_id), formats[0])
            export_with_format(self.orders, file_path, profile)
        except Exception as exc:
            QMessageBox.critical(self, "Excel 저장 실패", str(exc))
            return
        QMessageBox.information(self, "저장 완료", f"면세점 출고 파일을 저장했습니다.\n{file_path}")

    def open_warehouse_transfer(self) -> None:
        if not self.is_admin:
            QMessageBox.warning(self, "권한 없음", "이카운트 창고이동은 관리자만 실행할 수 있습니다.")
            return
        if not self.orders:
            QMessageBox.warning(self, "품목 없음", "먼저 면세점 입고 파일을 분석하세요.")
            return
        dialog = EcountTransferDialog(
            self.orders,
            self.catalog_items,
            self.ecount_config,
            self.completed_requests,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.status.setText(
                f"이카운트 창고이동 완료 · {dialog.transfer_scope} · 집계 품목 {len(dialog.items):,}개"
            )


class CalendarDropWidget(QCalendarWidget):
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.event_titles: dict[str, list[str]] = {}
        self.setGridVisible(True)
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        for child in self.findChildren(QWidget):
            child.setAcceptDrops(False)

    def set_event_titles(self, event_titles: dict[str, list[str]]) -> None:
        self.event_titles = event_titles
        self.updateCells()

    def paintCell(self, painter: QPainter, rect, date: QDate) -> None:
        titles = self.event_titles.get(date.toString("yyyy-MM-dd"), [])
        painter.save()
        is_selected = date == self.selectedDate()
        is_other_month = date.month() != self.monthShown()
        if is_selected:
            background = QColor("#48aaa3")
        elif titles:
            background = QColor("#c9efeb")
        elif is_other_month:
            background = QColor("#f6f6f3")
        else:
            background = QColor("#ffffff")
        painter.fillRect(rect, background)
        painter.setPen(QColor("#d8d8d3"))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        date_font = painter.font()
        date_font.setPointSize(max(8, date_font.pointSize()))
        date_font.setBold(False)
        painter.setFont(date_font)
        if is_selected:
            date_color = QColor("#ffffff")
        elif date.dayOfWeek() in {6, 7}:
            date_color = QColor("#e34b4b")
        elif is_other_month:
            date_color = QColor("#a0a19e")
        else:
            date_color = QColor("#252525")
        painter.setPen(date_color)
        painter.drawText(
            rect.adjusted(8, 5, -4, -4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            str(date.day()),
        )

        if titles:
            display = titles[0] if len(titles) == 1 else f"{titles[0]} 외 {len(titles) - 1}건"
            title_font = painter.font()
            title_font.setPointSize(max(10, title_font.pointSize() + 1))
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor("#ffffff") if is_selected else QColor("#174d49"))
            text_rect = rect.adjusted(7, 24, -7, -5)
            display = painter.fontMetrics().elidedText(
                display, Qt.TextElideMode.ElideRight, text_rect.width()
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                display,
            )
        painter.restore()

    def dragEnterEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        allowed = {".pdf", ".xls", ".xlsx", ".csv"}
        if paths and all(Path(path).suffix.lower() in allowed for path in paths):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class CalendarEventDialog(QDialog):
    def __init__(self, event_data: dict | None = None, default_date: QDate | None = None, parent=None):
        super().__init__(parent)
        self.event_data = event_data or {}
        self.deleted = False
        self.setWindowTitle("캘린더 일정 입력")
        self.setFixedSize(470, 360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        saved_date = QDate.fromString(str(self.event_data.get("date", "")), "yyyy-MM-dd")
        self.date_edit.setDate(saved_date if saved_date.isValid() else (default_date or QDate.currentDate()))
        self.title_edit = QLineEdit(str(self.event_data.get("title", "")))
        self.title_edit.setPlaceholderText("예: 8월 면세점 출고 예정")
        self.info_edit = QTextEdit()
        self.info_edit.setPlaceholderText("일정에 표시할 간단한 정보를 입력하세요.")
        self.info_edit.setPlainText(str(self.event_data.get("info", "")))
        self.file_list = QListWidget()
        saved_paths = self.event_data.get("file_paths") or [self.event_data.get("file_path", "")]
        for path in saved_paths:
            if path:
                item = QListWidgetItem(Path(str(path)).name)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.file_list.addItem(item)
        self.file_list.itemDoubleClicked.connect(self.open_attachment)
        attachment_buttons = QHBoxLayout()
        add_file_button = QPushButton("파일 추가")
        remove_file_button = QPushButton("선택 제거")
        open_file_button = QPushButton("선택 열기")
        add_file_button.clicked.connect(self.add_files)
        remove_file_button.clicked.connect(self.remove_selected_file)
        open_file_button.clicked.connect(self.open_selected_file)
        attachment_buttons.addWidget(add_file_button)
        attachment_buttons.addWidget(remove_file_button)
        attachment_buttons.addWidget(open_file_button)
        attachment_box = QWidget()
        attachment_layout = QVBoxLayout(attachment_box)
        attachment_layout.setContentsMargins(0, 0, 0, 0)
        attachment_layout.addWidget(self.file_list)
        attachment_layout.addLayout(attachment_buttons)
        form.addRow("날짜", self.date_edit)
        form.addRow("제목", self.title_edit)
        form.addRow("정보", self.info_edit)
        form.addRow("첨부 파일", attachment_box)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if self.event_data.get("id"):
            delete_button = buttons.addButton("일정 삭제", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_button.clicked.connect(self.delete_event)
        layout.addWidget(buttons)

    def delete_event(self) -> None:
        self.deleted = True
        self.accept()

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "첨부 파일 추가", "", "문서 파일 (*.pdf *.xls *.xlsx *.csv)"
        )
        existing = {
            self.file_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.file_list.count())
        }
        for path in paths:
            if path in existing:
                continue
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.file_list.addItem(item)
            existing.add(path)

    def remove_selected_file(self) -> None:
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def open_selected_file(self) -> None:
        item = self.file_list.currentItem()
        if item:
            self.open_attachment(item)

    def open_attachment(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "첨부 파일", "이 PC에서 첨부 파일을 찾을 수 없습니다.")
            return
        os.startfile(path)

    def values(self) -> dict:
        file_paths = [
            str(self.file_list.item(index).data(Qt.ItemDataRole.UserRole) or "")
            for index in range(self.file_list.count())
        ]
        return {
            "id": str(self.event_data.get("id") or uuid.uuid4()),
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "title": self.title_edit.text().strip(),
            "info": self.info_edit.toPlainText().strip(),
            "file_paths": [path for path in file_paths if path],
        }


class MiniWidgetDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(None)
        self.main_window = main_window
        self.opening_main_window = False
        self.setStyleSheet(main_window.styleSheet())
        self.setObjectName("miniWidget")
        self.setWindowTitle("REQM 미니 위젯")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedSize(430, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("REQM 미니 위젯")
        title.setObjectName("widgetTitle")
        self.today_label = QLabel(QDate.currentDate().toString("yyyy년 M월 d일"))
        self.today_label.setObjectName("dashboardHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.today_label)
        layout.addLayout(header)

        hint = QLabel("필요한 업무를 누르면 바로 실행됩니다.")
        hint.setObjectName("widgetHint")
        layout.addWidget(hint)

        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(10)
        action_grid.setVerticalSpacing(10)
        action_specs = [
            ("📦  출고 파일 변환\n일반 출고 파일 불러오기", "shipping"),
            ("🏬  면세점 출고\nPDF · 엑셀 변환", "duty_free"),
            ("↔  창고이동\n불러온 품목 전송", "warehouse"),
            ("📅  일정\n대시보드 일정 관리", "calendar"),
        ]
        self.action_buttons = []
        for index, (text, target) in enumerate(action_specs):
            button = QPushButton(text)
            button.setObjectName("widgetAction")
            button.setProperty("widgetTarget", target)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, selected_target=target: self.open_target(selected_target)
            )
            action_grid.addWidget(button, index // 2, index % 2)
            self.action_buttons.append(button)
        layout.addLayout(action_grid)

        self.event_summary = QLabel()
        self.event_summary.setObjectName("widgetEventSummary")
        self.event_summary.setWordWrap(True)
        layout.addWidget(self.event_summary)

        self.attachment_button = QPushButton("일정 첨부 파일 다운로드")
        self.attachment_button.setObjectName("widgetAttachment")
        self.attachment_button.setEnabled(False)
        self.attachment_button.clicked.connect(self.download_selected_attachments)
        layout.addWidget(self.attachment_button, 0, Qt.AlignmentFlag.AlignRight)
        self.refresh_events()

    def refresh_events(self) -> None:
        today_text = QDate.currentDate().toString("yyyy-MM-dd")
        upcoming = sorted(
            (row for row in self.main_window.calendar_events if str(row.get("date", "")) >= today_text),
            key=lambda row: (str(row.get("date", "")), str(row.get("title", ""))),
        )[:1]
        if not upcoming:
            self.upcoming_event = None
            self.event_summary.setText("다음 일정  ·  가까운 일정이 없습니다.")
            self.update_attachment_button()
            return
        self.upcoming_event = upcoming[0]
        self.event_summary.setText(
            f"다음 일정  ·  {self.upcoming_event.get('date', '')}  "
            f"{self.upcoming_event.get('title', '')}"
        )
        self.update_attachment_button()

    def selected_event(self) -> dict | None:
        return self.upcoming_event

    def update_attachment_button(self, current=None, previous=None) -> None:
        event_row = self.selected_event()
        paths = (event_row or {}).get("file_paths") or [(event_row or {}).get("file_path", "")]
        self.attachment_button.setEnabled(any(paths))

    def download_selected_attachments(self) -> None:
        event_row = self.selected_event()
        if event_row:
            self.main_window.download_event_attachments(event_row)

    def open_target(self, target: str) -> None:
        self.opening_main_window = True
        self.main_window.showNormal()
        if target == "shipping":
            self.main_window.show_shipping_workspace()
        else:
            self.main_window.show_dashboard()
        self.main_window.raise_()
        self.main_window.activateWindow()
        self.close()
        if target == "duty_free":
            self.main_window.open_duty_free_shipping()
        elif target == "warehouse":
            self.main_window.open_dashboard_warehouse_transfer()

    def open_main_window(self) -> None:
        self.open_target("calendar")

    def closeEvent(self, event) -> None:
        if not self.opening_main_window and self.main_window.isMinimized():
            self.main_window.showNormal()
            self.main_window.show_dashboard()
            self.main_window.raise_()
            self.main_window.activateWindow()
        event.accept()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.update_worker = None
        self.mini_widget = None
        self.matcher = None
        self.supabase_client = None
        self.catalog: dict = {}
        self.current_mode = "parcel"
        self.current_orders: list[dict[str, str]] = []
        self.completed_ecount_requests = load_completed_transfer_requests()
        self.duty_locations = load_locations()
        self.selected_location_name = ""
        self.is_admin = False
        self.setWindowTitle("REQM 출고 관리")
        self.resize(1420, 860)
        self.setStyleSheet("""
            QMainWindow, QWidget#mainContainer { background: #f7f7f3; color: #151515; font-family: '맑은 고딕'; font-size: 13px; }
            QLabel#appTitle { color: #111111; font-size: 30px; font-weight: 900; letter-spacing: -1px; }
            QLabel#appSubtitle { color: #6f716f; font-size: 13px; padding-left: 3px; }
            QLabel#versionLabel { color: #a3a5a2; font-size: 10px; padding: 0 0 4px 4px; }
            QLabel#sectionTitle { color: #111111; font-size: 18px; font-weight: 850; padding: 7px 2px; }
            QLabel#statusCard { background: #e3f6f3; color: #244945; border: none; border-radius: 17px; padding: 13px 17px; }
            QFrame#loginCard, QFrame#fileCard, QFrame#locationCard { background: #ffffff; border: 1px solid #e3e3df; border-radius: 20px; }
            QFrame#fileCard { background: #f0f0ed; border: none; }
            QFrame#locationCard { background: #f7efe2; border: none; }
            QLineEdit, QComboBox { background: #ffffff; color: #171717; border: 1px solid #d8d8d3; border-radius: 13px; padding: 10px 13px; selection-background-color: #5bcac2; selection-color: #111111; }
            QLineEdit:focus, QComboBox:focus { border: 1px solid #38aaa3; }
            QPushButton { background: #ffffff; color: #151515; border: 1px solid #cacac5; border-radius: 15px; padding: 10px 16px; font-weight: 700; }
            QPushButton:hover { background: #e9f8f6; border-color: #48bdb7; }
            QPushButton:pressed { background: #d6f0ed; }
            QPushButton:disabled { background: #e9e9e5; color: #a6a7a4; border-color: #e1e1dc; }
            QPushButton#primaryButton { background: #121212; color: #ffffff; border: none; padding: 13px 22px; font-size: 14px; }
            QPushButton#primaryButton:hover { background: #2f6662; }
            QPushButton#fileButton { background: #121212; color: #ffffff; border: none; padding: 8px 14px; font-size: 13px; }
            QPushButton#fileButton:hover { background: #2f6662; }
            QPushButton#exportButton { background: #121212; color: #ffffff; border: none; padding: 14px 28px; font-size: 16px; }
            QPushButton#exportButton:hover { background: #2f6662; }
            QPushButton#adminButton { background: #ffffff; color: #151515; border-color: #cfcfca; padding: 9px 16px; }
            QPushButton#dashboardCard { background: #ffffff; color: #151515; border: 1px solid #dfdfda; border-radius: 22px; padding: 22px; font-size: 17px; text-align: left; }
            QPushButton#dashboardCard:hover { background: #e9f8f6; border: 2px solid #48bdb7; }
            QLabel#dashboardTitle { color: #111111; font-size: 34px; font-weight: 900; }
            QLabel#dashboardSection { color: #111111; font-size: 19px; font-weight: 850; padding-top: 8px; }
            QLabel#dashboardHint { color: #71736f; font-size: 13px; }
            QDialog#miniWidget { background: #f7f7f3; color: #151515; font-family: '맑은 고딕'; }
            QDialog#startupLogin { background: #f7f7f3; color: #151515; font-family: '맑은 고딕'; }
            QLabel#widgetTitle { color: #111111; font-size: 20px; font-weight: 900; }
            QLabel#widgetHint { color: #71736f; font-size: 12px; }
            QPushButton#widgetAction { background: #ffffff; color: #151515; border: 1px solid #dfdfda; border-radius: 16px; padding: 13px 14px; min-height: 54px; font-size: 13px; text-align: left; }
            QPushButton#widgetAction:hover { background: #e9f8f6; border: 2px solid #48bdb7; }
            QLabel#widgetEventSummary { background: #eef7f5; color: #315d59; border-radius: 11px; padding: 9px 11px; font-size: 12px; }
            QPushButton#widgetAttachment { background: transparent; color: #5f6562; border: none; padding: 2px 4px; font-size: 11px; text-decoration: underline; }
            QListWidget#widgetEventList { background: #ffffff; border: 1px solid #dfdfda; border-radius: 16px; padding: 7px; }
            QListWidget#widgetEventList::item { padding: 11px 9px; border-bottom: 1px solid #eeeeea; font-size: 13px; }
            QListWidget#widgetEventList::item:selected { background: #e9f8f6; color: #151515; border-radius: 8px; }
            QListWidget#recentWork { background: #ffffff; border: 1px solid #dfdfda; border-radius: 18px; padding: 8px; }
            QListWidget#recentWork::item { padding: 12px 10px; border-bottom: 1px solid #eeeeea; font-size: 15px; }
            QListWidget#recentWork::item:selected { background: #ffffff; color: #151515; border-radius: 9px; }
            QTableWidget { background: #ffffff; alternate-background-color: #fafaf7; border: 1px solid #deded9; border-radius: 16px; gridline-color: #ecece8; selection-background-color: #d9f3f0; selection-color: #111111; }
            QHeaderView::section { background: #ecece8; color: #1b1b1b; border: none; border-right: 1px solid #dadad5; border-bottom: 1px solid #d6d6d1; padding: 11px; font-weight: 800; }
            QScrollBar:vertical { background: #ecece8; width: 22px; margin: 2px; border-radius: 10px; }
            QScrollBar::handle:vertical { background: #8fc9c4; min-height: 48px; border-radius: 9px; margin: 2px; }
            QScrollBar::handle:vertical:hover { background: #55aaa4; }
            QScrollBar:horizontal { background: #ecece8; height: 22px; margin: 2px; border-radius: 10px; }
            QScrollBar::handle:horizontal { background: #8fc9c4; min-width: 48px; border-radius: 9px; margin: 2px; }
            QScrollBar::handle:horizontal:hover { background: #55aaa4; }
            QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
            QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        """)

        title = QLabel("REQM  출고 관리")
        title.setObjectName("appTitle")
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setObjectName("versionLabel")
        subtitle = QLabel("주문 파일을 자동 분석하고 정확한 출고 데이터로 변환합니다")
        subtitle.setObjectName("appSubtitle")
        self.email = QLineEdit()
        self.email.setPlaceholderText("프로그램 계정 이메일")
        self.email.setText("")
        self.password = QLineEdit()
        self.password.setPlaceholderText("비밀번호")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_button = QPushButton("로그인")
        self.login_button.setObjectName("primaryButton")
        self.login_button.setFixedWidth(84)
        self.b2c_button = QPushButton("B2C 엑셀 파일 (셀메이트)")
        self.b2c_button.setEnabled(False)
        self.b2b_button = QPushButton("B2B 엑셀 파일 (면세점)")
        self.b2b_button.setEnabled(False)
        self.auto_button = QPushButton("📁  출고 작업 파일 선택")
        self.auto_button.setObjectName("fileButton")
        self.auto_button.setFixedHeight(34)
        self.auto_button.setMaximumWidth(175)
        self.auto_button.setEnabled(False)
        self.db_button = QPushButton("▣  DB 관리")
        self.db_button.setObjectName("adminButton")
        self.db_button.setMaximumWidth(155)
        self.db_button.setEnabled(False)
        self.settings_button = QPushButton("설정")
        self.settings_button.setObjectName("adminButton")
        self.settings_button.setMaximumWidth(100)
        self.update_button = QPushButton("업데이트")
        self.update_button.setObjectName("adminButton")
        self.update_button.setMaximumWidth(105)
        self.dashboard_button = QPushButton("←  메인으로")
        self.dashboard_button.setObjectName("adminButton")
        self.dashboard_button.setMaximumWidth(125)
        self.export_button = QPushButton("택배 출고용 변환")
        self.export_button.setObjectName("exportButton")
        self.export_button.setEnabled(False)
        self.ecount_button = QPushButton("이카운트 창고이동")
        self.ecount_button.setObjectName("exportButton")
        self.ecount_button.setEnabled(False)
        self.output_format_combo = QComboBox()
        self.output_format_combo.setMinimumWidth(220)
        self.output_format_manage_button = QPushButton("출력 양식 관리")
        self.status = QLabel("공개용 API 키 설정 후 연결을 확인하세요.")
        self.status.setObjectName("statusCard")
        self.status.setWordWrap(True)

        self.table = QTableWidget()
        headers = [
            "상태", "DB 대조 상품", "출고 품목코드", "판정 이유", "원본행", "원본 품목코드", "주문번호",
            "판매처", "상품명", "옵션", "수량", "수령인", "연락처", "우편번호", "주소", "재고매칭",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 14, 24, 16)
        layout.setSpacing(8)
        login_row = QHBoxLayout()
        login_row.setContentsMargins(14, 12, 14, 12)
        login_row.setSpacing(10)
        self.email.setFixedWidth(300)
        self.password.setFixedWidth(250)
        login_row.addWidget(self.email)
        login_row.addWidget(self.password)
        login_row.addWidget(self.login_button)
        self.header_row = QHBoxLayout()
        title_line = QHBoxLayout()
        title_line.setSpacing(2)
        title_line.addWidget(title)
        title_line.addWidget(version_label, 0, Qt.AlignmentFlag.AlignBottom)
        title_block = QWidget()
        title_block.setLayout(title_line)
        self.header_row.addWidget(title_block)
        self.header_row.addStretch(1)
        self.header_row.addWidget(self.dashboard_button)
        self.header_row.addWidget(self.db_button)
        self.header_row.addWidget(self.update_button)
        self.header_row.addWidget(self.settings_button)
        layout.addLayout(self.header_row)
        layout.addWidget(subtitle)
        self.login_row = login_row
        self.login_card = QFrame()
        self.login_card.setObjectName("loginCard")
        self.login_card.setLayout(login_row)
        self.login_card.setMaximumWidth(690)
        file_card = QFrame()
        file_card.setObjectName("fileCard")
        file_layout = QVBoxLayout(file_card)
        file_layout.setContentsMargins(12, 8, 12, 9)
        file_layout.setSpacing(5)
        file_label = QLabel("출고 파일 입력  ·  Excel / CSV / PDF")
        file_label.setObjectName("appSubtitle")
        file_label.setWordWrap(True)
        file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.order_drop_zone = FileDropZone(
            label_text="📄\n드래그 앤 드롭",
            allowed_suffixes={".xls", ".xlsx", ".csv", ".pdf"},
        )
        self.order_drop_zone.setFixedSize(92, 92)
        self.order_drop_zone.filesDropped.connect(self.load_dropped_order_files)
        file_layout.addWidget(file_label)
        file_layout.addWidget(self.auto_button, 0, Qt.AlignmentFlag.AlignCenter)
        file_layout.addWidget(self.order_drop_zone, 0, Qt.AlignmentFlag.AlignCenter)
        file_card.setFixedWidth(215)
        top_work_row = QHBoxLayout()
        top_work_row.setSpacing(18)
        top_work_row.addWidget(self.login_card, 0, Qt.AlignmentFlag.AlignTop)
        top_work_row.addStretch(1)
        top_work_row.addWidget(file_card, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        layout.addLayout(top_work_row)
        layout.addWidget(self.status)
        location_row = QHBoxLayout()
        location_row.setContentsMargins(12, 8, 12, 8)
        location_row.setSpacing(8)
        self.location_combo = QComboBox()
        self.location_combo.setPlaceholderText("면세점 출고지를 선택하세요")
        self.location_combo.setFixedWidth(340)
        self.location_manage_button = QPushButton("출고지 정보 관리")
        self.location_apply_button = QPushButton("선택 출고지 적용")
        self.location_apply_button.setEnabled(False)
        location_row.addWidget(QLabel("📍  면세점 출고지"))
        location_row.addWidget(self.location_combo)
        location_row.addWidget(self.location_manage_button)
        location_row.addWidget(self.location_apply_button)
        location_card = QFrame()
        location_card.setObjectName("locationCard")
        location_card.setLayout(location_row)
        location_card.setMaximumWidth(850)
        analysis_title = QLabel("▥  분석 결과")
        analysis_title.setObjectName("sectionTitle")
        analysis_header_row = QHBoxLayout()
        analysis_header_row.setSpacing(14)
        analysis_header_row.addWidget(analysis_title)
        analysis_header_row.addStretch(1)
        analysis_header_row.addWidget(location_card, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(analysis_header_row)
        layout.addWidget(self.table, 1)
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("변환 출력 양식"))
        export_row.addWidget(self.output_format_combo)
        export_row.addWidget(self.output_format_manage_button)
        export_row.addStretch(1)
        export_row.addWidget(self.ecount_button)
        export_row.addWidget(self.export_button)
        layout.addLayout(export_row)
        container = QWidget()
        container.setObjectName("mainContainer")
        container.setLayout(layout)
        self.work_page = container
        self.dashboard_page = self.build_dashboard_page()
        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self.dashboard_page)
        self.page_stack.addWidget(self.work_page)
        self.setCentralWidget(self.page_stack)
        self.page_stack.setCurrentWidget(self.dashboard_page)
        self.login_button.clicked.connect(self.login)
        self.settings_button.clicked.connect(self.open_account_settings)
        self.update_button.clicked.connect(self.check_for_updates)
        self.email.returnPressed.connect(self.login)
        self.password.returnPressed.connect(self.login)
        self.b2c_button.clicked.connect(self.select_b2c_file)
        self.b2b_button.clicked.connect(self.select_b2b_file)
        self.auto_button.clicked.connect(lambda: self.select_file("auto"))
        self.db_button.clicked.connect(self.open_db_manager)
        self.export_button.clicked.connect(self.export_file)
        self.ecount_button.clicked.connect(self.open_ecount_transfer)
        self.output_format_manage_button.clicked.connect(self.manage_output_formats)
        self.location_manage_button.clicked.connect(self.manage_locations)
        self.location_apply_button.clicked.connect(self.apply_location)
        self.dashboard_button.clicked.connect(self.show_dashboard)
        self.table.cellDoubleClicked.connect(self.edit_match)
        self.refresh_location_combo()
        self.refresh_output_formats()

    def require_startup_login(self) -> bool:
        dialog = StartupLoginDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.catalog:
            return False
        self.email.setText(dialog.email.text().strip())
        self.password.setText(dialog.password.text())
        self.on_success(dialog.item_count, dialog.catalog)
        return True

    def dashboard_card(self, title: str, description: str) -> QPushButton:
        button = QPushButton(title)
        button.setObjectName("dashboardCard")
        button.setFixedHeight(118)
        return button

    def build_dashboard_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("mainContainer")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("REQM 물류 대시보드")
        title.setObjectName("dashboardTitle")
        hint = QLabel("필요한 업무를 선택하면 해당 작업 화면이 열립니다.")
        hint.setObjectName("dashboardHint")
        title_box.addWidget(title)
        title_box.addWidget(hint)
        header.addLayout(title_box)
        header.addStretch(1)
        self.dashboard_db_button = QPushButton("DB 관리")
        self.dashboard_db_button.setObjectName("adminButton")
        self.dashboard_db_button.setFixedSize(92, 38)
        self.dashboard_db_button.setEnabled(False)
        self.dashboard_db_button.clicked.connect(self.open_db_manager)
        self.dashboard_update_button = QPushButton("업데이트")
        self.dashboard_update_button.setObjectName("adminButton")
        self.dashboard_update_button.setFixedSize(92, 38)
        self.dashboard_update_button.clicked.connect(self.check_for_updates)
        self.dashboard_widget_button = QPushButton("미니 위젯")
        self.dashboard_widget_button.setObjectName("adminButton")
        self.dashboard_widget_button.setFixedSize(100, 38)
        self.dashboard_widget_button.clicked.connect(self.open_mini_widget)
        self.dashboard_version = QLabel(f"v{APP_VERSION}")
        self.dashboard_version.setObjectName("versionLabel")
        header.addWidget(self.dashboard_widget_button, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.dashboard_db_button, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.dashboard_update_button, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.dashboard_version, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        cards = QGridLayout()
        cards.setSpacing(16)
        shipment = self.dashboard_card("📦  출고 파일 변환", "주문 파일 분석 · 품목 매칭 · 출고 양식 변환")
        shipment.clicked.connect(self.show_shipping_workspace)
        duty_free = self.dashboard_card("🏬  면세점 출고", "PDF·Excel 품목 인식 · 저장 출고지 자동 적용")
        duty_free.clicked.connect(self.open_duty_free_shipping)
        marketplace_options = self.dashboard_card("🛒  상품 관리 팝업", "29CM 옵션 매핑 · 품절/판매 재개 요청 관리")
        marketplace_options.clicked.connect(self.open_marketplace_option_manager)
        shipment.setMaximumWidth(430)
        duty_free.setMaximumWidth(430)
        marketplace_options.setMaximumWidth(430)
        cards.addWidget(shipment, 0, 0)
        cards.addWidget(duty_free, 0, 1)
        cards.addWidget(marketplace_options, 1, 0)
        cards.setColumnStretch(0, 1)
        cards.setColumnStretch(1, 1)
        self.dashboard_cards = [shipment, duty_free, marketplace_options]
        layout.addLayout(cards)

        self.calendar_widget = CalendarDropWidget()
        calendar_header = QHBoxLayout()
        calendar_title = QLabel("업무 캘린더")
        calendar_title.setObjectName("dashboardSection")
        calendar_hint = QLabel("PDF 또는 엑셀 파일을 캘린더에 드래그하면 일정을 등록할 수 있습니다.")
        calendar_hint.setObjectName("dashboardHint")
        self.calendar_year_combo = QComboBox()
        current_year = QDate.currentDate().year()
        for year in range(current_year - 5, current_year + 7):
            self.calendar_year_combo.addItem(f"{year}년", year)
        self.calendar_year_combo.setCurrentIndex(5)
        self.calendar_year_combo.setFixedWidth(105)
        self.calendar_month_combo = QComboBox()
        for month in range(1, 13):
            self.calendar_month_combo.addItem(f"{month}월", month)
        self.calendar_month_combo.setCurrentIndex(QDate.currentDate().month() - 1)
        self.calendar_month_combo.setFixedWidth(80)
        calendar_header.addWidget(calendar_title)
        calendar_header.addWidget(self.calendar_year_combo)
        calendar_header.addWidget(self.calendar_month_combo)
        calendar_header.addStretch(1)
        calendar_header.addWidget(calendar_hint)
        layout.addLayout(calendar_header)

        calendar_row = QHBoxLayout()
        calendar_row.setSpacing(14)
        self.calendar_widget.setMinimumHeight(310)
        self.calendar_widget.filesDropped.connect(self.add_calendar_files)
        self.calendar_widget.clicked.connect(self.refresh_calendar_event_list)
        self.calendar_widget.currentPageChanged.connect(self.sync_calendar_month_controls)
        self.calendar_year_combo.currentIndexChanged.connect(self.change_calendar_month)
        self.calendar_month_combo.currentIndexChanged.connect(self.change_calendar_month)
        self.calendar_event_list = QListWidget()
        self.calendar_event_list.setObjectName("recentWork")
        self.calendar_event_list.setFixedWidth(350)
        self.calendar_event_list.itemDoubleClicked.connect(self.edit_calendar_event)
        self.calendar_event_list.currentItemChanged.connect(self.update_calendar_download_button)
        self.calendar_download_button = QPushButton("첨부 파일 다운로드")
        self.calendar_download_button.setObjectName("primaryButton")
        self.calendar_download_button.setEnabled(False)
        self.calendar_download_button.clicked.connect(self.download_calendar_attachments)
        event_panel = QWidget()
        event_panel.setFixedWidth(350)
        event_panel_layout = QVBoxLayout(event_panel)
        event_panel_layout.setContentsMargins(0, 0, 0, 0)
        event_panel_layout.setSpacing(8)
        event_panel_layout.addWidget(self.calendar_event_list, 1)
        event_panel_layout.addWidget(
            self.calendar_download_button, 0, Qt.AlignmentFlag.AlignRight
        )
        calendar_row.addWidget(self.calendar_widget, 1)
        calendar_row.addWidget(event_panel)
        layout.addLayout(calendar_row, 1)
        self.calendar_events = load_calendar_events()
        self.highlighted_event_dates: set[str] = set()
        self.refresh_calendar_display()
        return page

    def change_calendar_month(self) -> None:
        year = int(self.calendar_year_combo.currentData() or QDate.currentDate().year())
        month = int(self.calendar_month_combo.currentData() or QDate.currentDate().month())
        self.calendar_widget.setCurrentPage(year, month)

    def sync_calendar_month_controls(self, year: int, month: int) -> None:
        year_index = self.calendar_year_combo.findData(year)
        if year_index >= 0:
            self.calendar_year_combo.blockSignals(True)
            self.calendar_year_combo.setCurrentIndex(year_index)
            self.calendar_year_combo.blockSignals(False)
        self.calendar_month_combo.blockSignals(True)
        self.calendar_month_combo.setCurrentIndex(month - 1)
        self.calendar_month_combo.blockSignals(False)

    def show_dashboard(self) -> None:
        self.refresh_calendar_display()
        self.page_stack.setCurrentWidget(self.dashboard_page)

    def show_shipping_workspace(self) -> None:
        self.page_stack.setCurrentWidget(self.work_page)

    def open_duty_free_shipping(self) -> None:
        dialog = DutyFreeShippingDialog(
            self.matcher,
            load_locations(),
            self,
            client=self.supabase_client,
            catalog_items=self.catalog.get("items", []),
            ecount_config=load_config().get("ecount", {}),
            completed_requests=self.completed_ecount_requests,
            is_admin=self.is_admin,
        )
        dialog.exec()

    def open_marketplace_option_manager(self) -> None:
        MarketplaceOptionDialog(self.email.text(), self).exec()

    def open_dashboard_warehouse_transfer(self) -> None:
        if not self.current_orders:
            self.show_shipping_workspace()
            self.status.setText("창고이동할 출고 파일을 먼저 불러오세요. 분석 후 '이카운트 창고이동'을 누르면 됩니다.")
            return
        self.open_ecount_transfer()

    def open_mini_widget(self) -> None:
        if self.mini_widget is not None:
            self.mini_widget.close()
        self.mini_widget = MiniWidgetDialog(self)
        screen = QApplication.primaryScreen().availableGeometry()
        self.mini_widget.move(
            screen.right() - self.mini_widget.width() - 22,
            screen.bottom() - self.mini_widget.height() - 22,
        )
        self.mini_widget.show()
        self.showMinimized()

    def open_inventory_check(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("재고 확인")
        dialog.setFixedSize(520, 260)
        layout = QVBoxLayout(dialog)
        title = QLabel("이카운트 실재고 확인")
        title.setObjectName("sectionTitle")
        message = QLabel(
            "대시보드 화면 구성을 먼저 확인하기 위한 테스트 메뉴입니다.\n"
            "다음 단계에서 이카운트 API를 연결하면 품목코드별 실재고를 조회할 수 있습니다."
        )
        message.setObjectName("statusCard")
        message.setWordWrap(True)
        back_button = QPushButton("←  메인으로")
        back_button.setObjectName("primaryButton")
        back_button.clicked.connect(dialog.accept)
        layout.addWidget(title)
        layout.addWidget(message)
        layout.addStretch(1)
        layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def refresh_recent_work(self) -> None:
        if not hasattr(self, "recent_work_list"):
            return
        self.recent_work_list.clear()
        rows = load_recent_work()
        if not rows:
            item = QListWidgetItem("아직 저장된 출고 작업이 없습니다.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.recent_work_list.addItem(item)
            return
        for row in rows[:10]:
            self.recent_work_list.addItem(
                f"{row.get('created_at', '')}   |   {row.get('format', '')}   |   "
                f"{int(row.get('rows', 0)):,}건   |   {row.get('file_name', '')}"
            )

    def record_recent_work(self, file_path: str, profile_name: str) -> None:
        rows = load_recent_work()
        rows.insert(0, {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "format": profile_name,
            "rows": len(self.current_orders),
            "file_name": Path(file_path).name,
        })
        save_recent_work(rows)
        self.refresh_recent_work()

    def add_calendar_files(self, paths: list[str]) -> None:
        if not paths:
            return
        draft = {
            "title": Path(paths[0]).stem,
            "file_paths": paths,
        }
        dialog = CalendarEventDialog(draft, self.calendar_widget.selectedDate(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["title"]:
            QMessageBox.warning(self, "일정 제목", "캘린더에 표시할 제목을 입력하세요.")
            return
        self.calendar_events.append(values)
        save_calendar_events(self.calendar_events)
        self.refresh_calendar_display()

    def refresh_calendar_display(self) -> None:
        if not hasattr(self, "calendar_widget"):
            return
        for date_text in self.highlighted_event_dates:
            date = QDate.fromString(date_text, "yyyy-MM-dd")
            if date.isValid():
                self.calendar_widget.setDateTextFormat(date, QTextCharFormat())
        self.highlighted_event_dates = {
            str(row.get("date", "")) for row in self.calendar_events if row.get("date")
        }
        event_format = QTextCharFormat()
        event_format.setBackground(QColor("#bfeae6"))
        event_format.setForeground(QColor("#173c39"))
        for date_text in self.highlighted_event_dates:
            date = QDate.fromString(date_text, "yyyy-MM-dd")
            if date.isValid():
                self.calendar_widget.setDateTextFormat(date, event_format)
        event_titles: dict[str, list[str]] = {}
        for row in self.calendar_events:
            date_text = str(row.get("date", ""))
            title = str(row.get("title", "")).strip()
            if date_text and title:
                event_titles.setdefault(date_text, []).append(title)
        self.calendar_widget.set_event_titles(event_titles)
        self.refresh_calendar_event_list(self.calendar_widget.selectedDate())

    def refresh_calendar_event_list(self, selected_date: QDate | None = None) -> None:
        if not hasattr(self, "calendar_event_list"):
            return
        date = selected_date or self.calendar_widget.selectedDate()
        date_text = date.toString("yyyy-MM-dd")
        self.calendar_event_list.clear()
        day_events = [row for row in self.calendar_events if row.get("date") == date_text]
        if not day_events:
            item = QListWidgetItem(f"{date_text}\n등록된 일정이 없습니다.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.calendar_event_list.addItem(item)
            self.calendar_download_button.setEnabled(False)
            return
        for row in day_events:
            title = str(row.get("title", "")).strip()
            detail = str(row.get("info", "")).strip()
            file_paths = row.get("file_paths") or [row.get("file_path", "")]
            file_names = [Path(str(path)).name for path in file_paths if path]
            if file_names:
                attachment_text = f"첨부 파일 {len(file_names)}개 : {', '.join(file_names[:2])}"
                if len(file_names) > 2:
                    attachment_text += f" 외 {len(file_names) - 2}개"
            else:
                attachment_text = "첨부 파일 0개"
            text = f"{title or '-'}\n\n{detail or '-'}\n\n{attachment_text}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, row.get("id"))
            self.calendar_event_list.addItem(item)
        self.calendar_event_list.setCurrentRow(0)

    def update_calendar_download_button(self, current: QListWidgetItem | None, previous=None) -> None:
        event_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        event_row = next((row for row in self.calendar_events if row.get("id") == event_id), None)
        paths = (event_row or {}).get("file_paths") or [(event_row or {}).get("file_path", "")]
        self.calendar_download_button.setEnabled(any(paths))

    def download_calendar_attachments(self) -> None:
        item = self.calendar_event_list.currentItem()
        event_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        event_row = next((row for row in self.calendar_events if row.get("id") == event_id), None)
        if not event_row:
            return
        self.download_event_attachments(event_row)

    def download_event_attachments(self, event_row: dict) -> None:
        paths = event_row.get("file_paths") or [event_row.get("file_path", "")]
        paths = [str(path) for path in paths if path]
        if not paths:
            QMessageBox.information(self, "첨부 파일", "다운로드할 첨부 파일이 없습니다.")
            return
        target_dir = QFileDialog.getExistingDirectory(self, "첨부 파일을 저장할 폴더 선택")
        if not target_dir:
            return
        saved = 0
        missing: list[str] = []
        for source_text in paths:
            source = Path(source_text)
            if not source.exists():
                missing.append(source.name or source_text)
                continue
            target = Path(target_dir) / source.name
            suffix_number = 1
            while target.exists():
                target = Path(target_dir) / f"{source.stem} ({suffix_number}){source.suffix}"
                suffix_number += 1
            shutil.copy2(source, target)
            saved += 1
        message = f"첨부 파일 {saved}개를 저장했습니다.\n{target_dir}"
        if missing:
            message += "\n\n이 PC에서 찾지 못한 파일: " + ", ".join(missing)
        QMessageBox.information(self, "첨부 파일 다운로드", message)

    def edit_calendar_event(self, item: QListWidgetItem) -> None:
        event_id = item.data(Qt.ItemDataRole.UserRole)
        event_row = next((row for row in self.calendar_events if row.get("id") == event_id), None)
        if not event_row:
            return
        dialog = CalendarEventDialog(event_row, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.deleted:
            answer = QMessageBox.question(
                self, "일정 삭제", f"'{event_row.get('title', '')}' 일정을 삭제할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.calendar_events = [row for row in self.calendar_events if row.get("id") != event_id]
        else:
            values = dialog.values()
            if not values["title"]:
                QMessageBox.warning(self, "일정 제목", "캘린더에 표시할 제목을 입력하세요.")
                return
            event_row.update(values)
        save_calendar_events(self.calendar_events)
        self.refresh_calendar_display()

    def refresh_output_formats(self, selected_id: str = "") -> None:
        selected_id = selected_id or str(self.output_format_combo.currentData() or "default_b2c")
        self.output_formats = load_output_formats()
        self.output_format_combo.clear()
        selected_index = 0
        for index, profile in enumerate(self.output_formats):
            self.output_format_combo.addItem(profile["name"], profile["id"])
            if profile["id"] == selected_id:
                selected_index = index
        self.output_format_combo.setCurrentIndex(selected_index)

    def manage_output_formats(self) -> None:
        selected_id = str(self.output_format_combo.currentData() or "default_b2c")
        dialog = OutputFormatManagerDialog(self)
        dialog.exec()
        self.refresh_output_formats(selected_id)

    def refresh_location_combo(self, preferred_channel: str = "") -> None:
        selected_id = self.location_combo.currentData() if hasattr(self, "location_combo") else ""
        self.duty_locations = load_locations()
        self.location_combo.clear()
        selected_index = -1
        for index, row in enumerate(self.duty_locations):
            label = row.get("name", "")
            self.location_combo.addItem(label, row.get("id", ""))
            if row.get("id") == selected_id:
                selected_index = index
            elif selected_index < 0 and preferred_channel and preferred_channel in row.get("channel", ""):
                selected_index = index
        if selected_index >= 0:
            self.location_combo.setCurrentIndex(selected_index)
        elif self.location_combo.count():
            self.location_combo.setCurrentIndex(0)

    def manage_locations(self) -> None:
        dialog = DutyLocationDialog(self.duty_locations, self, client=self.supabase_client)
        dialog.exec()
        self.refresh_location_combo()

    def apply_location(self) -> None:
        location_id = self.location_combo.currentData()
        location = next((row for row in self.duty_locations if row.get("id") == location_id), None)
        if not location:
            QMessageBox.warning(self, "출고지 선택", "적용할 면세점 출고지를 선택하세요.")
            return
        if not self.current_orders or self.current_mode != "duty_free":
            QMessageBox.information(self, "면세점 파일", "먼저 면세점 출고 파일을 불러오세요.")
            return
        for order in self.current_orders:
            order["recipient"] = location.get("recipient", "")
            order["phone"] = location.get("phone", "")
            order["zipcode"] = location.get("zipcode", "")
            order["address"] = location.get("address", "")
            if location.get("message"):
                order["message"] = location["message"]
        self.selected_location_name = location.get("name", "")
        self.populate_table(self.current_orders)
        self.export_button.setEnabled(True)
        self.status.setText(f"면세점 출고지 적용 완료: {self.selected_location_name} · {len(self.current_orders):,}행")

    def login(self) -> None:
        if self.supabase_client is not None:
            self.logout()
            return
        if not self.email.text().strip() or not self.password.text():
            QMessageBox.warning(self, "입력 확인", "이메일과 비밀번호를 입력하세요.")
            return
        self.login_button.setEnabled(False)
        self.status.setText("로그인 및 품목 DB 조회 중...")
        self.worker = LoginWorker(self.email.text().strip(), self.password.text())
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_failure)
        self.worker.start()

    def on_success(self, count: int, catalog: dict) -> None:
        self.login_button.setEnabled(True)
        self.b2c_button.setEnabled(True)
        self.b2b_button.setEnabled(True)
        self.auto_button.setEnabled(True)
        self.supabase_client = catalog["client"]
        self.catalog = catalog
        self.duty_locations, restored_count = sync_remote_locations(catalog.get("duty_locations", []))
        self.refresh_location_combo()
        self.is_admin = catalog.get("app_role") == "admin"
        self.db_button.setEnabled(self.is_admin)
        self.dashboard_db_button.setEnabled(self.is_admin)
        self.ecount_button.setEnabled(self.is_admin and bool(self.current_orders))
        self.matcher = ProductMatcher(
            catalog["items"], catalog["products"], catalog["components"],
            catalog["aliases"], catalog["barcodes"],
        )
        self.login_row.removeWidget(self.login_button)
        self.login_card.hide()
        self.login_button.setText("로그아웃")
        self.login_button.setObjectName("adminButton")
        self.login_button.setMaximumWidth(90)
        self.header_row.addWidget(self.login_button)
        self.login_button.style().unpolish(self.login_button)
        self.login_button.style().polish(self.login_button)
        self.status.setText(
            f"DB 준비 완료: 품목 {count:,}개 · 등록상품 {len(catalog['products']):,}개 · "
            f"구성품 {len(catalog['components']):,}개 · 주소 복구 {restored_count:,}건 · "
            f"권한: {'관리자' if self.is_admin else '일반 사용자(조회 전용)'}"
        )

    def open_account_settings(self) -> None:
        dialog = AccountSettingsDialog(
            self.email.text(), self.password.text(), self.supabase_client is not None, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        email, password = dialog.credentials()
        self.email.setText(email)
        self.password.setText(password)
        if self.supabase_client is not None:
            self.status.setText("계정 입력값을 변경했습니다. 변경된 계정은 다음 로그인부터 사용됩니다.")

    def logout(self) -> None:
        try:
            self.supabase_client.auth.sign_out()
        except Exception:
            pass
        self.supabase_client = None
        self.matcher = None
        self.catalog = {}
        self.is_admin = False
        self.current_orders = []
        self.table.setRowCount(0)
        self.db_button.setEnabled(False)
        self.dashboard_db_button.setEnabled(False)
        self.auto_button.setEnabled(False)
        self.b2c_button.setEnabled(False)
        self.b2b_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.ecount_button.setEnabled(False)
        self.header_row.removeWidget(self.login_button)
        self.login_row.addWidget(self.login_button)
        self.login_button.setText("로그인")
        self.login_button.setObjectName("primaryButton")
        self.login_button.setMaximumWidth(100)
        self.login_button.style().unpolish(self.login_button)
        self.login_button.style().polish(self.login_button)
        self.login_card.show()
        self.status.setText("로그아웃되었습니다. 다시 로그인해 주세요.")

    def check_for_updates(self) -> None:
        if self.update_worker and self.update_worker.isRunning():
            return
        self.update_button.setEnabled(False)
        self.status.setText(f"업데이트 확인 중... 현재 버전 {APP_VERSION}")
        self.update_worker = UpdateCheckWorker()
        self.update_worker.succeeded.connect(self.on_update_checked)
        self.update_worker.failed.connect(self.on_update_failed)
        self.update_worker.start()

    def on_update_checked(self, manifest: dict) -> None:
        self.update_button.setEnabled(True)
        latest = str(manifest.get("version", "0"))
        if version_key(latest) <= version_key(APP_VERSION):
            self.status.setText(f"최신 버전입니다. 현재 {APP_VERSION} · 배포 {latest}")
            QMessageBox.information(self, "업데이트", f"현재 최신 버전 {APP_VERSION}을 사용 중입니다.")
            return
        notes = str(manifest.get("notes", "새 기능과 오류 수정이 포함되어 있습니다."))
        answer = QMessageBox.question(
            self,
            "새 업데이트 발견",
            f"새 버전 {latest}이 있습니다. (현재 {APP_VERSION})\n\n{notes}\n\n지금 다운로드할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText(f"업데이트 보류 · 현재 버전 {APP_VERSION}")
            return
        self.update_button.setEnabled(False)
        self.status.setText(f"새 버전 {latest} 다운로드 및 보안 검사 중...")
        self.update_worker = UpdateDownloadWorker(manifest)
        self.update_worker.succeeded.connect(self.install_downloaded_update)
        self.update_worker.failed.connect(self.on_update_failed)
        self.update_worker.start()

    def on_update_failed(self, message: str) -> None:
        self.update_button.setEnabled(True)
        self.status.setText("업데이트 확인 실패 · 현재 버전은 그대로 사용할 수 있습니다.")
        QMessageBox.warning(self, "업데이트 실패", message)

    def install_downloaded_update(self, downloaded_path: str, manifest: dict) -> None:
        self.update_button.setEnabled(True)
        if not getattr(sys, "frozen", False):
            QMessageBox.information(self, "개발 실행", f"다운로드와 검증은 완료됐습니다.\n{downloaded_path}")
            return
        current_exe = Path(sys.executable).resolve()
        source_exe = Path(downloaded_path).resolve()
        update_dir = source_exe.parent
        script_path = update_dir / "apply_reqm_update.ps1"
        def ps_quote(path: Path) -> str:
            return str(path).replace("'", "''")
        script = (
            f"$target = '{ps_quote(current_exe)}'\n"
            f"$source = '{ps_quote(source_exe)}'\n"
            f"$pidToWait = {os.getpid()}\n"
            "$log = Join-Path (Split-Path -Parent $source) 'update.log'\n"
            "Set-Content -LiteralPath $log -Value ('Update started: ' + (Get-Date)) -Encoding UTF8\n"
            "for ($waitAttempt = 1; $waitAttempt -le 8; $waitAttempt++) {\n"
            "    if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) { break }\n"
            "    Start-Sleep -Seconds 1\n"
            "}\n"
            "$targetName = Split-Path -Leaf $target\n"
            "$lockingProcesses = Get-CimInstance Win32_Process -Filter (\"Name = '\" + $targetName + \"'\") -ErrorAction SilentlyContinue | "
            "Where-Object { $_.ExecutablePath -eq $target }\n"
            "foreach ($process in $lockingProcesses) {\n"
            "    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue\n"
            "    Add-Content -LiteralPath $log -Value ('Stopped locking process: ' + $process.ProcessId) -Encoding UTF8\n"
            "}\n"
            "Start-Sleep -Seconds 1\n"
            "$copied = $false\n"
            "for ($attempt = 1; $attempt -le 30; $attempt++) {\n"
            "    try {\n"
            "        Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop\n"
            "        $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash\n"
            "        $targetHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash\n"
            "        if ($sourceHash -ne $targetHash) { throw 'Copied file hash mismatch' }\n"
            "        $copied = $true\n"
            "        Add-Content -LiteralPath $log -Value ('Copy succeeded: attempt ' + $attempt) -Encoding UTF8\n"
            "        break\n"
            "    } catch {\n"
            "        Add-Content -LiteralPath $log -Value ('Copy retry ' + $attempt + ': ' + $_.Exception.Message) -Encoding UTF8\n"
            "        Start-Sleep -Seconds 1\n"
            "    }\n"
            "}\n"
            "if (-not $copied) {\n"
            "    Add-Content -LiteralPath $log -Value 'Update failed: target remained locked.' -Encoding UTF8\n"
            "    exit 1\n"
            "}\n"
            "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'\n"
            "Get-ChildItem Env: | Where-Object { $_.Name -like '_PYI_*' } | ForEach-Object { Remove-Item ('Env:' + $_.Name) -ErrorAction SilentlyContinue }\n"
            "Start-Sleep -Seconds 2\n"
            "Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target)\n"
            "Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue\n"
            "Add-Content -LiteralPath $log -Value ('Restart requested: ' + (Get-Date)) -Encoding UTF8\n"
        )
        script_path.write_text(script, encoding="utf-8-sig")
        answer = QMessageBox.question(
            self,
            "업데이트 준비 완료",
            f"버전 {manifest.get('version')} 다운로드와 보안 검사가 완료됐습니다.\n"
            "프로그램을 종료하고 업데이트한 뒤 자동으로 다시 실행할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText("업데이트 파일 준비 완료 · 업데이트 버튼을 다시 눌러 적용할 수 있습니다.")
            return
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script_path)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        QApplication.closeAllWindows()
        QApplication.processEvents()
        os._exit(0)

    def open_db_manager(self) -> None:
        if not self.is_admin:
            QMessageBox.warning(self, "권한 없음", "관리자에게 DB 수정 권한을 요청하세요.")
            return
        ItemManagerDialog(self.supabase_client, self.catalog["items"], self.catalog["barcodes"], self).exec()
        self.reload_catalog_after_db_change()

    def reload_catalog_after_db_change(self) -> None:
        """관리 화면에서 변경된 Supabase 데이터를 즉시 다시 불러온다."""
        try:
            for key, table in (
                ("items", "items"),
                ("products", "registered_products"),
                ("components", "product_components"),
                ("barcodes", "item_barcodes"),
                ("aliases", "item_aliases"),
            ):
                self.catalog[key] = fetch_all_rows(self.supabase_client, table)
            self.matcher = ProductMatcher(
                self.catalog["items"], self.catalog["products"],
                self.catalog["components"], self.catalog["aliases"], self.catalog["barcodes"],
            )
            rematched = self.rematch_deleted_items()
            self.status.setText(
                f"DB 변경사항 새로고침 완료: 품목 {len(self.catalog['items']):,}개 · "
                f"등록상품 {len(self.catalog['products']):,}개 · 별칭 {len(self.catalog['aliases']):,}개 · "
                f"삭제 품목 매칭 재검사 {rematched:,}행"
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "DB 새로고침 실패",
                f"DB 변경은 저장됐지만 프로그램에 다시 불러오지 못했습니다.\n프로그램을 재실행해 주세요.\n\n{exc}",
            )

    def rematch_deleted_items(self) -> int:
        if not self.current_orders or self.current_mode != "parcel":
            return 0
        active_codes = {
            str(item.get("item_code", ""))
            for item in self.catalog.get("items", []) if item.get("is_active", True)
        }
        changed = 0
        for order in self.current_orders:
            codes = [
                part.strip().split("×", 1)[0].strip()
                for part in str(order.get("components", "") or "").split("+")
                if part.strip()
            ]
            deleted_codes = [code for code in codes if code and code not in active_codes]
            if not deleted_codes:
                continue
            result = self.matcher.match(order)
            result["status"] = "ambiguous" if result.get("status") != "missing" else "missing"
            result["reason"] = (
                f"삭제된 DB 품목({', '.join(deleted_codes)}) 매칭 제거 · 더블클릭하여 재연결 | "
                + str(result.get("reason", ""))
            )
            order.update(result)
            changed += 1
        if changed:
            self.populate_table(self.current_orders)
        return changed

    def on_failure(self, message: str) -> None:
        self.login_button.setEnabled(True)
        self.status.setText("연결 실패")
        QMessageBox.critical(self, "Supabase 연결 실패", message)

    def select_b2c_file(self) -> None:
        self.select_file("b2c")

    def select_b2b_file(self) -> None:
        self.select_file("b2b")

    def select_file(self, expected_type: str) -> None:
        title = "출고 파일 자동 판별" if expected_type == "auto" else ("B2C 셀메이트 주문 파일 선택" if expected_type == "b2c" else "B2B 면세점 출고 요청 파일 선택")
        path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "출고 파일 (*.xls *.xlsx *.csv *.pdf)",
        )
        if not path:
            return
        self.load_order_file(path, expected_type)

    def load_dropped_order_files(self, paths: list[str]) -> None:
        if not paths:
            return
        if len(paths) > 1:
            QMessageBox.information(self, "파일 한 개씩 처리", "출고 파일은 한 번에 한 개씩 분석합니다. 첫 번째 파일을 불러옵니다.")
        self.load_order_file(paths[0], "auto")

    def load_order_file(self, path: str, expected_type: str = "auto") -> None:
        try:
            if self.matcher is None:
                raise RuntimeError("먼저 Supabase에 로그인해 DB를 불러오세요.")
            duty_result = load_duty_free(path)
            if duty_result:
                if expected_type not in {"b2b", "auto"}:
                    raise ValueError("면세점 B2B 파일로 감지됐습니다. B2B 엑셀 파일 버튼을 사용하세요.")
                orders, detected_type = duty_result
                if all(order.get("match_method") == "name_or_code" for order in orders):
                    for order in orders:
                        order.update(self.matcher.match(order))
                else:
                    match_barcodes(orders, self.catalog.get("barcodes", []), self.catalog.get("items", []))
                columns = {"duty_free": 1}
                self.current_mode = "duty_free"
                embedded_destination = bool(orders) and all(
                    order.get("embedded_destination") and order.get("recipient") and order.get("address")
                    for order in orders
                )
                self.selected_location_name = detected_type if embedded_destination else ""
                self.refresh_location_combo(detected_type)
                self.location_apply_button.setEnabled(True)
                self.export_button.setText(
                    "매장 출고용 변환" if detected_type.startswith("트래블메이트") else "면세점 출고용 변환"
                )
                self.export_button.setEnabled(embedded_destination)
            else:
                if expected_type not in {"b2c", "auto"}:
                    raise ValueError("면세점 B2B 양식을 찾지 못했습니다. B2C 파일이라면 B2C 엑셀 파일 버튼을 사용하세요.")
                try:
                    orders, columns = load_orders(path)
                except ValueError as original_error:
                    if "필수 열" not in str(original_error) and "양식" not in str(original_error):
                        raise
                    format_dialog = FileFormatDialog(path, self)
                    if format_dialog.exec() != QDialog.DialogCode.Accepted:
                        raise original_error
                    orders, columns = load_orders(path, format_dialog.profile)
                missing_columns = missing_shipping_columns(columns)
                if missing_columns:
                    labels = {
                        "order_number": "주문번호",
                        "product_name": "상품명",
                        "quantity": "수량",
                        "recipient": "수령인",
                        "phone": "연락처",
                        "zipcode": "우편번호",
                        "address1": "주소",
                    }
                    missing_text = ", ".join(labels[key] for key in labels if key in missing_columns)
                    QMessageBox.information(
                        self,
                        "입력 양식 연결 필요",
                        "다음 출고 필수 열을 자동으로 찾지 못했습니다.\n"
                        f"{missing_text}\n\n"
                        "원본 파일의 열을 프로그램 출고 항목에 연결해 주세요. "
                        "저장한 연결은 같은 양식의 다음 파일부터 자동 적용됩니다.",
                    )
                    format_dialog = FileFormatDialog(path, self)
                    if format_dialog.exec() != QDialog.DialogCode.Accepted:
                        raise ValueError("출고 필수 열 연결이 취소됐습니다.")
                    orders, columns = load_orders(path, format_dialog.profile)
                for order in orders:
                    order.update(self.matcher.match(order))
                    if Path(path).suffix.lower() == ".pdf":
                        missing_shipping = [
                            label for key, label in (("order_number", "주문번호"), ("recipient", "수령인"))
                            if not str(order.get(key, "")).strip()
                        ]
                        if missing_shipping:
                            order["status"] = "missing"
                            order["reason"] = (
                                "PDF 필수 출고 정보 누락: " + ", ".join(missing_shipping)
                                + " · 원본 PDF 표의 열 제목을 확인하세요 | " + order.get("reason", "")
                            )
                    if order.get("manual_input_detected"):
                        order["status"] = "similar"
                        order["reason"] = "재고매칭 표준 열 뒤 수기 추가 품목 감지 · 검토 필요 | " + order.get("reason", "")
                detected_type = orders[0].get("source_format", "일반 택배") if orders else "일반 택배"
                self.current_mode = "parcel"
                self.location_apply_button.setEnabled(False)
                self.export_button.setText("택배 출고용 변환")
                self.export_button.setEnabled(True)
            self.mark_duplicates(orders)
            if detected_type.startswith("판매처 직접파일"):
                suggestion_dialog = DirectSuggestionDialog(orders, self.catalog.get("items", []), self)
                if suggestion_dialog.entries and suggestion_dialog.exec() == QDialog.DialogCode.Accepted:
                    self.apply_direct_suggestions(
                        orders,
                        suggestion_dialog.confirmed_entries(),
                        suggestion_dialog.review_entries(),
                    )
        except Exception as exc:
            QMessageBox.critical(self, "파일 분석 실패", str(exc))
            return
        self.current_orders = orders
        self.ecount_button.setEnabled(self.is_admin and bool(self.current_orders))
        self.populate_table(self.current_orders)
        counts = {key: sum(1 for row in orders if row.get("status") == key) for key in ("exact", "similar", "ambiguous", "missing", "barcode_error")}
        self.status.setText(
            f"{detected_type} 분석 완료 {len(orders):,}행 · 정확 {counts['exact']:,} · 유사 {counts['similar']:,} · "
            f"확인필요 {counts['ambiguous']:,} · 미등록 {counts['missing']:,} · "
            f"바코드오류 {counts['barcode_error']:,} · {len(columns)}개 열 인식"
        )

    def apply_direct_suggestions(self, orders: list[dict], confirmed: list[dict], reviews: list[dict]) -> None:
        confirmed_by_key = {entry["key"]: entry["suggestion"] for entry in confirmed}
        review_by_key = {entry["key"]: entry["suggestion"] for entry in reviews}
        payloads = []
        for entry in confirmed:
            order, suggestion = entry["order"], entry["suggestion"]
            payloads.append(
                {
                    "source_channel": order.get("channel", ""),
                    "source_product_name": order.get("product_name", ""),
                    "source_options": order.get("options", ""),
                    "normalized_source": entry["key"],
                    "components": component_payload(suggestion["components"]),
                    "is_active": True,
                }
            )
        for order in orders:
            if order.get("status") == "duplicate":
                continue
            key = compact(order_source_text(order))
            suggestion = confirmed_by_key.get(key)
            if suggestion:
                components = suggestion["components"]
                order.update(
                    {
                        "status": "alias",
                        "matched_product": " / ".join(str(item.get("standard_name", "")) for item in components),
                        "components": components_text(components),
                        "reason": "모델·옵션 자동 추천 일괄 확정",
                    }
                )
            elif key in review_by_key:
                suggestion = review_by_key[key]
                order.update(
                    {
                        "status": "ambiguous",
                        "matched_product": " / ".join(str(item.get("standard_name", "")) for item in suggestion["components"]),
                        "components": components_text(suggestion["components"]),
                        "reason": "자동 추천 확인 필요 · " + suggestion["reason"],
                    }
                )
        if not payloads:
            return
        if not self.is_admin:
            QMessageBox.warning(self, "DB 저장 안 함", "자동 추천은 현재 파일에 적용했지만 관리자 권한이 없어 다음 파일용 연결 규칙은 저장하지 못했습니다.")
            return
        try:
            self.supabase_client.table("item_aliases").upsert(
                payloads, on_conflict="source_channel,normalized_source"
            ).execute()
            for payload in payloads:
                self.matcher.aliases[(payload["source_channel"], payload["normalized_source"])] = payload
            QMessageBox.information(self, "일괄 확정 완료", f"자동 추천 {len(payloads):,}개를 적용하고 다음 파일용 DB 연결 규칙으로 저장했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "별칭 일괄 저장 실패", f"현재 파일에는 적용했지만 DB 저장에 실패했습니다.\n{exc}")

    def mark_duplicates(self, orders: list[dict[str, str]]) -> None:
        """합포장은 허용하고, 동일 주문의 동일 상품 행만 중복으로 표시한다."""
        seen, shipped = set(), set()
        try:
            numbers = [r.get("order_number", "") for r in orders if r.get("order_number")]
            if numbers:
                response = self.supabase_client.table("shipment_history").select("duplicate_key").in_("order_number", list(set(numbers))).execute()
                shipped = {str(r.get("duplicate_key", "")) for r in (response.data or [])}
        except Exception:
            pass  # 마이그레이션 전에도 파일 내부 중복 검사는 동작한다.
        for row in orders:
            key = self.duplicate_key(row)
            if key and (key in seen or key in shipped):
                row["status"] = "duplicate"
                row["reason"] = "동일 주문·수령정보·상품 행이 현재 파일에서 반복됨" if key in seen else "동일 출고 행이 이전 출고 이력에 있음"
            if key: seen.add(key)

    @staticmethod
    def duplicate_key(row: dict[str, str]) -> str:
        # 수령인 이름만 같아서는 중복이 아니다. 합포장 내 서로 다른 상품도 각각 정상 행이다.
        fields = ("order_number", "recipient", "phone", "zipcode", "address", "product_name", "options", "quantity")
        normalized = "|".join(compact(str(row.get(field, ""))) for field in fields)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if row.get("order_number") else ""

    def populate_table(self, orders: list[dict[str, str]]) -> None:
        keys = [
            "status", "matched_product", "components", "reason", "source_row", "source_item_code", "order_number",
            "channel", "product_name", "options", "quantity", "recipient", "phone", "zipcode",
            "address", "matched_name",
        ]
        labels = {"exact": "정확", "similar": "유사", "ambiguous": "확인필요", "missing": "미등록", "barcode_error": "바코드오류", "manual": "수동확정", "alias": "별칭적용", "duplicate": "중복출고"}
        colors = {
            "exact": QColor("#d9ead3"),
            "similar": QColor("#fff2cc"),
            "ambiguous": QColor("#fce5cd"),
            "missing": QColor("#f4cccc"),
            "barcode_error": QColor("#e06666"),
            "manual": QColor("#cfe2f3"),
            "alias": QColor("#d9d2e9"),
            "duplicate": QColor("#ea9999"),
        }
        self.table.setRowCount(len(orders))
        for row_index, order in enumerate(orders):
            for col_index, key in enumerate(keys):
                value = labels.get(order.get(key, ""), order.get(key, "")) if key == "status" else order.get(key, "")
                item = QTableWidgetItem(value)
                item.setBackground(colors.get(order.get("status", ""), QColor("white")))
                self.table.setItem(row_index, col_index, item)

    def edit_match(self, row_index: int, _column_index: int) -> None:
        if self.matcher is None or not (0 <= row_index < len(self.current_orders)):
            return
        order = self.current_orders[row_index]
        dialog = CorrectionDialog(order, self.matcher.items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        matched_product, components, scope, component_data = dialog.result_data()
        targets = [row_index]
        if scope in {"same", "database"}:
            targets = [
                index for index, candidate in enumerate(self.current_orders)
                if candidate.get("product_name") == order.get("product_name")
                and candidate.get("options") == order.get("options")
                and candidate.get("model") == order.get("model")
            ]
        for index in targets:
            self.current_orders[index].update(
                {
                    "status": "manual",
                    "matched_product": matched_product,
                    "components": components,
                    "reason": "사용자 수동 확정",
                }
            )
        self.populate_table(self.current_orders)
        if scope == "database" and not self.is_admin:
            QMessageBox.warning(self, "권한 없음", "현재 파일에는 적용했지만 DB 별칭 저장은 관리자만 할 수 있습니다.")
            self.status.setText(f"수동 수정 완료: {len(targets)}개 행에 적용 (DB 저장 안 함)")
            return
        if scope == "database":
            try:
                source_key = compact(order_source_text(order))
                payload = {
                    "source_channel": order.get("channel", ""),
                    "source_product_name": order.get("product_name", ""),
                    "source_options": order.get("options", ""),
                    "normalized_source": source_key,
                    "components": component_data,
                    "is_active": True,
                }
                self.supabase_client.table("item_aliases").upsert(
                    payload, on_conflict="source_channel,normalized_source"
                ).execute()
                self.matcher.aliases[(order.get("channel", ""), source_key)] = payload
                self.status.setText(f"수동 수정 및 별칭 저장 완료: {len(targets)}개 행에 적용")
            except Exception as exc:
                QMessageBox.warning(self, "별칭 저장 실패", f"현재 파일 수정은 적용됐지만 DB 저장에 실패했습니다.\n{exc}")
        else:
            self.status.setText(f"수동 수정 완료: {len(targets)}개 행에 적용")

    def export_file(self) -> None:
        if not self.current_orders:
            QMessageBox.warning(self, "저장할 데이터 없음", "먼저 주문 파일을 불러오세요.")
            return
        if self.current_mode == "duty_free" and not self.selected_location_name:
            QMessageBox.warning(self, "출고지 미적용", "면세점 출고지를 선택하고 '선택 출고지 적용'을 눌러주세요.")
            return
        unresolved = [row for row in self.current_orders if row.get("status") in {"missing", "ambiguous", "duplicate", "barcode_error"}]
        if unresolved:
            answer = QMessageBox.question(
                self,
                "오류 항목 포함 변환",
                f"미등록·확인 필요·중복 출고 항목이 {len(unresolved)}개 남아 있습니다.\n"
                "오류 항목은 품목코드가 비어 있거나 중복될 수 있습니다.\n그래도 택배 출고용 파일로 변환하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "면세점 출고 파일 저장" if self.current_mode == "duty_free" else "위킵 택배 출고 파일 저장",
            "면세점_출고.xlsx" if self.current_mode == "duty_free" else "위킵_택배출고.xlsx",
            "Excel 파일 (*.xlsx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            selected_id = str(self.output_format_combo.currentData() or "default_b2c")
            available_formats = load_output_formats()
            profile = next(
                (row for row in available_formats if str(row.get("id")) == selected_id),
                available_formats[0],
            )
            export_with_format(self.current_orders, file_path, profile)
        except Exception as exc:
            QMessageBox.critical(self, "Excel 저장 실패", str(exc))
            return
        try:
            history = [{"duplicate_key": self.duplicate_key(row), "order_number": row.get("order_number", ""), "sales_channel": row.get("channel", ""), "recipient": row.get("recipient", ""), "phone": row.get("phone", ""), "address": row.get("address", ""), "product_name": row.get("product_name", ""), "options": row.get("options", ""), "quantity": row.get("quantity", ""), "source_type": "duty_free" if self.current_mode == "duty_free" else "b2c"} for row in self.current_orders if row.get("order_number")]
            if history:
                self.supabase_client.table("shipment_history").upsert(history, on_conflict="duplicate_key").execute()
        except Exception as exc:
            QMessageBox.warning(self, "이력 저장 안내", f"Excel은 저장됐지만 중복 방지 이력을 Supabase에 기록하지 못했습니다.\n관리자용 SQL 적용 여부를 확인하세요.\n{exc}")
        self.record_recent_work(file_path, str(profile.get("name", "출고 양식")))
        QMessageBox.information(self, "저장 완료", f"위킵 출고 파일을 저장했습니다.\n{file_path}")

    def open_ecount_transfer(self) -> None:
        if not self.is_admin:
            QMessageBox.warning(self, "권한 없음", "이카운트 창고이동은 관리자만 실행할 수 있습니다.")
            return
        if not self.current_orders:
            QMessageBox.warning(self, "주문 없음", "먼저 출고 주문 파일을 분석하세요.")
            return
        dialog = EcountTransferDialog(
            self.current_orders,
            self.catalog.get("items", []),
            load_config().get("ecount", {}),
            self.completed_ecount_requests,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.status.setText(
                f"이카운트 창고이동 완료 · {dialog.transfer_scope} · 집계 품목 {len(dialog.items):,}개"
            )

if __name__ == "__main__":
    remove_legacy_transfer_credentials()
    app = QApplication(sys.argv)
    window = MainWindow()
    if not window.require_startup_login():
        sys.exit(0)
    window.show()
    sys.exit(app.exec())
