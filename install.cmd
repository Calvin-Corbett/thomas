@echo off
REM Thomas AI — Windows installer
REM Usage: install.cmd
setlocal enabledelayedexpansion

echo.
echo   Thomas AI Installer
echo   ============================
echo.

REM ── Step 1: Check Python ──────────────────────────────────
echo [thomas] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    python3 --version >nul 2>&1
    if errorlevel 1 (
        echo [thomas] ERROR: Python 3.10+ not found.
        echo [thomas] Install Python from https://python.org
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

echo [thomas] Found:
%PYTHON% --version

REM ── Step 2: Check we're in the right directory ────────────
if not exist pyproject.toml (
    echo [thomas] ERROR: pyproject.toml not found.
    echo [thomas] Run this script from the Thomas project root.
    exit /b 1
)

REM ── Step 3: Install ───────────────────────────────────────
echo.
echo [thomas] Installing Thomas...
%PYTHON% -m pip install . --quiet
if errorlevel 1 (
    echo [thomas] ERROR: Installation failed.
    exit /b 1
)
echo [thomas] Thomas installed successfully.

REM ── Step 4: Run setup if needed ───────────────────────────
if not exist thomas.toml (
    echo.
    echo [thomas] No config found. Running setup wizard...
    %PYTHON% -m thomas setup
) else (
    echo [thomas] Config already exists.
)

REM ── Step 5: Done ──────────────────────────────────────────
echo.
echo   Installation complete!
echo.
echo   Quick start:
echo     thomas chat "hello"    — single query
echo     thomas repl            — interactive mode
echo     thomas serve           — web UI at localhost:8899
echo     thomas doctor          — check system health
echo.
pause
