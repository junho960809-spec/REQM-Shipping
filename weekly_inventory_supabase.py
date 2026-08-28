from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
from typing import Iterable


TABLE = "ecount_sales_rawdata"
SYNC_TABLE = "ecount_sales_sync_history"


def _integer(value, default=0) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return int(default)


def _number(value, default=0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def _text(value) -> str:
    return str(value or "").strip()


def raw_row_to_record(raw: Iterable, occurrence: int = 1) -> dict:
    values = list(raw)[:16]
    values.extend([None] * (16 - len(values)))
    year, month, day = (_integer(values[0]), _integer(values[1]), _integer(values[2]))
    compact_date = _integer(values[7]) or (year * 10000 + month * 100 + day)
    sale_date = date(compact_date // 10000, compact_date // 100 % 100, compact_date % 100)
    normalized = [value.isoformat() if isinstance(value, (date, datetime)) else value for value in values]
    stable = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), default=str)
    return {
        "row_key": hashlib.sha256(f"{stable}|{occurrence}".encode("utf-8")).hexdigest(),
        "sale_date": sale_date.isoformat(),
        "sale_year": sale_date.year,
        "sale_month": sale_date.month,
        "sale_day": sale_date.day,
        "weekday": _text(values[3]),
        "week_label": _text(values[4]),
        "period_label": _text(values[5]),
        "category": _text(values[6]),
        "customer_code": _text(values[8]),
        "customer_name": _text(values[9]),
        "item_code": _text(values[10]),
        "item_name": _text(values[11]),
        "quantity": _number(values[12]),
        "supply_amount": _integer(values[13]),
        "tax_amount": _integer(values[14]),
        "total_amount": _integer(values[15]),
        "source": "ecount",
        "synced_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def prepare_records(rows: Iterable[Iterable]) -> list[dict]:
    occurrences: dict[str, int] = defaultdict(int)
    records = []
    for raw in rows:
        values = list(raw)[:16]
        if not _integer(values[0] if values else 0) or len(values) < 11 or not _text(values[10]):
            continue
        stable = json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str)
        occurrences[stable] += 1
        try:
            records.append(raw_row_to_record(values, occurrences[stable]))
        except (TypeError, ValueError):
            continue
    return records


def upload_rows(client, rows: Iterable[Iterable], batch_size: int = 500) -> dict[str, int]:
    records = prepare_records(rows)
    for start in range(0, len(records), batch_size):
        client.table(TABLE).upsert(records[start:start + batch_size], on_conflict="row_key").execute()
    return {"inserted": len(records), "duplicates": 0}


def replace_period(client, start_date: date, end_date: date, rows: Iterable[Iterable]) -> dict:
    records = prepare_records(rows)
    response = client.rpc("replace_ecount_sales_period", {
        "p_start_date": start_date.isoformat(),
        "p_end_date": end_date.isoformat(),
        "p_rows": records,
    }).execute()
    result = response.data or {}
    if isinstance(result, list) and result:
        result = result[0]
    return dict(result) if isinstance(result, dict) else {"row_count": len(records)}


def fetch_rows(client, page_size: int = 1000) -> list[list]:
    result: list[list] = []
    start = 0
    while True:
        response = (
            client.table(TABLE)
            .select("sale_year,sale_month,sale_day,weekday,week_label,period_label,category,sale_date,customer_code,customer_name,item_code,item_name,quantity,supply_amount,tax_amount,total_amount")
            .order("sale_date")
            .order("id")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        for row in page:
            compact = str(row.get("sale_date") or "").replace("-", "")
            result.append([
                row.get("sale_year"), row.get("sale_month"), row.get("sale_day"), row.get("weekday"),
                row.get("week_label"), row.get("period_label"), row.get("category"), _integer(compact),
                row.get("customer_code"), row.get("customer_name"), row.get("item_code"), row.get("item_name"),
                row.get("quantity"), row.get("supply_amount"), row.get("tax_amount"), row.get("total_amount"),
            ])
        if len(page) < page_size:
            return result
        start += page_size


def fetch_monthly_sales(client, months: list[tuple[int, int]]) -> dict[str, dict[tuple[int, int], float]]:
    result: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    if not months:
        return result
    response = client.rpc("ecount_monthly_item_sales", {
        "p_months": [{"year": year, "month": month} for year, month in months]
    }).execute()
    for row in response.data or []:
        result[_text(row.get("item_code")).casefold()][
            (_integer(row.get("sale_year")), _integer(row.get("sale_month")))
        ] = _number(row.get("quantity"))
    return result


def row_count(client) -> int:
    response = client.table(TABLE).select("id", count="exact").limit(1).execute()
    return int(response.count or 0)
