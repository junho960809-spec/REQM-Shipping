"""User-facing copy. Business keys, provider selectors and state codes never belong here."""
from __future__ import annotations

import json
import os
from pathlib import Path


TEXT_OVERRIDE_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "ui_texts.json"

DEFAULT_TEXTS = {
    "app.title": "REQM 출고 관리",
    "app.subtitle": "주문 파일을 자동 분석하고 정확한 출고 데이터로 변환합니다",
    "login.window_title": "REQM 로그인",
    "login.eyebrow": "REQM OPERATIONS",
    "login.title": "물류 업무를 시작합니다",
    "login.guide": "등록된 프로그램 계정으로 로그인해 주세요.",
    "login.email_placeholder": "프로그램 계정 이메일",
    "login.password_placeholder": "비밀번호",
    "login.remember": "로그인 정보 저장",
    "login.ready": "로그인 후 물류 대시보드를 사용할 수 있습니다.",
    "login.submit": "로그인",
    "login.exit": "종료",
    "accounts.window_title": "연동 계정 관리",
    "accounts.title": "연동 계정 관리",
    "accounts.guide": "한 번 저장하면 연결된 업무 사이트에 안전하게 자동 로그인합니다.",
    "accounts.security": "모든 값은 현재 Windows 사용자만 해독할 수 있도록 암호화해 저장합니다.",
    "wekeep.preview.window_title": "위킵 출고 검토",
    "wekeep.preview.title": "위킵 출고 최종 검토",
    "wekeep.preview.guide": "상품과 배송정보를 검증한 뒤 프로그램 안에서 승인합니다. 승인 후 위킵 등록은 백그라운드로 처리됩니다.",
    "wekeep.preview.kind": "위킵 등록 유형",
    "wekeep.preview.submit": "검토 완료 · 위킵 출고 등록",
    "wekeep.preview.working": "위킵 등록 진행 중...",
    "common.close": "닫기",
    "preview.title": "REQM UI 미리보기",
    "preview.guide": "실제 로그인이나 출고 없이 색상과 문구를 확인할 수 있습니다.",
    "preview.reload": "테마·텍스트 다시 불러오기",
    "preview.create_files": "편집 파일 만들기",
    "preview.open_folder": "편집 폴더 열기",
    "preview.files_ready_title": "편집 파일 준비 완료",
    "preview.files_ready": "디자인과 문구 편집 파일을 준비했습니다.\n\n{folder}\n\n파일을 수정한 뒤 '테마·텍스트 다시 불러오기'를 눌러 주세요.",
}

_overrides: dict[str, str] | None = None


def reload_texts(path: str | Path | None = None) -> dict[str, str]:
    global _overrides
    source = Path(path) if path is not None else TEXT_OVERRIDE_PATH
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        value = {}
    _overrides = {
        key: value
        for key, value in value.items()
        if key in DEFAULT_TEXTS and isinstance(value, str) and value.strip()
    } if isinstance(value, dict) else {}
    return dict(_overrides)


def text(key: str, **values: object) -> str:
    global _overrides
    if key not in DEFAULT_TEXTS:
        raise KeyError(f"등록되지 않은 UI 텍스트 키입니다: {key}")
    if _overrides is None:
        reload_texts()
    template = (_overrides or {}).get(key, DEFAULT_TEXTS[key])
    return template.format(**values) if values else template
