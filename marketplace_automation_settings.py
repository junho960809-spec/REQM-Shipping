"""전용 자동화 PC의 브라우저 경로 설정.

로그인 쿠키·비밀번호는 저장하지 않는다. Chrome 프로필 경로만 저장한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


SETTINGS_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "marketplace_automation.json"
DEFAULT_29CM_PROFILE = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Google" / "Chrome" / "User Data" / "Profile 1"


def load_29cm_profile_path() -> str:
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        saved = str(settings.get("29cm_profile_path", "")).strip()
        if saved:
            return saved
    except (OSError, ValueError, TypeError):
        pass
    return str(DEFAULT_29CM_PROFILE)


def save_29cm_profile_path(profile_path: str) -> None:
    path = Path(profile_path).expanduser()
    if not path.is_dir():
        raise ValueError("Chrome Profile Path 폴더를 찾지 못했습니다.")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"29cm_profile_path": str(path)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
