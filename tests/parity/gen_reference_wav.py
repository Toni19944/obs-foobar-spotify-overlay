"""Generate tests/parity/reference/reference.wav (T010).

44.1 kHz mono 16-bit PCM, 32 s, fully synthesized (rights-clear), seeded RNG:
  0-3 s    digital silence                (noise gate, reset state)
  3-15 s   'music': chord + swept partial, amplitude-modulated (band motion)
  15-22 s  loud broadband passage         (AGC peak tracking)
  22-28 s  exponential loud->quiet fade   (peak decay vs smoothing)
  28-32 s  digital silence                (trailing decay)
"""
import sys
import wave

import numpy as np

SR = 44100
rng = np.random.default_rng(13)  # feature number; deterministic output


def seg(seconds):
    return np.arange(int(round(seconds * SR))) / SR


out = []

# 0-3 s silence
out.append(np.zeros(3 * SR))

# 3-15 s music: minor chord + harmonics + swept partial, slow AM
t = seg(12.0)
chord = sum(
    a * np.sin(2 * np.pi * f * t + p)
    for f, a, p in [
        (220.0, 0.22, 0.0), (261.63, 0.18, 1.1), (329.63, 0.16, 2.3),
        (440.0, 0.10, 0.7), (880.0, 0.06, 1.9), (1760.0, 0.04, 0.3),
        (3520.0, 0.03, 2.9), (7040.0, 0.02, 1.4),
    ]
)
sweep_f = 200.0 * (8000.0 / 200.0) ** (t / t[-1])          # 200 -> 8000 Hz
sweep = 0.10 * np.sin(2 * np.pi * np.cumsum(sweep_f) / SR)
am = 0.55 + 0.45 * np.sin(2 * np.pi * 0.35 * t)             # slow swell
music = (chord + sweep) * am * 0.55
out.append(music)

# 15-22 s loud: full chord + shaped noise, near full scale
t = seg(7.0)
loud_tone = sum(
    a * np.sin(2 * np.pi * f * t + p)
    for f, a, p in [
        (110.0, 0.30, 0.2), (220.0, 0.25, 1.3), (554.37, 0.20, 0.9),
        (1108.7, 0.15, 2.1), (2217.5, 0.10, 0.5), (4435.0, 0.08, 1.7),
        (8870.0, 0.06, 2.6), (13000.0, 0.04, 0.1),
    ]
)
noise = rng.standard_normal(t.size) * 0.12
beat = 0.75 + 0.25 * np.sign(np.sin(2 * np.pi * 2.0 * t))   # 2 Hz pumping
loud = (loud_tone + noise) * beat
loud = np.clip(loud, -0.98, 0.98)
out.append(loud)

# 22-28 s loud -> quiet exponential fade on sustained content
t = seg(6.0)
sus = sum(
    a * np.sin(2 * np.pi * f * t + p)
    for f, a, p in [
        (146.83, 0.30, 0.4), (293.66, 0.24, 1.6), (587.33, 0.18, 0.8),
        (1174.7, 0.12, 2.2), (2349.3, 0.08, 1.0), (4698.6, 0.05, 0.3),
    ]
)
fade = np.exp(np.log(0.012 / 0.9) * (t / t[-1])) * 0.9      # 0.9 -> ~0.011
out.append(sus * fade)

# 28-32 s silence
out.append(np.zeros(4 * SR))

signal = np.concatenate(out)
pcm = np.round(np.clip(signal, -1.0, 1.0) * 32767.0).astype(np.int16)

path = sys.argv[1]
with wave.open(path, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())

print(f"wrote {path}: {pcm.size} samples ({pcm.size / SR:.2f} s), "
      f"{pcm.size // 1024} full analysis windows")
