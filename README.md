# foobar2000 + Spotify OBS Overlay

A clean, minimal OBS browser-source overlay that shows your currently playing track —
from **foobar2000** or **Spotify** — inside a frosted-glass card with a real-time audio
spectrum visualizer glowing around the border. Optionally crossfades through a folder of
background images on every track change. Comes with a visual configurator and a GUI
control panel that starts/stops everything for you.

[![Watch the demo](preview.png)](https://youtu.be/GIjEJSzIUnQ)

---

## What's included

- **foobar2000 overlay** (`nowplaying-overlay.html`) — now-playing card driven by the
  [Beefweb](https://github.com/hyperblast/beefweb) HTTP API.
- **Spotify overlay** (`Now-Playing-Spotify/`) — the same card, driven by **Windows
  System Media Transport Controls (SMTC)** by default: it reads whatever the Spotify
  desktop app is playing locally (the same "now playing" the Win+A media panel shows),
  so there's **no login, no developer app, and no rate limits**. The Spotify Web API is
  kept as an optional fallback (see [Spotify now-playing source](#spotify-now-playing-source)).
- **Border spectrum visualizer** — real FFT data captured from your audio device and
  streamed to the overlay as a soft, frequency-reactive glow.
- **Configurator** (`configurator.html`) — a visual GUI for tweaking every overlay
  setting with a live preview, then exporting a ready-to-use overlay HTML.
- **GUI control panel** (the `FoobarOverlay` app) — a desktop launcher that starts and
  stops the servers, picks the audio device, switches between foobar2000 and Spotify, and
  opens the configurator. Ports are configurable from the UI.

---

## Two ways to run

### 1. Download the prebuilt app (easiest)

1. Go to the [**Releases**](https://github.com/Toni19944/obs-foobar-spotify-overlay/releases)
   page and download the `v0.1.0` zip.
2. Extract the **whole folder** somewhere convenient.
3. Run **`FoobarOverlay.exe`** (keep it next to its `_internal/` folder — don't move the
   exe out on its own).

The control panel handles starting the servers and pointing you at the right OBS URL.

### 2. Run from source (no build)

You don't need to build anything to use the overlay — the HTML + servers run directly:

```
nowplaying-overlay.html   # the overlay OBS points at
configurator.html         # visual settings editor
serve.bat                 # starts the overlay + spectrum servers
stop.bat                  # stops them
overlay-server.ps1        # static + Beefweb proxy server
spectrum-server.py        # FFT/WebSocket visualizer server
bg/                       # optional background images
Now-Playing-Spotify/      # the Spotify variant (its own serve.bat + overlay)
```

The spectrum visualizer needs Python with a few packages:

```
pip install sounddevice numpy scipy websockets
```

Then double-click `serve.bat` (foobar2000) or `Now-Playing-Spotify/serve.bat` (Spotify),
and add a Browser Source in OBS pointing at the overlay (default
`http://localhost:8081/nowplaying-overlay.html`). Set the OBS source background to
transparent (RGBA `0,0,0,0`).

---

## Requirements

- **foobar2000** with [Beefweb Remote Control](https://github.com/hyperblast/beefweb)
  (for the foobar2000 overlay), or the **Spotify desktop app** running (for the Spotify
  overlay — it reads now-playing locally via SMTC; no account linking or developer app
  needed). The optional Web API mode additionally needs a Spotify developer Client ID.
- [OBS Studio](https://obsproject.com/) (or any tool with a browser source).
- **Python 3.8+** — only for the spectrum visualizer when running from source. The
  prebuilt app bundles its own Python runtime.

---

## Ports

| Port   | Used for                          |
|--------|-----------------------------------|
| `8880` | Beefweb (foobar2000 API)          |
| `8081` | Overlay server (what OBS connects to) |
| `9001` | Spectrum server (visualizer data) |

When running the prebuilt app, ports are configurable from the control panel. When running
from source, `8880` is set in Beefweb's preferences and `overlay-server.ps1`, `8081` in
`overlay-server.ps1` and the overlay HTML, and `9001` in `spectrum-server.py` and the
overlay HTML.

---

## Configuration

Open **`configurator.html`** in any browser to adjust the card shape, colours, background
images, and more with a live preview, then export a ready-to-use overlay. You can also
edit the `CONFIG` and `:root` CSS-variable blocks near the top of
`nowplaying-overlay.html` directly. The visualizer settings live in `spectrum-server.py`
(capture device, bands, gain) and in the overlay HTML (glow colour, blur, depth).

![configurator preview](configurator-preview.png)

---

## Spotify now-playing source

The Spotify overlay reads track info from one of two sources, selected by the
`metadataSource` field in `%APPDATA%\FoobarOverlay\settings.json`:

- **`smtc`** (default) — Windows System Media Transport Controls. Reads the Spotify
  desktop app's local playback (title, artist, play/pause, position/duration). No login,
  no developer app, no rate limits — just have Spotify running and playing.
- **`webapi`** — the Spotify Web API. Needs a Spotify developer Client ID and a one-time
  "Connect Spotify" OAuth in the control panel. It's hardened against rate limits
  (throttled, backs off on HTTP 429, holds the last track instead of blanking), but
  `smtc` is simpler and recommended.

Only `webapi` requires a Spotify login. (Album art via SMTC isn't wired up yet, which
only matters if you turn on the album-art-as-background option.)

---

## Per-scene URL flags

Both overlays accept optional URL query parameters, so a second OBS browser source (e.g. a
BRB/intermission scene) can render a differently-sized or styled card without touching your
main source. With no parameters the overlay looks exactly as configured. Example:
`http://localhost:8081/?spectrumPort=9001&cardWidth=520&mirror=1`.

| Flag | Effect |
|------|--------|
| `port` | overlay server port (also used for background images) |
| `spectrumPort` | visualizer WebSocket port (default `9001`) |
| `hideWhenPaused=1` | hide the card while playback is paused |
| `cardWidth`, `cardHeight`, `cardRadius` | card size / corner radius, in px |
| `cardOpacity` | card background opacity, `0`–`1` |
| `imgOpacity` | background-image opacity, `0`–`1` |
| `bgMotion=1` / `bgMotion=0` | enable / disable FFT-reactive background motion |
| `bgMotionTarget=card` | apply that motion as a glow on the card instead of the image |
| `mirror=1` | mirrored outward glow that bleeds past the card edge |
| `mirrorSize`, `mirrorOpacity`, `mirrorBlur` | tune the mirrored glow |

The control panel already appends `?spectrumPort=…` to the OBS URL; add any of the others
onto the end of that.

---

## Building from source

Want to build the GUI control-panel executable yourself? See **[BUILD.md](BUILD.md)**.
You do **not** need this to use the overlay — it's only for producing the packaged app.

---

## License

[GPL-3.0](LICENSE).
