# overlay-server.ps1
# Serves the overlay HTML to OBS with cached static-file + bg-list serving,
# plus a Spotify metadata adapter (token refresh + currently-playing).
# Keep this window open while streaming.

# (FR-032) Additive, default-preserving port config: read from the env block when
# the GUI launcher sets it, otherwise fall back to today's value (8081).
$port = if ($env:OVERLAY_PORT) { [int]$env:OVERLAY_PORT } else { 8081 }
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── METADATA ADAPTER (Spotify): token refresh + currently-playing ── start
#   (T023) AUTH-PLUMBING EDIT — credentials now arrive via the child ENV BLOCK
#   from the GUI launcher (Authorization Code + PKCE; NO client secret). This
#   server therefore:
#     • holds no hardcoded secret,
#     • never reads/writes the plaintext spotify-token.txt,
#     • no longer runs the in-process browser OAuth (the GUI owns first-run auth
#       and the DPAPI-encrypted store).
#   The render / HTTP / metadata contract (and the 5 s timeout) is unchanged.
#   The static-file cache, bg-list cache, MIME map, and listener loop below are
#   the shared (reference-identical) static-serving core.

# ── Spotify config (from the GUI's env block) ──────────────────
$CLIENT_ID           = $env:SPOTIFY_CLIENT_ID
$SPOTIFY_TIMEOUT_SEC = 5   # bound outbound Spotify calls so a slow/failed API never wedges the request loop (FR-010)

# ── Token state ────────────────────────────────────────────────
$script:accessToken  = $null
$script:refreshToken = $env:SPOTIFY_REFRESH_TOKEN
$script:tokenExpiry  = [DateTime]::MinValue

# ── Token helper (PKCE refresh — public client, no secret) ─────
function Invoke-TokenRefresh {
    try {
        $body = "grant_type=refresh_token&refresh_token=$($script:refreshToken)&client_id=$CLIENT_ID"
        $response = Invoke-RestMethod -Uri "https://accounts.spotify.com/api/token" `
                                      -Method Post -Body $body `
                                      -ContentType "application/x-www-form-urlencoded" `
                                      -TimeoutSec $SPOTIFY_TIMEOUT_SEC
        $script:accessToken = $response.access_token
        $script:tokenExpiry = [DateTime]::UtcNow.AddSeconds($response.expires_in - 60)
        # Spotify may rotate the refresh token; keep the in-memory copy current.
        # (The GUI's DPAPI store is the durable owner and re-persists on its own
        # refresh — this process holds the rotated value only for its lifetime.)
        if ($response.refresh_token) { $script:refreshToken = $response.refresh_token }
        Write-Host "Token refreshed." -ForegroundColor DarkGray
    } catch {
        # A failed refresh degrades gracefully — the currently-playing proxy
        # returns {"is_playing":false} and the loop stays alive (FR-010).
        Write-Host "Token refresh failed: $_" -ForegroundColor Red
    }
}

# ── Validate creds (now supplied by the GUI launcher) ──────────
if (-not $CLIENT_ID -or -not $script:refreshToken) {
    Write-Host ""
    Write-Host "  ERROR: Spotify credentials not provided via the env block." -ForegroundColor Red
    Write-Host "  Launch this server through the GUI and use 'Connect Spotify' first." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ── Initial token refresh ──────────────────────────────────────
Invoke-TokenRefresh
# ── METADATA ADAPTER (Spotify) ── end

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

    # ── METADATA ADAPTER (Spotify) ── start
    # Refresh the access token if it is about to expire (a failed refresh
    # degrades gracefully and does not wedge or crash the loop — FR-010).
    if ([DateTime]::UtcNow -ge $script:tokenExpiry) { Invoke-TokenRefresh }
    # ── METADATA ADAPTER (Spotify) ── end

    try {
        # ── METADATA ADAPTER (Spotify) ── start
        if ($path -eq "api/spotify/current") {
            #   Bounded, non-blocking currently-playing proxy. -TimeoutSec keeps
            #   the single-threaded HttpListener loop responsive when Spotify is
            #   slow; the try/catch degrades to {"is_playing":false} on a
            #   204 / error / 429 so the overlay holds gracefully (FR-010).
            $payload = '{"is_playing":false}'
            try {
                $spotifyRes = Invoke-WebRequest `
                    -Uri "https://api.spotify.com/v1/me/player/currently-playing" `
                    -Headers @{ Authorization = "Bearer $($script:accessToken)" } `
                    -TimeoutSec $SPOTIFY_TIMEOUT_SEC -UseBasicParsing
                if ($spotifyRes.StatusCode -ne 204) { $payload = $spotifyRes.Content }
            } catch {
                $payload = '{"is_playing":false}'
            }
            $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
            $res.ContentType = "application/json"
            $res.ContentLength64 = $bytes.Length
            $res.OutputStream.Write($bytes, 0, $bytes.Length)
            # ── METADATA ADAPTER (Spotify) ── end

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
