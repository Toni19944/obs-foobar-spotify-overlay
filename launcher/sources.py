"""Source registry (data-model E2) and the launch matrix (orchestration O1).

Two mutually-exclusive overlay sources. Both point at the SINGLE, unified root
``spectrum-server.py`` (FR-023a) — the Spotify copy is retired. Carried asset
paths are resolved for frozen vs dev via ``asset_path``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from . import asset_path

FOOBAR = "foobar"
SPOTIFY = "spotify"


@dataclass(frozen=True)
class Source:
    id: str                 # "foobar" | "spotify"
    overlay_html: Path      # carried overlay markup
    overlay_server: Path    # carried overlay-server.ps1
    spectrum_server: Path   # SINGLE shared root spectrum-server.py (FR-023a)


def _registry() -> Dict[str, Source]:
    # The single, glow-fixed root spectrum server — shared by BOTH sources.
    spectrum = asset_path("spectrum-server.py")
    return {
        FOOBAR: Source(
            id=FOOBAR,
            overlay_html=asset_path("nowplaying-overlay.html"),
            overlay_server=asset_path("overlay-server.ps1"),
            spectrum_server=spectrum,
        ),
        SPOTIFY: Source(
            id=SPOTIFY,
            overlay_html=asset_path("Now-Playing-Spotify", "nowplaying-spotify.html"),
            overlay_server=asset_path("Now-Playing-Spotify", "overlay-server.ps1"),
            spectrum_server=spectrum,
        ),
    }


REGISTRY = _registry()


def get_source(source_id: str) -> Source:
    return REGISTRY[source_id]


def requires_spectrum(glow: bool, background_motion: bool) -> bool:
    """Mirror the overlay's own ``connectSpectrum`` guard.

    The overlay opens the spectrum WS only when ``VISUALIZER || (IMAGES &&
    BG_MOTION)``. ``glow`` maps to ``VISUALIZER`` (default true); images are on
    by default, so this reduces to ``glow OR backgroundMotion`` (FR-008a). When
    both are off the spectrum server would have no client — pure waste.
    """
    return bool(glow) or bool(background_motion)
