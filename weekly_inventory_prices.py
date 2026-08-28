from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable


TABLE = "weekly_inventory_item_settings"


def _number(value) -> float:
    try:
        return float(Decimal(str(value or 0)))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def fetch_price_settings(client) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            client.table(TABLE)
            .select("item_code,item_name,base_unit_cost,is_active,display_order,updated_at,updated_by")
            .order("display_order")
            .order("item_code")
            .range(start, start + 999)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def price_map(settings: Iterable[dict]) -> dict[str, float]:
    return {
        str(row.get("item_code", "")).strip().casefold(): _number(row.get("base_unit_cost")) * 1.1
        for row in settings
        if str(row.get("item_code", "")).strip()
    }


def active_items(settings: Iterable[dict]) -> list[tuple[str, str]]:
    return [
        (str(row.get("item_code", "")).strip(), str(row.get("item_name", "")).strip())
        for row in settings
        if row.get("is_active", True) and str(row.get("item_code", "")).strip()
    ]


def save_price_setting(client, row: dict, user_id: str | None = None) -> dict:
    code = str(row.get("item_code", "")).strip()
    if not code:
        raise ValueError("품목코드는 필수입니다.")
    payload = {
        "item_code": code,
        "item_name": str(row.get("item_name", "")).strip(),
        "base_unit_cost": _number(row.get("base_unit_cost")),
        "is_active": bool(row.get("is_active", True)),
        "display_order": int(row.get("display_order", 999999) or 999999),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": user_id or None,
    }
    response = client.table(TABLE).upsert(payload, on_conflict="item_code").execute()
    return (response.data or [payload])[0]
