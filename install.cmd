@echo off
REM Thomas AI - Windows installer
REM Usage: install.cmd   (run it from the Thomas project root)
REM run-ui.cmd is the one-click path; this script installs from a checkout into .venv.
setlocal

echo.
echo   Thomas AI Installer
echo   ============================
echo.

REM -- Step 1: Check Python ------------------------------------
echo [thomas] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    python3 --version >nul 2>&1
    if errorlevel 1 (
        echo [thomas] ERROR: Python 3.10 to 3.13 not found.
        echo [thomas] Install Python from https://python.org
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

REM Thomas pins numpy 2.2.6, which has no prebuilt package for Python 3.14 or newer, so
REM pip would try to compile it. 3.10 to 3.13 is the range pyproject.toml lists.
%PYTHON% -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [thomas] ERROR: Python 3.10 to 3.13 is required, found:
    %PYTHON% --version
    echo [thomas] Install Python 3.12 from https://python.org
    exit /b 1
)

echo [thomas] Found:
%PYTHON% --version

REM -- Step 2: Check we're in the right directory --------------
if not exist pyproject.toml (
    echo [thomas] ERROR: pyproject.toml not found.
    echo [thomas] Run this script from the Thomas project root.
    exit /b 1
)

REM -- Step 3: Virtual environment ------------------------------
REM Thomas pins exact versions of several packages, so keep them out of the global
REM Python. run-ui.cmd uses this same .venv. Set THOMAS_NO_VENV=1 to skip it.
if not "%THOMAS_NO_VENV%"=="1" (
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [thomas] Creating virtual environment in .venv...
        %PYTHON% -m venv .venv
        if errorlevel 1 (
            echo [thomas] ERROR: Could not create the virtual environment.
            exit /b 1
        )
    )
    set PYTHON=.venv\Scripts\python.exe
    REM An editable install already in this .venv, which run-ui.cmd makes, stays editable.
    REM A copy would replace it, and every launch would then run the old copy.
    if not "%THOMAS_DEV%"=="1" if exist ".venv\Lib\site-packages\__editable__*thomas_ai*" (
        echo [thomas] .venv already holds an editable install, so keeping it editable.
        set THOMAS_DEV=1
    )
)

REM -- Step 4: Install ------------------------------------------
REM The web UI (thomas serve) needs the server extra and thomas repl needs the repl
REM extra; a plain "pip install ." leaves both out.
REM run-ui.cmd installs into this same .venv in editable mode. Set THOMAS_DEV=1 to do the
REM same here, so edits to this checkout take effect; otherwise pip installs a copy.
echo.
echo [thomas] Installing Thomas (this can take a few minutes)...
if "%THOMAS_DEV%"=="1" (
    echo [thomas] Editable install: edits to this checkout take effect.
    %PYTHON% -m pip install -e ".[server,repl]" --quiet
) else (
    echo [thomas] Installing a copy. Set THOMAS_DEV=1 to install in editable mode instead.
    %PYTHON% -m pip install ".[server,repl]" --quiet
)
if errorlevel 1 (
    echo [thomas] ERROR: Installation failed.
    exit /b 1
)
echo [thomas] Thomas installed successfully.

REM -- Step 5: Run setup if needed ------------------------------
if not exist thomas.toml (
    echo.
    echo [thomas] No config found. Running setup wizard...
    %PYTHON% -m thomas setup
) else (
    echo [thomas] Config already exists.
)

REM -- Step 6: Done ----------------------------------------------
echo.
echo   Installation complete!
echo.
echo   Quick start:
if not "%THOMAS_NO_VENV%"=="1" echo     .venv\Scripts\activate       - use the environment Thomas was installed into
echo     thomas chat "hello"    - single query
echo     thomas repl            - interactive mode
echo     thomas serve           - web UI at http://127.0.0.1:8899
echo     thomas doctor          - check system health
echo.
echo   Or run run-ui.cmd to start the web UI in one step.
echo.
pause
