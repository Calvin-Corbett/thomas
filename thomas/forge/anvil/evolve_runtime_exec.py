"""Subprocess and green-chat runtime helpers for Thomas evolve sessions."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess  # nosec
from pathlib import Path
from typing import Any

from evolve_supervisor import run_process_with_spend_watchdog

from .evolve_verification import _truncate

EVOLVE_DENIED_TOOLS = (
    "code.find_definition",
    "code.find_references",
    "code.project_structure",
    "db.command",
    "flow_execute",
    "git.blame",
    "git.commit",
    "git.diff",
    "git.log",
    "git.status",
    "nodes_execute_node",
    "shell.exec",
    "ssh.exec",
    "upgrade_create_backup",
    "upgrade_ensure_green_venv",
    "upgrade_get_paths",
    "upgrade_latest_backup",
    "upgrade_promote_green_to_blue",
    "upgrade_rollback",
    "upgrade_run_green_tests",
    "upgrade_sync_blue_to_green",
    "upgrade_sync_green_to_blue",
    "workflow_execution",
)
EVOLVE_VERIFICATION_ENV_STRIP = (
    "THOMAS_SPEND_PATH",
    "THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT",
    "THOMAS_MEMORY_ROOT",
    "THOMAS_SECRET_ROOT",
    "THOMAS_EVOLVE_GREEN_RUNTIME_WRITES",
    "THOMAS_TOOLS_ALLOW_SHELL",
    "THOMAS_TOOL_ALLOWLIST",
    "THOMAS_TOOL_DENYLIST",
    "THOMAS_MAX_AGENT_ITERATIONS",
    "THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT",
    "THOMAS_QUALITY_ENABLED",
    "THOMAS_QUALITY_ENFORCE",
    "THOMAS_QUALITY_MAX_AUTO_RETRIES",
    "THOMAS_EVOLVE_EXEC_OUTPUT_DIR",
    "THOMAS_EVOLVE_EXEC_OUTPUT_PREFIX",
)


def _display_command(command: str | list[str]) -> str:
    if isinstance(command, str):
        return command
    return " ".join(shlex.quote(str(part)) for part in command)


def _safe_output_prefix(value: str) -> str:
    prefix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return (prefix or "exec")[:120]


def _output_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _attach_output_artifacts(result: dict[str, Any], env: dict[str, str], stdout: object, stderr: object) -> None:
    output_dir = str(env.get("THOMAS_EVOLVE_EXEC_OUTPUT_DIR") or "").strip()
    if not output_dir:
        return
    artifact_root = Path(output_dir)
    artifact_root.mkdir(parents=True, exist_ok=True)
    prefix = _safe_output_prefix(str(env.get("THOMAS_EVOLVE_EXEC_OUTPUT_PREFIX") or "exec"))
    for stream_name, stream_value in (("stdout", stdout), ("stderr", stderr)):
        text = _output_text(stream_value)
        encoded = text.encode("utf-8")
        path = artifact_root / f"{prefix}.{stream_name}.txt"
        path.write_text(text, encoding="utf-8")
        result[f"{stream_name}_artifact"] = {
            "path": str(path),
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }


def _evolve_child_env() -> dict[str, str]:
    env = dict(os.environ)
    # Windows console defaults can be cp1252. Green Thomas often streams rich
    # tool output; force UTF-8 so self-evolve runs do not crash on Unicode.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["THOMAS_TOOLS_ALLOW_SHELL"] = "false"
    return env


def _evolve_max_agent_iterations() -> str:
    raw = str(os.environ.get("THOMAS_EVOLVE_MAX_AGENT_ITERATIONS") or "4").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        value = 4
    return str(max(1, min(value, 20)))


def _evolve_retry_max_agent_iterations() -> str:
    return str(max(int(_evolve_max_agent_iterations()), 6))


def _evolve_cli_fallback_enabled() -> bool:
    """Whether run_evolve_session may spawn the headless ``claude``/``codex`` CLI
    fallback that builds a real improvement when the in-process model no-ops.

    Enabled by default so genuine evolve runs still complete on the operator's own
    subscription. The test harness sets ``THOMAS_EVOLVE_DISABLE_CLI_FALLBACK=1``
    (see tests/conftest.py) so the suite NEVER spawns a real external subprocess —
    a live ``claude -p`` blocks forever under pytest and hangs the run.
    """
    raw = str(os.environ.get("THOMAS_EVOLVE_DISABLE_CLI_FALLBACK") or "").strip().lower()
    return raw in ("", "0", "false", "no")


def _merge_tool_denylist(env: dict[str, str]) -> None:
    existing = str(env.get("THOMAS_TOOL_DENYLIST") or "").strip()
    names = [item.strip() for item in existing.replace(";", ",").split(",") if item.strip()]
    seen = {item.lower() for item in names}
    for name in EVOLVE_DENIED_TOOLS:
        if name.lower() not in seen:
            names.append(name)
            seen.add(name.lower())
    env["THOMAS_TOOL_DENYLIST"] = ",".join(names)


def _strip_evolve_verification_env(env: dict[str, str]) -> None:
    for key in EVOLVE_VERIFICATION_ENV_STRIP:
        env.pop(key, None)


def _build_green_chat_command(
    green_python: str,
    profile: str,
    prompt: str,
    *,
    max_iterations: str | None = None,
) -> list[str]:
    command = [
        green_python,
        "-m",
        "thomas",
        "chat",
        "--autonomy-level",
        "4",
        "--max-iterations",
        max_iterations or _evolve_max_agent_iterations(),
        "--job-type",
        "self_development",
    ]
    if profile:
        command.extend(["-m", profile])
    command.append(prompt)
    return command


def _run_exec(
    command: str | list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    shell = isinstance(command, str)
    spend_watchdog_root = str(env.get("THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT") or "").strip()
    if spend_watchdog_root:
        guarded = run_process_with_spend_watchdog(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            repo_root=Path(spend_watchdog_root),
            shell=shell,
        )
        result = {
            "command": _display_command(command),
            "returncode": int(guarded.returncode),
            "stdout_tail": _truncate(guarded.stdout),
            "stderr_tail": _truncate(guarded.stderr),
            "timed_out": bool(guarded.timed_out),
            "spend_watchdog_triggered": bool(guarded.watchdog_triggered),
        }
        _attach_output_artifacts(result, env, guarded.stdout, guarded.stderr)
        if guarded.watchdog_verdict is not None:
            result["spend_watchdog_verdict"] = guarded.watchdog_verdict.to_dict()
        return result

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            shell=shell,
        )
        result = {
            "command": _display_command(command),
            "returncode": int(completed.returncode),
            "stdout_tail": _truncate(completed.stdout),
            "stderr_tail": _truncate(completed.stderr),
            "timed_out": False,
        }
        _attach_output_artifacts(result, env, completed.stdout, completed.stderr)
        return result
    except subprocess.TimeoutExpired as exc:
        result = {
            "command": _display_command(command),
            "returncode": 124,
            "stdout_tail": _truncate(_output_text(exc.stdout)),
            "stderr_tail": _truncate(_output_text(exc.stderr)),
            "timed_out": True,
        }
        _attach_output_artifacts(result, env, exc.stdout or "", exc.stderr or "")
        return result
