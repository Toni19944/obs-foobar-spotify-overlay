# overlay-server.ps1
# Serves the overlay HTML to OBS with cached static-file + bg-list serving,
# plus a Spotify metadata adapter (token refresh + currently-playing).
# Keep this window open while streaming.

# (FR-032) Additive, default-preserving port config: read from the env block when
# the GUI launcher sets it, otherwise fall back to today's value (8081).
$port = if ($env:OVERLAY_PORT) { [int]$env:OVERLAY_PORT } else { 8081 }
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── METADATA ADAPTER ── start
#   Two now-playing sources, selected by the GUI via METADATA_SOURCE
#   (default 'smtc'):
#     • smtc   — local Windows System Media Transport Controls (the Win+A media
#                panel). No network, no OAuth, no rate limits. The default.
#     • webapi — Spotify Web API (Authorization Code + PKCE; creds via the child
#                env block). Kept as an opt-in fallback, hardened with a call
#                throttle + Retry-After backoff + last-good cache so a 429 can
#                never spiral into a multi-hour ban again.
#   Both return the SAME JSON contract the overlay consumes.
$MetadataSource      = if ($env:METADATA_SOURCE) { $env:METADATA_SOURCE.ToLower() } else { 'smtc' }
$SPOTIFY_TIMEOUT_SEC = 5   # bound outbound calls / WinRT awaits so nothing wedges the request loop

# ── Web API state (used only when $MetadataSource -eq 'webapi') ──
$CLIENT_ID               = $env:SPOTIFY_CLIENT_ID
$script:accessToken      = $null
$script:refreshToken     = $env:SPOTIFY_REFRESH_TOKEN
$script:tokenExpiry      = [DateTime]::MinValue
$script:lastGood         = '{"is_playing":false}'
$script:backoffUntil     = [DateTime]::MinValue
$script:lastCallAt       = [DateTime]::MinValue
$WEBAPI_MIN_INTERVAL_SEC = 3   # server-side floor between Spotify calls, independent of the overlay poll rate

function Invoke-TokenRefresh {
    try {
        $body = "grant_type=refresh_token&refresh_token=$($script:refreshToken)&client_id=$CLIENT_ID"
        $response = Invoke-RestMethod -Uri "https://accounts.spotify.com/api/token" `
                                      -Method Post -Body $body `
                                      -ContentType "application/x-www-form-urlencoded" `
                                      -TimeoutSec $SPOTIFY_TIMEOUT_SEC
        $script:accessToken = $response.access_token
        $script:tokenExpiry = [DateTime]::UtcNow.AddSeconds($response.expires_in - 60)
        if ($response.refresh_token) { $script:refreshToken = $response.refresh_token }
        Write-Host "Token refreshed." -ForegroundColor DarkGray
    } catch {
        Write-Host "Token refresh failed: $_" -ForegroundColor Red
    }
}

# Hardened Web API proxy. Throttles to WEBAPI_MIN_INTERVAL_SEC regardless of how
# fast the overlay polls, honors Retry-After on 429 by NOT calling until it
# elapses, caches the last good payload, and only reports not-playing on a
# genuine 204 — so a rate limit degrades to "holds last track" instead of a
# death spiral that Spotify escalates into a long ban.
function Get-WebApiPayload {
    $now = [DateTime]::UtcNow
    if ($now -lt $script:backoffUntil) { return $script:lastGood }
    if (($now - $script:lastCallAt).TotalSeconds -lt $WEBAPI_MIN_INTERVAL_SEC) { return $script:lastGood }
    $script:lastCallAt = $now
    if ($now -ge $script:tokenExpiry) { Invoke-TokenRefresh }
    try {
        $r = Invoke-WebRequest -Uri "https://api.spotify.com/v1/me/player/currently-playing" `
             -Headers @{ Authorization = "Bearer $($script:accessToken)" } `
             -TimeoutSec $SPOTIFY_TIMEOUT_SEC -UseBasicParsing
        if ($r.StatusCode -eq 204) { $script:lastGood = '{"is_playing":false}' }
        else { $script:lastGood = $r.Content }
        return $script:lastGood
    } catch {
        $sec  = 10
        $resp = $_.Exception.Response
        if ($resp -and [int]$resp.StatusCode -eq 429) {
            $ra = $resp.Headers['Retry-After']
            if ($ra) { [int]::TryParse($ra, [ref]$sec) | Out-Null }
            if ($sec -gt 3600) { $sec = 3600 }
            Write-Host "Spotify 429 - backing off ${sec}s (not calling until then)." -ForegroundColor Yellow
        }
        $script:backoffUntil = [DateTime]::UtcNow.AddSeconds($sec)
        return $script:lastGood
    }
}

# ── SMTC state + reader (used only when $MetadataSource -eq 'smtc') ──
$script:smtcMgr = $null
$script:asTask  = $null

function Await($op, $resultType) {
    $t = $script:asTask.MakeGenericMethod($resultType).Invoke($null, @($op))
    [void]$t.Wait($SPOTIFY_TIMEOUT_SEC * 1000)
    return $t.Result
}

# Reads the local Spotify SMTC session into the overlay's JSON contract. No
# network. Paused/stopped returns is_playing:false but keeps the item (so the
# card holds the last track unless the overlay's hideWhenPaused flag is set),
# matching the Web API's currently-playing behavior. Album art via the SMTC
# thumbnail is a follow-up (WinRT stream marshaling is unreliable from PS 5.1);
# images stays empty, matching the overlay default (ALBUM_ART_BG off).
function Get-SmtcPayload {
    if (-not $script:smtcMgr) { return '{"is_playing":false}' }
    try {
        $session = $null
        foreach ($s in $script:smtcMgr.GetSessions()) {
            if ($s.SourceAppUserModelId -like '*Spotify*') { $session = $s; break }
        }
        if (-not $session) { return '{"is_playing":false}' }

        $props  = Await ($session.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        $title  = [string]$props.Title
        $artist = [string]$props.Artist
        if ([string]::IsNullOrEmpty($title)) { return '{"is_playing":false}' }

        $tl = $session.GetTimelineProperties()
        $pi = $session.GetPlaybackInfo()
        $isPlaying = ($pi.PlaybackStatus -eq [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionPlaybackStatus]::Playing)

        $durMs = [int64]((($tl.EndTime) - ($tl.StartTime)).TotalMilliseconds)
        $posMs = [int64]($tl.Position.TotalMilliseconds)
        if ($durMs -lt 0) { $durMs = 0 }
        if ($posMs -lt 0) { $posMs = 0 }

        # Stable track id from title|artist (SMTC exposes no track id).
        $md5     = [System.Security.Cryptography.MD5]::Create()
        $idBytes = $md5.ComputeHash([Text.Encoding]::UTF8.GetBytes("$title|$artist"))
        $id      = (([BitConverter]::ToString($idBytes)) -replace '-','').Substring(0,16).ToLower()

        $obj = [ordered]@{
            is_playing  = $isPlaying
            progress_ms = $posMs
            item = [ordered]@{
                id          = $id
                name        = $title
                artists     = @(@{ name = $artist })
                album       = [ordered]@{ images = @() }
                duration_ms = $durMs
            }
        }
        return ($obj | ConvertTo-Json -Depth 6 -Compress)
    } catch {
        Write-Host "SMTC read error: $_" -ForegroundColor Red
        return '{"is_playing":false}'
    }
}

# ── Source init ────────────────────────────────────────────────
if ($MetadataSource -eq 'webapi') {
    if (-not $CLIENT_ID -or -not $script:refreshToken) {
        Write-Host ""
        Write-Host "  ERROR: metadataSource=webapi but Spotify credentials were not provided." -ForegroundColor Red
        Write-Host "  Use 'Connect Spotify' in the GUI, or switch metadataSource to 'smtc'." -ForegroundColor Yellow
        Write-Host ""
        exit 1
    }
    Invoke-TokenRefresh
    Write-Host "Metadata source: Spotify Web API." -ForegroundColor DarkGray
} else {
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
        $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties,Windows.Media.Control,ContentType=WindowsRuntime]
        $script:asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
        $script:smtcMgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
        Write-Host "Metadata source: Windows SMTC (local; no OAuth, no rate limits)." -ForegroundColor DarkGray
    } catch {
        Write-Host "SMTC init failed: $_" -ForegroundColor Red
    }
}
# ── METADATA ADAPTER ── end

# ── (#2) Cache bg-list JSON at startup ───────────────────────────
$bgListBytes = $null

function Build-BgListCache {
    $bgDir = Join-Path $root "bg"
    # (#3) Single list, no array concatenation
    $files = [System.Collections.Generic.List[string]]::new()

    if (Test-Path $bgDir) {
        $exts = @("*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif")
        foreach ($ext in $exts) {
            Get-ChildItem -Path $bgDir -Filter $ext | ForEach-Object {
                $files.Add("bg/$($_.Name)")
            }
        }
    }

    $json = "[" + (($files | ForEach-Object { "`"$_`"" }) -join ",") + "]"
    return [Text.Encoding]::UTF8.GetBytes($json)
}

$bgListBytes = Build-BgListCache

# ── (#4) Static file cache ───────────────────────────────────────
$fileCache = @{}

function Get-CachedFile([string]$filePath) {
    $lastWrite = [IO.File]::GetLastWriteTimeUtc($filePath)
    $cached    = $fileCache[$filePath]

    if ($cached -and $cached.LastWrite -eq $lastWrite) {
        return $cached.Bytes
    }

    $bytes = [IO.File]::ReadAllBytes($filePath)
    $fileCache[$filePath] = @{ Bytes = $bytes; LastWrite = $lastWrite }
    return $bytes
}

# ── (#6) MIME type map ───────────────────────────────────────────
$mimeTypes = @{
    ".html" = "text/html"
    ".css"  = "text/css"
    ".js"   = "application/javascript"
    ".json" = "application/json"
    ".svg"  = "image/svg+xml"
    ".jpg"  = "image/jpeg"
    ".jpeg" = "image/jpeg"
    ".png"  = "image/png"
    ".webp" = "image/webp"
    ".avif" = "image/avif"
}

# ── Listener ─────────────────────────────────────────────────────
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$port/")
$listener.Start()

Write-Host "Overlay server running at http://localhost:$port/" -ForegroundColor Green
Write-Host "Close this window to stop." -ForegroundColor DarkGray
Write-Host ""

while ($listener.IsListening) {
    $ctx   = $listener.GetContext()
    $req   = $ctx.Request
    $res   = $ctx.Response
    $path  = $req.Url.LocalPath.TrimStart('/')
    $query = $req.Url.Query

    $res.Headers.Add("Access-Control-Allow-Origin", "*")

    try {
        # ── METADATA ADAPTER ── start
        if ($path -eq "api/spotify/current") {
            # Source chosen at startup: SMTC (local, default) or hardened Web API.
            # Both return the same JSON contract; token refresh + rate-limit
            # backoff live inside Get-WebApiPayload, so the loop stays simple.
            $payload = if ($MetadataSource -eq 'webapi') { Get-WebApiPayload } else { Get-SmtcPayload }
            $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
            $res.ContentType = "application/json"
            $res.ContentLength64 = $bytes.Length
            $res.OutputStream.Write($bytes, 0, $bytes.Length)
            # ── METADATA ADAPTER ── end

        } elseif ($path -eq "bg-list") {
            # (#2) Serve cached bg-list
            $res.ContentType = "application/json"
            $res.ContentLength64 = $bgListBytes.Length
            $res.OutputStream.Write($bgListBytes, 0, $bgListBytes.Length)

        } else {
            # Serve static file
            if ($path -eq "") { $path = "nowplaying-spotify.html" }
            $file = Join-Path $root $path

            if (Test-Path $file) {
                # (#4) Cached file read with modification check
                $bytes = Get-CachedFile $file
                $ext   = [IO.Path]::GetExtension($file).ToLower()
                # (#6) Extended MIME type lookup
                $res.ContentType = if ($mimeTypes.ContainsKey($ext)) { $mimeTypes[$ext] } else { "application/octet-stream" }
                $res.ContentLength64 = $bytes.Length
                $res.OutputStream.Write($bytes, 0, $bytes.Length)
            } else {
                $res.StatusCode = 404
            }
        }
    } catch {
        $res.StatusCode = 500
        Write-Host "Error: $_" -ForegroundColor Red
    }

    $res.Close()
}
