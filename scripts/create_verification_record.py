#!/usr/bin/env python3
"""Create a verification record proving agent work was tested.

This script is what agents run BEFORE committing. It:
1. Runs the specified test command
2. Runs regression tests
3. Captures results into .git/agent_verification.json
4. The pre-commit hook then validates this record

Usage:
    # Basic: run tests and create record
    python scripts/create_verification_record.py \
        --test-command "python -m pytest tests/test_my_feature.py -v" \
        --task "Added memory cleanup scheduler"

    # With shrinkage justification
    python scripts/create_verification_record.py \
        --test-command "python -m pytest tests/ -v" \
        --task "Refactored curator into smaller files" \
        --shrinkage-reason "Split curator.py into curator_core.py and curator_cleanup.py"

    # With scope justification for large commits
    python scripts/create_verification_record.py \
        --test-command "python -m pytest tests/ -v" \
        --task "Migrated all routes to new pattern" \
        --scope-reason "Bulk migration of 25 route files to async handlers"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _record_path() -> Path:
    """Where this checkout keeps its record: .git/ normally, the worktree's own git dir in a linked worktree (.git is a file there)."""
    fallback = ROOT / ".git" / "agent_verification.json"
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--git-path", "agent_verification.json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return fallback
    found = done.stdout.strip()
    if done.returncode != 0 or not found:
        return fallback
    path = Path(found)
    return path if path.is_absolute() else ROOT / path


RECORD_PATH = _record_path()
REGRESSION_COMMAND = "python -m pytest tests/test_architecture.py -x --tb=short -q"


def _run_command(command: str, timeout: int = 120) -> tuple[int, str]:
    """Run a shell command and return (exit_code, output)."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return 1, f"Command timed out after {timeout}s"
    except OSError as e:
        return 1, f"Command failed: {e}"


def _hash_output(output: str) -> str:
    """Hash test output for verification."""
    return "sha256:" + hashlib.sha256(output.encode("utf-8")).hexdigest()[:16]


def _parse_pytest_output(output: str) -> tuple[int, int]:
    """Extract pass/fail counts from pytest output."""
    passed = 0
    failed = 0
    for line in output.splitlines():
        line_lower = line.lower()
        if "passed" in line_lower:
            import re

            m = re.search(r"(\d+)\s+passed", line_lower)
            if m:
                passed = int(m.group(1))
        if "failed" in line_lower:
            import re

            m = re.search(r"(\d+)\s+failed", line_lower)
            if m:
                failed = int(m.group(1))
    return passed, failed


def _resolve_agent() -> str:
    """Identify which agent is creating the record."""
    import os

    for key in ("AGENT_ID", "THOMAS_AGENT_ID", "AGENT_NAME"):
        val = os.getenv(key, "").strip()
        if val:
            return val
    import getpass

    return getpass.getuser() or "unknown"


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test-command", required=True, help="The pytest command to run for your changes.")
    parser.add_argument("--task", default="", help="Brief description of what you changed.")
    parser.add_argument("--shrinkage-reason", default="", help="If you deleted significant code, explain why.")
    parser.add_argument("--scope-reason", default="", help="If committing 20+ files, explain why.")
    parser.add_argument("--skip-regression", action="store_true", help="Skip regression tests (not recommended).")
    parser.add_argument(
        "--test-timeout",
        type=int,
        default=120,
        help="Seconds the test command may run before it counts as failed (default 120).",
    )
    args = parser.parse_args(argv)

    print("Creating verification record...")
    print(f"Task: {args.task or '(not specified)'}")
    print()

    # Step 1: Run the agent's tests
    print(f"Running tests: {args.test_command}")
    test_code, test_output = _run_command(args.test_command, timeout=args.test_timeout)
    test_passed, test_failed = _parse_pytest_output(test_output)
    print(f"  Result: {test_passed} passed, {test_failed} failed (exit code {test_code})")

    if test_code != 0:
        print()
        print("WARNING: Tests did not pass cleanly. The verification record will")
        print("show failures, and the pre-commit hook will block the commit.")
        print("Fix your tests first, then re-run this script.")
        print()
        print("Test output:")
        print(test_output[-500:] if len(test_output) > 500 else test_output)

    # Step 2: Run regression tests
    # A skipped check is not a pass. This defaulted to True, so --skip-regression
    # wrote "command": "skipped" next to "passed": true, and the gate accepted it.
    regression_passed = False
    regression_output = ""
    if not args.skip_regression:
        print()
        print(f"Running regression tests: {REGRESSION_COMMAND}")
        reg_code, regression_output = _run_command(REGRESSION_COMMAND)
        regression_passed = reg_code == 0
        print(f"  Result: {'PASS' if regression_passed else 'FAIL'} (exit code {reg_code})")
    else:
        print("Skipping regression tests (--skip-regression)")
        print("  Recorded as NOT passed: the commit gate refuses a skipped regression check.")

    # Step 3: Build the record
    record = {
        "version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": _resolve_agent(),
        "task_summary": args.task,
        "tests_run": {
            "command": args.test_command,
            "passed": test_passed,
            "failed": test_failed,
            "exit_code": test_code,
            "output_hash": _hash_output(test_output),
        },
        "regression_check": {
            "command": REGRESSION_COMMAND if not args.skip_regression else "skipped",
            "passed": regression_passed,
            "output_hash": _hash_output(regression_output) if regression_output else "",
        },
        "shrinkage": {
            "deletions_justified": args.shrinkage_reason,
        },
        "scope_justification": args.scope_reason,
    }

    # Step 4: Write the record
    RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORD_PATH.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print()
    print(f"Verification record written to: {RECORD_PATH}")
    print()

    # A run that timed out, could not start, or failed after its tests counts zero failures but is not clean: it printed
    # "Record is clean" over "Command timed out after 120s" on 2026-11-06. The test command's own exit code decides too.
    if test_code != 0 or test_failed > 0 or not regression_passed:
        if test_code != 0 and test_failed == 0:
            print(f"NOTE: The test command did not finish cleanly (exit code {test_code}), so nothing here is a pass.")
            print("Its output above says why: a time limit (--test-timeout), a command that could not start, or")
            print("a failure after the tests ran. The pre-commit hook will block your commit until it passes.")
            return 1
        print("NOTE: The record contains failures. The pre-commit hook will")
        print("block your commit until tests pass. Fix and re-run this script.")
        return 1

    print("Record is clean. You can now commit your changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
