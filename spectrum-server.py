#!/usr/bin/env python3
"""
spectrum-server.py
Captures audio from a Windows audio device, computes FFT frequency bands,
and streams them to connected WebSocket clients in real time.

The overlay connects to ws://localhost:9001 and receives a JSON array of
band levels (0.0–1.0) roughly 30 times per second.

Requirements:
    pip install sounddevice numpy scipy websockets

Usage:
    python spectrum-server.py
    python spectrum-server.py --device "Line 1"   # specify device by name
    python spectrum-server.py --list              # list available devices
"""

import argparse
import asyncio
import json
import sys
import threading
import numpy as np
import sounddevice as sd
import websockets                       # (11) moved to top-level

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════

PORT        = 9001          # WebSocket port the overlay connects to
DEVICE      = 'Line 1'      # Partial name match of your audio input device
SAMPLE_RATE = 44100         # Hz — standard audio sample rate
CHUNK       = 1024          # Samples per capture chunk
BANDS       = 64            # Number of frequency bands to output
FPS         = 30            # Target updates per second
SMOOTHING   = 0.67          # 0–1 — higher = smoother/slower band response
GAIN        = 3              # Pre-AGC amplification. The per-band peak normalizer
                            # (AGC) in audio_callback is scale-invariant, so GAIN
                            # (and foobar's volume) cancel in steady state — GAIN
                            # now only shapes the attack ramp out of silence, not
                            # the steady brightness. (Before the clip was removed,
                            # this gated how early loud audio flattened.)

# Frequency range to analyse (Hz)
FREQ_MIN    = 120
FREQ_MAX    = 16000

# ═══════════════════════════════════════════════════════════════
#  PRECOMPUTED CONSTANTS  (1, 2, 3)
# ═══════════════════════════════════════════════════════════════

# (2) Hann window — always the same size as CHUNK
_WINDOW = np.hanning(CHUNK).astype(np.float32)

# (3) Frequency axis & mask — constant for a given CHUNK / SAMPLE_RATE
_ALL_FREQS = np.fft.rfftfreq(CHUNK, d=1.0 / SAMPLE_RATE)
_FREQ_MASK = (_ALL_FREQS >= FREQ_MIN) & (_ALL_FREQS <= FREQ_MAX)
_MASKED_FREQS = _ALL_FREQS[_FREQ_MASK]

# (1) Band-edge bin indices — maps each masked FFT bin to a band index
#     so we can use np.bincount instead of 64× np.where
_LOG_MIN = np.log10(FREQ_MIN)
_LOG_MAX = np.log10(FREQ_MAX)
_EDGES   = np.logspace(_LOG_MIN, _LOG_MAX, BANDS + 1)

_BIN_TO_BAND = np.full(len(_MASKED_FREQS), -1, dtype=np.intp)
for _b in range(BANDS):
    _in_band = (_MASKED_FREQS >= _EDGES[_b]) & (_MASKED_FREQS < _EDGES[_b + 1])
    _BIN_TO_BAND[_in_band] = _b
# Include the very last edge frequency in the final band
_BIN_TO_BAND[_MASKED_FREQS == _EDGES[-1]] = BANDS - 1

# Boolean mask for bins that actually belong to a band (drop any gaps)
_VALID_BINS  = _BIN_TO_BAND >= 0
_BIN_TO_BAND_VALID = _BIN_TO_BAND[_VALID_BINS]

# Per-band bin counts for averaging (float for division)
_BAND_COUNTS = np.bincount(_BIN_TO_BAND_VALID, minlength=BANDS).astype(np.float64)
_BAND_COUNTS[_BAND_COUNTS == 0] = 1.0   # avoid division by zero

# Pre-allocate a zero array for the noise-gate fast path
_ZEROS = np.zeros(BANDS, dtype=np.float64)

# ═══════════════════════════════════════════════════════════════
#  GLOBALS
# ═══════════════════════════════════════════════════════════════

# (5) numpy arrays instead of Python lists
band_levels  = np.zeros(BANDS, dtype=np.float64)
peak_levels  = np.ones(BANDS, dtype=np.float64)
clients      = set()           # connected WebSocket clients
lock         = threading.Lock()

# ═══════════════════════════════════════════════════════════════
#  DEVICE HELPERS
# ═══════════════════════════════════════════════════════════════

def find_device(name):
    """Find input device index by partial name match."""
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0 and name.lower() in d['name'].lower():
            return i, d['name']
    return None, None


def list_devices():
    """Print all available input devices."""
    print("\nAvailable input devices:")
    print("─" * 50)
    for i, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] > 0:
            print(f"  [{i:2d}] {d['name']}")
    print()

# ═══════════════════════════════════════════════════════════════
#  AUDIO CAPTURE + FFT
# ═══════════════════════════════════════════════════════════════

def compute_bands(data):
    """Convert raw audio chunk to BANDS frequency band levels."""
    # Flatten stereo to mono if needed
    if data.ndim > 1:
        data = data.mean(axis=1)

    # Noise gate — silence if signal is too quiet
    rms = float(np.sqrt(np.mean(data ** 2)))
    if rms < 0.0002:
        return _ZEROS

    # (2) Apply precomputed Hann window
    windowed = data * _WINDOW

    # FFT — apply precomputed mask (3)
    fft_vals = np.abs(np.fft.rfft(windowed))
    fft_vals = fft_vals[_FREQ_MASK]

    if len(fft_vals) == 0:
        return _ZEROS

    # (1) Vectorized band averaging via bincount
    valid_fft = fft_vals[_VALID_BINS]
    band_sums = np.bincount(_BIN_TO_BAND_VALID, weights=valid_fft, minlength=BANDS)
    band_vals = band_sums / _BAND_COUNTS

    # (4) Bass boost taper removed entirely

    # Apply gain, then hand the UNCLIPPED signal to the AGC in audio_callback.
    # The [0,1] clip that used to live here was the SOLE source of volume-
    # dependence: at loud foobar volume bands slammed into 1.0 → the spectrum
    # shape flattened → "all glow, no motion." Removing it lets the per-band peak
    # normalizer (which IS scale-invariant) run on raw magnitudes, so the output
    # shape — and the overlay glow — is now independent of foobar's volume. The
    # AGC's own min(1.0, …) bounds the result to [0,1], so no clip is needed here.
    np.multiply(band_vals, GAIN, out=band_vals)

    return band_vals


def audio_callback(indata, frames, time, status):
    """Called by sounddevice for each captured chunk."""
    global band_levels, peak_levels
    if status:
        print(f"  Audio status: {status}", file=sys.stderr)

    new_bands = compute_bands(indata)

    # (5) Vectorized per-band peak normalization
    peak_levels *= 0.995
    np.maximum(peak_levels, new_bands, out=peak_levels)
    # Normalise — peak_levels is always >= 1.0 initially and decays, never zero
    normalized = np.minimum(1.0, new_bands / peak_levels)

    # (6) Minimal time under lock — single array operation
    with lock:
        band_levels *= SMOOTHING
        band_levels += normalized * (1.0 - SMOOTHING)

# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET SERVER
# ═══════════════════════════════════════════════════════════════

async def handler(websocket):
    """Handle a connected WebSocket client."""
    clients.add(websocket)
    print(f"  Client connected   ({len(clients)} total)")
    try:
        await websocket.wait_closed()
    finally:
        clients.discard(websocket)
        print(f"  Client disconnected ({len(clients)} total)")


async def broadcast_loop():
    """Send band data to all connected clients at FPS rate."""
    interval = 1.0 / FPS
    # (9) Drift-compensating sleep — anchor to wall clock
    next_tick = asyncio.get_event_loop().time() + interval

    while True:
        now = asyncio.get_event_loop().time()
        sleep_for = max(0.0, next_tick - now)
        await asyncio.sleep(sleep_for)
        next_tick += interval
        # If we fell behind by more than one full interval, reset
        if next_tick < asyncio.get_event_loop().time():
            next_tick = asyncio.get_event_loop().time() + interval

        if not clients:
            continue

        # (F-011) Hold the lock only for the array read; serialize outside it.
        with lock:
            snapshot = band_levels.copy()
        payload = json.dumps(np.round(snapshot, 4).tolist())

        # (7) Parallel sends via asyncio.gather  (8) no list() copy needed
        async def _send(ws):
            try:
                await ws.send(payload)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in clients))
        dead = {ws for ws in results if ws is not None}
        if dead:
            clients.difference_update(dead)


async def main_async(device_index, port=PORT):
    print(f"\n  Spectrum server starting on ws://localhost:{port}")
    print(f"  Press Ctrl+C to stop\n")

    async with websockets.serve(handler, 'localhost', port):
        await broadcast_loop()

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Audio spectrum WebSocket server')
    parser.add_argument('--device', type=str, default=DEVICE,
                        help='Partial name of audio input device')
    parser.add_argument('--port', type=int, default=PORT,
                        help=f'WebSocket port to listen on (default {PORT})')
    parser.add_argument('--list', action='store_true',
                        help='List available input devices and exit')
    args = parser.parse_args()

    if args.list:
        list_devices()
        return

    device_index, device_name = find_device(args.device)
    if device_index is None:
        print(f"\n  Device not found: '{args.device}'")
        print("  Run with --list to see available devices.\n")
        sys.exit(1)

    print(f"\n  Device:  {device_name}  [{device_index}]")
    print(f"  Bands:   {BANDS}")
    print(f"  Rate:    {SAMPLE_RATE} Hz")
    print(f"  Chunk:   {CHUNK} samples")

    # Start audio capture in background thread
    stream = sd.InputStream(
        device=device_index,
        channels=1,
        samplerate=SAMPLE_RATE,
        blocksize=CHUNK,
        dtype='float32',
        callback=audio_callback,
    )

    with stream:
        asyncio.run(main_async(device_index, args.port))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Stopped.")
