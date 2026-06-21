@echo off
start /min "Spectrum Server" python "%~dp0spectrum-server.py"
start /min "Overlay Server" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay-server.ps1"
