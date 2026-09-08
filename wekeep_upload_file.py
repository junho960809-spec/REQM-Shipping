"""Build WeKeep's official manual-upload workbooks from validated REQM rows."""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "wekeep_orders"

ORDER_KIND_LABELS = {
    "b2c": "B2C 일반주문",
    "b2c_buying": "B2C 사입형",
    "b2b": "B2B 일반주문",
    "b2b_buying": "B2B 사입형",
}
ORDER_KIND_CAPACITIES = {"b2c": 42, "b2c_buying": 42, "b2b": 1003, "b2b_buying": 1003}


def bundled_template_path(order_kind: str) -> Path:
    if order_kind not in ORDER_KIND_LABELS:
        raise ValueError(f"지원하지 않는 위킵 주문 유형입니다: {order_kind}")
    root = Path(getattr(sys, "_MEIPASS", APP_DIR))
    return root / "assets" / "wekeep_templates" / f"{order_kind}.xlsx"


def _clean_text(value: object) -> str:
    # Excel formulas are never valid customer/order values here.
    text = str(value or "").strip()
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _quantity_text(value: object) -> str:
    try:
        quantity = float(str(value if value is not None else "").replace(",", "").strip())
    except ValueError as exc:
        raise ValueError(f"위킵 수량이 숫자가 아닙니다: {value}") from exc
    if quantity <= 0 or not quantity.is_integer():
        raise ValueError(f"위킵 수량은 1 이상의 정수여야 합니다: {value}")
    return str(int(quantity))


def _b2c_values(row: dict) -> list[object]:
    phone = _clean_text(row.get("phone"))
    return [
        _clean_text(row.get("order_number")),
        _clean_text(row.get("sku_no")),
        _clean_text(row.get("wekeep_product_name") or row.get("source_product_name")),
        _clean_text(row.get("options")),
        _quantity_text(row.get("quantity")),
        None,
        None,
        _clean_text(row.get("recipient")),
        phone,
        phone,
        _clean_text(row.get("zipcode")),
        _clean_text(row.get("address")),
        _clean_text(row.get("message")),
        None,
        None,
    ]


def _b2b_values(row: dict) -> list[object]:
    phone = _clean_text(row.get("phone"))
    values: list[object] = [None] * 29
    values[0] = _clean_text(row.get("order_number"))
    values[1] = _clean_text(row.get("wekeep_product_name") or row.get("source_product_name"))
    values[2] = _clean_text(row.get("sku_no"))
    values[6] = _quantity_text(row.get("quantity"))
    values[9] = _clean_text(row.get("recipient"))
    values[10] = phone
    values[11] = phone
    values[12] = _clean_text(row.get("zipcode"))
    values[13] = _clean_text(row.get("address"))
    values[14] = _clean_text(row.get("message"))
    return values


def create_wekeep_upload(
    rows: list[dict], order_kind: str, output_path: str | Path | None = None,
) -> Path:
    """Copy the official template and fill it without changing its validation/layout."""
    if order_kind not in ORDER_KIND_LABELS:
        raise ValueError(f"지원하지 않는 위킵 주문 유형입니다: {order_kind}")
    if not rows:
        raise ValueError("위킵에 반영할 주문이 없습니다.")
    if any(row.get("state") != "ready" for row in rows):
        raise ValueError("검토 필요 주문이 남아 있어 위킵 파일을 만들 수 없습니다.")

    template = bundled_template_path(order_kind)
    if not template.exists():
        raise FileNotFoundError(f"위킵 공식 양식을 찾을 수 없습니다: {template}")
    target = Path(output_path) if output_path else OUTPUT_DIR / (
        f"위킵_{ORDER_KIND_LABELS[order_kind]}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)

    workbook = load_workbook(target)
    sheet = workbook.active
    capacity = ORDER_KIND_CAPACITIES[order_kind]
    if len(rows) > capacity:
        target.unlink(missing_ok=True)
        raise ValueError(f"위킵 공식 양식은 한 번에 최대 {capacity:,}행까지 등록할 수 있습니다.")
    values_for = _b2b_values if order_kind.startswith("b2b") else _b2c_values
    for row_index, row in enumerate(rows, start=2):
        for column_index, value in enumerate(values_for(row), start=1):
            sheet.cell(row_index, column_index).value = value
    workbook.save(target)
    workbook.close()

    quantity_column = 7 if order_kind.startswith("b2b") else 5
    verification = load_workbook(target, read_only=True, data_only=True)
    try:
        saved_sheet = verification.active
        invalid_rows = []
        for row_index in range(2, len(rows) + 2):
            saved_value = str(saved_sheet.cell(row_index, quantity_column).value or "").strip()
            if not saved_value.isdigit() or int(saved_value) <= 0:
                invalid_rows.append(row_index)
    finally:
        verification.close()
    if invalid_rows:
        target.unlink(missing_ok=True)
        raise ValueError(
            "위킵 업로드 파일의 수량 검증에 실패했습니다. 행: "
            + ", ".join(map(str, invalid_rows))
        )
    return target
