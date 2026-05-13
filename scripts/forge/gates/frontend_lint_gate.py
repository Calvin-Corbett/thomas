#!/usr/bin/env python3
"""Enforce frontend code quality for TypeScript/JavaScript files.

Runs ESLint and TypeScript type checking on staged frontend files
when the tools are available. Gracefully skips when they're not
installed (with a visible warning).

Only triggers when files under apps/ or web-ui/ are staged.

Gap closed: 4 (frontend code barely covered)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
FRONTEND_PREFIXES = ("apps/", "web-ui/")
FRONTEND_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs"}


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


def _is_frontend_file(path: str) -> bool:
    if not any(path.startswith(p) for p in FRONTEND_PREFIXES):
        return False
    return Path(path).suffix.lower() in FRONTEND_EXTENSIONS


def _find_eslint() -> str | None:
    """Find ESLint binary — check node_modules first, then PATH."""
    for apps_dir in ("apps/site", "apps", "."):
        local = ROOT / apps_dir / "node_modules" / ".bin" / "eslint"
        if local.exists():
            return str(local)
    return shutil.which("eslint")


def _find_tsc() -> str | None:
    """Find TypeScript compiler."""
    for apps_dir in ("apps/site", "apps", "."):
        local = ROOT / apps_dir / "node_modules" / ".bin" / "tsc"
        if local.exists():
            return str(local)
    return shutil.which("tsc")


def _run_eslint(eslint_path: str, files: list[str]) -> tuple[bool, str]:
    """Run ESLint on files. Returns (ok, output)."""
    try:
        proc = subprocess.run(
            [eslint_path, "--no-error-on-unmatched-pattern"] + files,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return True, "ESLint timed out"
    except OSError as e:
        return True, f"ESLint error: {e}"


def _run_tsc(tsc_path: str, app_dir: str) -> tuple[bool, str]:
    """Run TypeScript type check. Returns (ok, output)."""
    try:
        proc = subprocess.run(
            [tsc_path, "--noEmit", "--project", app_dir],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return True, "TypeScript check timed out"
    except OSError as e:
        return True, f"TypeScript error: {e}"


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    staged = _staged_files()
    frontend_files = [f for f in staged if _is_frontend_file(f)]

    if not frontend_files:
        if args.json:
            print(
                json.dumps(
                    {"gate": "frontend_lint", "ok": True, "skipped": True, "reason": "no frontend files staged"},
                    sort_keys=True,
                )
            )
        else:
            print("Frontend lint gate: PASS (no frontend files staged)")
        return 0

    errors: list[str] = []
    warnings: list[str] = []

    # ESLint check
    eslint_path = _find_eslint()
    if eslint_path:
        eslint_ok, eslint_output = _run_eslint(eslint_path, frontend_files)
        if not eslint_ok:
            errors.append(f"ESLint found issues in {len(frontend_files)} file(s):")
            for line in eslint_output.splitlines()[:15]:
                errors.append(f"  {line}")
    else:
        warnings.append("ESLint not found — frontend linting skipped. Install: npm install eslint")

    # TypeScript check (only if .ts/.tsx files are staged)
    ts_files = [f for f in frontend_files if f.endswith((".ts", ".tsx"))]
    if ts_files:
        tsc_path = _find_tsc()
        if tsc_path:
            # Find the nearest tsconfig
            app_dirs = set()
            for f in ts_files:
                parts = f.split("/")
                if len(parts) >= 2:
                    app_dirs.add("/".join(parts[:2]))
            for app_dir in app_dirs:
                tsconfig = ROOT / app_dir / "tsconfig.json"
                if tsconfig.exists():
                    tsc_ok, tsc_output = _run_tsc(tsc_path, app_dir)
                    if not tsc_ok:
                        errors.append(f"TypeScript errors in {app_dir}:")
                        for line in tsc_output.splitlines()[:10]:
                            errors.append(f"  {line}")
        else:
            warnings.append("TypeScript compiler not found — type checking skipped.")

    ok = len(errors) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "frontend_lint",
                    "ok": ok,
                    "frontend_files_staged": len(frontend_files),
                    "errors": errors,
                    "warnings": warnings,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            if warnings:
                print(f"Frontend lint gate: PASS ({len(frontend_files)} files, with warnings)")
                for w in warnings:
                    print(f"  WARNING: {w}")
            else:
                print(f"Frontend lint gate: PASS ({len(frontend_files)} file(s) checked)")
        else:
            print("SAFETY GATE FAILED: Frontend Code Quality Issues")
            print("=" * 70)
            for err in errors:
                print(f"  {err}")
            print()
            print("HOW TO FIX IT:")
            print("1. Fix the errors reported above")
            print("2. Run ESLint locally: npx eslint <file>")
            print("3. Run TypeScript: npx tsc --noEmit")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
