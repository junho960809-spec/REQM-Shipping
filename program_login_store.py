from __future__ import annotations

import json
import os
from pathlib import Path

from ecount_credential_store import protect_secret, unprotect_secret


PROGRAM_LOGIN_PATH = (
    Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "program_login.json"
)


def save_program_login(email: str, password: str, path: Path = PROGRAM_LOGIN_PATH) -> None:
    email = str(email).strip()
    password = str(password)
    if not email or not password:
        raise ValueError("이메일과 비밀번호를 모두 입력하세요.")
    payload = {"email": protect_secret(email), "password": protect_secret(password)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_program_login(path: Path = PROGRAM_LOGIN_PATH) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return unprotect_secret(str(payload.get("email", ""))), unprotect_secret(str(payload.get("password", "")))
    except (OSError, ValueError, TypeError):
        return "", ""


def delete_program_login(path: Path = PROGRAM_LOGIN_PATH) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
