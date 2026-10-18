# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PoliSense-Setup.exe
#
# Build from project root:
#   pip install pyinstaller
#   pyinstaller installer/polisense_setup.spec
#
# Output: dist/PoliSense-Setup.exe

a = Analysis(
    ["setup_project.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "_tkinter",
        "tkinter",
        "tkinter.ttk",
        "tkinter.font",
        "tkinter.messagebox",
        "queue",
        "threading",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude packages that don't belong in the installer itself.
        # (These are installed INTO the project venv by the installer, not needed here.)
        "langchain",
        "langchain_core",
        "langchain_google_genai",
        "sentence_transformers",
        "psycopg2",
        "numpy",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PoliSense-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # windowed mode — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,             # add installer/icon.ico here if available
)
