from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


BOARD_ROOT = "http://orora.ipdisk.co.kr:8000/apache/gnuboard5/bbs/board.php"
BOARD_SOURCES = (
    ("신규 접수", "Sian"),
    ("인쇄 진행", "Order"),
    ("패킹 진행", "List"),
    ("출고 대기", "LIST2"),
)
CHROME_PATHS = (
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[dict[str, str]]] = []
        self._row: list[dict[str, str]] | None = None
        self._cell: dict[str, str] | None = None
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        attributes = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("th", "td") and self._row is not None:
            self._cell = {"text": "", "href": ""}
            self._cell_parts = []
        elif tag == "a" and self._cell is not None and attributes.get("href"):
            self._cell["href"] = html.unescape(attributes["href"])

    def handle_data(self, data: str):
        if self._cell is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag in ("th", "td") and self._cell is not None and self._row is not None:
            self._cell["text"] = re.sub(r"\s+", " ", " ".join(self._cell_parts)).strip()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def parse_board_html(source: str, status: str, board_url: str) -> list[dict[str, str]]:
    parser = _TableParser()
    parser.feed(source)
    result: list[dict[str, str]] = []
    for cells in parser.rows:
        values = [cell["text"] for cell in cells]
        if not values or values[0] == "번호" or "게시물이 없습니다" in values[0]:
            continue
        # 게시판 행: 번호, 제목, 상호, 등록일, 인쇄내용, 젠더, 포장, 수량,
        # 출고요청일, 배송구분, 작성자. 끝의 관리용 빈 셀은 무시한다.
        if len(values) < 11 or not values[0].isdigit():
            continue
        detail_href = next((cell["href"] for cell in cells if "wr_id=" in cell["href"]), "")
        result.append({
            "status": status,
            "customer": values[2] or values[1],
            "product": values[4],
            "quantity": values[7],
            "request_date": values[8],
            "print_pack": f"인쇄 · {values[6]}",
            "registered_at": values[3],
            "url": urljoin(board_url, detail_href),
        })
    return result


def _page_numbers(source: str) -> list[int]:
    pages = {1}
    for value in re.findall(r"[?&](?:amp;)?page=(\d+)", source):
        pages.add(int(value))
    return sorted(page for page in pages if page <= 100)


def fetch_active_orders(credentials: dict[str, str]) -> list[dict[str, str]]:
    if not credentials.get("user_id") or not credentials.get("password"):
        raise RuntimeError("연동 계정 관리에서 인쇄 게시판 아이디와 비밀번호를 저장하세요.")
    chrome = next((path for path in CHROME_PATHS if path.exists()), None)
    if chrome is None:
        raise RuntimeError("Google Chrome을 찾지 못했습니다.")

    rows: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
        try:
            page = browser.new_page()
            login_url = f"{BOARD_ROOT}?bo_table=Order"
            page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)
            if page.locator("#login_id").count():
                page.locator("#login_id").fill(credentials["user_id"])
                page.locator("#login_pw").fill(credentials["password"])
                page.locator('input[type="submit"]').click()
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
            if page.locator("#login_id").count():
                raise RuntimeError("인쇄 게시판 로그인에 실패했습니다. 저장된 계정을 확인하세요.")

            for status, board_name in BOARD_SOURCES:
                board_url = f"{BOARD_ROOT}?bo_table={board_name}"
                first_source = page.request.get(board_url).body().decode("utf-8", errors="replace")
                rows.extend(parse_board_html(first_source, status, board_url))
                for page_number in _page_numbers(first_source):
                    if page_number == 1:
                        continue
                    page_url = f"{board_url}&page={page_number}"
                    source = page.request.get(page_url).body().decode("utf-8", errors="replace")
                    rows.extend(parse_board_html(source, status, page_url))
        finally:
            browser.close()
    return rows


def status_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return {status: sum(row.get("status") == status for row in rows) for status, _ in BOARD_SOURCES}
