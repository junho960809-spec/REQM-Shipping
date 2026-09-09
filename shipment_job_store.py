"""Durable local state for outbound shipment submissions."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ecount_credential_store import protect_secret, unprotect_secret
from shipment_domain import shipment_idempotency_key


DEFAULT_DB_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "shipment_jobs.sqlite3"
BLOCKING_STATES = {"approved", "submitting", "verifying", "completed", "unknown"}
ALLOWED_TRANSITIONS = {
    "approved": {"submitting", "failed"},
    "submitting": {"verifying", "completed", "failed", "unknown"},
    "verifying": {"completed", "failed", "unknown"},
    "failed": {"approved"},
    "unknown": {"completed", "failed"},
    "completed": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ShipmentJobStore:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS shipment_jobs (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    order_kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_encrypted TEXT NOT NULL,
                    upload_path TEXT NOT NULL DEFAULT '',
                    provider_reference TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS shipment_jobs_idempotency_idx
                    ON shipment_jobs(idempotency_key, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS shipment_jobs_one_active_submission_idx
                    ON shipment_jobs(idempotency_key)
                    WHERE state IN ('approved', 'submitting', 'verifying', 'completed', 'unknown');
                CREATE TABLE IF NOT EXISTS shipment_job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES shipment_jobs(id),
                    state TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )

    def create(self, rows: list[dict], order_kind: str, *, provider: str = "wekeep") -> dict:
        key = shipment_idempotency_key(rows, order_kind, provider)
        existing = self.find_blocking(key)
        if existing:
            raise ValueError(
                f"동일한 출고 작업이 이미 존재합니다. 상태: {existing['state']} · 작업 ID: {existing['id']}"
            )
        job_id = str(uuid.uuid4())
        timestamp = _now()
        encrypted = protect_secret(json.dumps({"rows": rows}, ensure_ascii=False))
        try:
            with self._session() as connection:
                connection.execute(
                    """INSERT INTO shipment_jobs
                       (id, provider, order_kind, state, idempotency_key, payload_encrypted, created_at, updated_at)
                       VALUES (?, ?, ?, 'approved', ?, ?, ?, ?)""",
                    (job_id, provider, order_kind, key, encrypted, timestamp, timestamp),
                )
                connection.execute(
                    "INSERT INTO shipment_job_events(job_id, state, detail, created_at) VALUES (?, 'approved', ?, ?)",
                    (job_id, "작업자 승인", timestamp),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("동일한 출고 작업이 동시에 생성되어 중복 실행을 차단했습니다.") from exc
        return self.get(job_id)

    def get(self, job_id: str, *, include_payload: bool = False) -> dict:
        with self._session() as connection:
            row = connection.execute("SELECT * FROM shipment_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"출고 작업을 찾을 수 없습니다: {job_id}")
        result = dict(row)
        if include_payload:
            result["payload"] = json.loads(unprotect_secret(result.pop("payload_encrypted")))
        else:
            result.pop("payload_encrypted", None)
        return result

    def find_blocking(self, idempotency_key: str) -> dict | None:
        placeholders = ",".join("?" for _ in BLOCKING_STATES)
        with self._session() as connection:
            row = connection.execute(
                f"SELECT * FROM shipment_jobs WHERE idempotency_key = ? AND state IN ({placeholders}) "
                "ORDER BY updated_at DESC LIMIT 1",
                (idempotency_key, *sorted(BLOCKING_STATES)),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop("payload_encrypted", None)
        return result

    def transition(
        self, job_id: str, state: str, *, detail: str = "", upload_path: str | Path | None = None,
        provider_reference: str = "", error: str = "",
    ) -> dict:
        current = self.get(job_id)
        if state not in ALLOWED_TRANSITIONS.get(current["state"], set()):
            raise ValueError(f"허용되지 않는 출고 상태 변경입니다: {current['state']} → {state}")
        timestamp = _now()
        next_upload = str(upload_path) if upload_path is not None else current["upload_path"]
        with self._session() as connection:
            updated = connection.execute(
                """UPDATE shipment_jobs SET state = ?, upload_path = ?, provider_reference = ?, error = ?, updated_at = ?
                   WHERE id = ? AND state = ?""",
                (state, next_upload, provider_reference, error, timestamp, job_id, current["state"]),
            )
            if updated.rowcount != 1:
                raise RuntimeError("다른 작업이 출고 상태를 먼저 변경했습니다.")
            connection.execute(
                "INSERT INTO shipment_job_events(job_id, state, detail, created_at) VALUES (?, ?, ?, ?)",
                (job_id, state, detail or error, timestamp),
            )
        return self.get(job_id)
