#!/usr/bin/env bash
# Thomas AI — Cross-platform installer for macOS and Linux.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Calvin-Corbett/thomas/main/install.sh | bash
#   # or locally:
#   bash install.sh
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${CYAN}[thomas]${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}[thomas]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[thomas]${NC} %s\n" "$*"; }
fail()  { printf "${RED}[thomas]${NC} %s\n" "$*"; exit 1; }

# ── Step 1: Check Python ────────────────────────────────────
info "Checking Python installation..."

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.10+ is required but not found. Install Python first: https://python.org"
fi

ok "Found $PYTHON ($($PYTHON --version 2>&1))"

# ── Step 2: Determine install directory ─────────────────────
INSTALL_DIR="${THOMAS_INSTALL_DIR:-$(pwd)}"
if [ ! -f "$INSTALL_DIR/pyproject.toml" ]; then
    # Try to find it relative to script location
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
        INSTALL_DIR="$SCRIPT_DIR"
    else
        fail "Cannot find pyproject.toml. Run this script from the Thomas project root."
    fi
fi
info "Installing from: $INSTALL_DIR"

# ── Step 3: Virtual environment (optional) ──────────────────
USE_VENV=false
if [ "${THOMAS_NO_VENV:-}" != "1" ]; then
    printf "${CYAN}[thomas]${NC} Create a virtual environment? [Y/n] "
    read -r answer </dev/tty 2>/dev/null || answer="y"
    answer="${answer:-y}"
    if [[ "$answer" =~ ^[Yy] ]]; then
        USE_VENV=true
    fi
fi

if $USE_VENV; then
    VENV_DIR="$INSTALL_DIR/.venv"
    if [ -d "$VENV_DIR" ]; then
        info "Existing venv found at $VENV_DIR"
    else
        info "Creating virtual environment..."
        $PYTHON -m venv "$VENV_DIR"
        ok "Created venv: $VENV_DIR"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PYTHON="python"
    ok "Activated venv"
fi

# ── Step 4: Install Thomas ──────────────────────────────────
info "Installing Thomas..."
cd "$INSTALL_DIR"

if [ "${THOMAS_DEV:-}" = "1" ]; then
    $PYTHON -m pip install -e "." --quiet 2>&1 | tail -3
else
    $PYTHON -m pip install "." --quiet 2>&1 | tail -3
fi

ok "Thomas installed successfully"

# ── Step 5: Verify installation ─────────────────────────────
info "Verifying installation..."
if $PYTHON -m thomas --help &>/dev/null; then
    ok "thomas CLI works"
else
    warn "thomas CLI verification failed — may need PATH adjustment"
fi

# ── Step 6: Run setup wizard ────────────────────────────────
if [ ! -f "thomas.toml" ] && [ ! -f "$HOME/.thomas/thomas.toml" ]; then
    printf "\n${CYAN}[thomas]${NC} Run the setup wizard now? [Y/n] "
    read -r answer </dev/tty 2>/dev/null || answer="y"
    answer="${answer:-y}"
    if [[ "$answer" =~ ^[Yy] ]]; then
        $PYTHON -m thomas setup
    else
        info "Skipped. Run 'thomas setup' when ready."
    fi
else
    ok "Config already exists — skipping setup wizard"
fi

# ── Step 7: Shell alias suggestion ──────────────────────────
printf "\n"
ok "Installation complete!"
printf "\n"
info "Quick start:"
printf "  ${YELLOW}thomas chat \"hello\"${NC}    — single query\n"
printf "  ${YELLOW}thomas repl${NC}              — interactive mode\n"
printf "  ${YELLOW}thomas serve${NC}             — web UI at localhost:8899\n"
printf "  ${YELLOW}thomas doctor${NC}            — check system health\n"
printf "\n"

if $USE_VENV; then
    info "To activate the venv in future sessions:"
    printf "  ${YELLOW}source $VENV_DIR/bin/activate${NC}\n\n"
fi
