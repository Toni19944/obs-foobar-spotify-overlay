@echo off
start /min "Spectrum Server" python "%~dp0spectrum-server.py"
start /min "Overlay Server" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay-server.ps1"
start /min "Chat-Clip Server" cmd /c "D:\StreamAssets\Chat-Clip-Player\serve.bat"

REM Wait ~1.5 seconds
powershell -command "Start-Sleep -Milliseconds 1500"

REM Launch OBS via Start Menu shortcut
start "" "%ProgramData%\Microsoft\Windows\Start Menu\Programs\OBS Studio.lnk"

