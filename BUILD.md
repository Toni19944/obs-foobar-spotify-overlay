# Building from source

This guide covers building the **GUI control panel** (`FoobarOverlay.exe`) from source
with PyInstaller. If you just want to run the overlay, you don't need this — either grab
the prebuilt binary from the [Releases](https://github.com/Toni19944/obs-foobar-spotify-overlay/releases)
page, or run the overlay directly from the source files (see the README's "Run from
source" section). This page is only for producing the packaged executable yourself.

## Prerequisites

- **Python 3.12** — this is required. Build with the explicit interpreter `py -3.12`.

  > ⚠️ **Do not use bare `py` / `python` if your default is 3.14.** PyInstaller does not
  > support Python 3.14, and the build will **fail silently** (it can appear to "succeed"
  > against a stale `dist/`). Always invoke the 3.12 interpreter explicitly. Verify with:
  >
  > ```powershell
  > py -3.12 -c "import PyInstaller, sys; print(sys.version)"
  > ```
  >
  > This must print a `3.12.x` version. If it errors, install Python 3.12 and the dev
  > dependencies below.

- Windows (the build targets Win64).

## 1. Install the build dependencies

```powershell
py -3.12 -m pip install -r packaging/requirements-dev.txt
```

## 2. Build the one-folder bundle

```powershell
py -3.12 -m PyInstaller --noconfirm packaging/FoobarOverlay.spec
```

This produces a **one-folder** bundle at `dist/FoobarOverlay/`:

```
dist/FoobarOverlay/
   FoobarOverlay.exe
   _internal/        <- bundled Python runtime + all overlay assets
```

> **Run the exe in place.** `FoobarOverlay.exe` needs its sibling `_internal/` folder to
> run — do not move the exe out of `dist/FoobarOverlay/`. When distributing, zip the whole
> folder, not the bare exe.

## 3. Verify the bundled assets

The overlay's visual fidelity depends on the glow/spectrum assets being byte-for-byte
identical inside the bundle. Run the verification gate:

```powershell
py -3.12 packaging/verify_assets.py dist/FoobarOverlay
```

It must exit `0`. A non-zero exit means the bundled assets drifted from the source — fix
that before shipping.
