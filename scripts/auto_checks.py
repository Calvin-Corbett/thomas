"""Automated repository checks for Thomas.

Run once to exercise syntax/lint, core gates, and test suite.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
CLEAN_DEV_VERIFY_PRESETS: tuple[str, ...] = ("strict-worktree",)

CORE_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Python compile check", (PY, "-m", "compileall", "-q", "thomas", "tests")),
    (
        "Ruff fatal lint",
        (
            PY,
            "-m",
            "ruff",
            "check",
            "thomas",
            "tests",
            "--select",
            "F821,F822,F823,F632,E902",
        ),
    ),
)

GATE_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Monolith guard gate", (PY, "scripts/check_monolith_guard.py")),
    ("Repo hygiene gate", (PY, "scripts/check_repo_hygiene.py")),
    ("Plan structure gate", (PY, "scripts/check_plan_structure_gate.py")),
    ("Workboard claims gate", (PY, "scripts/check_workboard_claims.py")),
    ("Workboard issue tool smoke", (PY, "scripts/workboard_issue.py", "--help")),
    ("Feature master sync gate", (PY, "scripts/sync_feature_master_list.py", "--check")),
    ("Release hygiene gate", (PY, "scripts/check_release_hygiene.py")),
    ("Release update gate", (PY, "scripts/check_release_update_gate.py")),
)

TEST_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Full test suite", (PY, "-m", "pytest", "-q", "tests")),
)

OPTIONAL_MODULES: tuple[tuple[str, str], ...] = (
    ("PIL", "Pillow"),
    ("reportlab", "reportlab"),
    ("jsonschema", "jsonschema"),
    ("watchdog", "watchdog"),
    ("aiohttp.pytest_plugin", "pytest-aiohttp"),
)


def _fmt_cmd(cmd: Sequence[str]) -> str:
    return shlex.join([str(part) for part in cmd])


def _run_step(label: str, cmd: Sequence[str]) -> int:
    print(f"\n[auto] {label}")
    print(f"[auto] $ {_fmt_cmd(cmd)}")
    started = time.monotonic()
    completed = subprocess.run(list(cmd), cwd=ROOT, check=False)
    elapsed = time.monotonic() - started
    if completed.returncode == 0:
        print(f"[auto] PASS {label} ({elapsed:.1f}s)")
    else:
        print(f"[auto] FAIL {label} ({elapsed:.1f}s, exit={completed.returncode})")
    return int(completed.returncode)


def _warn_missing_optional_modules() -> None:
    missing: list[str] = []
    for module_name, package_name in OPTIONAL_MODULES:
        try:
            __import__(module_name)
        except Exception:
            missing.append(package_name)
    if missing:
        deduped = sorted(set(missing))
        print("[auto] Optional test dependencies missing:")
        print(f"[auto]   {', '.join(deduped)}")
        print("[auto] Some optional tests may skip until those packages are installed.")


def run(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run automated Thomas repository checks.")
    parser.add_argument("--quick", action="store_true", help="Run syntax/lint only.")
    cleanup_group = parser.add_mutually_exclusive_group()
    cleanup_group.add_argument(
        "--clean-dev-artifacts",
        action="store_true",
        help="Audit local dev-artifact candidates before checks (dry-run).",
    )
    cleanup_group.add_argument(
        "--clean-dev-artifacts-apply",
        action="store_true",
        help="Delete local dev-artifact candidates before checks (requires verification commands).",
    )
    parser.add_argument(
        "--clean-dev-verify-command",
        action="append",
        default=[],
        help="End-to-end verification command for --clean-dev-artifacts-apply (repeatable).",
    )
    parser.add_argument(
        "--clean-dev-verify-preset",
        action="append",
        choices=CLEAN_DEV_VERIFY_PRESETS,
        default=[],
        help="Named verification preset for --clean-dev-artifacts-apply (repeatable).",
    )
    parser.add_argument("--skip-gates", action="store_true", help="Skip gate scripts.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest suite.")
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="Continue running remaining steps after a failure.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    steps: list[tuple[str, tuple[str, ...]]] = []
    if args.clean_dev_artifacts:
        steps.append(("Dev artifact cleanup (dry-run)", (PY, "scripts/clean_dev_artifacts.py")))
    if args.clean_dev_artifacts_apply:
        cleanup_cmd: list[str] = [PY, "scripts/clean_dev_artifacts.py", "--apply"]
        for preset in [str(item or "").strip() for item in list(args.clean_dev_verify_preset or [])]:
            if preset:
                cleanup_cmd.extend(["--verify-preset", preset])
        for command in [str(item or "").strip() for item in list(args.clean_dev_verify_command or [])]:
            if command:
                cleanup_cmd.extend(["--verify-command", command])
        steps.append(("Dev artifact cleanup (apply)", tuple(cleanup_cmd)))
    steps.extend(CORE_STEPS)
    if not args.quick and not args.skip_gates:
        steps.extend(GATE_STEPS)
    if not args.quick and not args.skip_tests:
        steps.extend(TEST_STEPS)

    print(f"[auto] Root: {ROOT}")
    print(f"[auto] Steps: {len(steps)}")
    _warn_missing_optional_modules()

    failures: list[tuple[str, int]] = []
    started = time.monotonic()
    for label, cmd in steps:
        rc = _run_step(label, cmd)
        if rc != 0:
            failures.append((label, rc))
            if not args.continue_on_fail:
                break

    elapsed = time.monotonic() - started
    if failures:
        print("\n[auto] Summary: FAILED")
        for label, rc in failures:
            print(f"[auto] - {label}: exit {rc}")
        print(f"[auto] Total time: {elapsed:.1f}s")
        return 1

    print("\n[auto] Summary: PASS")
    print(f"[auto] Total time: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
