"""Doc reliability runner.

Runs critical gates and protocol safety tests in one command.
Designed for local hardening before commits/PRs.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

GATE_COMMANDS: Sequence[tuple[str, Sequence[str]]] = (
    ("Model onboarding gate", (PY, "scripts/check_model_onboarding_gate.py")),
    ("Module audit gate", (PY, "scripts/check_module_audit_gate.py")),
    ("Plan structure gate", (PY, "scripts/check_plan_structure_gate.py")),
    ("Pre-commit skip policy gate", (PY, "scripts/check_precommit_skip_policy.py")),
    ("Workboard claims gate", (PY, "scripts/check_workboard_claims.py")),
    ("Workboard task problems gate", (PY, "scripts/check_workboard_task_problems.py")),
    ("Repo identity gate", (PY, "scripts/check_repo_identity.py")),
    ("Workboard issue tool smoke", (PY, "scripts/workboard_issue.py", "--help")),
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


def run(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Doc reliability checks.")
    parser.add_argument("--skip-gates", action="store_true", help="Skip gate scripts.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip protocol safety tests.")
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
    total_started = time.monotonic()
    for label, cmd in steps:
        rc, _elapsed = _run_step(label, cmd)
        if rc != 0:
            failures.append((label, rc))
            if not args.continue_on_fail:
                break

    total_elapsed = time.monotonic() - total_started
    if failures:
        print("\n[doc] Summary: FAILED", flush=True)
        for label, rc in failures:
            print(f"[doc] - {label}: exit {rc}", flush=True)
        print(f"[doc] Total time: {total_elapsed:.1f}s", flush=True)
        return 1

    print("\n[doc] Summary: PASS", flush=True)
    print(f"[doc] Total time: {total_elapsed:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
