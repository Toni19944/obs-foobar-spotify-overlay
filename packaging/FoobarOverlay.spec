# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder spec for the Foobar/Spotify Overlay launcher (feature 008,
converted from one-file to one-folder in feature 010 to kill the ~60 s launch hang).

Carries the (mostly byte-for-byte) overlay/spectrum/configurator assets as data and
bundles PySide6 + QtWebEngine plus the spectrum-server's native deps so the exe runs
on a clean machine with no Python (FR-028). A one-folder bundle extracts nothing at
launch — the bootloader maps the on-disk _internal/ directory directly. Build from
the repo root:

    ./packaging/build.ps1     # → dist/FoobarOverlay/ (FoobarOverlay.exe + _internal/)
"""

import os

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_all

# SPECPATH is provided by PyInstaller; the repo root is its parent.
ROOT = os.path.dirname(SPECPATH)


def _root(*p):
    return os.path.join(ROOT, *p)


# ── Carried assets (--add-data), per CA-1/CA-3 ─────────────────────
datas = [
    # Edited-but-default-preserving (single unified spectrum + both overlay servers).
    (_root("spectrum-server.py"), "."),                       # FR-023a + --port
    (_root("overlay-server.ps1"), "."),                       # foobar (+port config)
    (_root("nowplaying-overlay.html"), "."),                  # +pause-hide/+ports (default-off)
    (_root("Now-Playing-Spotify", "overlay-server.ps1"), "Now-Playing-Spotify"),  # auth-plumbing
    # Byte-for-byte.
    (_root("Now-Playing-Spotify", "nowplaying-spotify.html"), "Now-Playing-Spotify"),
    (_root("configurator.html"), "."),
    # Tray icon (resolved via asset_path("launcher","resources","tray.ico")).
    (_root("launcher", "resources", "tray.ico"), os.path.join("launcher", "resources")),
    # GUI restyle (feature 009): Qt stylesheet (always present, committed).
    (_root("launcher", "resources", "style.qss"), os.path.join("launcher", "resources")),
]

# Bundled display/body fonts (feature 009, FR-013). Added only if present so the
# build never hard-fails on missing fonts — the app falls back to the nearest
# installed family at runtime.
_fonts_dir = _root("launcher", "resources", "fonts")
for _font in ("Oswald.ttf", "DMSans.ttf"):
    _font_path = os.path.join(_fonts_dir, _font)
    if os.path.exists(_font_path):
        datas.append((_font_path, os.path.join("launcher", "resources", "fonts")))
# Background images are added as a Tree to a.datas AFTER Analysis (Tree yields
# 3-tuple TOC entries that cannot be mixed into the 2-tuple ``datas=`` list).

binaries = []
hiddenimports = [
    "scipy",
    "scipy.signal",
    "websockets",
    "win32crypt",
    "win32job",
    "win32api",
    "win32con",
]

# sounddevice ships a bundled PortAudio DLL + data — collect everything it needs.
for pkg in ("sounddevice", "numpy"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h


a = Analysis(
    [_root("packaging", "pyi_entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
# Carry the background images (recursively) now that the TOC exists.
a.datas += Tree(_root("bg"), prefix="bg")

pyz = PYZ(a.pure)

# Startup splash (feature 010): painted by the C bootloader BEFORE Python/Qt import,
# so a cold/AV-scanned first run shows a "starting" sign within ~2 s (SC-003/FR-004).
# Dismissed at runtime via pyi_splash.close() once the control panel is shown.
splash = Splash(
    _root("launcher", "resources", "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,                       # static image — no progress text (contract §"Out of scope")
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,                              # one-folder splash recipe: splash in EXE
    exclude_binaries=True,               # one-folder: binaries/datas live in _internal/
    name="FoobarOverlay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,                       # GUI app — no console window (SC-002)
    icon=_root("launcher", "resources", "tray.ico"),
)

# One-folder COLLECT (feature 010): gather the exe + its DLLs and carried assets
# into dist/FoobarOverlay/ (FoobarOverlay.exe + _internal/). Nothing is extracted
# to %TEMP% at launch, so the control panel opens in seconds (SC-001/002) instead
# of unpacking the whole ~260 MB payload every run.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    splash.binaries,                     # one-folder splash recipe: splash.binaries in COLLECT
    strip=False,
    upx=False,
    name="FoobarOverlay",
)
