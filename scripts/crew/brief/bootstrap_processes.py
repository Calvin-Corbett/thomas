"""Process launching helpers for agent bootstrap coordination loops."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from thomas.core import agent_presence

ROOT = Path(__file__).resolve().parents[3]


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _detached_flags() -> tuple[int, bool]:
    flags = 0
    close_fds = True
    if os.name == "nt":
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        close_fds = False
    return flags, close_fds


def _spawn(command: list[str], *, identity: str, cadence_name: str, cadence: float):
    flags, close_fds = _detached_flags()
    try:
        env = _clean_env()
        for key in agent_presence.SESSION_ENV_KEYS:
            env.pop(str(key), None)
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=close_fds,
            creationflags=flags,
        )
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as exc:
        return False, None, str(exc)
    return (
        True,
        {
            "agent": identity,
            "pid": int(process.pid),
            "command": " ".join(command),
            cadence_name: float(cadence),
        },
        None,
    )


def spawn_worker_loop(
    *, workboard_path: Path, worker_agent: str, task_manager_agent: str, poll_seconds: float
) -> tuple[bool, dict[str, object] | None, str | None]:
    script = (ROOT / "scripts" / "crew" / "workboard" / "worker.py").resolve()
    command = [
        sys.executable,
        str(script),
        "--workboard",
        str(workboard_path),
        "--agent",
        str(worker_agent),
        "--task-manager-agent",
        str(task_manager_agent),
        "--cycles",
        "0",
        "--poll-seconds",
        str(float(poll_seconds)),
    ]
    return _spawn(command, identity=str(worker_agent), cadence_name="poll_seconds", cadence=poll_seconds)


def spawn_task_manager_loop(
    *, workboard_path: Path, task_manager_agent: str, interval_seconds: float
) -> tuple[bool, dict[str, object] | None, str | None]:
    script = (ROOT / "scripts" / "workboard_task_manager.py").resolve()
    command = [
        sys.executable,
        str(script),
        "--workboard",
        str(workboard_path),
        "--monitor",
        "--apply",
        "--cycles",
        "0",
        "--interval-seconds",
        str(float(interval_seconds)),
        "--task-manager-agent",
        task_manager_agent,
    ]
    return _spawn(command, identity=str(task_manager_agent), cadence_name="interval_seconds", cadence=interval_seconds)


def start_task_manager_loop(
    *, workboard_path: Path, task_manager_agent: str, interval_seconds: float = 30.0
) -> tuple[bool, str, int]:
    script = (ROOT / "scripts" / "workboard_task_manager.py").resolve()
    command = [
        sys.executable,
        str(script),
        "--workboard",
        str(workboard_path),
        "--monitor",
        "--apply",
        "--cycles",
        "0",
        "--interval-seconds",
        str(float(interval_seconds)),
        "--task-manager-agent",
        task_manager_agent,
    ]
    try:
        process = subprocess.run(command, cwd=str(ROOT), env=_clean_env(), check=False)
    except FileNotFoundError as exc:
        return False, str(exc), 1
    return True, "", int(process.returncode or 0)


def start_worker_loop(*, workboard_path: Path, agent: str, poll_seconds: float = 15.0) -> tuple[bool, str, int]:
    script = (ROOT / "scripts" / "crew" / "workboard" / "worker.py").resolve()
    command = [
        sys.executable,
        str(script),
        "--workboard",
        str(workboard_path),
        "--agent",
        agent,
        "--cycles",
        "0",
        "--poll-seconds",
        str(float(poll_seconds)),
    ]
    try:
        process = subprocess.run(command, cwd=str(ROOT), env=_clean_env(), check=False)
    except FileNotFoundError as exc:
        return False, str(exc), 1
    return True, "", int(process.returncode or 0)
