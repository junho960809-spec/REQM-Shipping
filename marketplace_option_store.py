"""판매처 옵션 매핑과 품절 처리 요청을 로컬에 보관한다.

로그인 세션이나 비밀번호는 이 파일에 저장하지 않는다. 실제 판매처 실행기는
전용 자동화 PC에만 두고, 출고 프로그램은 매핑과 승인된 요청만 관리한다.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path


APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM"
MAPPING_PATH = APP_DATA_DIR / "marketplace_option_mappings.json"
ACTION_LOG_PATH = APP_DATA_DIR / "marketplace_option_actions.json"


def _load_rows(path: Path) -> list[dict[str, str]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _save_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def load_option_mappings() -> list[dict[str, str]]:
    return _load_rows(MAPPING_PATH)


def upsert_option_mapping(row: dict[str, str]) -> list[dict[str, str]]:
    required = ("marketplace", "marketplace_item_no", "marketplace_option_no")
    normalized = {key: str(value or "").strip() for key, value in row.items()}
    if any(not normalized.get(key) for key in required):
        raise ValueError("판매처, 상품번호, 옵션번호는 필수입니다.")
    normalized["verified_at"] = datetime.now().isoformat(timespec="seconds")

    rows = load_option_mappings()
    key = tuple(normalized[key].casefold() for key in required)
    for index, existing in enumerate(rows):
        existing_key = tuple(str(existing.get(field, "")).strip().casefold() for field in required)
        if existing_key == key:
            rows[index] = {**existing, **normalized}
            break
    else:
        rows.append(normalized)
    _save_rows(MAPPING_PATH, rows)
    return rows


def load_option_actions() -> list[dict[str, str]]:
    return _load_rows(ACTION_LOG_PATH)


def create_option_action(mapping: dict[str, str], action: str, requested_by: str = "", target_stock: str = "") -> dict[str, str]:
    if action not in {"SOLD_OUT", "RESTOCK"}:
        raise ValueError("지원하지 않는 옵션 처리입니다.")
    event = {
        "action_id": str(uuid.uuid4()),
        "requested_at": datetime.now().isoformat(timespec="seconds"),
        "marketplace": str(mapping.get("marketplace", "")).strip(),
        "marketplace_item_no": str(mapping.get("marketplace_item_no", "")).strip(),
        "marketplace_option_no": str(mapping.get("marketplace_option_no", "")).strip(),
        "internal_item_code": str(mapping.get("internal_item_code", "")).strip(),
        "internal_option_name": str(mapping.get("internal_option_name", "")).strip(),
        "action": action,
        "status": "PENDING",
        "requested_by": requested_by.strip(),
        "processed_by": "",
        "target_stock": str(target_stock or "0").strip(),
    }
    if not all(event[key] for key in ("marketplace", "marketplace_item_no", "marketplace_option_no")):
        raise ValueError("처리할 판매처 상품번호와 옵션번호가 필요합니다.")
    rows = load_option_actions()
    rows.append(event)
    _save_rows(ACTION_LOG_PATH, rows)
    return event


def complete_option_action(
    action_id: str, status: str, processed_by: str, error_message: str = "", details: dict[str, str] | None = None,
) -> dict[str, str]:
    """전용 자동화 PC가 판매처 실행 결과를 기록한다."""
    if status not in {"COMPLETED", "FAILED"}:
        raise ValueError("처리 결과는 COMPLETED 또는 FAILED여야 합니다.")
    rows = load_option_actions()
    for row in rows:
        if row.get("action_id") == action_id:
            row["status"] = status
            row["processed_by"] = processed_by.strip()
            row["processed_at"] = datetime.now().isoformat(timespec="seconds")
            row["error_message"] = error_message.strip()
            row.update({key: str(value) for key, value in (details or {}).items()})
            _save_rows(ACTION_LOG_PATH, rows)
            return dict(row)
    raise ValueError("처리 이력을 찾지 못했습니다.")
