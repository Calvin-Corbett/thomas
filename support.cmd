@echo off
setlocal
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\support_bundle.ps1" %*
exit /b %ERRORLEVEL%
