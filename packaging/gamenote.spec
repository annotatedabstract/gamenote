# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for gamenote (one-folder, CPU default).

The small.en faster-whisper model is NOT bundled; it downloads on first run to
%LOCALAPPDATA%\\gamenote\\models, which keeps the installer small (~90 MB). The big
CUDA wheels (nvidia-cublas-cu12 / nvidia-cudnn-cu12) are intentionally NOT
installed in the build environment, so they are never collected; the CUDA path
stays as a runtime fallback for anyone who installs them and runs from source.

Build from the repo root:  pyinstaller --noconfirm --clean packaging/gamenote.spec
(or use packaging/build.sh).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # repo root (SPECPATH is packaging/)

datas = []
binaries = []
hiddenimports = []

# faster-whisper + its native backend and audio deps: collect DLLs/data/submodules.
for pkg in ("faster_whisper", "ctranslate2", "sounddevice", "av", "tokenizers"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # pragma: no cover - build-time diagnostics
        print(f"[gamenote.spec] collect_all({pkg!r}) skipped: {exc}")

# keyboard loads platform submodules dynamically (e.g. keyboard._winkeyboard).
hiddenimports += collect_submodules("keyboard")

# The model is NOT bundled (keeps the installer small, ~90 MB). It downloads
# once on first run to %LOCALAPPDATA%\gamenote\models and persists across
# updates. See gamenote.transcribe.resolve_model_source.

# App icon as data so the __file__-relative lookup in app.load_icon() works frozen.
assets = ROOT / "gamenote" / "assets"
for name in ("icon.ico", "icon.png"):
    p = assets / name
    if p.exists():
        datas.append((str(p), "gamenote/assets"))

a = Analysis(
    [str(ROOT / "main.pyw")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],  # the overlay is Qt now; tkinter is unused
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gamenote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowless; the app lives in the tray
    icon=str(assets / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="gamenote",
)
