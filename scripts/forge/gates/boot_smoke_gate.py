#!/usr/bin/env python3
"""Lightweight boot smoke check for Thomas.

Verifies that core Thomas modules can be imported without crashing.
This is NOT a full server boot — it only checks that import-time code
works (no syntax errors, no missing dependencies, no circular imports
at load time).

Full boot verification (python -m thomas serve --port 0) remains a
manual step and CI check. This hook catches the 80% of boot failures
caused by import-time errors, which are the most common agent mistakes.

Only runs when files under thomas/ are staged.

Audit reference: Adversarial Audit Finding 5 (2026-03-19)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Load config from agent_safety.toml if available
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from agent_safety_config import config as _cfg

    SMOKE_IMPORTS: list[str] = _cfg.boot_imports()
    _TRIGGER_DIRS = _cfg.boot_trigger_dirs()
except ImportError:
    SMOKE_IMPORTS = []
    _TRIGGER_DIRS = []

# Timeout per import — if an import hangs, something is very wrong.
IMPORT_TIMEOUT_SECONDS = 15


def _staged_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _try_import(module_name: str) -> tuple[bool, str]:
    """Try importing a module in a subprocess. Returns (ok, error_msg)."""
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=IMPORT_TIMEOUT_SECONDS,
    )
    if proc.returncode == 0:
        return True, ""
    # Extract the meaningful part of the error
    stderr = proc.stderr.strip()
    # Get just the last line (the actual error), not the full traceback
    lines = stderr.splitlines()
    error_summary = lines[-1] if lines else "unknown import error"
    return False, error_summary


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    staged = _staged_files()
    trigger_dirs = _TRIGGER_DIRS or ["src/"]
    triggered_files = [f for f in staged if any(f.startswith(d) for d in trigger_dirs) and f.endswith(".py")]

    if not triggered_files:
        if args.json:
            print(json.dumps({"gate": "boot_smoke", "ok": True, "skipped": True}, sort_keys=True))
        else:
            print("Boot smoke gate: PASS (no trigger-directory Python files staged)")
        return 0

    failures: list[dict[str, str]] = []

    for module in SMOKE_IMPORTS:
        try:
            ok, error = _try_import(module)
        except subprocess.TimeoutExpired:
            ok = False
            error = f"import timed out after {IMPORT_TIMEOUT_SECONDS}s (possible circular import)"

        if not ok:
            failures.append({"module": module, "error": error})

    all_ok = len(failures) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "boot_smoke",
                    "ok": all_ok,
                    "modules_tested": len(SMOKE_IMPORTS),
                    "failures": failures,
                    "thomas_files_staged": len(thomas_files),
                },
                sort_keys=True,
            )
        )
    else:
        if all_ok:
            print(f"Boot smoke gate: PASS ({len(SMOKE_IMPORTS)} core imports OK)")
        else:
            print("SAFETY GATE FAILED: Core Module Import Failure")
            print("=" * 70)
            print(f"Failed to import {len(failures)} core module(s):")
            print()
            print("WHAT YOU DID WRONG:")
            for f in failures:
                print(f"  - import {f['module']}")
                print(f"    {f['error']}")
            print()
            print("HOW TO FIX IT:")
            print("1. Check for syntax errors in the files you changed:")
            for tf in thomas_files[:8]:
                print(f"   python -m py_compile {tf}")
            if len(thomas_files) > 8:
                print(f"   ... and {len(thomas_files) - 8} more")
            print()
            print("2. Check for circular imports:")
            print(f"   python -c \"import {failures[0]['module']}\"")
            print()
            print("3. Check for missing dependencies:")
            print("   pip install -r requirements-lock.txt")
            print()
            print("4. Full boot test:")
            print("   python -m thomas serve --port 0")
            print("=" * 70)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
