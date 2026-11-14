#!/usr/bin/env python3
"""Require agents to produce a verification record before committing.

The verification record is a JSON file proving the agent:
1. Ran tests for its changes, with a real runner and a real count
2. Ran regression tests (existing tests still pass)
3. Did both for THIS change, not one from weeks ago

The record lives at .git/agent_verification.json and is checked
at commit time. If it's missing or incomplete, the commit is blocked.

The agent creates this record by running:
    python scripts/create_verification_record.py

Deletions (gap 2) and commit scope (gap 7) are NOT judged here. They have their
own gates, shrinkage_gate.py and commit_scope_gate.py, which read the same record
for their justification fields. This file carried duplicates of both until
2026-09-19; see the note above VERIFICATION_THRESHOLD for why they were worse.

Gaps closed: 1 (bad logic), 3 (no tests), 10 (no runtime verification)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]


def _record_path(root: Path) -> Path:
    """Where this checkout keeps its record: .git/ normally, its own git dir in a linked worktree (.git is a file there)."""
    fallback = root / ".git" / "agent_verification.json"
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-path", "agent_verification.json"],
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
    return path if path.is_absolute() else root / path


RECORD_PATH = _record_path(ROOT)


def _rebind_root(raw: str | None) -> None:
    """Point the gate at another checkout so it can be run against a fixture.

    Without this the gate always judges the repo it lives in, so it could never have
    a red-path selftest - and the enforcement ratchet will not let an unprovable gate
    enforce. Same option, same default, as monolith_guard.py.
    """
    global ROOT, RECORD_PATH
    if not raw:
        return
    ROOT = Path(raw).resolve()
    RECORD_PATH = _record_path(ROOT)


# A record is evidence about the change in front of it. Found live 2026-09-19: a
# record from three months earlier still satisfied today's commit, claiming a pass
# from `python -c print(123)` with a regression check recorded as "skipped".
MAX_RECORD_AGE = timedelta(hours=24)
REGRESSION_HINT = "python -m pytest tests/test_architecture.py -x --tb=short -q"
_TEST_RUNNERS = ("pytest", "unittest", "vitest", "jest", "npm test", "node --test", "cargo test", "go test")
# The shape of a real runner invocation: the command STARTS with the runner (create_verification_record.py runs whatever
# --test-command it is given through a shell, and the record keeps that string). `echo pytest` or `true # pytest` names a
# runner without running one. A record is still a file anyone can write: this stops a careless or lazy one, not a forgery.
_RUNNER_SHAPE = re.compile(
    r"^\s*(?:(?:\S*[\\/])?(?:python[\d.]*|py)(?:\.exe)?\s+(?:-\S+\s+)*-m\s+(?:pytest|unittest)\b"
    r"|(?:\S*[\\/])?pytest(?:\.exe)?\b"
    r"|(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b|npx\s+(?:vitest|jest)\b|(?:vitest|jest)\b"
    r"|node\s+--test\b|cargo\s+test\b|go\s+test\b)",
    re.IGNORECASE,
)
_CHAINING = re.compile(r";|\|\||`|\$\(|\bor\s+true\b", re.IGNORECASE)


def _names_a_test_runner(command: str) -> bool:
    """True only when the command is a test-runner invocation, not a command that merely mentions one."""
    return bool(_RUNNER_SHAPE.match(command)) and not _CHAINING.search(command)


def _count(value: object) -> int | None:
    """A pass/fail count as an int, or None when the record carries something else (a string, a list, a bool)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


# How many code files trigger the verification requirement
VERIFICATION_THRESHOLD = 3

# Scope and shrinkage are NOT checked here. This file used to carry its own copies
# of both, and they were the cruder ones: the scope copy had no exemption for files
# a commit merely moves or removes, so it hard-blocked cleanup (measured 2026-09-19
# against commit 93415742, which removed 1,584 dead listings), and the shrinkage
# copy sat below the 3-code-file threshold above, so it never saw the one-file
# gutting it existed to catch. Both live in their own gates, which this one does
# not duplicate: commit_scope_gate.py and shrinkage_gate.py.


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
    """The record as a dict, or None when there is none. A record that is not a JSON object is returned as {}: present but empty."""
    if not RECORD_PATH.exists():
        return None
    try:
        data = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else {}


def _check_tests_run(record: dict) -> list[str]:
    """Verify the record shows tests were actually run."""
    errors = []
    tests = record.get("tests_run")
    if not tests or not isinstance(tests, dict):
        errors.append("Verification record missing 'tests_run' section.")
        errors.append("  You must run tests and record the results.")
        return errors

    command = str(tests.get("command", "") or "")
    if not command:
        errors.append("Verification record 'tests_run.command' is empty.")
        errors.append("  Record what test command you ran.")
    elif not _names_a_test_runner(command):
        # Found live: a record claiming a pass from `python -c print(123)`.
        errors.append(f"Verification record 'tests_run.command' does not name a test runner: {command!r}")
        errors.append(f"  Use one of: {', '.join(sorted(_TEST_RUNNERS))}.")

    passed, failed = _count(tests.get("passed", -1)), _count(tests.get("failed", -1))
    if passed is None or failed is None:
        errors.append("Verification record 'tests_run' pass/fail counts are not whole numbers.")
        errors.append("  Re-run: python scripts/create_verification_record.py")
    elif passed < 0 and failed < 0:
        errors.append("Verification record 'tests_run' has no pass/fail counts.")
    elif passed <= 0 and failed <= 0:
        errors.append("Verification record shows no tests ran (0 passed, 0 failed).")
        errors.append("  A run that tested nothing is not evidence; run the tests that cover your change.")

    if failed is not None and failed > 0:
        errors.append(f"Verification record shows {failed} FAILED test(s).")
        errors.append("  Fix failing tests before committing.")

    return errors


def _check_regression(record: dict) -> list[str]:
    """Verify regression tests were run."""
    errors = []
    regression = record.get("regression_check")
    if not regression or not isinstance(regression, dict):
        errors.append("Verification record missing 'regression_check' section.")
        errors.append("  Run: python -m pytest tests/test_architecture.py -x --tb=short -q")
        return errors

    command = str(regression.get("command", "") or "").strip()
    if not command or command.lower() == "skipped":
        # Found live: "command": "skipped" recorded alongside "passed": true.
        errors.append("Verification record shows the regression check was skipped.")
        errors.append(f"  Run: {REGRESSION_HINT}")
        return errors
    if not _names_a_test_runner(command):
        errors.append(f"Verification record 'regression_check.command' is not a test-runner invocation: {command!r}")
        errors.append(f"  Run: {REGRESSION_HINT}")
        return errors

    passed = regression.get("passed", False)
    if not passed:
        errors.append("Verification record shows regression tests did NOT pass.")
        errors.append("  Fix regressions before committing.")

    return errors


def _check_freshness(record: dict) -> list[str]:
    """A record covers the work in front of it, not work from weeks ago.

    Found live: a record from 2026-06-26 still satisfied a commit in September."""
    raw = str(record.get("timestamp", "") or "").strip()
    if not raw:
        return ["Verification record has no timestamp.", "  Re-run: python scripts/create_verification_record.py"]
    try:
        stamped = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return [f"Verification record timestamp is unreadable: {raw!r}"]
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - stamped
    if age > MAX_RECORD_AGE:
        hours = int(age.total_seconds() // 3600)
        return [
            f"Verification record is {hours}h old (limit {int(MAX_RECORD_AGE.total_seconds() // 3600)}h).",
            "  Re-run the tests for the change you are committing now.",
        ]
    return []


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred from script location).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)
    _rebind_root(args.repo_root)

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
    all_errors.extend(_check_freshness(record))
    all_errors.extend(_check_tests_run(record))
    all_errors.extend(_check_regression(record))

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
