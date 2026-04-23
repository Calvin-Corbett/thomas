"""Task-manager bootstrap helpers for app startup."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from thomas.core.benchmark_lane import benchmark_single_agent_enabled

log = logging.getLogger(__name__)

_TASK_MANAGER_LOOP_CMD_RE = re.compile(r"(?:^|[\\/\s])workboard_task_manager\.py(?:\s|$)", re.IGNORECASE)
_TASK_MANAGER_AGENT_RE = re.compile(
    r"(?:^|\s)--task-manager-agent(?:\s+|=)\"?(?:task-manager-agent|thomas)\"?(?:\s|$)",
    re.IGNORECASE,
)
_TASK_MANAGER_WORKER_CMD_RE = re.compile(r"(?:^|[\\/\s])workboard_worker\.py(?:\s|$)", re.IGNORECASE)
_TASK_MANAGER_CHAT_WORKER = "thomas-chat-worker"
_DEFAULT_TASK_MANAGER_CHAT_WORKER_POOL_SIZE = 3
_TASK_MANAGER_BOOTSTRAP_INTERVAL_SECONDS = 5.0
_TASK_MANAGER_WORKER_POLL_SECONDS = 2.0


def _task_manager_loop_enabled() -> bool:
    if benchmark_single_agent_enabled():
        return False
    if os.getenv("PYTEST_CURRENT_TEST") and "THOMAS_TASK_MANAGER_LOOP_ENABLED" not in os.environ:
        return False
    raw = str(os.getenv("THOMAS_TASK_MANAGER_LOOP_ENABLED", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _find_task_manager_loop_pids() -> list[int]:
    hits: list[int] = []
    try:
        if os.name == "nt":
            probe = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6.0,
                check=False,
            )
            if probe.returncode != 0 or not str(probe.stdout or "").strip():
                return hits
            payload = json.loads(probe.stdout)
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                command = str(row.get("CommandLine") or "")
                if not command or not _TASK_MANAGER_LOOP_CMD_RE.search(command):
                    continue
                if not _TASK_MANAGER_AGENT_RE.search(command):
                    continue
                pid = int(row.get("ProcessId") or 0)
                if pid > 0:
                    hits.append(pid)
        else:
            probe = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6.0,
                check=False,
            )
            if probe.returncode != 0:
                return hits
            for raw in str(probe.stdout or "").splitlines():
                line = raw.strip()
                if not line:
                    continue
                pid_text, _, command = line.partition(" ")
                if not command or not _TASK_MANAGER_LOOP_CMD_RE.search(command):
                    continue
                if not _TASK_MANAGER_AGENT_RE.search(command):
                    continue
                pid = int(pid_text or 0)
                if pid > 0:
                    hits.append(pid)
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        log.debug("Task-manager loop lookup failed: %s", exc)
    return hits


def _find_task_manager_worker_pids(agent: str = _TASK_MANAGER_CHAT_WORKER) -> list[int]:
    hits: list[int] = []
    agent_re = re.compile(
        rf"(?:^|\s)--agent(?:\s+|=)\"?{re.escape(str(agent or _TASK_MANAGER_CHAT_WORKER))}\"?(?:\s|$)",
        re.IGNORECASE,
    )
    try:
        if os.name == "nt":
            probe = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6.0,
                check=False,
            )
            if probe.returncode != 0 or not str(probe.stdout or "").strip():
                return hits
            payload = json.loads(probe.stdout)
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                command = str(row.get("CommandLine") or "")
                if not command or not _TASK_MANAGER_WORKER_CMD_RE.search(command):
                    continue
                if not agent_re.search(command):
                    continue
                pid = int(row.get("ProcessId") or 0)
                if pid > 0:
                    hits.append(pid)
        else:
            probe = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6.0,
                check=False,
            )
            if probe.returncode != 0:
                return hits
            for raw in str(probe.stdout or "").splitlines():
                line = raw.strip()
                if not line:
                    continue
                pid_text, _, command = line.partition(" ")
                if not command or not _TASK_MANAGER_WORKER_CMD_RE.search(command):
                    continue
                if not agent_re.search(command):
                    continue
                pid = int(pid_text or 0)
                if pid > 0:
                    hits.append(pid)
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        log.debug("Task-manager worker lookup failed: %s", exc)
    return hits


def _task_manager_chat_worker_pool_size() -> int:
    raw = str(os.getenv("THOMAS_CHAT_WORKER_POOL_SIZE", str(_DEFAULT_TASK_MANAGER_CHAT_WORKER_POOL_SIZE)) or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_TASK_MANAGER_CHAT_WORKER_POOL_SIZE


def _task_manager_chat_worker_agents() -> list[str]:
    size = _task_manager_chat_worker_pool_size()
    agents = [_TASK_MANAGER_CHAT_WORKER]
    for idx in range(2, size + 1):
        agents.append(f"{_TASK_MANAGER_CHAT_WORKER}-{idx}")
    return agents


def ensure_task_manager_loop_started(repo_root: Path) -> dict[str, Any]:
    if not _task_manager_loop_enabled():
        return {"ok": False, "reason": "disabled"}

    try:
        from scripts import agent_bootstrap_claim as bootstrap
    except (ImportError, ModuleNotFoundError, AttributeError, RuntimeError) as exc:
        return {"ok": False, "reason": f"bootstrap_import_failed:{type(exc).__name__}"}

    workboard_path = (repo_root / "plans" / "thomas" / "WORKBOARD.md").resolve()
    task_manager_agent = str(getattr(bootstrap, "DEFAULT_TASK_MANAGER_AGENT", "task-manager-agent"))
    worker_agents = _task_manager_chat_worker_agents()
    existing_loops = _find_task_manager_loop_pids()
    existing_workers_by_agent = {agent: _find_task_manager_worker_pids(agent) for agent in worker_agents}
    existing_workers = [pid for pids in existing_workers_by_agent.values() for pid in pids]
    if existing_loops and all(existing_workers_by_agent.get(agent) for agent in worker_agents):
        return {
            "ok": True,
            "reason": "already_running",
            "loop_pids": existing_loops,
            "worker_pids": existing_workers,
            "worker_agents": worker_agents,
        }

    claim_issue = ""
    if not existing_loops:
        try:
            if not bootstrap._is_task_manager_claimed(workboard_path, task_manager_agent):
                claim_scope = bootstrap._default_task_manager_scope(workboard_path)
                ok_claim, claim_message = bootstrap.claim_tool.claim(
                    workboard_path=workboard_path,
                    agent=task_manager_agent,
                    scope=claim_scope,
                    task="[WIP][TM] task-manager control loop",
                    name=task_manager_agent,
                    role="solo",
                    parent="none",
                    allow_dirty=True,
                    dirty_reason="server startup task-manager bootstrap",
                    allow_presence_override=True,
                    presence_override_reason="server startup task-manager bootstrap",
                )
                if not ok_claim:
                    claim_issue = str(claim_message or "")
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            claim_issue = f"{type(exc).__name__}: {exc}"

    loop_payload: dict[str, Any] = {}
    worker_payloads: list[dict[str, Any]] = []
    worker_errors: list[str] = []

    if not existing_loops:
        try:
            ok_loop, spawned_loop_payload, spawn_loop_error = bootstrap._spawn_task_manager_loop(
                workboard_path=workboard_path,
                task_manager_agent=task_manager_agent,
                interval_seconds=_TASK_MANAGER_BOOTSTRAP_INTERVAL_SECONDS,
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "reason": f"spawn_exception:{type(exc).__name__}", "detail": str(exc)}
        if not ok_loop:
            return {
                "ok": False,
                "reason": "spawn_failed",
                "detail": str(spawn_loop_error or ""),
                "claim_issue": claim_issue,
            }
        loop_payload = dict(spawned_loop_payload or {})

    for worker_agent in worker_agents:
        if existing_workers_by_agent.get(worker_agent):
            continue
        try:
            ok_worker, spawned_worker_payload, spawn_worker_error = bootstrap._spawn_worker_loop(
                workboard_path=workboard_path,
                worker_agent=worker_agent,
                task_manager_agent=task_manager_agent,
                poll_seconds=_TASK_MANAGER_WORKER_POLL_SECONDS,
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            worker_errors.append(f"{worker_agent}: {type(exc).__name__}: {exc}")
        else:
            if ok_worker:
                worker_payloads.append(dict(spawned_worker_payload or {}))
            else:
                worker_errors.append(f"{worker_agent}: {str(spawn_worker_error or '')}")

    ok = bool(existing_loops or loop_payload) and all(
        existing_workers_by_agent.get(agent) or any(str(row.get("agent") or "").strip() == agent for row in worker_payloads)
        for agent in worker_agents
    )
    reason = "already_running"
    if loop_payload or worker_payloads:
        reason = "spawned"
    elif existing_loops and worker_errors:
        reason = "worker_spawn_failed"
    return {
        "ok": ok,
        "reason": reason,
        "loop": loop_payload,
        "workers": worker_payloads,
        "loop_pids": existing_loops,
        "worker_pids": existing_workers
        + [int(row.get("pid") or 0) for row in worker_payloads if int(row.get("pid") or 0) > 0],
        "worker_agent": worker_agents[0] if worker_agents else _TASK_MANAGER_CHAT_WORKER,
        "worker_agents": worker_agents,
        "claim_issue": claim_issue,
        "worker_error": "; ".join(worker_errors),
        "worker_errors": worker_errors,
    }
