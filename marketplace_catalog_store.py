"""판매처에서 동기화한 상품·옵션 캐시를 보관한다.

로그인 쿠키나 비밀번호는 저장하지 않는다. 이 파일은 검색 화면에 필요한
상품/옵션 식별자와 마지막 확인 상태만 보관한다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


CATALOG_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "marketplace_catalog.json"


def load_catalog_options(marketplace: str = "29CM") -> list[dict[str, str]]:
    try:
        rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return [dict(row) for row in rows if isinstance(row, dict) and row.get("marketplace") == marketplace]


def save_catalog_options(marketplace: str, options: list[dict[str, str]]) -> list[dict[str, str]]:
    try:
        all_rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        existing = [dict(row) for row in all_rows if isinstance(row, dict) and row.get("marketplace") != marketplace]
    except (OSError, ValueError, TypeError):
        existing = []
    synced_at = datetime.now().isoformat(timespec="seconds")
    normalized = []
    for row in options:
        item_no = str(row.get("marketplace_item_no", "")).strip()
        option_no = str(row.get("marketplace_option_no", "")).strip()
        if not item_no or not option_no:
            continue
        normalized.append({
            "marketplace": marketplace,
            "marketplace_item_no": item_no,
            "marketplace_option_no": option_no,
            "marketplace_item_name": str(row.get("marketplace_item_name", "")).strip(),
            "marketplace_option_name": str(row.get("marketplace_option_name", "")).strip(),
            "stock": str(row.get("stock", "")).strip(),
            "sale_status": str(row.get("sale_status", "")).strip(),
            "synced_at": synced_at,
        })
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(existing + normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def update_catalog_option(
    marketplace: str, item_no: str, option_no: str, *, stock: str, sale_status: str,
) -> bool:
    """판매처 실행이 완료된 옵션의 화면 캐시를 즉시 갱신한다."""
    try:
        rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return False
    except (OSError, ValueError, TypeError):
        return False

    for row in rows:
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("marketplace", "")).strip() == marketplace
            and str(row.get("marketplace_item_no", "")).strip() == str(item_no).strip()
            and str(row.get("marketplace_option_no", "")).strip() == str(option_no).strip()
        ):
            row["stock"] = str(stock).strip()
            row["sale_status"] = str(sale_status).strip()
            row["synced_at"] = datetime.now().isoformat(timespec="seconds")
            CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CATALOG_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
    return False


def search_catalog_options(query: str, marketplace: str = "29CM") -> list[dict[str, str]]:
    needle = query.strip().casefold()
    rows = load_catalog_options(marketplace)
    if not needle:
        return rows
    fields = ("marketplace_item_name", "marketplace_option_name", "marketplace_item_no", "marketplace_option_no")
    return [row for row in rows if any(needle in str(row.get(field, "")).casefold() for field in fields)]
