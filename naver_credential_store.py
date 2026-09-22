from __future__ import annotations

import json
import os
from pathlib import Path

from ecount_credential_store import protect_secret, unprotect_secret


NAVER_CREDENTIAL_PATH = (
    Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "naver_commerce_credentials.json"
)


def save_naver_credentials(client_id: str, client_secret: str, path: Path = NAVER_CREDENTIAL_PATH) -> None:
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if not client_id or not client_secret:
        raise ValueError("네이버 커머스 API 애플리케이션 ID와 시크릿을 모두 입력하세요.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "client_id": protect_secret(client_id),
        "client_secret": protect_secret(client_secret),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_naver_credentials(path: Path = NAVER_CREDENTIAL_PATH) -> dict[str, str]:
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        return {
            "client_id": unprotect_secret(str(stored.get("client_id") or "")),
            "client_secret": unprotect_secret(str(stored.get("client_secret") or "")),
        }
    except Exception:
        return {"client_id": "", "client_secret": ""}


def delete_naver_credentials(path: Path = NAVER_CREDENTIAL_PATH) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
