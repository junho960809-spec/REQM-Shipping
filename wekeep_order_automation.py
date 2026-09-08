"""Attach a validated workbook to the matching WeKeep registration surface."""
from __future__ import annotations

import json
from pathlib import Path

from ecount_credential_store import protect_secret, unprotect_secret
from wekeep_report_service import PROFILE_PATH, launch_wekeep_context


ORDER_LIST_URL = "https://fbw.wekeep.co.kr/fbw/admin/v2/order/list.do"
ORDER_ROUTES = {
    "b2c": ('button[id^="EXCEL-"]', "#excelOrderBtn", "#file_upload_excelPopup"),
    "b2c_buying": ('button[id^="BUYING-"]', "#shipmentExcelBtn", "#file_upload_excelPopup_shipment"),
    "b2b": ('button[id^="B2B-"]', "#excelOrderBtn", "#file_upload_excelPopup"),
    "b2b_buying": ('button[id^="B2B-"]', "#shipmentExcelBtn", "#file_upload_excelPopup_shipment"),
}


def load_pending_payload(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict) and value.get("encrypted"):
        value = json.loads(unprotect_secret(str(value["encrypted"])))
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        raise ValueError("위킵 전송 대기 파일 형식이 올바르지 않습니다.")
    return value


def save_pending_payload(path: str | Path, payload: dict) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("위킵 전송 대기 파일 형식이 올바르지 않습니다.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encrypted = protect_secret(json.dumps(payload, ensure_ascii=False))
    target.write_text(json.dumps({"version": 1, "encrypted": encrypted}), encoding="utf-8")


def open_registration_panel(page, order_kind: str, upload_path: str | Path | None = None) -> None:
    route = ORDER_ROUTES.get(order_kind)
    if not route:
        raise ValueError(f"지원하지 않는 위킵 주문 유형입니다: {order_kind}")
    seller_selector, registration_selector, file_selector = route
    page.get_by_role("button", name="주문 등록 주문 등록", exact=True).click()
    page.locator(seller_selector).click()
    page.locator(registration_selector).click()
    page.wait_for_timeout(300)
    if upload_path:
        path = Path(upload_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"위킵 업로드 파일을 찾을 수 없습니다: {path}")
        page.locator(file_selector).set_input_files(str(path))
        page.wait_for_timeout(300)


def open_order_registration(payload_path: str | Path) -> None:
    """Open the requested seller panel and leave final registration to the user."""
    from playwright.sync_api import sync_playwright

    pending_path = Path(payload_path)
    payload = load_pending_payload(pending_path)
    pending_path.unlink(missing_ok=True)
    order_kind = str(payload.get("order_kind") or "b2c")
    upload_path = Path(str(payload.get("upload_path") or "")) if payload.get("upload_path") else None
    if any(row.get("state") != "ready" for row in payload["rows"]):
        raise ValueError("검토 필요 주문이 남아 있어 위킵 자동입력을 시작할 수 없습니다.")

    PROFILE_PATH.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = launch_wekeep_context(playwright, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(ORDER_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_000)
            if "/order/list.do" not in page.url:
                raise RuntimeError("위킵 로그인 상태가 만료되었습니다. 재고 알림의 '위킵 로그인'을 먼저 진행하세요.")
            open_registration_panel(page, order_kind, upload_path)
            # Upload file is attached, but the modal's Save button is intentionally left
            # to the operator because it creates external fulfillment orders.
            try:
                page.wait_for_event("close", timeout=1_800_000)
            except Exception:
                pass
        finally:
            context.close()
            if upload_path:
                upload_path.unlink(missing_ok=True)
