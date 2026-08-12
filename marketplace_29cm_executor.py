"""REQM_CS Chrome 프로필로 29CM 옵션 재고를 변경한다."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


CHROME_PATHS = (
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
)


def _chrome_path() -> str:
    chrome = next((path for path in CHROME_PATHS if path.exists()), None)
    if chrome is None:
        raise RuntimeError("Google Chrome을 찾지 못했습니다.")
    return str(chrome)


def execute_29cm_action(action: dict[str, str], profile_path: str) -> dict[str, str]:
    """옵션을 품절(재고 0) 또는 지정 수량으로 판매 재개하고 결과를 반환한다."""
    profile = Path(profile_path)
    if not profile.is_dir():
        raise RuntimeError("29CM Chrome 프로필 폴더를 찾지 못했습니다.")
    target_stock = int(str(action.get("target_stock", "0")))
    if action.get("action") == "SOLD_OUT":
        target_stock = 0
    if target_stock < 0:
        raise RuntimeError("재고 수량은 0 이상이어야 합니다.")

    item_no = str(action.get("marketplace_item_no", "")).strip()
    option_no = str(action.get("marketplace_option_no", "")).strip()
    if not item_no or not option_no:
        raise RuntimeError("29CM 상품번호와 옵션번호가 필요합니다.")

    # Chrome은 Profile N 폴더의 부모(User Data)를 user_data_dir로 사용한다.
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile.parent),
                executable_path=_chrome_path(),
                headless=False,
                args=[f"--profile-directory={profile.name}"],
            )
        except Exception as error:
            raise RuntimeError(
                "REQM_CS Chrome 프로필을 열지 못했습니다. 해당 프로필로 열린 Chrome 창을 모두 닫은 뒤 다시 실행해 주세요."
            ) from error
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(f"https://partner-item.29cm.co.kr/{item_no}?from=option-stock", wait_until="domcontentloaded", timeout=60_000)
            if "login" in page.url.lower():
                raise RuntimeError("29CM 로그인이 필요합니다. REQM_CS 프로필에서 다시 로그인해 주세요.")
            row = page.locator("tr").filter(has_text=option_no)
            if row.count() != 1:
                raise RuntimeError(f"29CM 옵션번호 {option_no}를 정확히 하나 찾지 못했습니다.")
            inputs = row.locator("input")
            if inputs.count() < 2:
                raise RuntimeError("29CM 옵션 재고 입력칸을 찾지 못했습니다.")
            previous_stock = inputs.nth(1).input_value()
            inputs.nth(1).fill(str(target_stock))
            page.get_by_role("button", name="수정 완료", exact=True).click()
            page.get_by_text("상품이 수정 되었습니다.", exact=True).wait_for(timeout=15_000)
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            verified_row = page.locator("tr").filter(has_text=option_no)
            verified_inputs = verified_row.locator("input")
            actual_stock = verified_inputs.nth(1).input_value()
            expected_status = "일시품절" if target_stock == 0 else "판매중"
            if actual_stock != str(target_stock) or not verified_row.get_by_text(expected_status, exact=True).is_visible():
                raise RuntimeError("29CM 변경 후 재고 또는 판매 상태 검증에 실패했습니다.")
            return {
                "previous_stock": previous_stock,
                "target_stock": str(target_stock),
                "verified_status": expected_status,
            }
        finally:
            context.close()
