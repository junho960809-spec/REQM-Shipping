"""Load the bundled theme and optional user overrides."""
from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
CUSTOM_THEME_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "REQM" / "theme.qss"


def bundled_theme_path() -> Path:
    root = Path(getattr(sys, "_MEIPASS", APP_DIR))
    return root / "ui" / "styles" / "theme.qss"


def load_theme(custom_path: str | Path | None = None) -> str:
    """Return the stable base theme plus optional presentation-only overrides."""
    base = bundled_theme_path().read_text(encoding="utf-8")
    override_path = Path(custom_path) if custom_path is not None else CUSTOM_THEME_PATH
    try:
        override = override_path.read_text(encoding="utf-8").strip()
    except OSError:
        override = ""
    return base + ("\n\n/* Local overrides */\n" + override if override else "")
