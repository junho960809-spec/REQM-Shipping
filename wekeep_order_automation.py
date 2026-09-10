"""Attach a validated workbook to the matching WeKeep registration surface."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from ecount_credential_store import protect_secret, unprotect_secret
from integration_credential_store import load_integration_credentials
from shipment_job_store import ALLOWED_TRANSITIONS, ShipmentJobStore
from wekeep_report_service import PROFILE_PATH, launch_wekeep_context
from wekeep_upload_file import OUTPUT_DIR, create_wekeep_upload


ORDER_LIST_URL = "https://fbw.wekeep.co.kr/fbw/admin/v2/order/list.do"
ORDER_ROUTES = {
    "b2c": ('button[id^="EXCEL-"]', "#excelOrderBtn", "#file_upload_excelPopup"),
    "b2c_buying": ('button[id^="BUYING-"]', "#shipmentExcelBtn", "#file_upload_excelPopup_shipment"),
    "b2b": ('button[id^="B2B-"]', "#excelOrderBtn", "#file_upload_excelPopup"),
    "b2b_buying": ('button[id^="B2B-"]', "#shipmentExcelBtn", "#file_upload_excelPopup_shipment"),
}
REGISTRATION_PANELS = {
    "b2c": ("#orderExcelPopup", "주식회사 리큐엠(B2C)"),
    "b2b": ("#orderExcelPopup", "주식회사 리큐엠(B2B)"),
    "b2c_buying": ("#shipmentOrderExcelPopup", "주식회사 리큐엠(사입형B2C)"),
    "b2b_buying": ("#shipmentOrderExcelPopup", "주식회사 리큐엠(B2B)"),
}
SUCCESS_MARKERS = ("등록되었습니다", "등록 완료", "성공적으로 등록")
FAILURE_MARKERS = ("등록 실패", "오류가 발생", "업로드 실패")


def verified_registration_panel(page, order_kind: str):
    """Return only the visible upload modal whose seller matches the requested route."""
    panel_config = REGISTRATION_PANELS.get(order_kind)
    if not panel_config:
        raise ValueError(f"지원하지 않는 위킵 주문 유형입니다: {order_kind}")
    panel_selector, expected_seller = panel_config
    panel = page.locator(panel_selector)
    if panel.count() != 1 or not panel.is_visible():
        raise RuntimeError("선택한 판매처의 위킵 엑셀 등록 화면을 확인하지 못했습니다.")
    if expected_seller not in panel.inner_text():
        raise RuntimeError(
            f"위킵 등록 화면의 판매처가 일치하지 않습니다. 전송 대상: {expected_seller}"
        )
    return panel


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
    verified_registration_panel(page, order_kind)
    if upload_path:
        path = Path(upload_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"위킵 업로드 파일을 찾을 수 없습니다: {path}")
        page.locator(file_selector).set_input_files(str(path))
        page.wait_for_timeout(300)


def ensure_authenticated(page, user_id: str, password: str) -> None:
    """Reuse the saved session, or log in with encrypted integration credentials."""
    if "/order/" in page.url:
        return
    if not str(user_id).strip() or not password:
        raise RuntimeError("연동 계정에서 위킵 아이디와 비밀번호를 저장해 주세요.")
    username = page.locator('input[name="j_username"]')
    password_field = page.locator('input[name="j_password"]')
    if not username.is_visible() or not password_field.is_visible():
        raise RuntimeError("위킵 로그인 화면을 확인할 수 없습니다. 사이트 화면이 변경됐을 수 있습니다.")
    username.fill(str(user_id).strip())
    password_field.fill(password)
    remember = page.locator("#_spring_security_remember_me")
    if remember.count() == 1:
        remember.check()
    page.locator('input[type="submit"][value="시작하기"]').click()
    page.wait_for_timeout(1_000)
    page.goto(ORDER_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
    if "/order/list.do" not in page.url:
        raise RuntimeError("위킵 자동 로그인에 실패했습니다. 계정 정보 또는 추가 인증을 확인해 주세요.")


def submit_registration(page, order_kind: str, *, on_submitted=None) -> dict:
    """Click the exact final button and classify only an explicit response as success."""
    panel = verified_registration_panel(page, order_kind)
    button = panel.get_by_role("button", name="저장", exact=True)
    if button.count() != 1 or not button.is_visible() or not button.is_enabled():
        raise RuntimeError(
            "선택한 판매처의 엑셀 등록 화면에서 저장 버튼을 정확히 확인하지 못했습니다. 전송을 중단합니다."
        )
    dialog_messages: list[str] = []
    if hasattr(page, "on"):
        def handle_dialog(dialog) -> None:
            dialog_messages.append(str(dialog.message))
            dialog.accept()
        page.on("dialog", handle_dialog)
    if on_submitted:
        on_submitted()
    button.click()
    page.wait_for_timeout(1_500)
    body_text = page.locator("body").inner_text()
    response_text = "\n".join([body_text, *dialog_messages])
    if any(marker in response_text for marker in FAILURE_MARKERS):
        raise RuntimeError("위킵이 주문 등록 실패를 반환했습니다. " + " / ".join(dialog_messages))
    if any(marker in response_text for marker in SUCCESS_MARKERS):
        reference_match = re.search(r"(?:주문|접수)번호\s*[:：]?\s*([A-Za-z0-9_-]+)", response_text)
        return {"state": "completed", "provider_reference": reference_match.group(1) if reference_match else ""}
    return {"state": "unknown", "provider_reference": "", "message": " / ".join(dialog_messages)}


def verify_registered_orders(page, rows: list[dict], order_kind: str) -> bool:
    """Confirm an uncertain submission by finding every order on today's seller list."""
    from wekeep_tracking_service import SALE_CHANNELS, collect_tracking_rows

    lookup_kind = "b2b" if order_kind == "b2b_buying" else order_kind
    sale_channel = SALE_CHANNELS.get(lookup_kind)
    if not sale_channel:
        return False
    remote_rows = collect_tracking_rows(page, date.today(), sale_channel)
    expected = {re.sub(r"\W", "", str(row.get("order_number") or "")).casefold() for row in rows}
    found = {re.sub(r"\W", "", str(row.get("order_number") or "")).casefold() for row in remote_rows}
    expected.discard("")
    return bool(expected) and expected.issubset(found)


def run_wekeep_job(job_id: str, db_path: str | Path | None = None) -> dict:
    """Submit an approved job headlessly and persist every safety-relevant state."""
    from playwright.sync_api import sync_playwright

    store = ShipmentJobStore(db_path) if db_path is not None else ShipmentJobStore()
    job = store.get(job_id, include_payload=True)
    rows = job["payload"]["rows"]
    upload_path = OUTPUT_DIR / f"wekeep_{job_id}.xlsx"
    submitted = False
    try:
        create_wekeep_upload(rows, job["order_kind"], upload_path)
        store.transition(job_id, "submitting", detail="위킵 백그라운드 전송 시작", upload_path=upload_path)
        credentials = load_integration_credentials()
        PROFILE_PATH.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = launch_wekeep_context(playwright, headless=True)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(ORDER_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
                ensure_authenticated(page, credentials.get("wekeep_user_id", ""), credentials.get("wekeep_password", ""))
                open_registration_panel(page, job["order_kind"], upload_path)

                def mark_submitted() -> None:
                    nonlocal submitted
                    submitted = True
                    store.transition(job_id, "verifying", detail="위킵 최종 등록 버튼 클릭")

                result = submit_registration(page, job["order_kind"], on_submitted=mark_submitted)
                if result["state"] != "completed":
                    try:
                        if verify_registered_orders(page, rows, job["order_kind"]):
                            result = {"state": "completed", "provider_reference": ""}
                    except Exception:
                        pass
            finally:
                context.close()
        if result["state"] == "completed":
            return store.transition(
                job_id, "completed", detail="위킵 성공 응답 확인",
                provider_reference=result.get("provider_reference", ""),
            )
        detail = "등록 요청 후 주문 목록에서 결과를 확인하지 못함"
        if result.get("message"):
            detail += " · 위킵 알림: " + result["message"]
        return store.transition(job_id, "unknown", detail=detail)
    except Exception as exc:
        current = store.get(job_id)
        target = "unknown" if submitted or current["state"] == "verifying" else "failed"
        if target in ALLOWED_TRANSITIONS.get(current["state"], set()):
            store.transition(job_id, target, error=str(exc))
        raise


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
