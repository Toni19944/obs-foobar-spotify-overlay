# foobar2000 OBS Overlay

A clean, minimal OBS browser-source overlay that shows your currently playing
**foobar2000** track inside a frosted-glass card with a real-time audio spectrum
visualizer glowing around the border. Optionally crossfades through a folder of
background images on every track change. Comes with a visual configurator.

[![Watch the demo](preview.png)](https://youtu.be/GIjEJSzIUnQ)

---

## What's included

- **Overlay** (`nowplaying-overlay.html`) — now-playing card driven by the
  [Beefweb](https://github.com/hyperblast/beefweb) HTTP API.
- **Border spectrum visualizer** — real FFT data captured from your audio device and
  streamed to the overlay as a soft, frequency-reactive glow.
- **Configurator** (`configurator.html`) — a visual GUI for tweaking every overlay
  setting with a live preview, then exporting a ready-to-use overlay HTML.

---

## Running it

No build step — the HTML + servers run directly from the repo:

```
nowplaying-overlay.html   # the overlay OBS points at
configurator.html         # visual settings editor
serve.bat                 # starts the overlay + spectrum servers
stop.bat                  # stops them
overlay-server.ps1        # static + Beefweb proxy server
spectrum-server.py        # FFT/WebSocket visualizer server
bg/                       # optional background images
```

The spectrum visualizer needs Python with a few packages:

```
pip install sounddevice numpy scipy websockets
```

Then double-click `serve.bat` and add a Browser Source in OBS pointing at the overlay
(default `http://localhost:8081/nowplaying-overlay.html`). Set the OBS source background
to transparent (RGBA `0,0,0,0`). `stop.bat` shuts both servers down again.

---

## Requirements

- **foobar2000** with [Beefweb Remote Control](https://github.com/hyperblast/beefweb).
- [OBS Studio](https://obsproject.com/) (or any tool with a browser source).
- **Python 3.8+** — only for the spectrum visualizer.

---

## Ports

| Port   | Used for                          |
|--------|-----------------------------------|
| `8880` | Beefweb (foobar2000 API)          |
| `8081` | Overlay server (what OBS connects to) |
| `9001` | Spectrum server (visualizer data) |

`8880` is set in Beefweb's preferences and `overlay-server.ps1`, `8081` in
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

## Looking for the desktop app?

The GUI control panel and its bundled executable were retired from the main tree. If you
still want them:

- The [`v0.1.1` release](https://github.com/Toni19944/obs-foobar-spotify-overlay/releases/tag/v0.1.1)
  carries the last prebuilt app (`FoobarOverlay-v0.1.1-win64.zip`).
- The `archive/exe-bundle` branch is the home of the exe build files (`launcher/`,
  `packaging/`, `BUILD.md`) for anyone building it from source.

---

## License

[GPL-3.0](LICENSE).
