"""REQM.exe를 자동 업데이트용 청크와 manifest.json으로 묶는다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CHUNK_SIZE = 20 * 1024 * 1024


def build_release(executable: Path, output: Path, version: str, notes: str) -> Path:
    if not executable.is_file():
        raise FileNotFoundError(executable)
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob(f"REQM_{version}.exe.part*"):
        old.unlink()
    digest = hashlib.sha256()
    chunks: list[str] = []
    with executable.open("rb") as source:
        index = 1
        while block := source.read(CHUNK_SIZE):
            digest.update(block)
            name = f"REQM_{version}.exe.part{index:03d}"
            (output / name).write_bytes(block)
            chunks.append(name)
            index += 1
    manifest = {
        "version": version,
        "file": "REQM.exe",
        "sha256": digest.hexdigest(),
        "size": executable.stat().st_size,
        "chunks": chunks,
        "notes": notes,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("version")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    print(build_release(args.executable, args.output, args.version, args.notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
