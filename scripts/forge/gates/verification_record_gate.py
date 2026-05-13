#!/usr/bin/env python3
"""Require agents to produce a verification record before committing.

The verification record is a JSON file proving the agent:
1. Ran tests for its changes
2. Ran regression tests (existing tests still pass)
3. Reviewed its own changes
4. Justified any significant code deletions
5. Justified large commit scope (if applicable)

The record lives at .git/agent_verification.json and is checked
at commit time. If it's missing or incomplete, the commit is blocked.

The agent creates this record by running:
    python scripts/create_verification_record.py

Gaps closed: 1 (bad logic), 2 (silent deletion), 3 (no tests),
             7 (huge commits), 10 (no runtime verification)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
RECORD_PATH = ROOT / ".git" / "agent_verification.json"

# How many code files trigger the verification requirement
VERIFICATION_THRESHOLD = 3

# Max files before scope justification is required
SCOPE_WARN_THRESHOLD = 20
SCOPE_HARD_LIMIT = 50

# Max percentage a file can shrink before justification is needed
SHRINKAGE_THRESHOLD = 0.30  # 30%


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


def _is_code_file(path: str) -> bool:
    code_extensions = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".html"}
    return Path(path).suffix.lower() in code_extensions


def _staged_code_files(staged: list[str]) -> list[str]:
    return [f for f in staged if _is_code_file(f)]


def _load_record() -> dict | None:
    if not RECORD_PATH.exists():
        return None
    try:
        return json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _check_tests_run(record: dict) -> list[str]:
    """Verify the record shows tests were actually run."""
    errors = []
    tests = record.get("tests_run")
    if not tests:
        errors.append("Verification record missing 'tests_run' section.")
        errors.append("  You must run tests and record the results.")
        return errors

    command = tests.get("command", "")
    if not command:
        errors.append("Verification record 'tests_run.command' is empty.")
        errors.append("  Record what test command you ran.")

    passed = tests.get("passed", -1)
    failed = tests.get("failed", -1)
    if passed < 0 and failed < 0:
        errors.append("Verification record 'tests_run' has no pass/fail counts.")

    if failed and int(failed) > 0:
        errors.append(f"Verification record shows {failed} FAILED test(s).")
        errors.append("  Fix failing tests before committing.")

    return errors


def _check_regression(record: dict) -> list[str]:
    """Verify regression tests were run."""
    errors = []
    regression = record.get("regression_check")
    if not regression:
        errors.append("Verification record missing 'regression_check' section.")
        errors.append("  Run: python -m pytest tests/test_architecture.py -x --tb=short -q")
        return errors

    passed = regression.get("passed", False)
    if not passed:
        errors.append("Verification record shows regression tests did NOT pass.")
        errors.append("  Fix regressions before committing.")

    return errors


def _check_shrinkage(record: dict, staged: list[str]) -> list[str]:
    """Check if files shrank significantly and justification exists."""
    errors = []

    # Get line counts for staged files vs HEAD
    shrunk_files = []
    for filepath in staged:
        if not _is_code_file(filepath):
            continue
        full_path = ROOT / filepath
        if not full_path.exists():
            continue

        # Get HEAD line count
        proc = subprocess.run(
            ["git", "show", f"HEAD:{filepath}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            continue  # New file, no shrinkage possible

        head_lines = len(proc.stdout.splitlines())
        if head_lines == 0:
            continue

        current_lines = len(full_path.read_text(encoding="utf-8").splitlines())
        shrinkage = (head_lines - current_lines) / head_lines

        if shrinkage > SHRINKAGE_THRESHOLD:
            shrunk_files.append(
                {
                    "file": filepath,
                    "head_lines": head_lines,
                    "current_lines": current_lines,
                    "shrinkage_pct": round(shrinkage * 100),
                }
            )

    if shrunk_files:
        justification = record.get("shrinkage", {}).get("deletions_justified", "")
        if not justification or len(str(justification).strip()) < 10:
            errors.append(f"Found {len(shrunk_files)} file(s) that shrank by >{int(SHRINKAGE_THRESHOLD*100)}%:")
            for sf in shrunk_files[:5]:
                errors.append(
                    f"  - {sf['file']}: {sf['head_lines']} -> {sf['current_lines']} lines ({sf['shrinkage_pct']}% removed)"
                )
            errors.append("")
            errors.append("Verification record needs 'shrinkage.deletions_justified' explaining why.")

    return errors


def _check_scope(record: dict, staged_code: list[str]) -> list[str]:
    """Check commit scope and require justification for large commits."""
    errors = []

    if len(staged_code) > SCOPE_HARD_LIMIT:
        errors.append(f"Commit touches {len(staged_code)} code files (hard limit: {SCOPE_HARD_LIMIT}).")
        errors.append("  Split this into smaller, focused commits.")
        return errors

    if len(staged_code) > SCOPE_WARN_THRESHOLD:
        justification = record.get("scope_justification", "")
        if not justification or len(str(justification).strip()) < 10:
            errors.append(f"Commit touches {len(staged_code)} code files (>{SCOPE_WARN_THRESHOLD}).")
            errors.append("  Add 'scope_justification' to the verification record explaining why.")

    return errors


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    staged = _staged_files()
    staged_code = _staged_code_files(staged)

    # Only require verification for substantial changes
    if len(staged_code) < VERIFICATION_THRESHOLD:
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "verification_record",
                        "ok": True,
                        "skipped": True,
                        "reason": f"only {len(staged_code)} code files",
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"Verification record gate: PASS ({len(staged_code)} code files, under threshold)")
        return 0

    # Load the record
    record = _load_record()
    if record is None:
        if args.json:
            print(
                json.dumps(
                    {"gate": "verification_record", "ok": False, "reason": "no verification record found"},
                    sort_keys=True,
                )
            )
        else:
            print("SAFETY GATE FAILED: No Verification Record")
            print("=" * 70)
            print(f"You staged {len(staged_code)} code files but no verification record exists.")
            print()
            print("WHAT YOU NEED TO DO:")
            print("1. Run your tests and capture the results")
            print("2. Run regression tests (python -m pytest tests/test_architecture.py -x)")
            print("3. Create the verification record:")
            print("   python scripts/create_verification_record.py")
            print()
            print("The record proves you tested your work before committing.")
            print("=" * 70)
        return 1

    # Validate the record
    all_errors = []
    all_errors.extend(_check_tests_run(record))
    all_errors.extend(_check_regression(record))
    all_errors.extend(_check_shrinkage(record, staged))
    all_errors.extend(_check_scope(record, staged_code))

    ok = len(all_errors) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "verification_record",
                    "ok": ok,
                    "errors": all_errors,
                    "code_files_staged": len(staged_code),
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print(f"Verification record gate: PASS ({len(staged_code)} code files verified)")
        else:
            print("SAFETY GATE FAILED: Verification Record Incomplete")
            print("=" * 70)
            for err in all_errors:
                print(f"  {err}")
            print()
            print("HOW TO FIX IT:")
            print("1. Fix the issues listed above")
            print("2. Regenerate the verification record:")
            print("   python scripts/create_verification_record.py")
            print("3. Retry your commit")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
