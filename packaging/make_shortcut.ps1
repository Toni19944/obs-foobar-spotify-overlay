# make_shortcut.ps1 - create a Desktop shortcut to the one-folder bundle (feature 010).
#
# The operator launches the product by double-clicking this single icon and never
# opens or arranges the dist/FoobarOverlay/ folder internals (FR-010 / research D3).
# Invoked at the end of build.ps1; safe to run standalone after a build.
#
#     ./packaging/make_shortcut.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repoRoot "dist/FoobarOverlay/FoobarOverlay.exe"
$workDir = Join-Path $repoRoot "dist/FoobarOverlay"
$icon = Join-Path $repoRoot "launcher/resources/tray.ico"

if (-not (Test-Path $exe)) {
    Write-Host "Cannot create shortcut: $exe not found - build the one-folder bundle first." -ForegroundColor Red
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "FoobarOverlay.lnk"

# Standard WScript.Shell COM API - no extra dependency (research D3).
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = $workDir
if (Test-Path $icon) {
    $lnk.IconLocation = $icon
}
$lnk.Description = "Foobar / Spotify Overlay"
$lnk.Save()

Write-Host "Desktop shortcut created: $lnkPath" -ForegroundColor Green
Write-Host "  -> $exe" -ForegroundColor DarkGray
