"""capture_reference.py — legacy DSP reference capture (T011, FR-013).

Drives the REAL legacy pipeline: imports compute_bands/audio_callback from
the repo-root spectrum-server.py (no audio device involved) and feeds it
consecutive 1024-sample windows of a WAV from reset state. Emits JSONL:
line k = the 64 full-precision `level` values after window k
(contracts/dsp-parity.md reference-capture format).

MUST run while spectrum-server.py still exists in the tree — i.e. before the
FR-014 legacy-deletion commit. The captured reference.jsonl is committed and
outlives the legacy stack.

Usage:
    py -3.12 tests/parity/capture_reference.py \
        tests/parity/reference/reference.wav \
        tests/parity/reference/reference.jsonl

Requires numpy only (sounddevice/websockets are stubbed for import).
"""
import importlib.util
import json
import sys
import types
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY = REPO_ROOT / "spectrum-server.py"


def import_legacy():
    if not LEGACY.exists():
        sys.exit(
            f"ERROR: {LEGACY} not found. This capture must run before the "
            "legacy stack is deleted (FR-013); check out a pre-deletion tree."
        )
    # Stub the audio/network deps so module import has no side effects and
    # needs no devices. Module top level only builds numpy tables.
    for name in ("sounddevice", "websockets"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    spec = importlib.util.spec_from_file_location("spectrum_server", LEGACY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <reference.wav> <out.jsonl>")
    wav_path, out_path = sys.argv[1], sys.argv[2]

    ss = import_legacy()

    with wave.open(wav_path, "rb") as w:
        assert w.getnchannels() == 1, "reference WAV must be mono"
        assert w.getframerate() == ss.SAMPLE_RATE, "reference WAV must be 44.1 kHz"
        assert w.getsampwidth() == 2, "reference WAV must be 16-bit PCM"
        raw = w.readframes(w.getnframes())

    # Exactly what sounddevice would deliver: float32 in [-1, 1), shape
    # (frames, channels). int16/32768 is exact in float32.
    samples = (np.frombuffer(raw, dtype=np.int16).astype(np.float32)
               / np.float32(32768.0))

    # Reset state (the oracle's starting condition, SC-003).
    ss.band_levels[:] = 0.0
    ss.peak_levels[:] = 1.0

    chunk = ss.CHUNK
    n_windows = samples.size // chunk
    with open(out_path, "w", encoding="ascii", newline="\n") as out:
        for k in range(n_windows):
            window = samples[k * chunk:(k + 1) * chunk].reshape(-1, 1)
            # The legacy per-window step, verbatim (gate/FFT/AGC/smoothing).
            ss.audio_callback(window, chunk, None, None)
            out.write(json.dumps(ss.band_levels.tolist()) + "\n")

    print(f"captured {n_windows} windows x {ss.BANDS} bands -> {out_path}")


if __name__ == "__main__":
    main()
