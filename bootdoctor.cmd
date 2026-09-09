@echo off
setlocal
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\bootdoctor.ps1" %*
exit /b %ERRORLEVEL%
