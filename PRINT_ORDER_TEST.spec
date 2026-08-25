# -*- mode: python ; coding: utf-8 -*-

a = Analysis(["print_order_test.py"], pathex=[], binaries=[], datas=[("assets/windows_ocr.ps1", "assets")], hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="REQM_PRINT_ORDER_TEST", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, disable_windowed_traceback=False)
