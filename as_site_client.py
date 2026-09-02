from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ecount_credential_store import protect_secret, unprotect_secret


BASE_URL = "https://reqm.co.kr"
LOGIN_URL = f"{BASE_URL}/admin/index.php"
LIST_URL = f"{BASE_URL}/admin/content/passivedata1.list.php"
CREDENTIAL_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "as_site_credentials.json"


def cache_bust_url(url: str) -> str:
    """Return a URL that intermediaries cannot reuse for a previous AS response."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_reqm_ts"] = uuid.uuid4().hex
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode"] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)

    def text(self) -> str:
        values = list(self.chunks)
        for child in self.children:
            values.append(child.text())
        return " ".join(" ".join(values).split())

    def find_all(self, tag: str) -> list["HtmlNode"]:
        rows = [self] if self.tag == tag else []
        for child in self.children:
            rows.extend(child.find_all(tag))
        return rows


class MiniDomParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs) -> None:
        node = HtmlNode(tag.casefold(), {str(k): str(v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag.casefold() not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag) -> None:
        wanted = tag.casefold()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == wanted:
                del self.stack[index:]
                return

    def handle_data(self, data) -> None:
        value = str(data or "").strip()
        if value:
            self.stack[-1].chunks.append(value)


def parse_html(source: str) -> HtmlNode:
    parser = MiniDomParser()
    parser.feed(source)
    return parser.root


def save_as_credentials(user_id: str, password: str, path: Path = CREDENTIAL_PATH) -> None:
    user_id = str(user_id or "").strip()
    password = str(password or "")
    if not user_id or not password:
        raise ValueError("AS 사이트 아이디와 비밀번호를 입력하세요.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"user_id": user_id, "password": protect_secret(password)}, ensure_ascii=False), encoding="utf-8")


def load_as_credentials(path: Path = CREDENTIAL_PATH) -> tuple[str, str]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        return str(row.get("user_id", "")), unprotect_secret(str(row.get("password", "")))
    except (OSError, ValueError, TypeError):
        return "", ""


class AsSiteClient:
    def __init__(self, user_id: str, password: str) -> None:
        self.user_id = str(user_id or "").strip()
        self.password = str(password or "")
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def _open(self, url: str, data: dict | None = None) -> str:
        payload = urlencode(data).encode("utf-8") if data is not None else None
        target = url if data is not None else cache_bust_url(url)
        request = Request(target, data=payload, headers={
            "User-Agent": "REQM-AS-Daily/1.0",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        })
        with self.opener.open(request, timeout=25) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

    def login(self) -> None:
        if not self.user_id or not self.password:
            raise RuntimeError("AS 사이트 계정 설정이 필요합니다.")
        page = self._open(LOGIN_URL, {"userlevel": "100", "userid": self.user_id, "passwd": self.password})
        if "login_chk" in page or "admin-login-btn" in page or 'name="userid"' in page:
            raise RuntimeError("AS 사이트 로그인에 실패했습니다. 계정 정보를 확인하세요.")

    @staticmethod
    def _row_cells(row: HtmlNode) -> list[HtmlNode]:
        return [child for child in row.children if child.tag in {"td", "th"}]

    def fetch_records(self, start_date: str, end_date: str, receipt_type: str = "", status: str = "") -> list[dict]:
        query = {"limit": "5000", "start_date": start_date, "end_date": end_date}
        if receipt_type:
            query["type"] = receipt_type
        if status:
            query["status_no"] = status
        root = parse_html(self._open(f"{LIST_URL}?{urlencode(query)}"))
        rows: list[dict] = []
        for tr in root.find_all("tr"):
            links = tr.find_all("a")
            detail = next((a.attrs.get("href", "") for a in links if "passivedata1.view.php?cs_no=" in a.attrs.get("href", "")), "")
            cells = self._row_cells(tr)
            if not detail or len(cells) < 11:
                continue
            values = [cell.text() for cell in cells]
            record = {
                "detail_url": urljoin(LIST_URL, detail),
                "receipt_date": values[2] if len(values) > 2 else "",
                "type": values[3] if len(values) > 3 else "",
                "purchase_place": values[4] if len(values) > 4 else "",
                "purchase_date": values[5] if len(values) > 5 else "",
                "name": values[6] if len(values) > 6 else "",
                "phone": values[7] if len(values) > 7 else "",
                "product": values[8] if len(values) > 8 else "",
                "quantity": next((n.attrs.get("value", "") for n in cells[9].find_all("input") if n.attrs.get("type") == "number"), "0"),
                "reason": values[10] if len(values) > 10 else "",
                "status": values[11] if len(values) > 11 else "",
                "processing": values[12] if len(values) > 12 else "",
                "invoice": values[14] if len(values) > 14 else "",
                "memo": values[15] if len(values) > 15 else "",
            }
            rows.append(record)
        if rows:
            # 상세 페이지는 서로 독립적이므로 제한된 동시 요청으로 일일 조회 시간을 줄인다.
            # 작업자 수를 작게 유지해 AS 사이트에 과도한 부하를 주지 않는다.
            with ThreadPoolExecutor(max_workers=min(6, len(rows))) as executor:
                list(executor.map(self._add_detail, rows))
        return rows

    def _add_detail(self, record: dict) -> None:
        root = parse_html(self._open(record["detail_url"]))
        labelled: dict[str, HtmlNode] = {}
        for tr in root.find_all("tr"):
            cells = self._row_cells(tr)
            if len(cells) == 2:
                label = cells[0].text()
                if label:
                    labelled.setdefault(label, cells[1])

        def field(name: str) -> str:
            for node in root.find_all("input") + root.find_all("textarea"):
                if node.attrs.get("name") == name:
                    return node.attrs.get("value", "") or node.text()
            return ""

        def selected(name: str) -> str:
            for select in root.find_all("select"):
                if select.attrs.get("name") == name:
                    option = next((o for o in select.find_all("option") if "selected" in o.attrs), None)
                    return option.text() if option else ""
            return ""

        record.update({
            "postcode": field("postcode"),
            "address": " ".join(part for part in (field("address"), field("address_detail")) if part).strip(),
            "manufacture": field("date_of_manufacture"),
            "processing": field("admin_comment") or record.get("processing", ""),
            "memo": field("memo") or record.get("memo", ""),
            "purchase_place": selected("buy_category_no") or record.get("purchase_place", ""),
            "product": labelled.get("제품명", HtmlNode("td")).text() or record.get("product", ""),
            "color": labelled.get("컬러", HtmlNode("td")).text(),
            "reason": labelled.get("불량유형", HtmlNode("td")).text() or record.get("reason", ""),
        })
