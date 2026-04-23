@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\setup.ps1" -Easy -AutoInstallTools %*
