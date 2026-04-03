# overlay-server.ps1
# Serves the overlay HTML and proxies Beefweb API requests.
# Keep this window open while streaming.

$port    = 8081
$beefweb = "http://localhost:8880"
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── (#1) Persistent WebClient for beefweb proxy ─────────────────
$wc = New-Object System.Net.WebClient

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
        if ($path -like "api*") {
            # (#1) Proxy to Beefweb via persistent WebClient
            $proxyRes = $wc.DownloadData("$beefweb/$path$query")
            $res.ContentType = "application/json"
            $res.ContentLength64 = $proxyRes.Length
            $res.OutputStream.Write($proxyRes, 0, $proxyRes.Length)

        } elseif ($path -eq "bg-list") {
            # (#2) Serve cached bg-list
            $res.ContentType = "application/json"
            $res.ContentLength64 = $bgListBytes.Length
            $res.OutputStream.Write($bgListBytes, 0, $bgListBytes.Length)

        } else {
            # Serve static file
            if ($path -eq "") { $path = "nowplaying-overlay.html" }
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
