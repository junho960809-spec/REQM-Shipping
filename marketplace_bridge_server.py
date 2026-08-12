"""REQM 데스크톱 앱과 로그인된 Chrome 확장 프로그램을 연결하는 로컬 브리지."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from marketplace_catalog_store import save_catalog_options
from marketplace_option_store import complete_option_action


class MarketplaceBridge:
    def __init__(self) -> None:
        self.sync_requested = False
        self.last_catalog_count = 0
        self.pending_action: dict | None = None
        self._server: ThreadingHTTPServer | None = None

    def request_29cm_sync(self) -> None:
        self.sync_requested = True

    def queue_29cm_action(self, action: dict) -> None:
        self.pending_action = dict(action)

    def start(self) -> None:
        if self._server is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, payload: dict) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                if self.path == "/health":
                    self._reply(200, {"ok": True})
                elif self.path == "/api/29cm/sync-request":
                    self._reply(200, {"requested": bridge.sync_requested})
                elif self.path == "/api/29cm/pending-action":
                    action = bridge.pending_action
                    bridge.pending_action = None
                    self._reply(200, {"action": action})
                else:
                    self._reply(404, {"error": "not_found"})

            def do_POST(self):
                if self.path != "/api/29cm/catalog":
                    if self.path == "/api/29cm/action-result":
                        try:
                            length = int(self.headers.get("Content-Length", "0"))
                            payload = json.loads(self.rfile.read(length).decode("utf-8"))
                            complete_option_action(
                                str(payload["action_id"]), str(payload["status"]), "REQM_CS Chrome 확장",
                                str(payload.get("error_message", "")), dict(payload.get("details", {})),
                            )
                            self._reply(200, {"ok": True})
                        except (KeyError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                            self._reply(400, {"error": "invalid_action_result"})
                        return
                    self._reply(404, {"error": "not_found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    rows = payload.get("rows", [])
                    if not isinstance(rows, list):
                        raise ValueError("rows must be a list")
                    saved = save_catalog_options("29CM", rows)
                    bridge.last_catalog_count = len(saved)
                    bridge.sync_requested = False
                    self._reply(200, {"ok": True, "count": len(saved)})
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    self._reply(400, {"error": "invalid_catalog"})

            def log_message(self, _format, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()


bridge = MarketplaceBridge()
