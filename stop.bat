@echo off
taskkill /fi "WindowTitle eq Windows Powershell*" /f >nul 2>&1
taskkill /fi "WindowTitle eq Spectrum Server*" /f >nul 2>&1
