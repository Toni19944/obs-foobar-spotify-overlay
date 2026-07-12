# foobar2000 OBS Overlay

A clean, minimal OBS browser-source overlay that shows your currently playing
**foobar2000** track inside a frosted-glass card with a real-time audio spectrum
visualizer glowing around the border. Optionally crossfades through a folder of
background images on every track change. Comes with a visual configurator.

Everything is served by a **native foobar2000 component** — no external servers,
no Python, no Beefweb. Install the component, point OBS at it, done.

[![Watch the demo](preview.png)](https://youtu.be/GIjEJSzIUnQ)

---

## What's included

- **`foo_obs_overlay` component** (`component/`) — serves the overlay page and
  backgrounds over HTTP, now-playing metadata, and a 64-band FFT spectrum over
  WebSocket, all in-process. Servers start and stop with foobar2000.
- **Overlay** (`nowplaying-overlay.html`) — the now-playing card OBS renders.
- **Configurator** (`configurator.html`) — a visual GUI for tweaking every overlay
  setting with a live preview, then exporting a ready-to-use overlay HTML.

---

## Setup

1. Build `foo_obs_overlay.fb2k-component` (see **Building from source** below) or
   grab it from the [Releases](https://github.com/Toni19944/obs-foobar-spotify-overlay/releases)
   page if a component build is attached.
2. Double-click the `.fb2k-component` file (or use foobar2000 → Preferences →
   Components → Install) and let foobar2000 restart.
3. In OBS, add a **Browser Source** pointing at `http://localhost:8081/` with a
   transparent background (RGBA `0,0,0,0`). To hide the card while playback is
   paused, add `?hideWhenPaused=1` to the URL:
   `http://localhost:8081/?hideWhenPaused=1`.

That's it — play a track and the card, backgrounds, and spectrum glow are live.

### Requirements

- **foobar2000 v2.x, 64-bit** — no other components needed.
- [OBS Studio](https://obsproject.com/) (or any tool with a browser source).

---

## Configuration

All runtime settings live in **foobar2000 → Preferences → Tools → OBS Overlay**:

| Setting | Default | Notes |
|---------|---------|-------|
| Overlay (HTTP) port | `8081` | what OBS connects to |
| Spectrum (WebSocket) port | `9001` | visualizer data |
| Background folder | `<profile>\foo_obs_overlay\bg` | default images are extracted here on first run — add/remove your own freely |
| Spectrum timing offset | `0 ms` | ±500 ms; shift the spectrum earlier/later if your audio chain adds delay |

Apply restarts the servers on the spot — no foobar2000 restart needed.

For the overlay's **look** (card shape, colours, glow, blur, backgrounds), open
**`configurator.html`** in any browser, tweak with live preview, and export a
ready-to-use overlay HTML. You can also edit the `CONFIG` and `:root` CSS-variable
blocks near the top of `nowplaying-overlay.html` directly.

![configurator preview](configurator-preview.png)

---

## Building from source

Needs Visual Studio 2022+ Build Tools (C++ x64 workload) — CMake and Ninja are
included with them.

```
"C:\Program Files (x86)\Microsoft Visual Studio\<ver>\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cmake -S component -B component/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build component/build
```

Output: `component/build/foo_obs_overlay.fb2k-component` (and the raw DLL).
The build embeds `nowplaying-overlay.html` and `bg/` byte-for-byte, so overlay
edits require a rebuild to ship inside the component.

The DSP parity test (compares the component's spectrum pipeline against the
captured legacy reference) runs with:

```
component/build/oracle_runner.exe tests/parity/reference/reference.wav tests/parity/reference/reference.jsonl
```

---

## Spotify / desktop app version

Spotify support and the standalone desktop app (bundled exe, no foobar2000
required) live in the **v0.1.1** line, preserved in full:

- The [`v0.1.1` release](https://github.com/Toni19944/obs-foobar-spotify-overlay/releases/tag/v0.1.1)
  has the last prebuilt app (`FoobarOverlay-v0.1.1-win64.zip`) and matching source.
- The [`archive/exe-bundle`](https://github.com/Toni19944/obs-foobar-spotify-overlay/tree/archive/exe-bundle)
  branch is the same tree browsable on GitHub — build instructions in its
  `BUILD.md` (Python 3.12 + PyInstaller), Spotify overlay under
  `Now-Playing-Spotify/`, exe tooling under `launcher/` and `packaging/`.

The exe line runs the older external-server stack and is kept as-is; new
development happens on the foobar2000 component.

---

## License

[GPL-3.0](LICENSE).
