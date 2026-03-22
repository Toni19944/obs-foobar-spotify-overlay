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
GAIN        = 10             # Amplification — increase if bands are too quiet

# Frequency range to analyse (Hz)
FREQ_MIN    = 120
FREQ_MAX    = 16000

# ═══════════════════════════════════════════════════════════════
#  GLOBALS
# ═══════════════════════════════════════════════════════════════

band_levels  = [0.0] * BANDS   # current smoothed band values
peak_levels  = [1.0] * BANDS   # per-band peak tracker for normalization
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
    rms = float(np.sqrt(np.mean(data**2)))
    if rms < 0.0002:
        return [0.0] * BANDS

    # Apply Hann window to reduce spectral leakage
    window  = np.hanning(len(data))
    windowed = data * window

    # FFT
    fft_vals = np.abs(np.fft.rfft(windowed))
    freqs    = np.fft.rfftfreq(len(windowed), d=1.0 / SAMPLE_RATE)

    # Only keep frequencies in our range
    mask     = (freqs >= FREQ_MIN) & (freqs <= FREQ_MAX)
    freqs    = freqs[mask]
    fft_vals = fft_vals[mask]

    if len(fft_vals) == 0:
        return [0.0] * BANDS

    # Split into logarithmically spaced bands (sounds more natural)
    log_min  = np.log10(FREQ_MIN)
    log_max  = np.log10(FREQ_MAX)
    edges    = np.logspace(log_min, log_max, BANDS + 1)

    band_vals = []
    for i in range(BANDS):
        lo, hi = edges[i], edges[i + 1]
        idx    = np.where((freqs >= lo) & (freqs < hi))[0]
        if len(idx) > 0:
            band_vals.append(float(np.mean(fft_vals[idx])))
        else:
            band_vals.append(0.0)

    # Gentle taper across full range
    for i in range(len(band_vals)):
        bass_boost = 1.0 + (i / len(band_vals)) * 1.4
        band_vals[i] *= bass_boost

    # Normalise to 0–1 with gain — use absolute scale, not relative peak
    band_vals = [min(1.0, v * GAIN) for v in band_vals]

    return band_vals


def audio_callback(indata, frames, time, status):
    """Called by sounddevice for each captured chunk."""
    global band_levels, peak_levels
    if status:
        print(f"  Audio status: {status}", file=sys.stderr)

    new_bands = compute_bands(indata)

    # Per-band peak normalization — prevents loud bands from pinning at 1.0
    for i in range(BANDS):
        peak_levels[i] = max(peak_levels[i] * 0.995, new_bands[i])
        if peak_levels[i] > 0:
            new_bands[i] = min(1.0, new_bands[i] / peak_levels[i])

    with lock:
        for i in range(BANDS):
            band_levels[i] = band_levels[i] * SMOOTHING + new_bands[i] * (1 - SMOOTHING)

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
    while True:
        await asyncio.sleep(interval)
        if not clients:
            continue
        with lock:
            payload = json.dumps([round(v, 4) for v in band_levels])
        dead = set()
        for ws in list(clients):
            try:
                await ws.send(payload)
            except Exception:
                dead.add(ws)
        clients.difference_update(dead)


async def main_async(device_index):
    import websockets
    print(f"\n  Spectrum server starting on ws://localhost:{PORT}")
    print(f"  Press Ctrl+C to stop\n")

    async with websockets.serve(handler, 'localhost', PORT):
        await broadcast_loop()

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Audio spectrum WebSocket server')
    parser.add_argument('--device', type=str, default=DEVICE,
                        help='Partial name of audio input device')
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
        asyncio.run(main_async(device_index))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Stopped.")
