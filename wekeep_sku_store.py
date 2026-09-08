"""WeKeep SKU mappings and order payload preparation."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
LOCAL_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM"
LOCAL_MAPPING_PATH = LOCAL_DIR / "wekeep_sku_mappings.json"
COMPONENT_RE = re.compile(r"\s*([^+×]+?)\s*×\s*(\d+)\s*(?:\+|$)")


def bundled_mapping_path() -> Path:
    root = Path(getattr(sys, "_MEIPASS", APP_DIR))
    return root / "assets" / "wekeep_sku_mappings.json"


def _read_rows(path: Path) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = value.get("mappings", []) if isinstance(value, dict) else value
    return [dict(row) for row in rows if isinstance(row, dict)]


def load_wekeep_sku_mappings(
    seed_path: Path | None = None, local_path: Path | None = None,
) -> list[dict]:
    """Merge bundled seed data with local overrides, keyed by internal item code."""
    merged: dict[str, dict] = {}
    for path in (seed_path or bundled_mapping_path(), local_path or LOCAL_MAPPING_PATH):
        for row in _read_rows(path):
            item_code = str(row.get("item_code") or "").strip()
            sku_no = str(row.get("sku_no") or "").strip()
            if not item_code or not sku_no:
                continue
            clean = {
                "item_code": item_code,
                "wekeep_manage_code": str(row.get("wekeep_manage_code") or item_code).strip(),
                "product_name": str(row.get("product_name") or "").strip(),
                "sku_no": sku_no,
                "customer_barcode": str(row.get("customer_barcode") or "").strip(),
                "is_active": bool(row.get("is_active", True)),
            }
            merged[item_code.casefold()] = clean
    return sorted(merged.values(), key=lambda row: row["item_code"].casefold())


def save_wekeep_sku_mapping(mapping: dict, local_path: Path | None = None) -> None:
    """Save or replace one local SKU override without modifying the bundled seed."""
    path = local_path or LOCAL_MAPPING_PATH
    existing = load_wekeep_sku_mappings(seed_path=Path("__missing__"), local_path=path)
    by_code = {str(row["item_code"]).casefold(): row for row in existing}
    item_code = str(mapping.get("item_code") or "").strip()
    sku_no = str(mapping.get("sku_no") or "").strip()
    if not item_code or not sku_no:
        raise ValueError("내부 품목코드와 위킵 SKU는 필수입니다.")
    by_code[item_code.casefold()] = {
        "item_code": item_code,
        "wekeep_manage_code": str(mapping.get("wekeep_manage_code") or item_code).strip(),
        "product_name": str(mapping.get("product_name") or "").strip(),
        "sku_no": sku_no,
        "customer_barcode": str(mapping.get("customer_barcode") or "").strip(),
        "is_active": bool(mapping.get("is_active", True)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "mappings": list(by_code.values())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def component_codes(value: str) -> list[tuple[str, int]]:
    text = str(value or "").strip()
    if not text:
        return []
    parsed = [(code.strip(), int(quantity)) for code, quantity in COMPONENT_RE.findall(text)]
    return parsed or [(text, 1)]


def prepare_wekeep_orders(
    orders: list[dict], *, order_kind: str, mappings: list[dict] | None = None,
) -> list[dict]:
    """Expand matched REQM order rows into WeKeep-ready SKU rows."""
    index = {
        str(row.get("item_code") or "").casefold(): row
        for row in (mappings if mappings is not None else load_wekeep_sku_mappings())
        if row.get("is_active", True)
    }
    result: list[dict] = []
    blocked_statuses = {"missing", "ambiguous", "barcode_error", "duplicate"}
    for source_index, order in enumerate(orders):
        base = {
            "source_index": source_index,
            "order_kind": order_kind,
            "order_number": str(order.get("order_number") or "").strip(),
            "channel": str(order.get("channel") or "").strip(),
            "source_product_name": str(order.get("product_name") or "").strip(),
            "options": str(order.get("options") or "").strip(),
            "recipient": str(order.get("recipient") or "").strip(),
            "phone": str(order.get("phone") or "").strip(),
            "zipcode": str(order.get("zipcode") or "").strip(),
            "address": str(order.get("address") or "").strip(),
            "message": str(order.get("message") or "").strip(),
        }
        if str(order.get("status") or "") in blocked_statuses:
            result.append({**base, "state": "review", "reason": "REQM 품목 매칭을 먼저 확정하세요."})
            continue
        components = component_codes(str(order.get("components") or ""))
        if not components:
            result.append({**base, "state": "review", "reason": "연결된 내부 품목코드가 없습니다."})
            continue
        order_quantity = max(1, int(float(order.get("quantity") or 1)))
        missing_codes = [code for code, _ in components if code.casefold() not in index]
        if missing_codes:
            result.append({
                **base,
                "state": "review",
                "item_code": ", ".join(missing_codes),
                "reason": "위킵 SKU 미등록: " + ", ".join(missing_codes),
            })
            continue
        for item_code, component_quantity in components:
            mapping = index[item_code.casefold()]
            result.append({
                **base,
                "state": "ready",
                "reason": "위킵 자동입력 준비 완료",
                "item_code": item_code,
                "wekeep_manage_code": mapping.get("wekeep_manage_code", ""),
                "wekeep_product_name": mapping.get("product_name", ""),
                "sku_no": mapping.get("sku_no", ""),
                "customer_barcode": mapping.get("customer_barcode", ""),
                "quantity": order_quantity * component_quantity,
            })
    return result


def readiness_counts(rows: list[dict]) -> dict[str, int]:
    return {
        "total": len(rows),
        "ready": sum(row.get("state") == "ready" for row in rows),
        "review": sum(row.get("state") != "ready" for row in rows),
    }
