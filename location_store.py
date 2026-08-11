from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import uuid


FIELDS = ("id", "name", "channel", "recipient", "phone", "zipcode", "address", "message")


def location_file() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "REQM"
    return base / "duty_free_locations.json"


def load_locations() -> list[dict[str, str]]:
    path = location_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [
            {key: str(row.get(key, "") or "").strip() for key in FIELDS}
            for row in data
            if isinstance(row, dict) and row.get("name")
        ]
    except (OSError, ValueError, TypeError):
        return []


def save_locations(locations: list[dict[str, Any]]) -> None:
    path = location_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [
        {key: str(row.get(key, "") or "").strip() for key in FIELDS}
        for row in locations
        if row.get("name")
    ]
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def remote_to_local(row: dict[str, Any]) -> dict[str, str] | None:
    active = row.get("is_active", True)
    if str(active).strip().lower() in {"false", "0", "no"}:
        return None
    address = str(row.get("address", "") or "").strip()
    if not address:
        return None
    channel = str(row.get("duty_free_name") or row.get("channel") or "면세점").strip()
    store_name = str(row.get("store_name") or "").strip()
    name = " ".join(part for part in (channel, store_name) if part and part != "미등록")
    return {
        "id": str(row.get("location_id") or row.get("id") or uuid.uuid4()),
        "name": name or channel,
        "channel": channel,
        "recipient": str(row.get("recipient", "") or "").strip(),
        "phone": str(row.get("phone", "") or "").strip(),
        "zipcode": str(row.get("postal_code") or row.get("zipcode") or "").strip(),
        "address": address,
        "message": str(row.get("message", "") or "").strip(),
    }


def merge_remote_locations(
    local_locations: list[dict[str, Any]], remote_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, str]], int]:
    merged = [
        {key: str(row.get(key, "") or "").strip() for key in FIELDS}
        for row in local_locations
        if row.get("name")
    ]
    added = 0
    for remote_row in remote_rows:
        remote = remote_to_local(remote_row)
        if not remote:
            continue
        remote_name = remote["name"].casefold()
        remote_address = "".join(remote["address"].split()).casefold()
        index = next(
            (
                i for i, local in enumerate(merged)
                if local.get("name", "").casefold() == remote_name
                or (
                    remote_address
                    and "".join(local.get("address", "").split()).casefold() == remote_address
                )
            ),
            -1,
        )
        if index < 0:
            merged.append(remote)
            added += 1
            continue
        existing = merged[index]
        combined = dict(remote)
        combined.update({key: value for key, value in existing.items() if value})
        combined["id"] = remote["id"]
        merged[index] = combined
    return merged, added


def sync_remote_locations(remote_rows: list[dict[str, Any]]) -> tuple[list[dict[str, str]], int]:
    merged, added = merge_remote_locations(load_locations(), remote_rows)
    save_locations(merged)
    return merged, added


def local_to_remote(row: dict[str, Any], active: bool = True) -> dict[str, Any]:
    channel = str(row.get("channel", "") or "면세점").strip()
    name = str(row.get("name", "") or channel).strip()
    store_name = name
    if channel and name.casefold().startswith(channel.casefold()):
        store_name = name[len(channel) :].strip() or name
    return {
        "location_id": str(row.get("id") or uuid.uuid4()),
        "duty_free_name": channel,
        "store_name": store_name,
        "store_code": "",
        "recipient": str(row.get("recipient", "") or "").strip(),
        "phone": str(row.get("phone", "") or "").strip(),
        "postal_code": str(row.get("zipcode", "") or "").strip(),
        "address": str(row.get("address", "") or "").strip(),
        "template_type": "DUTY_FREE_LABEL",
        "is_active": bool(active),
    }

