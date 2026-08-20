from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable


STORE_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "weekly_inventory.sqlite3"
RAW_HEADERS = [
    "년", "월", "일", "요일", "주차", "구간", "구분", "일별\t", "거래처코드\t", "거래처\t",
    "품목명[규격]코드\t", "품목명[규격]\t", "수량\t", "공급가액\t", "부가세\t", "합계\t",
]


@contextmanager
def _connect(path: str | Path | None = None):
    target = Path(path) if path else STORE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sales_raw (
            row_key TEXT PRIMARY KEY,
            sale_year INTEGER NOT NULL,
            sale_month INTEGER NOT NULL,
            sale_day INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            quantity REAL NOT NULL,
            payload TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS item_prices (
            item_code TEXT PRIMARY KEY COLLATE NOCASE,
            item_name TEXT NOT NULL,
            unit_price REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS sales_raw_month_item ON sales_raw(sale_year, sale_month, item_code)")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _number(value, default=0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def _integer(value, default=0) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return int(default)


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def add_sales_rows(rows: Iterable[Iterable], path: str | Path | None = None) -> tuple[int, int]:
    """Append sales rows without removing history; identical occurrences are idempotent."""
    occurrences: dict[str, int] = defaultdict(int)
    prepared = []
    imported_at = datetime.now().isoformat(timespec="seconds")
    for raw in rows:
        values = list(raw)[:16]
        values.extend([None] * (16 - len(values)))
        year, month, day = (_integer(values[0]), _integer(values[1]), _integer(values[2]))
        item_code = str(values[10] or "").strip()
        if not year or not 1 <= month <= 12 or not item_code:
            continue
        normalized = [_json_value(value) for value in values]
        stable = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), default=str)
        occurrences[stable] += 1
        row_key = hashlib.sha256(f"{stable}|{occurrences[stable]}".encode("utf-8")).hexdigest()
        prepared.append((row_key, year, month, day, item_code, _number(values[12]), stable, imported_at))
    if not prepared:
        return 0, 0
    with _connect(path) as connection:
        before = connection.total_changes
        connection.executemany(
            "INSERT OR IGNORE INTO sales_raw VALUES (?, ?, ?, ?, ?, ?, ?, ?)", prepared
        )
        inserted = connection.total_changes - before
    return inserted, len(prepared) - inserted


def save_item_prices(prices: Iterable[tuple[str, str, float]], path: str | Path | None = None) -> int:
    prepared = [
        (str(code).strip(), str(name or "").strip(), _number(price), datetime.now().isoformat(timespec="seconds"))
        for code, name, price in prices if str(code or "").strip()
    ]
    with _connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO item_prices VALUES (?, ?, ?, ?)
            ON CONFLICT(item_code) DO UPDATE SET
                item_name=excluded.item_name, unit_price=excluded.unit_price, updated_at=excluded.updated_at
            """,
            prepared,
        )
    return len(prepared)


def load_item_prices(path: str | Path | None = None) -> dict[str, float]:
    with _connect(path) as connection:
        return {str(code).casefold(): float(price) for code, price in connection.execute("SELECT item_code, unit_price FROM item_prices")}


def recent_months(reference: date | None = None, count: int = 5) -> list[tuple[int, int]]:
    current = reference or date.today()
    absolute = current.year * 12 + current.month - 1
    result = []
    for offset in range(count - 1, -1, -1):
        value = absolute - offset
        result.append((value // 12, value % 12 + 1))
    return result


def monthly_sales(months: list[tuple[int, int]] | None = None, path: str | Path | None = None) -> dict[str, dict[tuple[int, int], float]]:
    selected = months or recent_months()
    result: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    if not selected:
        return result
    conditions = " OR ".join("(sale_year=? AND sale_month=?)" for _ in selected)
    params = [value for pair in selected for value in pair]
    with _connect(path) as connection:
        query = f"SELECT item_code, sale_year, sale_month, SUM(quantity) FROM sales_raw WHERE {conditions} GROUP BY item_code, sale_year, sale_month"
        for code, year, month, quantity in connection.execute(query, params):
            result[str(code).casefold()][(int(year), int(month))] = float(quantity or 0)
    return result


def load_sales_rows(path: str | Path | None = None) -> list[list]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT payload FROM sales_raw ORDER BY sale_year, sale_month, sale_day, rowid"
        ).fetchall()
    return [json.loads(payload) for (payload,) in rows]


def sales_row_count(path: str | Path | None = None) -> int:
    with _connect(path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM sales_raw").fetchone()[0])
