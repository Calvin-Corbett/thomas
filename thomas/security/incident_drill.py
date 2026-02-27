"""Incident response drill runner for security program maturity."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str], Path], tuple[int, str, str]]


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

    required_artifacts = [
        ("threat_model", repo_root / "docs" / "THREAT_MODEL_WEB_API.md"),
        ("troubleshooting", repo_root / "docs" / "support" / "TROUBLESHOOTING.md"),
        ("migration_guide", repo_root / "docs" / "support" / "MIGRATION_GUIDE.md"),
    ]

    for step_id, path in required_artifacts:
        ok = path.exists()
        steps.append(
            {
                "id": step_id,
                "type": "artifact_check",
                "status": "pass" if ok else "fail",
                "details": str(path),
            }
        )

    if include_command_checks:
        command_steps = [
            ("config_validator", [sys.executable, "scripts/config_validator.py", "--json"]),
            ("onboarding_outcomes", [sys.executable, "scripts/onboarding_outcomes_report.py", "--days", "7", "--json"]),
        ]
        for step_id, command in command_steps:
            code, stdout, stderr = runner(command, repo_root)
            steps.append(
                {
                    "id": step_id,
                    "type": "command_check",
                    "status": "pass" if code == 0 else "fail",
                    "exit_code": int(code),
                    "command": list(command),
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
        },
        "steps": steps,
    }
