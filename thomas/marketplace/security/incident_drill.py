"""Incident response drill runner for security program maturity."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str], Path], tuple[int, str, str]]


_SCOPE_PREFIXES: dict[str, tuple[str, ...]] = {
    "plan": ("docs/THREAT_MODEL_WEB_API.md",),
    "workspace": (
        "docs/support/TROUBLESHOOTING.md",
        "docs/support/MIGRATION_GUIDE.md",
        "scripts/config_validator.py",
        "scripts/onboarding_outcomes_report.py",
    ),
}


def _normalize_rel_path(path: Path) -> str:
    return path.as_posix()


def _validate_scoped_path(repo_root: Path, rel_path: str, scope: str) -> Path:
    if scope not in _SCOPE_PREFIXES:
        raise ValueError(f"unknown scope '{scope}' for {rel_path}")

    root = repo_root.resolve()
    path = (repo_root / rel_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {rel_path}") from exc

    rel = _normalize_rel_path(path.relative_to(root))
    allowed = tuple(prefix.rstrip("/\\") for prefix in _SCOPE_PREFIXES.get(scope, ()))
    if allowed and not any(rel == prefix or rel.startswith(f"{prefix}/") for prefix in allowed):
        raise ValueError(f"{rel_path} is not allowed under {scope} scope")

    return path


def _required_artifacts() -> tuple[tuple[str, str, str], ...]:
    return (
        ("threat_model", "plan", "docs/THREAT_MODEL_WEB_API.md"),
        ("troubleshooting", "workspace", "docs/support/TROUBLESHOOTING.md"),
        ("migration_guide", "workspace", "docs/support/MIGRATION_GUIDE.md"),
    )


def _command_artifacts() -> tuple[tuple[str, str, list[str]], ...]:
    return (
        ("config_validator", "workspace", [sys.executable, "scripts/config_validator.py", "--json"]),
        (
            "onboarding_outcomes",
            "workspace",
            [sys.executable, "scripts/onboarding_outcomes_report.py", "--days", "7", "--json"],
        ),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_runner(cmd: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    completed = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return int(completed.returncode), str(completed.stdout or ""), str(completed.stderr or "")


def run_security_incident_drill(
    repo_root: Path,
    *,
    scenario: str = "web_api",
    include_command_checks: bool = True,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    started = _now_iso()
    steps: list[dict[str, Any]] = []
    scoped_files: set[str] = set()

    for step_id, scope, rel in _required_artifacts():
        try:
            path = _validate_scoped_path(repo_root, rel, scope=scope)
            scope_violation = False
            scope_error = ""
        except ValueError as exc:
            path = (repo_root / rel).resolve()
            scope_violation = True
            scope_error = str(exc)

            ok = (not scope_violation) and path.exists()
            scoped_files.add(str(path))
            steps.append(
                {
                    "id": step_id,
                    "type": "artifact_check",
                    "status": "pass" if ok else "fail",
                    "scope": scope,
                    "details": str(path),
                    "scope_error": scope_error,
                }
            )

    if include_command_checks:
        command_steps = _command_artifacts()
        for step_id, scope, command in command_steps:
            command_target = (repo_root / str(command[1])).resolve()
            try:
                script_path = _validate_scoped_path(repo_root, str(command[1]), scope=scope)
            except ValueError as exc:
                scoped_files.add(str(command_target))
                steps.append(
                    {
                        "id": step_id,
                        "type": "command_check",
                        "scope": scope,
                        "status": "fail",
                        "path": str(command_target),
                        "command": list(command),
                        "exit_code": 1,
                        "scope_error": str(exc),
                    }
                )
                continue

            scoped_command = [command[0], str(script_path)] + list(command[2:])
            code, stdout, stderr = runner(scoped_command, repo_root)
            steps.append(
                {
                    "id": step_id,
                    "type": "command_check",
                    "status": "pass" if code == 0 else "fail",
                    "exit_code": int(code),
                    "scope": scope,
                    "path": str(script_path),
                    "command": scoped_command,
                    "stdout_tail": "\n".join(str(stdout).splitlines()[-10:]),
                    "stderr_tail": "\n".join(str(stderr).splitlines()[-10:]),
                }
            )

    failed = [step for step in steps if str(step.get("status")) != "pass"]
    completed = _now_iso()

    return {
        "ok": len(failed) == 0,
        "scenario": str(scenario),
        "started_at": started,
        "completed_at": completed,
        "summary": {
            "step_count": len(steps),
            "passed": len(steps) - len(failed),
            "failed": len(failed),
            "scoped_files": sorted(scoped_files),
        },
        "steps": steps,
    }
