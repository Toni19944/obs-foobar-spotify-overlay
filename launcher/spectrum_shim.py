"""Spectrum-server shim (research D5).

Runs the SINGLE, unified root ``spectrum-server.py`` (FR-023a) in-process on the
bundled interpreter via ``runpy.run_path``, so a clean machine needs no separate
Python. Both ``--run-spectrum foobar`` and ``--run-spectrum spotify`` execute the
same glow-fixed file; ``--device`` and ``--port`` (FR-032) are passed through.
"""

from __future__ import annotations

import runpy
import sys
from typing import Optional

from . import asset_path


def run_spectrum(source: str, device: Optional[str], port: Optional[int]) -> None:
    """Execute the carried ``spectrum-server.py`` as ``__main__``.

    ``source`` is accepted for symmetry/diagnostics but does not change which
    file runs — there is one unified spectrum server (FR-023a).
    """
    script = asset_path("spectrum-server.py")

    argv = [str(script)]
    if device:
        argv += ["--device", device]
    if port:
        argv += ["--port", str(port)]

    sys.argv = argv
    runpy.run_path(str(script), run_name="__main__")
