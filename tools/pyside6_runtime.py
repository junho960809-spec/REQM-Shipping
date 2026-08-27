"""Make the bundled PySide6 Qt DLL directory available before QtCore imports."""

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    qt_directory = Path(sys._MEIPASS) / "PySide6"
    if qt_directory.is_dir():
        os.add_dll_directory(str(qt_directory))
        os.environ["PATH"] = str(qt_directory) + os.pathsep + os.environ.get("PATH", "")
