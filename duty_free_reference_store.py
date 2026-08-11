import json
import os
from pathlib import Path


REFERENCE_MAPPING_PATH = (
    Path(os.getenv("LOCALAPPDATA", str(Path.home())))
    / "REQM"
    / "duty_free_reference_mappings.json"
)

TEST_MAPPINGS = [
    {"channel": "롯데면세점", "ref_no": "8809477248685", "item_code": "CASE-QP2000C_Hand_La", "product_name": "QP2000C 실리콘케이스 핸디형_라벤더"},
    {"channel": "롯데면세점", "ref_no": "8809477248692", "item_code": "CASE-QP2000C_Hand_Mi", "product_name": "QP2000C 실리콘케이스 핸디형_민트"},
    {"channel": "롯데면세점", "ref_no": "8809477248708", "item_code": "CASE-QP2000C_Hand_Sa", "product_name": "QP2000C 실리콘케이스 핸디형_샌드"},
    {"channel": "롯데면세점", "ref_no": "8809477248715", "item_code": "CASE-QP2000C_Hand_PK", "product_name": "QP2000C 실리콘케이스 핸디형_핑크"},
    {"channel": "롯데면세점", "ref_no": "8809477248814", "item_code": "QP1000C1-Butter", "product_name": "QP1000C 버터"},
]


def save_reference_mappings(rows: list[dict[str, str]]) -> None:
    REFERENCE_MAPPING_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_MAPPING_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_reference_mappings() -> list[dict[str, str]]:
    try:
        data = json.loads(REFERENCE_MAPPING_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(row) for row in data if isinstance(row, dict)]
    except (OSError, ValueError, TypeError):
        pass
    save_reference_mappings(TEST_MAPPINGS)
    return [dict(row) for row in TEST_MAPPINGS]


def find_reference_mapping(channel: str, ref_no: str) -> dict[str, str] | None:
    channel_key = str(channel or "").strip().casefold()
    reference_key = str(ref_no or "").strip().casefold()
    if not reference_key:
        return None
    return next(
        (
            row
            for row in load_reference_mappings()
            if str(row.get("ref_no", "")).strip().casefold() == reference_key
            and (
                not str(row.get("channel", "")).strip()
                or str(row.get("channel", "")).strip().casefold() == channel_key
            )
        ),
        None,
    )
