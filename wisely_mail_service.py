"""Download today's Wisely purchase-order workbook from REQM Cafe24 webmail."""
from __future__ import annotations

import hashlib
import os
from datetime import date
from pathlib import Path

WEBMAIL_URL = "http://webmail.reqm.co.kr/intro.php"
SENDER_ADDRESS = "purchase@wisely.store"
SENDER_NAME = "와이즐리 물류팀"
DOWNLOAD_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "wisely_orders"
PROFILE_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "webmail-chrome-profile"


def launch_mail_context(playwright, *, headless: bool):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR), channel=channel, headless=headless, args=["--disable-gpu"],
            )
        except Exception as exc:
            errors.append(f"{channel}: {exc}")
    raise RuntimeError("Chrome 또는 Edge를 실행하지 못했습니다.\n" + " / ".join(errors))


def subject_for(day: date) -> str:
    return f"{day:%Y-%m-%d} 리큐엠 주문 발주서 입니다."


def attachment_name_for(day: date) -> str:
    return f"orders_{day:%Y-%m-%d}_리큐엠.xlsx"


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def download_today_order(user_id: str, password: str, *, day: date | None = None) -> Path:
    """Log in when needed and download the exact sender/date attachment."""
    from playwright.sync_api import sync_playwright

    target_day = day or date.today()
    expected_subject = subject_for(target_day)
    expected_name = attachment_name_for(target_day)
    if not str(user_id).strip() or not password:
        raise ValueError("연동 계정에서 REQM 웹메일 아이디와 비밀번호를 저장해 주세요.")

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = launch_mail_context(playwright, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(WEBMAIL_URL, wait_until="domcontentloaded", timeout=60_000)
            if "/user/mail/" not in page.url:
                page.locator('form[name="userLoginForm"] input[name="mail"]').fill(str(user_id).strip())
                page.locator('form[name="userLoginForm"] input[name="password"]').fill(password)
                page.locator("form[name=\"userLoginForm\"] button[type=\"submit\"]").click()
                page.wait_for_url("**/user/mail/**", timeout=60_000)
            page.goto("http://webmail.reqm.co.kr/user/mail/main.php?page=list&mbox=INBOX", wait_until="domcontentloaded", timeout=60_000)
            row = page.locator("tr").filter(has_text=SENDER_NAME).filter(has_text=expected_subject).first
            if not row.is_visible():
                raise FileNotFoundError(f"오늘 와이즐리 주문 메일을 찾지 못했습니다: {expected_subject}")
            row.get_by_text(expected_subject, exact=True).click()
            page.wait_for_load_state("domcontentloaded")
            body_text = page.locator("body").inner_text()
            if SENDER_ADDRESS not in body_text:
                raise RuntimeError("메일 발신 주소가 와이즐리 물류팀 주소와 일치하지 않습니다.")
            attachment = page.get_by_text(expected_name, exact=False).first
            if not attachment.is_visible():
                raise FileNotFoundError(f"와이즐리 주문 첨부파일을 찾지 못했습니다: {expected_name}")
            with page.expect_download(timeout=60_000) as download_info:
                attachment.click()
            target = DOWNLOAD_DIR / expected_name
            download_info.value.save_as(target)
            if not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError("와이즐리 주문 첨부파일 다운로드에 실패했습니다.")
            return target
        finally:
            context.close()
