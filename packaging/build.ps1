# build.ps1 - one-command build wrapper for the single-exe + GUI bundle (feature 008,
# converted to a one-folder bundle in feature 010 to kill the ~60 s launch hang).
# Run from the repo root:
#
#     ./packaging/build.ps1
#
# Produces the one-folder bundle dist/FoobarOverlay/ (FoobarOverlay.exe + _internal/)
# and a Desktop shortcut to it. Nothing is extracted to %TEMP% at launch, so the
# control panel opens in seconds. Requires the dev deps:
#     python -m pip install -r packaging/requirements-dev.txt

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Building FoobarOverlay (one-folder) via PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm "packaging/FoobarOverlay.spec"

$distDir = Join-Path $repoRoot "dist/FoobarOverlay"
$exe = Join-Path $distDir "FoobarOverlay.exe"
if (Test-Path $exe) {
    $size = "{0:N1} MB" -f (((Get-ChildItem -Recurse -File $distDir | Measure-Object -Property Length -Sum).Sum) / 1MB)
    Write-Host ""
    Write-Host "Built: $distDir ($size folder)" -ForegroundColor Green
    Write-Host "  -> $exe" -ForegroundColor DarkGray
} else {
    Write-Host "Build finished but $exe was not found - check the PyInstaller output." -ForegroundColor Red
    exit 1
}

# Embedded-asset verification (feature 009, FR-003 / C4): fail the build if the
# carried spectrum-server.py / nowplaying-overlay.html are not byte-identical to the
# committed glow-fixed files, or if the configurator generators still carry pre-fix
# glow code. A rebuild can never silently ship a pre-fix snapshot. Pointed at the
# one-folder bundle dir (feature 010).
Write-Host ""
Write-Host "Verifying carried glow assets..." -ForegroundColor Cyan
python "packaging/verify_assets.py" $distDir
if ($LASTEXITCODE -ne 0) {
    Write-Host "Embedded-asset verification FAILED - see above. Build rejected." -ForegroundColor Red
    exit 1
}

# Desktop shortcut so the operator launches with one double-click and never touches
# the folder internals (FR-010 / research D3).
Write-Host ""
Write-Host "Creating Desktop shortcut..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "make_shortcut.ps1")
