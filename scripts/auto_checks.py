"""Automated repository checks for Thomas.

Run once to exercise syntax/lint, core gates, and test suite.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.breakglass_auth import authorize_breakglass
except ImportError:  # pragma: no cover
    from breakglass_auth import authorize_breakglass  # type: ignore

CLEAN_DEV_VERIFY_PRESETS: tuple[str, ...] = ("strict-worktree",)
DEFAULT_PROBLEM_TASK_ID = "audit-24h-backstop"
BREAKGLASS_ENV = "THOMAS_SKIP_BREAKGLASS"
BREAKGLASS_TICKET_ENV = "THOMAS_SKIP_TICKET"
BREAKGLASS_REASON_ENV = "THOMAS_SKIP_REASON"
AGENT_ENV_KEYS: tuple[str, ...] = (
    "AGENT_ID",
    "THOMAS_AGENT_ID",
    "THOMAS_AGENT_NAME",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)

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
    ("Monolith split filename gate", (PY, "scripts/forge/gates/monolith_filename_guard.py")),
    ("Monolith guard gate", (PY, "scripts/forge/gates/monolith_guard.py")),
    ("Repo hygiene gate", (PY, "scripts/forge/gates/repo_hygiene.py")),
    ("Plan structure gate", (PY, "scripts/forge/gates/plan_structure_gate.py")),
    ("Pre-commit skip policy gate", (PY, "scripts/forge/gates/precommit_skip_policy.py")),
    ("Surface parity gate", (PY, "scripts/forge/gates/surface_parity.py")),
    ("Workboard claims gate", (PY, "scripts/forge/gates/workboard_claims.py")),
    ("Workboard task problems gate", (PY, "scripts/forge/gates/workboard_task_problems.py")),
    ("Workboard issue tool smoke", (PY, "scripts/workboard_issue.py", "--help")),
    ("Workboard problem recorder smoke", (PY, "scripts/workboard_problem_record.py", "--help")),
    ("Feature master sync gate", (PY, "scripts/sync_feature_master_list.py", "--check")),
    ("Release hygiene gate", (PY, "scripts/forge/gates/release_hygiene.py")),
    ("Release update gate", (PY, "scripts/forge/gates/release_update_gate.py")),
)

TEST_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Thomas step-up test protocol", (PY, "scripts/test_stepup_protocol.py")),
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


def _record_problem_failure(
    *,
    label: str,
    cmd: Sequence[str],
    exit_code: int,
    task_id: str,
    agent: str,
) -> tuple[bool, str]:
    record_cmd: list[str] = [
        PY,
        "scripts/workboard_problem_record.py",
        "--runner",
        "auto_checks",
        "--step",
        str(label),
        "--exit-code",
        str(int(exit_code)),
        "--command",
        _fmt_cmd(cmd),
        "--json",
    ]
    task_clean = str(task_id or "").strip()
    if task_clean:
        record_cmd.extend(["--task-id", task_clean])
    agent_clean = str(agent or "").strip()
    if agent_clean:
        record_cmd.extend(["--agent", agent_clean])

    completed = subprocess.run(record_cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    stdout = str(completed.stdout or "").strip()
    if completed.returncode != 0:
        if stdout:
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = {}
            error = str(payload.get("error", "")).strip()
            if error:
                return False, error
        stderr = str(completed.stderr or "").strip()
        return False, stderr or f"problem recorder exited {completed.returncode}"

    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {}
        problem_path = str(payload.get("problem_path", "")).strip()
        task = str(payload.get("task_id", "")).strip()
        if task and problem_path:
            return True, f"task `{task}` -> {problem_path}"
    return True, "problem record updated"


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


def _truthy_env(name: str) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_agent_id() -> str:
    for key in AGENT_ENV_KEYS:
        value = str(os.getenv(key, "")).strip()
        if value:
            return value
    fallback = str(getpass.getuser() or "").strip()
    return fallback


def _ensure_breakglass_metadata(*, skip_gates: bool, skip_tests: bool) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    if not (skip_gates or skip_tests):
        return None, notes
    if not _truthy_env(BREAKGLASS_ENV):
        return (
            f"--skip-gates/--skip-tests are breakglass-only. Set {BREAKGLASS_ENV}=1 and provide audited metadata.",
            notes,
        )
    agent = _resolve_agent_id()
    if agent and not str(os.getenv("AGENT_ID", "")).strip():
        os.environ["AGENT_ID"] = agent
        notes.append("agent id auto-filled")
    ticket = str(os.getenv(BREAKGLASS_TICKET_ENV, "")).strip()
    if len(ticket) < 6:
        return (f"breakglass requires {BREAKGLASS_TICKET_ENV} with at least 6 characters.", notes)
    reason = " ".join(str(os.getenv(BREAKGLASS_REASON_ENV, "")).split()).strip()
    if len(reason) < 12:
        return (f"breakglass requires {BREAKGLASS_REASON_ENV} with at least 12 characters.", notes)
    auth = authorize_breakglass(
        purpose="auto_checks skip override",
        agent=agent or "unknown-agent",
        ticket=ticket,
        reason=reason,
        skip_hooks=[
            item
            for item, enabled in (
                ("auto_checks:skip-gates", bool(skip_gates)),
                ("auto_checks:skip-tests", bool(skip_tests)),
            )
            if enabled
        ],
    )
    if not auth.ok:
        return (
            auth.message or "human breakglass authorization failed for auto_checks skip override.",
            notes,
        )
    if auth.method:
        notes.append(f"human authorization verified via {auth.method}")
    if auth.actor:
        notes.append(f"authorized by {auth.actor}")
    return None, notes


def _default_require_clean_worktree() -> bool:
    # Keep dirty-worktree enforcement strict by default for both local and CI runs.
    return True


def _resolved_gate_steps(require_clean_worktree: bool) -> tuple[tuple[str, tuple[str, ...]], ...]:
    steps: list[tuple[str, tuple[str, ...]]] = []
    for label, cmd in GATE_STEPS:
        if label == "Repo hygiene gate" and not require_clean_worktree:
            steps.append((label, (PY, "scripts/forge/gates/repo_hygiene.py", "--no-require-clean-worktree")))
        else:
            steps.append((label, cmd))
    return tuple(steps)


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
        "--problem-task-id",
        default=str(os.getenv("THOMAS_TASK_ID", "")).strip() or DEFAULT_PROBLEM_TASK_ID,
        help=(
            "Task id used for automatic PROBLEM.md failure logging "
            "(defaults to THOMAS_TASK_ID or audit-24h-backstop)."
        ),
    )
    parser.add_argument(
        "--problem-agent",
        default="",
        help="Agent id used for automatic PROBLEM.md failure logging (defaults from AGENT_ID/THOMAS_AGENT_ID env).",
    )
    parser.add_argument(
        "--no-record-problem-on-fail",
        action="store_true",
        help="Disable automatic task PROBLEM.md logging when a step fails.",
    )
    parser.add_argument(
        "--require-clean-worktree",
        dest="require_clean_worktree",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=("Override repo-hygiene dirty-worktree enforcement. Defaults to enabled locally and in CI."),
    )
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="Continue running remaining steps after a failure.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    skip_override_error, breakglass_notes = _ensure_breakglass_metadata(
        skip_gates=bool(args.skip_gates),
        skip_tests=bool(args.skip_tests),
    )
    if skip_override_error:
        print(f"[auto] FAIL {skip_override_error}")
        return 1
    for note in breakglass_notes:
        print(f"[auto] breakglass metadata: {note}")

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
        require_clean_worktree = (
            _default_require_clean_worktree()
            if args.require_clean_worktree is None
            else bool(args.require_clean_worktree)
        )
        steps.extend(_resolved_gate_steps(require_clean_worktree))
    if not args.quick and not args.skip_tests:
        steps.extend(TEST_STEPS)

    print(f"[auto] Root: {ROOT}")
    print(f"[auto] Steps: {len(steps)}")
    _warn_missing_optional_modules()

    failures: list[tuple[str, int]] = []
    recorder_failures: list[str] = []
    started = time.monotonic()
    for label, cmd in steps:
        rc = _run_step(label, cmd)
        if rc != 0:
            failures.append((label, rc))
            if not args.no_record_problem_on_fail:
                logged, details = _record_problem_failure(
                    label=label,
                    cmd=cmd,
                    exit_code=rc,
                    task_id=str(args.problem_task_id),
                    agent=str(args.problem_agent),
                )
                if logged:
                    print(f"[auto] Problem ledger updated for failed step ({details})")
                else:
                    recorder_failures.append(f"{label}: {details}")
                    print(f"[auto] FAIL problem ledger update for `{label}`: {details}")
            if not args.continue_on_fail:
                break

    elapsed = time.monotonic() - started
    if failures or recorder_failures:
        print("\n[auto] Summary: FAILED")
        for label, rc in failures:
            print(f"[auto] - {label}: exit {rc}")
        for item in recorder_failures:
            print(f"[auto] - Problem ledger: {item}")
        print(f"[auto] Total time: {elapsed:.1f}s")
        return 1

    print("\n[auto] Summary: PASS")
    print(f"[auto] Total time: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
