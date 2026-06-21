"""Foobar/Spotify Overlay launcher package.

This is the single authored code unit for feature 008 (single-exe + GUI build).
It orchestrates the carried overlay/spectrum servers as managed child processes
and hosts the configurator in a QtWebEngine view. The carried assets are bundled
as PyInstaller data and read from the unpacked bundle dir at runtime.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["resource_base", "asset_path", "appdata_dir", "APP_DIR_NAME"]

APP_DIR_NAME = "FoobarOverlay"


def resource_base() -> Path:
    """Root directory that carried assets are resolved against.

    - Frozen (PyInstaller one-folder, feature 010): ``sys._MEIPASS`` — still set;
      it points at the bundle root / ``_internal`` directory where the carried
      ``--add-data`` assets sit on disk (no per-launch extraction). The resolution
      below is therefore unchanged from the previous one-file build.
    - Dev run: the repository root (the parent of this ``launcher/`` package).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def asset_path(*parts: str) -> Path:
    """Resolve a carried asset path (frozen or dev), e.g.
    ``asset_path("spectrum-server.py")`` or
    ``asset_path("Now-Playing-Spotify", "nowplaying-spotify.html")``."""
    return resource_base().joinpath(*parts)


def appdata_dir() -> Path:
    """``%APPDATA%\\FoobarOverlay`` — runtime data root, created on first use.

    Never inside the repo or the bundle (Principle V; FR-018/FR-029).
    """
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    d = Path(base) / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d
