#!/usr/bin/env python3
"""
Agent Safety Gate: validate that staged changes do not violate core safety rules.

Exit codes:
  0 = all checks passed
  1 = one or more checks failed
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from agent_safety_config import load_config


def _default_dead_code_dirs() -> list[str]:
    return ["thomas/server/web/js/app_parts/"]


def _default_dead_code_redirect() -> str:
    return "thomas/server/web/js/runtime/"


def _default_build_output_files() -> list[str]:
    return [
        "thomas/server/web/js/app.js",
        "thomas/server/web/css/app.css",
    ]


def _default_placeholder_files() -> list[str]:
    return [
        "thomas/memory/episodic.py",
        "thomas/memory/episodic_store.py",
        "thomas/memory/summarization.py",
    ]


def check_dead_code_not_edited(staged_files: list[str]) -> tuple[bool, list[str]]:
    """Fail when staged changes touch configured dead-code paths."""
    cfg = load_config()
    dead_code_dirs = list(cfg.dead_code_dirs() or _default_dead_code_dirs())
    redirect_target = str(cfg.dead_code_redirect() or _default_dead_code_redirect())
    edited_dead_files = [path for path in staged_files if any(path.startswith(prefix) for prefix in dead_code_dirs)]

    if not edited_dead_files:
        return True, []

    errors = [
        "",
        "SAFETY GATE FAILED: Dead Code Files Edited",
        "=" * 70,
        f"You edited {len(edited_dead_files)} file(s) in configured dead-code directories.",
        "These paths are marked as dead code or generated surfaces.",
        "",
        "WHAT YOU DID WRONG:",
    ]
    errors.extend(f"  - {path}" for path in edited_dead_files)
    errors.extend(
        [
            "",
            "HOW TO FIX IT:",
            "1. Undo your changes to the configured dead-code paths.",
            "2. If you need to update live behavior, edit:",
            f"   {redirect_target}",
            "=" * 70,
        ]
    )
    return False, errors


def check_javascript_syntax(staged_files: list[str]) -> tuple[bool, list[str]]:
    """Validate the live frontend runtime when it is part of the change set."""
    runtime_files = [f for f in staged_files if f.startswith("thomas/server/web/js/runtime/")]
    loader_file = "thomas/server/web/js/app_runtime_loader.js"

    if not runtime_files and loader_file not in staged_files:
        return True, []

    try:
        # Check runtime files and loader
        files_to_check = runtime_files + ([loader_file] if loader_file in staged_files else [])
        for js_file in files_to_check:
            result = subprocess.run(["node", "--check", js_file], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                errors = [
                    "",
                    "SAFETY GATE FAILED: JavaScript Syntax Error",
                    "=" * 70,
                    f"File: {js_file}",
                    "",
                    "WHAT YOU DID WRONG:",
                    "Your changes introduced JavaScript syntax errors.",
                    "",
                    "Error output:",
                    result.stderr.rstrip(),
                    "",
                    "HOW TO FIX IT:",
                    f"1. Run: node --check {js_file}",
                    "2. Fix all reported syntax errors.",
                    "=" * 70,
                ]
                return False, errors
    except FileNotFoundError:
        return True, []
    except subprocess.TimeoutExpired:
        return True, []

    return True, []


def check_python_syntax(staged_files: list[str]) -> tuple[bool, list[str]]:
    """Validate that all modified Python files parse."""
    python_files = [path for path in staged_files if path.endswith(".py")]
    if not python_files:
        return True, []

    failed_files: list[tuple[str, str]] = []
    for py_file in python_files:
        # Skip files deleted in this commit -- they have no syntax to validate.
        if not Path(py_file).exists():
            continue
        try:
            with open(py_file, encoding="utf-8") as handle:
                ast.parse(handle.read())
        except SyntaxError as exc:
            failed_files.append((py_file, str(exc)))
        except (OSError, ValueError) as exc:
            failed_files.append((py_file, f"Read error: {exc}"))

    if not failed_files:
        return True, []

    errors = [
        "",
        "SAFETY GATE FAILED: Python Syntax Errors",
        "=" * 70,
        f"Found {len(failed_files)} Python file(s) with syntax errors:",
        "",
        "WHAT YOU DID WRONG:",
    ]
    for py_file, error_msg in failed_files:
        errors.append(f"  - {py_file}")
        errors.append(f"    {error_msg}")
    errors.extend(
        [
            "",
            "HOW TO FIX IT:",
            "1. Review each file listed above.",
            "2. Test each file with: python -m py_compile <filename>",
            "3. Fix all syntax errors until compile succeeds.",
            "=" * 70,
        ]
    )
    return False, errors


def check_no_pyc_files(staged_files: list[str]) -> tuple[bool, list[str]]:
    """Reject staged compiled Python artifacts."""
    pyc_files = [path for path in staged_files if path.endswith(".pyc")]
    if not pyc_files:
        return True, []

    errors = [
        "",
        "SAFETY GATE FAILED: Compiled Python Files Staged",
        "=" * 70,
        f"Found {len(pyc_files)} .pyc file(s) in staging:",
        "",
        "WHAT YOU DID WRONG:",
    ]
    errors.extend(f"  - {path}" for path in pyc_files)
    errors.extend(
        [
            "",
            "HOW TO FIX IT:",
            "1. Remove compiled files from staging.",
            "2. Delete local __pycache__ directories and .pyc files.",
            "=" * 70,
        ]
    )
    return False, errors


def check_monolith_stubs_not_edited(staged_files: list[str]) -> tuple[bool, list[str]]:
    """Fail when configured build-output files are edited directly."""
    cfg = load_config()
    build_output_files = list(cfg.build_output_files() or _default_build_output_files())
    edited_stubs = [path for path in staged_files if path in build_output_files]

    if not edited_stubs:
        return True, []

    errors = [
        "",
        "SAFETY GATE FAILED: Build Output Files Edited",
        "=" * 70,
        f"You edited {len(edited_stubs)} configured build-output file(s):",
        "",
        "WHAT YOU DID WRONG:",
    ]
    errors.extend(f"  - {path}" for path in edited_stubs)
    errors.extend(
        [
            "",
            "HOW TO FIX IT:",
            "1. Revert direct edits to generated or aggregation surfaces.",
            "2. Update the source inputs that produce these files instead.",
            "=" * 70,
        ]
    )
    return False, errors


def check_placeholder_files_not_modified(staged_files: list[str]) -> tuple[bool, list[str]]:
    """Fail when configured placeholder files are modified directly."""
    cfg = load_config()
    placeholder_files = list(cfg.placeholder_files() or _default_placeholder_files())
    modified_placeholders = [path for path in staged_files if path in placeholder_files]

    if not modified_placeholders:
        return True, []

    errors = [
        "",
        "SAFETY GATE FAILED: Placeholder Files Modified",
        "=" * 70,
        f"You modified {len(modified_placeholders)} configured placeholder file(s):",
        "",
        "WHAT YOU DID WRONG:",
    ]
    errors.extend(f"  - {path}" for path in modified_placeholders)
    errors.extend(
        [
            "",
            "HOW TO FIX IT:",
            "1. Keep intentional placeholder files stubbed.",
            "2. Implement the real behavior in a live module and update imports there.",
            "=" * 70,
        ]
    )
    return False, errors


def get_staged_files() -> list[str]:
    """Return currently staged file paths."""
    try:
        result = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, timeout=5)
    except Exception:  # pragma: no cover - defensive
        return []
    if result.returncode != 0:
        return []
    return [path.strip() for path in result.stdout.splitlines() if path.strip()]


def main() -> int:
    """Run the safety gate against staged files."""
    staged_files = get_staged_files()
    if not staged_files:
        print("No staged files to check.")
        return 0

    print(f"Validating {len(staged_files)} staged file(s)...\n")

    all_errors: list[str] = []
    checks = (
        check_dead_code_not_edited,
        check_javascript_syntax,
        check_python_syntax,
        check_no_pyc_files,
        check_monolith_stubs_not_edited,
        check_placeholder_files_not_modified,
    )
    for check in checks:
        passed, errors = check(staged_files)
        if not passed:
            all_errors.extend(errors)

    if all_errors:
        for line in all_errors:
            print(line)
        print()
        return 1

    print("All safety checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
