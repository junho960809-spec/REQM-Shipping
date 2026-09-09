"""Domain rules shared by every outbound-shipment integration."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation


class ShipmentValidationError(ValueError):
    """Raised when a shipment cannot safely be submitted."""


FIELD_LABELS = {
    "order_number": "주문번호",
    "channel": "판매처",
    "wekeep_product_name": "상품명",
    "source_product_name": "상품명",
    "sku_no": "위킵 SKU",
    "recipient": "수령인",
    "phone": "연락처",
    "zipcode": "우편번호",
    "address": "주소",
}


def positive_integer(value: object, *, label: str = "수량") -> int:
    """Return an exact positive integer without rounding or coercing bad input."""
    if isinstance(value, bool):
        raise ShipmentValidationError(f"{label}은 1 이상의 정수여야 합니다: {value}")
    text = str(value if value is not None else "").replace(",", "").strip()
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ShipmentValidationError(f"{label}이 숫자가 아닙니다: {value}") from exc
    if not number.is_finite() or number <= 0 or number != number.to_integral_value():
        raise ShipmentValidationError(f"{label}은 1 이상의 정수여야 합니다: {value}")
    return int(number)


def required_fields(order_kind: str) -> tuple[str, ...]:
    common = ("recipient", "phone", "zipcode", "address")
    if order_kind == "b2c":
        return ("order_number", "channel", *common)
    if order_kind == "b2c_buying":
        return ("sku_no", *common)
    if order_kind in {"b2b", "b2b_buying"}:
        return ("order_number", "sku_no", *common)
    raise ShipmentValidationError(f"지원하지 않는 출고 유형입니다: {order_kind}")


def validate_prepared_shipment(row: dict, order_kind: str) -> None:
    missing = [FIELD_LABELS[key] for key in required_fields(order_kind) if not str(row.get(key) or "").strip()]
    if not str(row.get("wekeep_product_name") or row.get("source_product_name") or "").strip():
        missing.append("상품명")
    if missing:
        raise ShipmentValidationError("필수 배송정보 누락: " + ", ".join(dict.fromkeys(missing)))
    positive_integer(row.get("quantity"))


def shipment_idempotency_key(rows: list[dict], order_kind: str, provider: str = "wekeep") -> str:
    """Build a stable, non-PII key for one exact submission batch."""
    normalized = []
    for row in rows:
        normalized.append({
            "order_number": str(row.get("order_number") or "").strip(),
            "item_code": str(row.get("item_code") or "").strip(),
            "sku_no": str(row.get("sku_no") or "").strip(),
            "quantity": positive_integer(row.get("quantity")),
            "recipient": str(row.get("recipient") or "").strip(),
            "zipcode": str(row.get("zipcode") or "").strip(),
            "address": str(row.get("address") or "").strip(),
        })
    document = json.dumps(
        {"provider": provider, "order_kind": order_kind, "rows": normalized},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(document.encode("utf-8")).hexdigest()
