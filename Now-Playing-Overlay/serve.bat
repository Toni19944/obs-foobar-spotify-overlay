@echo off
start /min "Spectrum Server" python "%~dp0spectrum-server.py"
start /min "Overlay Server" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay-server.ps1"
REM no minimized window, only in TM as a powershell.exe, swap for teh above powershell line
REM "%ComSpec%" /c C:\Windows\System32\WindowsPowerShell\v1.0\Powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay-server.ps1"
