from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


class NaverCommerceError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, trace_id: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.trace_id = trace_id


class NaverCommerceClient:
    BASE_URL = "https://api.commerce.naver.com/external"

    def __init__(self, client_id: str, client_secret: str, *, timeout: int = 20) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("네이버 커머스 API 인증정보가 없습니다.")
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.timeout = timeout
        self._access_token = ""
        self._expires_at = 0.0

    def _signature(self, timestamp: int) -> str:
        try:
            import bcrypt
        except ImportError as exc:
            raise RuntimeError("네이버 API 인증에 필요한 bcrypt 패키지가 설치되지 않았습니다.") from exc
        password = f"{self.client_id}_{timestamp}".encode("utf-8")
        hashed = bcrypt.hashpw(password, self.client_secret.encode("utf-8"))
        return base64.b64encode(hashed).decode("ascii")

    def access_token(self, *, force: bool = False) -> str:
        if not force and self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        timestamp = int(time.time() * 1000)
        body = urllib.parse.urlencode({
            "client_id": self.client_id,
            "timestamp": timestamp,
            "client_secret_sign": self._signature(timestamp),
            "grant_type": "client_credentials",
            "type": "SELF",
        }).encode("utf-8")
        payload = self._request_json("POST", "/v1/oauth2/token", body=body, authenticated=False,
                                     content_type="application/x-www-form-urlencoded")
        token = str(payload.get("access_token") or "")
        if not token:
            raise NaverCommerceError("네이버 인증 응답에 액세스 토큰이 없습니다.")
        self._access_token = token
        self._expires_at = time.time() + int(payload.get("expires_in") or 1800)
        return token

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict | None = None,
        json_body: dict | None = None,
        body: bytes | None = None,
        authenticated: bool = True,
        content_type: str = "application/json",
        retry_auth: bool = True,
    ):
        url = f"{self.BASE_URL}{path}"
        if query:
            values = {key: str(value).lower() if isinstance(value, bool) else value for key, value in query.items() if value is not None}
            url += "?" + urllib.parse.urlencode(values)
        headers = {"Accept": "application/json", "Content-Type": content_type}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.access_token()}"
        request_body = json.dumps(json_body, ensure_ascii=False).encode("utf-8") if json_body is not None else body
        request = urllib.request.Request(url, data=request_body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                error = json.loads(raw)
            except ValueError:
                error = {}
            if authenticated and retry_auth and exc.code == 401 and error.get("code") == "GW.AUTHN":
                self.access_token(force=True)
                return self._request_json(method, path, query=query, json_body=json_body, body=body,
                                          authenticated=True, content_type=content_type, retry_auth=False)
            trace_id = str(exc.headers.get("GNCP-GW-Trace-ID") or "")
            message = str(error.get("message") or raw or f"HTTP {exc.code}")
            raise NaverCommerceError(message, status=exc.code, trace_id=trace_id) from exc

    @staticmethod
    def qna_search_period(days: int = 30) -> tuple[str, str]:
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat(timespec="milliseconds"), now.isoformat(timespec="milliseconds")

    def product_qnas(
        self,
        *,
        answered: bool = False,
        page: int = 1,
        size: int = 100,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        default_from, default_to = self.qna_search_period()
        payload = self._request_json("GET", "/v1/contents/qnas", query={
            "fromDate": from_date or default_from,
            "toDate": to_date or default_to,
            "answered": answered,
            "page": page,
            "size": size,
        })
        if isinstance(payload, list):
            return payload
        for key in ("contents", "content", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []

    def customer_inquiries(
        self,
        *,
        start_date: str,
        end_date: str,
        answered: bool = False,
        page: int = 1,
        size: int = 100,
    ) -> list[dict]:
        payload = self._request_json("GET", "/v1/pay-user/inquiries", query={
            "startSearchDate": start_date,
            "endSearchDate": end_date,
            "answered": answered,
            "page": page,
            "size": size,
        })
        return list(payload.get("content") or []) if isinstance(payload, dict) else []

    def answer_product_qna(self, question_id: int | str, answer: str) -> None:
        if not answer.strip():
            raise ValueError("전송할 답변이 비어 있습니다.")
        self._request_json("PUT", f"/v1/contents/qnas/{question_id}", json_body={"commentContent": answer.strip()})
