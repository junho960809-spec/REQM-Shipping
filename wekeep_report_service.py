"""Local WeKeep low-stock reporting configuration and scheduled runner."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REQM_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM"
CONFIG_PATH = REQM_DIR / "wekeep_report.json"
PROFILE_PATH = REQM_DIR / "wekeep-chrome-profile"
REPORT_DIR = REQM_DIR / "reports"
TASK_NAME = "REQM 위킵 재고 보고"
INVENTORY_URL = "https://fbw.wekeep.co.kr/fbw/admin/v2/inventory/search.do"

def normalize_schedule_time(value: str | None) -> str:
    try:
        return datetime.strptime(str(value or "09:00"), "%H:%M").strftime("%H:%M")
    except ValueError:
        return "09:00"


def load_config() -> dict:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value.setdefault("selected_items", [])
            value["schedule_time"] = normalize_schedule_time(value.get("schedule_time"))
            return value
    except (OSError, ValueError):
        pass
    return {"selected_items": [], "schedule_time": "09:00"}

def save_config(selected_items: list[dict], schedule_time: str | None = None) -> None:
    REQM_DIR.mkdir(parents=True, exist_ok=True)
    clean, seen = [], set()
    for row in selected_items:
        item_code = str(row.get("item_code") or "").strip()
        wekeep_code = str(row.get("wekeep_code") or item_code).strip()
        if not item_code or not wekeep_code or item_code.casefold() in seen:
            continue
        seen.add(item_code.casefold())
        clean.append({"item_code": item_code, "item_name": str(row.get("item_name") or "").strip(), "wekeep_code": wekeep_code, "threshold": max(0, int(row.get("threshold") or 0))})
    saved_time = normalize_schedule_time(schedule_time if schedule_time is not None else load_config().get("schedule_time"))
    CONFIG_PATH.write_text(json.dumps({"selected_items": clean, "schedule_time": saved_time}, ensure_ascii=False, indent=2), encoding="utf-8")

def schedule_command(executable: str | Path | None = None, schedule_time: str = "09:00") -> list[str]:
    command = f'"{str(executable or sys.executable)}" --wekeep-report'
    return ["schtasks.exe", "/Create", "/TN", TASK_NAME, "/TR", command, "/SC", "DAILY", "/ST", normalize_schedule_time(schedule_time), "/RU", os.getenv("USERNAME", ""), "/IT", "/RL", "LIMITED", "/F"]

def register_daily_task(schedule_time: str = "09:00") -> None:
    result = subprocess.run(schedule_command(schedule_time=schedule_time), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "작업 스케줄러 등록에 실패했습니다.")

def remove_daily_task() -> None:
    result = subprocess.run(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode and "cannot find" not in (result.stderr + result.stdout).casefold():
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "작업 스케줄러 해제에 실패했습니다.")

def open_login_window() -> None:
    from playwright.sync_api import sync_playwright
    PROFILE_PATH.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(PROFILE_PATH), channel="chrome", headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(INVENTORY_URL, wait_until="domcontentloaded", timeout=60_000)
        try: page.wait_for_event("close", timeout=1_800_000)
        except Exception: pass
        context.close()

def run_report() -> dict:
    from playwright.sync_api import sync_playwright
    selected = {str(row["wekeep_code"]).casefold(): row for row in load_config().get("selected_items", []) if row.get("wekeep_code")}
    if not selected:
        raise RuntimeError("재고 보고에 선택된 품목이 없습니다. 출고 프로그램에서 품목을 선택하세요.")
    PROFILE_PATH.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(PROFILE_PATH), channel="chrome", headless=True)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(INVENTORY_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        if "/inventory/" not in page.url:
            raise RuntimeError("위킵 로그인 상태가 만료되었습니다. 프로그램에서 '위킵 로그인'을 다시 진행하세요.")
        rows = page.evaluate("""() => { const c=v=>String(v||'').replace(/\\s+/g,' ').trim(); const t=[...document.querySelectorAll('table')].find(t=>{const h=[...t.querySelectorAll('th')].map(x=>c(x.textContent));return h.includes('상품관리코드')&&h.includes('가용재고')}); if(!t)throw Error('재고 목록을 찾지 못했습니다.'); const h=[...t.querySelectorAll('th')].map(x=>c(x.textContent)),ci=h.indexOf('상품관리코드'),si=h.indexOf('가용재고'),ni=h.findIndex(x=>x.startsWith('상품명')); return [...t.querySelectorAll('tbody tr')].map(tr=>{const x=[...tr.querySelectorAll('td')].map(td=>c(td.textContent));return {code:x[ci],name:x[ni],stock:Number((x[si]||'').replace(/,/g,''))}}) }""")
        context.close()
    matched = [{**selected[row["code"].casefold()], "available_stock": row["stock"]} for row in rows if row.get("code", "").casefold() in selected and isinstance(row.get("stock"), (int, float))]
    low = [row for row in matched if row["available_stock"] <= row["threshold"]]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"wekeep_low_stock_{datetime.now():%Y%m%d_%H%M}.txt"
    lines = ["위킵 재고 보고", f"조회: {datetime.now():%Y-%m-%d %H:%M}", ""]
    lines += [f"{row['item_name']} · 가용재고 {row['available_stock']}개 (기준 {row['threshold']}개)" for row in low] or ["소량 재고 품목이 없습니다."]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    subprocess.Popen(["notepad.exe", str(report_path)])
    return {"report_path": str(report_path), "selected": len(selected), "matched": len(matched), "low": len(low)}
