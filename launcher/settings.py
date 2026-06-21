"""AppSettings persistence (data-model E1 / gui-state-contract G1).

Global, source-independent preferences stored at
``%APPDATA%\\FoobarOverlay\\settings.json``. Loaded at startup, saved on change.
Named profiles are NOT here — they are owned by the carried configurator's
``localStorage`` and persisted by the QtWebEngine host (G7).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from . import appdata_dir

SETTINGS_FILE = "settings.json"

# Default port contract (FR-032 — defaults exactly match today's wire behaviour).
DEFAULT_PORTS = {
    "overlayHttp": 8081,
    "spectrumWs": 9001,
    "spotifyCallback": 8082,
    "beefwebTarget": 8880,
}


@dataclass
class DebugSettings:
    showTerminals: bool = False
    logToFile: bool = False


@dataclass
class Ports:
    overlayHttp: int = 8081
    spectrumWs: int = 9001
    spotifyCallback: int = 8082
    beefwebTarget: int = 8880


@dataclass
class ProfileFlags:
    """Launch-matrix read bridge (data-model E4 / G7).

    The configurator host mirrors the active profile's ``glow`` (VISUALIZER) and
    ``backgroundMotion`` (BG_MOTION) here so the orchestrator can gate the
    spectrum server at Start even when the configurator view is not loaded.
    ``glow`` defaults true (FR-008a) so the safe default launches the spectrum.
    """

    glow: bool = True
    backgroundMotion: bool = False


@dataclass
class AppSettings:
    activeSource: Optional[str] = None          # "foobar" | "spotify" | None
    minimizeToTray: bool = False                # ON: minimize hides to tray (no taskbar button)
    closeToTray: bool = True                    # ON: close (X) hides to tray; OFF: full shutdown
    hideCardWhenPaused: bool = False
    audioDevice: str = "Line 1"
    previewEnabled: bool = False
    activeProfile: str = "Default"
    debug: DebugSettings = field(default_factory=DebugSettings)
    ports: Ports = field(default_factory=Ports)
    profileFlags: ProfileFlags = field(default_factory=ProfileFlags)

    # ── persistence ────────────────────────────────────────────────
    @classmethod
    def path(cls) -> Path:
        return appdata_dir() / SETTINGS_FILE

    @classmethod
    def load(cls) -> "AppSettings":
        p = cls.path()
        if not p.exists():
            s = cls()
            s.save()
            return s
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt/unreadable settings → fall back to defaults, don't crash.
            return cls()
        s = cls.from_dict(raw)
        # If a stored port was out of range, _port() healed it in memory; persist
        # that repair so the on-disk file stops carrying the corruption (the "1"
        # artifact from the old sync bug self-heals on the first launch).
        raw_ports = raw.get("ports", {}) or {}
        if any(
            key in raw_ports and getattr(s.ports, key) != raw_ports.get(key)
            for key in DEFAULT_PORTS
        ):
            s.save()
        return s

    @staticmethod
    def _port(raw: dict, key: str) -> int:
        """Read a port, healing corrupt/implausible values back to the default.

        All ports this app uses are ephemeral high ports; a stored value below
        1024 (privileged) is treated as corruption — notably the QSpinBox
        range-minimum artifact (`1`) that an earlier sync bug could persist.
        """
        try:
            v = int(raw.get(key, DEFAULT_PORTS[key]))
        except (TypeError, ValueError):
            return DEFAULT_PORTS[key]
        return v if 1024 <= v <= 65535 else DEFAULT_PORTS[key]

    @classmethod
    def from_dict(cls, raw: dict) -> "AppSettings":
        debug = raw.get("debug", {}) or {}
        ports = raw.get("ports", {}) or {}
        flags = raw.get("profileFlags", {}) or {}
        return cls(
            activeSource=raw.get("activeSource"),
            # Two coherent tray toggles replace the legacy stopServersOnClose key,
            # which is simply not read here (ignored on load — no migration, no crash).
            minimizeToTray=bool(raw.get("minimizeToTray", False)),
            closeToTray=bool(raw.get("closeToTray", True)),
            hideCardWhenPaused=bool(raw.get("hideCardWhenPaused", False)),
            audioDevice=str(raw.get("audioDevice", "Line 1")),
            previewEnabled=bool(raw.get("previewEnabled", False)),
            activeProfile=str(raw.get("activeProfile", "Default")),
            debug=DebugSettings(
                showTerminals=bool(debug.get("showTerminals", False)),
                logToFile=bool(debug.get("logToFile", False)),
            ),
            ports=Ports(
                overlayHttp=cls._port(ports, "overlayHttp"),
                spectrumWs=cls._port(ports, "spectrumWs"),
                spotifyCallback=cls._port(ports, "spotifyCallback"),
                beefwebTarget=cls._port(ports, "beefwebTarget"),
            ),
            profileFlags=ProfileFlags(
                glow=bool(flags.get("glow", True)),
                backgroundMotion=bool(flags.get("backgroundMotion", False)),
            ),
        )

    def save(self) -> None:
        self.path().write_text(
            json.dumps(asdict(self), indent=2), encoding="utf-8"
        )
