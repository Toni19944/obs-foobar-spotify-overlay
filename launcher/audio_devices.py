"""Capture-device enumeration for the audio selector (FR-022 / research D7).

Reuses the SAME device interface the spectrum server uses (``sounddevice``), so a
device picked here matches ``spectrum-server.py --device "<name>"`` exactly. The
chosen name is passed through the existing ``--device`` CLI — no server edit.
"""

from __future__ import annotations

from typing import List


def list_capture_devices() -> List[str]:
    """Return input-capable device names (deduped, order-preserving).

    Falls back to an empty list if ``sounddevice`` can't enumerate (e.g. no audio
    backend); the GUI then shows the free-text default and a clear status.
    """
    names: List[str] = []
    try:
        import sounddevice as sd

        seen = set()
        for d in sd.query_devices():
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name", "").strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
    except Exception:
        return []
    return names
