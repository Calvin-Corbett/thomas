"""Doc reliability runner.

Runs critical gates and protocol safety tests in one command.
Designed for local hardening before commits/PRs.
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

GATE_COMMANDS: Sequence[tuple[str, Sequence[str]]] = (
    ("Model onboarding gate", (PY, "scripts/check_model_onboarding_gate.py")),
    ("Module audit gate", (PY, "scripts/check_module_audit_gate.py")),
    ("Plan structure gate", (PY, "scripts/check_plan_structure_gate.py")),
    ("Pre-commit skip policy gate", (PY, "scripts/check_precommit_skip_policy.py")),
    ("Workboard claims gate", (PY, "scripts/check_workboard_claims.py")),
    ("Workboard task problems gate", (PY, "scripts/check_workboard_task_problems.py")),
    ("Repo identity gate", (PY, "scripts/check_repo_identity.py")),
    ("Workboard issue tool smoke", (PY, "scripts/workboard_issue.py", "--help")),
    ("Workboard problem recorder smoke", (PY, "scripts/workboard_problem_record.py", "--help")),
    ("Release update gate", (PY, "scripts/check_release_update_gate.py")),
    ("Release hygiene gate", (PY, "scripts/check_release_hygiene.py")),
    ("Surface parity gate", (PY, "scripts/check_surface_parity.py")),
    ("Feature catalog gate", (PY, "scripts/check_feature_catalog_gate.py")),
    ("Competitive scope gate", (PY, "scripts/check_competitive_scope_gate.py")),
    ("OpenClaw metric parity gate", (PY, "scripts/check_openclaw_metric_parity_gate.py")),
    ("Chat control protocol gate", (PY, "scripts/check_chat_control_protocol.py")),
)

CRITICAL_TEST_FILES: Sequence[str] = (
    "tests/test_llm_openai_tool_compat.py",
    "tests/test_agent_loop_tool_policy.py",
    "tests/test_tool_registry_resolution.py",
    "tests/test_chat_controls.py",
    "tests/test_server_chat_controls.py",
    "tests/test_model_switching.py",
    "tests/test_agent_loop_autonomy.py",
    "tests/test_server_access_mode.py",
    "tests/test_intent_routing.py",
    "tests/test_realtime_ws.py",
    "tests/test_companion_policy_compliance.py",
    "tests/test_server_companion_api.py",
    "tests/test_openclaw_metric_parity_gate.py",
)


def _fmt_cmd(cmd: Sequence[str]) -> str:
    return shlex.join([str(part) for part in cmd])


def _run_step(label: str, cmd: Sequence[str]) -> tuple[int, float]:
    print(f"\n[doc] {label}", flush=True)
    print(f"[doc] $ {_fmt_cmd(cmd)}", flush=True)
    started = time.monotonic()
    proc = subprocess.run(list(cmd), cwd=ROOT)
    elapsed = time.monotonic() - started
    if proc.returncode == 0:
        print(f"[doc] PASS {label} ({elapsed:.1f}s)", flush=True)
    else:
        print(f"[doc] FAIL {label} ({elapsed:.1f}s, exit={proc.returncode})", flush=True)
    return int(proc.returncode), float(elapsed)


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
        "doc",
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


def _iter_steps(
    *,
    include_gates: bool,
    include_tests: bool,
    full: bool,
) -> list[tuple[str, Sequence[str]]]:
    steps: list[tuple[str, Sequence[str]]] = []
    if include_gates:
        steps.extend(GATE_COMMANDS)
    if include_tests:
        steps.append(
            (
                "Protocol safety tests",
                (PY, "-m", "pytest", "-q", *CRITICAL_TEST_FILES),
            )
        )
    if full:
        steps.append(("Full pytest sweep", (PY, "-m", "pytest", "-q")))
    return steps


def _is_truthy(value: str) -> bool:
    raw = str(value or "").strip().lower()
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
    if not _is_truthy(os.getenv(BREAKGLASS_ENV, "")):
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
        purpose="doc runner skip override",
        agent=agent or "unknown-agent",
        ticket=ticket,
        reason=reason,
        skip_hooks=[
            item
            for item, enabled in (
                ("doc:skip-gates", bool(skip_gates)),
                ("doc:skip-tests", bool(skip_tests)),
            )
            if enabled
        ],
    )
    if not auth.ok:
        return (
            auth.message or "human breakglass authorization failed for doc skip override.",
            notes,
        )
    if auth.method:
        notes.append(f"human authorization verified via {auth.method}")
    if auth.actor:
        notes.append(f"authorized by {auth.actor}")
    return None, notes


def run(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Doc reliability checks.")
    parser.add_argument("--skip-gates", action="store_true", help="Skip gate scripts.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip protocol safety tests.")
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
        default=str(os.getenv("AGENT_ID", "")).strip(),
        help="Agent id used for automatic PROBLEM.md failure logging (defaults to AGENT_ID).",
    )
    parser.add_argument(
        "--no-record-problem-on-fail",
        action="store_true",
        help="Disable automatic task PROBLEM.md logging when a step fails.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="After quick checks, also run the full pytest suite.",
    )
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="Run remaining steps even after a failure.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    skip_override_error, breakglass_notes = _ensure_breakglass_metadata(
        skip_gates=bool(args.skip_gates),
        skip_tests=bool(args.skip_tests),
    )
    if skip_override_error:
        print(f"[doc] FAIL {skip_override_error}", flush=True)
        return 1
    for note in breakglass_notes:
        print(f"[doc] breakglass metadata: {note}", flush=True)

    steps = _iter_steps(
        include_gates=not args.skip_gates,
        include_tests=not args.skip_tests,
        full=bool(args.full),
    )
    if not steps:
        print("[doc] No steps selected (all skipped).", flush=True)
        return 0

    print(f"[doc] Root: {ROOT}", flush=True)
    print(f"[doc] Steps: {len(steps)}", flush=True)

    failures: list[tuple[str, int]] = []
    recorder_failures: list[str] = []
    total_started = time.monotonic()
    for label, cmd in steps:
        rc, _elapsed = _run_step(label, cmd)
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
                    print(f"[doc] Problem ledger updated for failed step ({details})", flush=True)
                else:
                    recorder_failures.append(f"{label}: {details}")
                    print(f"[doc] FAIL problem ledger update for `{label}`: {details}", flush=True)
            if not args.continue_on_fail:
                break

    total_elapsed = time.monotonic() - total_started
    if failures or recorder_failures:
        print("\n[doc] Summary: FAILED", flush=True)
        for label, rc in failures:
            print(f"[doc] - {label}: exit {rc}", flush=True)
        for item in recorder_failures:
            print(f"[doc] - Problem ledger: {item}", flush=True)
        print(f"[doc] Total time: {total_elapsed:.1f}s", flush=True)
        return 1

    print("\n[doc] Summary: PASS", flush=True)
    print(f"[doc] Total time: {total_elapsed:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
