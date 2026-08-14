import json
import os
from pathlib import Path


SAFETY_STOCK_PATH = (
    Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "inventory_safety_stock.json"
)


def load_safety_stocks(path: Path = SAFETY_STOCK_PATH) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = {}
    for code, value in data.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            result[str(code).strip().casefold()] = number
    return result


def save_safety_stock(code: str, value: float, path: Path = SAFETY_STOCK_PATH) -> None:
    rows = load_safety_stocks(path)
    rows[str(code).strip().casefold()] = float(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
