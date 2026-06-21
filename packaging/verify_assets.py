#!/usr/bin/env python3
"""Embedded-asset verification for the single-exe bundle (feature 009, FR-003 / C4).

Two jobs:

1. **Strict verify** (default; run by ``build.ps1`` after the PyInstaller freeze):
   assert the *carried* copies of ``spectrum-server.py`` and
   ``nowplaying-overlay.html`` in the one-folder bundle
   (``dist/FoobarOverlay/_internal/``) are **byte-identical** to the committed
   working-tree files, and that the data-model E3 glow markers are present in the
   ``configurator.html`` generators (and the pre-fix markers are gone). Any
   mismatch exits non-zero so a build can never silently ship a pre-fix glow
   snapshot. (Feature 010 switched the deliverable from a one-file exe to a
   one-folder bundle, so the carried files are now plain files under ``_internal/``
   rather than entries in a one-file CArchive.)

2. **Inspect** (``--inspect <exe>``; diagnostic only, always exits 0): report
   whether the glow assets embedded in an *arbitrary* one-file exe (e.g. a
   previously shipped one) are the fixed or the stale variant, for the changelog.

Usage::

    python packaging/verify_assets.py                       # verify dist/FoobarOverlay/
    python packaging/verify_assets.py path/to/Bundle/       # verify a specific bundle dir
    python packaging/verify_assets.py --inspect old/FoobarOverlay.exe   # legacy one-file
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# One-folder deliverable root (feature 010). build.ps1 points the verifier here.
DEFAULT_DIST = ROOT / "dist" / "FoobarOverlay"

# Render assets that MUST be embedded byte-for-byte from the committed root files.
BYTE_IDENTICAL_ASSETS = ("spectrum-server.py", "nowplaying-overlay.html")

# data-model E3 markers for the configurator generators (working-tree check).
GEN_REQUIRED = (
    "const visGain = 1.33",                              # generateHTML (volume-blind)
    "peak_levels[i] = max(peak_levels[i] * 0.995",       # generateSpectrumPy AGC
)
GEN_FORBIDDEN = (
    "Math.abs(volume) / 25",                             # pre-fix overlay curve
    "[min(1.0, v * GAIN) for v in band_vals]",           # pre-fix spectrum clip
)


def _internal_dir(target: Path) -> Path:
    """Resolve the one-folder asset directory for a build *target*.

    Accepts the bundle root (``dist/FoobarOverlay/``) or the exe inside it
    (``dist/FoobarOverlay/FoobarOverlay.exe``). Carried ``--add-data`` assets land
    under ``_internal/`` in a PyInstaller 6.x one-folder build (where ``_MEIPASS``
    points at runtime); if no ``_internal/`` exists, fall back to the root itself.
    """
    if target.is_dir():
        root = target
    elif target.suffix.lower() == ".exe":
        root = target.parent
    else:
        root = target
    internal = root / "_internal"
    return internal if internal.is_dir() else root


def _read_embedded(exe: Path) -> dict[str, bytes]:
    """Return {basename: bytes} for every file embedded in a one-file PyInstaller exe."""
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(exe))
    out: dict[str, bytes] = {}
    for name in reader.toc:
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        try:
            out[base] = reader.extract(name)
        except Exception:
            continue
    return out


def _spectrum_is_fixed(data: bytes) -> bool:
    """Heuristic: the spectrum source carries the scale-invariant AGC (fixed)."""
    return b"peak_levels" in data and b"min" in data and b"0.995" in data


def _overlay_is_fixed(data: bytes) -> bool:
    """Heuristic: the overlay carries the constant, volume-blind visGain (fixed)."""
    return b"const visGain = 1.33" in data


def verify(target: Path) -> int:
    problems: list[str] = []

    # (a) carried render assets byte-identical to the committed root files. In the
    # one-folder build (feature 010) these are plain files under _internal/.
    internal = _internal_dir(target)
    if not internal.exists():
        print(f"  [X] bundle asset dir not found: {internal}")
        print(f"      (expected a one-folder build at {target} — run build.ps1 first)")
        return 2

    for name in BYTE_IDENTICAL_ASSETS:
        src = (ROOT / name).read_bytes()
        carried_path = internal / name
        if not carried_path.exists():
            problems.append(f"{name}: not carried in {internal}")
        else:
            emb = carried_path.read_bytes()
            if emb != src:
                problems.append(
                    f"{name}: carried bytes differ from committed working-tree file "
                    f"(carried {len(emb)} B vs root {len(src)} B)"
                )
            else:
                print(f"  [OK] {name}: carried == committed ({len(src)} B)")

    # (b) configurator generator markers (data-model E3) in the working tree.
    cfg = (ROOT / "configurator.html").read_text(encoding="utf-8")
    for marker in GEN_REQUIRED:
        if marker in cfg:
            print(f"  [OK] configurator.html: required marker present - {marker!r}")
        else:
            problems.append(f"configurator.html: missing required glow marker {marker!r}")
    for marker in GEN_FORBIDDEN:
        if marker in cfg:
            problems.append(f"configurator.html: pre-fix marker still present {marker!r}")
        else:
            print(f"  [OK] configurator.html: pre-fix marker absent - {marker!r}")

    if problems:
        print("\nEMBEDDED-ASSET VERIFICATION FAILED:")
        for p in problems:
            print(f"  [X] {p}")
        return 1

    print("\nEmbedded-asset verification PASSED - bundle carries the glow-fixed assets.")
    return 0


def inspect(exe: Path) -> int:
    if not exe.exists():
        print(f"  exe not found: {exe}")
        return 0
    try:
        embedded = _read_embedded(exe)
    except Exception as exc:
        print(f"  could not read embedded archive from {exe}: {exc}")
        return 0

    print(f"Inspecting embedded glow assets in {exe}:")
    spec = embedded.get("spectrum-server.py")
    over = embedded.get("nowplaying-overlay.html")
    if spec is None:
        print("  spectrum-server.py: NOT EMBEDDED")
    else:
        print(f"  spectrum-server.py: {'FIXED (AGC)' if _spectrum_is_fixed(spec) else 'STALE (pre-fix clip)'}")
    if over is None:
        print("  nowplaying-overlay.html: NOT EMBEDDED")
    else:
        print(f"  nowplaying-overlay.html: {'FIXED (visGain=1.33)' if _overlay_is_fixed(over) else 'STALE (volume-derived visGain)'}")
    # Diagnostic only — never fails the build.
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify the bundle carries the glow-fixed render assets.")
    ap.add_argument("target", nargs="?", default=None,
                    help="one-folder bundle dir or exe to check (default: dist/FoobarOverlay/)")
    ap.add_argument("--inspect", metavar="EXE", default=None,
                    help="diagnostic: report stale-vs-fixed for a legacy one-file EXE and exit 0")
    args = ap.parse_args(argv)

    if args.inspect is not None:
        return inspect(Path(args.inspect))
    target = Path(args.target) if args.target else DEFAULT_DIST
    return verify(target)


if __name__ == "__main__":
    raise SystemExit(main())
