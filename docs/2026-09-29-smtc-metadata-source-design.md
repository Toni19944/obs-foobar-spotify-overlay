# Design: SMTC now-playing source (with Web API kept as fallback)

Status: draft for review · Branch: `archive/exe-bundle` (via `018-spotify-url-flags`) · 2026-09-29

## Problem

The Spotify overlay gets now-playing data by polling Spotify's Web API
(`/v1/me/player/currently-playing`) once per second through
`Now-Playing-Spotify/overlay-server.ps1`. This has two chronic failure modes,
both hit during testing on 2026-09-29:

1. **Rate limiting → multi-hour lockout.** 1 s polling with no backoff, and a
   server that treats *any* error (including HTTP 429) as `{"is_playing":false}`,
   creates a death spiral: once rate-limited, the overlay keeps hammering every
   second, and Spotify escalated the block to `Retry-After: 53383` (~14.8 h).
   The card blanks and never recovers until the ban clears.
2. **OAuth friction.** Client ID, a Spotify developer app, redirect URI,
   PKCE token store (`spotify.dat`), token refresh, and the "no active device"
   (`204`) case that also blanks the card.

## Insight (proven)

Windows exposes now-playing locally via **SMTC** (System Media Transport
Controls) — the same data the Win+A media panel shows. The referenced project
[`lingeriegoat/OBSSpotifyPlugin`](https://github.com/lingeriegoat/OBSSpotifyPlugin)
uses exactly this (`GlobalSystemMediaTransportControlsSessionManager` via
C++/WinRT) and never touches the Web API.

A PowerShell WinRT spike on this machine (2026-09-29) confirmed it works from
**our exact stack** and returns everything we need — even while the Web API was
banned:

```
SMTC session: SpotifyAB.SpotifyMusic...!Spotify
status=Paused  title='Leave It All Behind'  artist='DJ Zinc'  pos=43s  dur=128s  hasThumb=True
```

SMTC is a free local OS call: **no network, no OAuth, no client ID, no rate
limits.** Polling it even 4×/s is fine.

## Goals

- Make SMTC the **default** metadata source for the Spotify overlay.
- Eliminate rate-limit lockouts and OAuth friction on the default path.
- Keep the Web API adapter as a **selectable fallback** (not deleted), hardened
  so it can never spiral into a long ban again.
- Keep the overlay HTML essentially unchanged (same JSON contract).
- No new bundled dependencies; no change to the PyInstaller spec.

## Non-goals

- Generic multi-app now-playing (we match the Spotify SMTC session only for now).
- A launcher GUI toggle in this pass (settings-file field first; GUI is a fast follow — see D5).
- Any change to the foobar overlay or the shared `spectrum-server.py`.

## Key decisions (please confirm on review)

- **D1 — Manual source selection, no silent auto-fallback.** A setting
  `metadataSource: "smtc" | "webapi"` (default `"smtc"`). If SMTC finds no
  Spotify session, the overlay shows nothing-playing — it does **not** silently
  fall back to the Web API (that could quietly re-introduce the ban risk).
  Switching to the Web API is a deliberate choice.
- **D2 — Hardened Web API fallback.** When `metadataSource: "webapi"`, the
  server (a) calls Spotify at most once per `WEBAPI_MIN_INTERVAL` (default 3 s)
  regardless of how fast the overlay polls, (b) on `429` reads `Retry-After` and
  **stops calling** until it elapses, (c) caches the last good payload and
  serves it during backoff/transient errors, (d) only reports not-playing on a
  genuine `204`. This removes the death spiral.
- **D3 — SMTC adapter in `overlay-server.ps1`** (PowerShell WinRT). Manager
  created once at startup and reused. Per request: pick the session whose
  `SourceAppUserModelId` contains `Spotify`; read `Title`, `Artist`,
  `PlaybackStatus`, `TimelineProperties` (position/duration), and `Thumbnail`.
- **D4 — Same JSON contract.** Server returns the shape the overlay already
  consumes: `{is_playing, item:{id, name, artists:[{name}], album:{images:[{url}]},
  duration_ms}, progress_ms}`. `id` = short hash of `title|artist` (SMTC has no
  track id); album art = thumbnail read once per track and returned as a
  `data:` URI, cached by `id` to avoid re-reading every poll. Overlay HTML poll
  stays as-is (SMTC has no rate limit, so 1 s is fine).
- **D5 — Selection plumbing.** `metadataSource` lives in `settings.json`
  (per-profile), passed to `overlay-server.ps1` via the child env block
  (`METADATA_SOURCE`). GUI toggle deferred to a follow-up unless you want it now.
- **D6 — Build.** No new deps: SMTC via OS WinRT + `System.Runtime.WindowsRuntime`
  (already present on Windows). `FoobarOverlay.spec` unchanged.
- **D7 — OAuth retained.** `spotify_auth.py` and the callback stay, because the
  Web API fallback still needs them. Not dead code.

## Architecture

```
overlay (nowplaying-spotify.html)   ── GET /api/spotify/current (unchanged, ~1s) ──►  overlay-server.ps1
                                                                                       │
                                          METADATA_SOURCE = "smtc" (default) ──────────┤
                                                                                       │
                                          ┌── smtc ──►  read GlobalSystemMediaTransportControls (local, free)
                                          │             └─ map → same JSON, art cached per track
                                          └── webapi ─► throttled + backoff Web API proxy (hardened)
```

The overlay is source-agnostic: it always fetches the same endpoint and shape.
Throttling/backoff live in the server's webapi branch, so the overlay stays dumb
and needs no polling changes.

## SMTC adapter detail (`overlay-server.ps1`, `metadataSource=smtc`)

- **Init once:** load WinRT types, `RequestAsync()` the session manager, keep it.
- **Per `/api/spotify/current`:**
  - `GetSessions()`, pick the first whose `SourceAppUserModelId` matches `*Spotify*`.
    (If none: return `{"is_playing":false}`.)
  - `TryGetMediaPropertiesAsync()` → `Title`, `Artist`.
  - `GetTimelineProperties()` → `progress_ms = Position`, `duration_ms = EndTime - StartTime`.
  - `GetPlaybackInfo().PlaybackStatus` → `is_playing = (== Playing)`.
  - `id = shortHash(Title + '|' + Artist)`.
  - **Art:** if `id` != cached id, read `Thumbnail` stream → bytes → `data:image/...;base64,` URI, cache `{id → uri}`. Put in `item.album.images[0].url`.
- WinRT async is handled with the proven `AsTask().Wait()` helper; per-request
  cost is a few tens of ms — negligible at a 1 s poll.

## Web API adapter detail (`metadataSource=webapi`, hardened)

Server-side state: `$lastGood` (payload), `$backoffUntil` (DateTime),
`$lastCallAt`. On request:
- If `now < backoffUntil` **or** `now - lastCallAt < WEBAPI_MIN_INTERVAL`: return `$lastGood` (no Spotify call).
- Else call currently-playing:
  - `200` → cache + return.
  - `204` → return `{"is_playing":false}` (genuine idle).
  - `429` → `backoffUntil = now + Retry-After` (capped), return `$lastGood`.
  - other error/timeout → short backoff (e.g., 10 s), return `$lastGood`.

## Overlay changes

Minimal. The fetch/poll and `updateUI` stay. `item.id` is now the server's
title|artist hash (still works as the track-change key). No new flags.

## Edge cases

- **Spotify not running / nothing in SMTC:** `{"is_playing":false}` → card hidden (correct).
- **Browser playback (Spotify web player):** SMTC session AUMID won't contain
  "Spotify.exe"; out of scope for v1 (desktop app only). Could broaden matching later.
- **Paused:** SMTC reports `Paused` → `is_playing:false`; respects the existing
  `hideWhenPaused` flag behavior.
- **Art churn:** cached per track id so we read the thumbnail once per song, not every poll.
- **Two sources of truth:** only one adapter runs per launch (chosen by setting); no mixing.

## Verification

- **SMTC read (unit-ish):** a PowerShell/py probe that maps a live SMTC session
  to the JSON shape and asserts fields (already spiked).
- **Overlay unchanged:** re-run the Playwright/Edge parity suite (flags + no-query
  parity + glow) against the served page — must still pass.
- **Contract:** curl `/api/spotify/current` in `smtc` mode returns valid JSON with
  a playing track when Spotify plays; `{"is_playing":false}` when stopped.
- **Web API hardening:** simulate 429 (or point at a stub) and confirm the server
  stops calling until `Retry-After` elapses and keeps serving last-good — i.e.
  no death spiral.

## Rollout

Default `metadataSource=smtc` on next build. Existing users' `settings.json`
gets the field defaulted to `smtc` on load. Web API remains one setting away.
