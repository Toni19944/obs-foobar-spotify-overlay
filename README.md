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

### Browser-source URL flags

The overlay page itself understands a few query parameters:

| Flag | Example | Effect |
|------|---------|--------|
| `hideWhenPaused=1` | `http://localhost:8081/?hideWhenPaused=1` | hide the card while playback is paused |
| `port=<n>` | `http://localhost:9080/?port=9080` | tell the page which overlay port to poll — **required if you changed the overlay port** in Preferences (the page's internal default is 8081) |
| `spectrumPort=<n>` | `http://localhost:8081/?spectrumPort=9500` | same for the spectrum WebSocket — **required if you changed the spectrum port** (internal default 9001) |
| `cardWidth=<px>` | `?cardWidth=480` | card width in pixels (default `340`) |
| `cardHeight=<px>` | `?cardHeight=200` | card height in pixels (default: auto, sized to content) — unlike the configurator's slider, `0` here is literal `0px` (a collapsed, invisible card), not "auto"; omit the flag entirely for auto sizing |
| `cardRadius=<px>` | `?cardRadius=1` | card corner radius in pixels (default `20`) — also rounds the card's clip and the visualizer glow canvas to match. **Use `1`, not `0`, for square corners** — see the known issue below |
| `cardOpacity=<0-1>` | `?cardOpacity=0.6` | card background opacity (default `0.97`) |
| `imgOpacity=<0-1>` | `?imgOpacity=0.5` | background image opacity (default `0.24`) |
| `bgMotion=1\|0` | `?bgMotion=1` | force background FFT motion on/off (default off) |
| `bgMotionTarget=card` | `?bgMotion=1&bgMotionTarget=card` | redirect bgMotion's audio-reactive pulse from the background image to a subtle inner white glow across the card itself instead — mutually exclusive with image motion (never both at once); default (omitted) is `image`, today's unchanged behavior |
| `mirror=1` | `?mirror=1` | mirror the border visualizer's glow outward, so the same glow also runs *outside* the card edge (default off) — cut hard at the card's edge exactly like the inner glow, just pointing the other way |
| `mirrorSize=<px>` | `?mirror=1&mirrorSize=30` | outward bar depth in pixels for the mirrored glow (default `22`, matching the inner glow's depth) — no effect unless `mirror=1` |
| `mirrorOpacity=<0-1>` | `?mirror=1&mirrorOpacity=0.4` | opacity of the mirrored glow layer (default `0.55`) — no effect unless `mirror=1` |
| `mirrorBlur=<px>` | `?mirror=1&mirrorBlur=8` | blur radius in pixels for the mirrored glow (default `12`, matching the inner glow's blur) — no effect unless `mirror=1` |

Flags combine with `&`, e.g.
`http://localhost:9080/?port=9080&spectrumPort=9500&hideWhenPaused=1`.

None of these are range-checked — an out-of-range value just renders however
it renders, so feel free to push `cardWidth` past what the configurator's
slider allows.

**`bgMotionTarget=card`** trades the background-image motion for a
subtle white glow washing across the card itself, pulsing with the same
audio — useful if you want an audio-reactive look without animating the
background image at all. This is an inset `box-shadow` on the card, not
`backdrop-filter` (which can't reach through to whatever OBS composites
behind a transparent browser source) and not `filter: brightness()`
(which is multiplicative and has no visible effect on the card's black
background). The card's frosted-glass blur (`CARD_BACKDROP_BLUR`, see
below) is a separate, unrelated static toggle that `bgMotionTarget` does
not touch.

**`mirror=1`** paints the same 44 perimeter bands a second time, pointing
outward instead of inward. Both layers share one renderer and read the
same smoothed band values in the same frame, so they cannot drift apart.
The mirrored layer is masked to the region *outside* the card, giving it
the same hard cut at the card's edge that `overflow: hidden` gives the
inner glow — so it never washes over the card or dilutes the inner glow.
Defaults deliberately match the inner glow (`mirrorSize` `22` =
`VIS_BAR_DEPTH`, `mirrorBlur` `12` = `VIS_BLUR`), making the default look
a true reflection; turn them down for something tighter, e.g.
`?mirror=1&mirrorSize=14&mirrorBlur=8`.

It also reserves extra room on the page to hold the outward glow: the
page's outer padding grows from the default `16px` to
`max(16, mirrorSize + 2 * mirrorBlur)` px — `46px` at default settings.
That has two knock-on effects on your OBS browser source: the card itself
renders `30px` further down and right than with the mirror off (at
defaults), and the overlay's total footprint grows by `60px` on each axis
(also at defaults). In practice that means you need to both reposition
*and* enlarge the browser source in OBS — repositioning alone will leave
the outward glow clipped at the source's right and bottom edges. With
`mirror` off, padding stays `16px` and nothing about the existing layout
changes.

**Known issue — `cardRadius=0` is ignored by the glow geometry.** The card's
own outline goes square, but both the inner visualizer glow and the mirrored
outward glow keep following a rounded R=20 path, so you get a rounded halo
around a square card. The cause is a falsy-zero fallback when the radius is
read at startup, and it predates the mirror feature — the mirror only makes
it easier to see.

**Workaround: use `?cardRadius=1`.** A 1px radius is visually square and takes
the normal code path, so the card, its clip, and both glow layers all agree.

A proper fix is scoped for a later release. It is deliberately not bundled
here because correcting it shifts the *inner* glow's geometry for anyone
already passing `cardRadius=0`, and this release's whole guarantee is that the
existing glow renders identically — so that change wants its own release and
its own before/after baseline.

**Per-scene setups:** because these are plain URL flags, you can point two
different OBS browser sources at the same overlay URL with different query
strings — e.g. your normal gaming scene with no flags, and a BRB/intermission
scene at `?cardWidth=560&cardOpacity=0.5&bgMotion=1` — without maintaining a
second overlay file or a second component build.

### Changing the overlay's look

The component serves `nowplaying-overlay.html` from memory — the page is embedded
into the DLL at build time, byte-for-byte. That means **look changes require a
rebuild**:

1. Open **`configurator.html`** in any browser, tweak the card shape, colours,
   glow, blur, etc. with live preview, and export the overlay HTML — or edit the
   `CONFIG` and `:root` CSS-variable blocks near the top of
   `nowplaying-overlay.html` directly.
2. Save/overwrite the repo-root `nowplaying-overlay.html` with the result.
3. Rebuild the component (see below) and reinstall the `.fb2k-component`.

**Exporting from the configurator drops the URL flags:** the export template
doesn't include the `applyRuntimeOverrides()` block described under
"Browser-source URL flags" above, so a freshly-exported `nowplaying-overlay.html`
silently ignores every query-string flag. Manually copy that block back into
the exported file before saving it over the repo-root copy. For
`bgMotionTarget`, copying back the override block alone isn't enough: the
configurator's own exported `CONFIG`/`bgAnimate` template has no
`BG_MOTION_TARGET`/`CARD_FLASH_GLOW_*` keys or card-mode branch, so
`bgMotionTarget=card` on such a file silently does nothing — you'd also
need to copy in those CONFIG keys and the updated `bgAnimate` function from
the repo-root overlay.

No rebuild is needed for: ports, background folder, timing offset (Preferences),
or URL flags that your currently-installed component build already
understands, like `?hideWhenPaused=1` — a flag new to the repo (not yet in
an installed build) still needs the same rebuild-and-reinstall cycle
described above before it does anything. The background images themselves
also need no rebuild — the bg folder is read live, add/remove images
anytime.

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
required) live on the **`archive/exe-bundle`** branch and its own release line:

- The [`0.4.1` release](https://github.com/Toni19944/obs-foobar-spotify-overlay/releases/tag/v0.4.1)
  has the latest prebuilt app (`FoobarOverlay-v0.4.1-win64.zip`). It reads Spotify
  now-playing from **Windows SMTC** — no login, developer app, or rate limits — keeps
  the Spotify Web API as an optional fallback, and supports the same per-scene overlay
  URL flags as the component (mirror glow, card sizing, background motion, pause-hide).
- The [`archive/exe-bundle`](https://github.com/Toni19944/obs-foobar-spotify-overlay/tree/archive/exe-bundle)
  branch is that tree — build instructions in its `BUILD.md` (Python 3.12 +
  PyInstaller), Spotify overlay under `Now-Playing-Spotify/`, exe tooling under
  `launcher/` and `packaging/`, and its own `README.md` for full usage.

The foobar2000 **component** (this repo's main line) remains the primary, actively
developed path; the bundled desktop app is a parallel line for users who want a
no-foobar, no-config app.

---

## License

[GPL-3.0](LICENSE).
