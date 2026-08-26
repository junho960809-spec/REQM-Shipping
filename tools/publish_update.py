"""REQM 자동 업데이트 파일을 Supabase Storage에 안전하게 배포한다.

새 실행 파일 청크와 manifest를 모두 올리고 공개 manifest 검증까지 끝난 뒤에만
이전 버전의 `REQM_*.exe.part*` 파일을 삭제한다.

사용 예:
  set SUPABASE_SERVICE_ROLE_KEY=...
  python tools/publish_update.py C:\\release\\reqm-shipping-update-1.0.49
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


SUPABASE_URL = os.getenv("SUPABASE_URL", "https://jcslohuraqclhryeqxoc.supabase.co").rstrip("/")
BUCKET = "reqm-updates"


def request(path: str, key: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    request_headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    request_headers.update(headers or {})
    request = urllib.request.Request(f"{SUPABASE_URL}{path}", data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def load_release(folder: Path) -> tuple[dict, list[Path]]:
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    chunks = [folder / str(name) for name in manifest.get("chunks", [])]
    if not manifest.get("version") or not chunks or any(not chunk.is_file() for chunk in chunks):
        raise ValueError("manifest.json과 모든 업데이트 청크가 필요합니다.")
    return manifest, chunks


def list_bucket_files(key: str) -> list[str]:
    body = json.dumps({"prefix": "", "limit": 1000, "offset": 0, "sortBy": {"column": "name", "order": "asc"}}).encode()
    response = request(
        f"/storage/v1/object/list/{BUCKET}", key, method="POST", data=body,
        headers={"Content-Type": "application/json"},
    )
    return [str(row.get("name", "")) for row in json.loads(response) if isinstance(row, dict)]


def upload_file(path: Path, key: str) -> None:
    content_type = "application/json" if path.name == "manifest.json" else "application/octet-stream"
    request(
        f"/storage/v1/object/{BUCKET}/{path.name}", key, method="POST", data=path.read_bytes(),
        headers={"Content-Type": content_type, "x-upsert": "true"},
    )


def delete_files(names: list[str], key: str) -> None:
    if not names:
        return
    request(
        f"/storage/v1/object/{BUCKET}", key, method="DELETE",
        data=json.dumps({"prefixes": names}).encode(), headers={"Content-Type": "application/json"},
    )


def publish(folder: Path, key: str) -> list[str]:
    manifest, chunks = load_release(folder)
    existing = list_bucket_files(key)

    # 먼저 새 청크를 모두 올리고 manifest를 마지막에 교체한다. 이 순서면 사용자가
    # 새 manifest를 받는 시점에는 참조 파일이 이미 존재한다.
    for chunk in chunks:
        upload_file(chunk, key)
    upload_file(folder / "manifest.json", key)

    published_manifest = json.loads(
        request(f"/storage/v1/object/public/{BUCKET}/manifest.json?cache={time.time_ns()}", key)
    )
    if published_manifest.get("version") != manifest["version"] or published_manifest.get("chunks") != manifest["chunks"]:
        raise ValueError("공개 manifest 검증에 실패해 이전 파일을 삭제하지 않았습니다.")

    current_chunks = {chunk.name for chunk in chunks}
    old_chunks = [
        name for name in existing
        if name.startswith("REQM_") and ".exe.part" in name and name not in current_chunks
    ]
    delete_files(old_chunks, key)
    return old_chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="REQM 업데이트를 배포하고 이전 EXE 청크를 정리합니다.")
    parser.add_argument("release_folder", type=Path)
    args = parser.parse_args()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        print("SUPABASE_SERVICE_ROLE_KEY 환경 변수가 필요합니다.", file=sys.stderr)
        return 2
    try:
        deleted = publish(args.release_folder, key)
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError) as error:
        print(f"배포 실패: {error}", file=sys.stderr)
        return 1
    print(f"배포 완료 · 이전 EXE 청크 {len(deleted)}개 삭제")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
