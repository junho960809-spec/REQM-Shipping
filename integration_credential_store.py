from __future__ import annotations

import json
import os
from pathlib import Path

from ecount_credential_store import protect_secret, unprotect_secret


INTEGRATION_CREDENTIAL_PATH = (
    Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "integration_credentials.json"
)
FIELDS = (
    "ecount_user_id",
    "ecount_password",
    "ecount_api_key",
    "print_board_user_id",
    "print_board_password",
)


def save_integration_credentials(values: dict[str, str], path: Path = INTEGRATION_CREDENTIAL_PATH) -> None:
    normalized = {field: str(values.get(field, "")).strip() for field in FIELDS}
    if not normalized["ecount_user_id"] or not normalized["ecount_api_key"]:
        raise ValueError("이카운트 사용자 ID와 API 인증키를 입력하세요.")
    if not normalized["print_board_user_id"] or not normalized["print_board_password"]:
        raise ValueError("인쇄 게시판 아이디와 비밀번호를 입력하세요.")
    encrypted = {field: protect_secret(value) for field, value in normalized.items() if value}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(encrypted, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_integration_credentials(path: Path = INTEGRATION_CREDENTIAL_PATH) -> dict[str, str]:
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {field: "" for field in FIELDS}
    result = {field: "" for field in FIELDS}
    for field in FIELDS:
        encrypted = stored.get(field, "") if isinstance(stored, dict) else ""
        if not encrypted:
            continue
        try:
            result[field] = unprotect_secret(str(encrypted))
        except Exception:
            result[field] = ""
    return result


def delete_integration_credentials(path: Path = INTEGRATION_CREDENTIAL_PATH) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def print_board_credentials() -> dict[str, str]:
    values = load_integration_credentials()
    return {
        "user_id": values["print_board_user_id"],
        "password": values["print_board_password"],
    }

