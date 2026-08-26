# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

pdf_datas, pdf_binaries, pdf_hidden = collect_all("pdfplumber")
miner_datas, miner_binaries, miner_hidden = collect_all("pdfminer")
playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")
python_runtime_dir = Path(sys.base_prefix)
runtime_binaries = [
    (str(python_runtime_dir / dll_name), ".")
    for dll_name in ("vcruntime140.dll", "vcruntime140_1.dll")
    if (python_runtime_dir / dll_name).exists()
]

a = Analysis(
    ["main.py"], pathex=[], binaries=runtime_binaries + pdf_binaries + miner_binaries + playwright_binaries,
    datas=pdf_datas + miner_datas + playwright_datas + [
        ("assets/app_icon.png", "assets"),
        ("assets/direct_conversion_reference.xlsx", "assets"),
        ("assets/weekly_inventory_template.xlsx", "assets"),
        ("assets/windows_ocr.ps1", "assets"),
    ],
    hiddenimports=pdf_hidden + miner_hidden + playwright_hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name="REQM", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    icon="assets/app_icon.ico",
    codesign_identity=None, entitlements_file=None,
)
