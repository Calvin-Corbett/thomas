"""Chat Dispatcher: bridges /api/chat to the task-manager execution path.

Thomas stays the front door. This module is only the handoff from actionable
chat requests into the task-bot subsystem.

Compatibility note:
- Tasks are still mirrored onto WORKBOARD.md so existing scripts/agents keep working.
- Canonical live execution state lives in runtime/coordination/task_bots.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.core.benchmark_lane import (
    benchmark_single_agent_enabled,
    resolve_benchmark_repo_root,
    resolve_benchmark_workboard_path,
)

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _ROOT / "scripts"
_DEFAULT_WORKBOARD = _ROOT / "plans" / "thomas" / "WORKBOARD.md"

CHAT_DISPATCHER_AGENT = "thomas"
TASK_MANAGER_AGENT = "task-manager-agent"
TASK_MANAGER_LOOP_AGENT = "thomas"
CHAT_TASK_WORKER_AGENT = "thomas-chat-worker"
DEFAULT_CHAT_WORKER_POOL_SIZE = 3
DEFAULT_VISIBILITY = "background"
_WORKBOARD_LOCK_TIMEOUT_SECONDS = 5.0
_WORKBOARD_LOCK_STALE_SECONDS = 30.0


@dataclass
class DispatchResult:
    ok: bool
    task_id: str
    execution_id: str = ""
    error: str | None = None


def _resolved_repo_root(repo_root: Path | None = None) -> Path:
    default_root = repo_root if repo_root is not None else _ROOT
    resolved = resolve_benchmark_repo_root(default_root)
    return resolved if resolved is not None else Path(default_root).resolve()


def _resolved_workboard_path(workboard_path: Path | None = None) -> Path:
    default_path = workboard_path if workboard_path is not None else _DEFAULT_WORKBOARD
    resolved = resolve_benchmark_workboard_path(default_path)
    return resolved if resolved is not None else Path(default_path).resolve()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_task_id(text: str) -> str:
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()[:4]
    slug = "-".join(words) if words else "task"
    suffix = secrets.token_hex(3)
    return f"chat-{slug}-{suffix}"


def _resolve_dispatch_scope(task_id: str, scope: str = "") -> str:
    scope_clean = str(scope or "").strip()
    if scope_clean and scope_clean.lower() != "chat":
        return scope_clean
    task_clean = str(task_id or "").strip() or "task"
    return f"chat/{task_clean}"


def _import_workboard_message():
    import sys

    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    try:
        from scripts import workboard_message

        return workboard_message
    except ImportError:
        import workboard_message  # type: ignore

        return workboard_message


@contextlib.contextmanager
def _workboard_lock(workboard_path: Path):
    lock_path = workboard_path.with_suffix(f"{workboard_path.suffix}.lock")
    start = time.monotonic()
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError as err:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > _WORKBOARD_LOCK_STALE_SECONDS:
                with contextlib.suppress(Exception):
                    lock_path.unlink()
                continue
            if time.monotonic() - start >= _WORKBOARD_LOCK_TIMEOUT_SECONDS:
                raise TimeoutError(f"Timed out waiting for workboard lock: {lock_path}") from err
            time.sleep(0.02)

    try:
        yield
    finally:
        if fd is not None:
            with contextlib.suppress(Exception):
                os.close(fd)
        with contextlib.suppress(Exception):
            lock_path.unlink()


_WORKBOARD_SECTION_ORDER = [
    "Agent Claims",
    "Active Tasks",
    "Up For Grabs",
    "Issues / Blockers",
    "Agent Message Traffic",
]


def _normalize_workboard(lines: list[str]) -> list[str]:
    text = "".join(lines).strip()
    if not text:
        normalized: list[str] = ["# Thomas Workboard\n\n"]
    else:
        normalized = list(lines)
        if not normalized[0].lstrip().startswith("# "):
            normalized.insert(0, "# Thomas Workboard\n\n")
        elif not normalized[0].endswith("\n"):
            normalized[0] += "\n"
        if len(normalized) == 1 or normalized[1].strip():
            normalized.insert(1, "\n")
    current_text = "".join(normalized)
    for heading in _WORKBOARD_SECTION_ORDER:
        if f"## {heading}" in current_text:
            continue
        if normalized and normalized[-1].strip():
            normalized.append("\n")
        normalized.extend(
            [
                f"## {heading}\n\n",
                "- none\n\n",
            ]
        )
        current_text = "".join(normalized)
    return normalized


def _add_task_to_workboard(
    task_id: str,
    summary: str,
    scope: str = "",
    workboard_path: Path | None = None,
) -> bool:
    wb = workboard_path or _DEFAULT_WORKBOARD
    wb.parent.mkdir(parents=True, exist_ok=True)
    resolved_scope = _resolve_dispatch_scope(task_id, scope)
    new_line = (
        f"- task_id={task_id}; scope={resolved_scope}; "
        f"summary={summary}; reported_by=chat_dispatch; status=up_for_grabs; "
        f"created_at={_now_iso()}; source=chat_dispatch\n"
    )

    with _workboard_lock(wb):
        if wb.exists():
            lines = wb.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            lines = []
        lines = _normalize_workboard(lines)
        if any(f"task_id={task_id};" in line for line in lines):
            return True

        insert_idx = None
        in_section = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("## Up For Grabs"):
                in_section = True
                insert_idx = idx + 1
                continue
            if not in_section:
                continue
            if stripped.startswith("## "):
                insert_idx = idx
                break
            if stripped == "- none":
                lines[idx] = new_line
                wb.write_text("".join(lines), encoding="utf-8")
                return True
            if stripped.startswith("- "):
                insert_idx = idx + 1
            elif not stripped:
                insert_idx = idx

        if insert_idx is None:
            log.error("Could not find ## Up For Grabs section in workboard")
            return False
        lines.insert(insert_idx, new_line)
        wb.write_text("".join(lines), encoding="utf-8")
        return True


def _send_dispatch_message(
    task_id: str,
    summary: str,
    workboard_path: Path | None = None,
) -> bool:
    try:
        wm = _import_workboard_message()
        wb = _resolved_workboard_path(workboard_path)
        send_message = getattr(wm, "send_message", None)
        if not callable(send_message):
            return False
        ok, payload = send_message(
            wb,
            sender=CHAT_DISPATCHER_AGENT,
            recipient=TASK_MANAGER_AGENT,
            task_id=task_id,
            kind="coordination",
            priority="p1",
            summary=f"New task from chat: {summary}",
            requested_action="dispatch",
            decision="pending",
            require_claims_to_have_active_task=False,
        )
        if not ok:
            log.warning("Dispatch message rejected for %s: %s", task_id, payload)
        return bool(ok)
    except Exception as exc:
        log.warning("Failed to send dispatch message: %s", exc)
        return False


def _chat_worker_pool_size() -> int:
    raw = str(os.getenv("THOMAS_CHAT_WORKER_POOL_SIZE", str(DEFAULT_CHAT_WORKER_POOL_SIZE)) or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_CHAT_WORKER_POOL_SIZE


def _chat_worker_agents() -> list[str]:
    size = _chat_worker_pool_size()
    agents = [CHAT_TASK_WORKER_AGENT]
    for idx in range(2, size + 1):
        agents.append(f"{CHAT_TASK_WORKER_AGENT}-{idx}")
    return agents


def _find_chat_worker_pids(agent: str = CHAT_TASK_WORKER_AGENT) -> list[int]:
    hits: list[int] = []
    agent_re = re.compile(
        rf"(?:^|\s)--agent(?:\s+|=)\"?{re.escape(str(agent or CHAT_TASK_WORKER_AGENT))}\"?(?:\s|$)",
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
                if "workboard_worker.py" not in command:
                    continue
                if not agent_re.search(command):
                    continue
                pid = int(row.get("ProcessId") or 0)
                if pid > 0:
                    hits.append(pid)
            return hits
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        log.debug("Chat worker PID lookup failed for %s: %s", agent, exc)
    return hits


def _parse_workboard_fields(line: str) -> dict[str, str] | None:
    text = str(line or "").strip()
    if not text.startswith("- "):
        return None
    fields: dict[str, str] = {}
    for part in text[2:].split(";"):
        key, sep, value = part.partition("=")
        if not sep:
            continue
        fields[key.strip()] = value.strip()
    return fields or None


def _select_available_chat_worker(workboard_path: Path | None = None) -> tuple[str | None, dict[str, Any]]:
    wb = _resolved_workboard_path(workboard_path)
    agents = _chat_worker_agents()
    busy_statuses = {"claimed", "queued", "in_progress"}
    status_by_agent: dict[str, list[str]] = {agent: [] for agent in agents}
    if wb.exists():
        in_active = False
        for raw_line in wb.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("## Active Tasks"):
                in_active = True
                continue
            if in_active and stripped.startswith("## "):
                break
            if not in_active:
                continue
            fields = _parse_workboard_fields(raw_line)
            if not fields:
                continue
            agent = str(fields.get("agent") or "").strip()
            if agent not in status_by_agent:
                continue
            status = str(fields.get("status") or "").strip().lower()
            if status:
                status_by_agent[agent].append(status)
    idle_agents = [agent for agent in agents if not any(status in busy_statuses for status in status_by_agent[agent])]
    selected = idle_agents[0] if idle_agents else None
    return selected, {
        "selected_worker": selected or "",
        "idle_workers": idle_agents,
        "worker_statuses": {agent: list(statuses) for agent, statuses in status_by_agent.items()},
        "worker_agents": agents,
    }


def _trigger_immediate_task_assignment(
    *,
    task_id: str,
    workboard_path: Path | None = None,
    task_manager_agent: str = TASK_MANAGER_LOOP_AGENT,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    if benchmark_single_agent_enabled():
        return False, None, "benchmark_single_agent"
    try:
        import sys

        if str(_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS))
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        try:
            from scripts import (
                workboard_task_manager,
                workboard_task_manager_reactivate,
            )
        except ImportError:
            import workboard_task_manager  # type: ignore
            import workboard_task_manager_reactivate  # type: ignore

        resolved_workboard = _resolved_workboard_path(workboard_path)
        selected_worker, pool_payload = _select_available_chat_worker(resolved_workboard)
        idle_workers = list(pool_payload.get("idle_workers") or [])
        if selected_worker:
            ok_direct, payload_direct = workboard_task_manager_reactivate._reactivate_task(
                workboard_path=resolved_workboard,
                task_id=str(task_id or "").strip(),
                agent=selected_worker,
                task_summary=None,
                scope_override=None,
                name=selected_worker,
                role="solo",
                parent="none",
                require_claims_to_have_active_task=False,
            )
            if ok_direct:
                merged_payload = dict(pool_payload or {})
                merged_payload.update(dict(payload_direct or {}))
                merged_payload["assignments"] = [
                    {
                        "task_id": str(task_id or "").strip(),
                        "agent": selected_worker,
                        "source": "chat_worker_pool",
                    }
                ]
                return True, merged_payload, None

        ok, payload = workboard_task_manager.dispatch_idle_agents_once(
            workboard_path=resolved_workboard,
            task_manager_agent=str(task_manager_agent or TASK_MANAGER_LOOP_AGENT),
            max_dispatch_per_cycle=len(idle_workers),
            online_lookback_minutes=30.0,
            apply=True,
        )
        merged_payload = dict(pool_payload or {})
        merged_payload.update(dict(payload or {}))
        return bool(ok), merged_payload, None
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def _message_timestamp(row: dict[str, Any]) -> datetime | None:
    raw = str((row or {}).get("updated_at") or (row or {}).get("created_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_dispatch_signal_agent(agent: str) -> bool:
    agent_key = str(agent or "").strip().lower()
    if not agent_key:
        return False
    return agent_key in {CHAT_DISPATCHER_AGENT, TASK_MANAGER_AGENT, "task-manager"} or "worker" in agent_key


def is_task_manager_dispatch_ready(
    *,
    workboard_path: Path | None = None,
    max_signal_age_seconds: float = 300.0,
) -> bool:
    if benchmark_single_agent_enabled():
        return False
    worker_pids: list[int] = []
    for agent in _chat_worker_agents():
        worker_pids.extend(_find_chat_worker_pids(agent))
    # Background chat execution is viable as soon as the worker pool is alive.
    # The dedicated task-manager loop helps with faster claim/sync behavior, but
    # workers can still poll the workboard and execute queued chat tasks without it.
    if worker_pids:
        return True

    wb = _resolved_workboard_path(workboard_path)
    if not wb.exists():
        return False
    try:
        wm = _import_workboard_message()
        send_message = getattr(wm, "send_message", None)
        list_messages = getattr(wm, "list_messages", None)
        if not callable(send_message) or not callable(list_messages):
            return False
        ok, payload = list_messages(wb)
        if not ok:
            return False
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(0.0, float(max_signal_age_seconds)))
        for row in reversed(messages):
            if not isinstance(row, dict):
                continue
            stamp = _message_timestamp(row)
            if stamp is None or stamp < cutoff:
                continue
            sender = str(row.get("from") or "")
            recipient = str(row.get("to") or "")
            if _is_dispatch_signal_agent(sender) or _is_dispatch_signal_agent(recipient):
                return True
        return False
    except (AttributeError, ImportError, OSError, TypeError, ValueError) as exc:
        log.debug("Task-manager readiness check failed: %s", exc)
        return False


def dispatch_to_workboard(
    text: str,
    session_id: str,
    *,
    scope: str = "",
    visibility: str = DEFAULT_VISIBILITY,
    workboard_path: Path | None = None,
    repo_root: Path | None = None,
) -> DispatchResult:
    if benchmark_single_agent_enabled():
        return DispatchResult(
            ok=False,
            task_id="",
            execution_id="",
            error="Benchmark single-agent mode disables task-manager dispatch.",
        )
    task_id = _make_task_id(text)
    summary = text[:200].replace("\n", " ").replace(";", ",").strip()
    if len(text) > 200:
        summary += "..."

    repo_root_path = _resolved_repo_root(repo_root)
    resolved_workboard = _resolved_workboard_path(workboard_path)
    resolved_scope = _resolve_dispatch_scope(task_id, scope)
    scope_tokens = [resolved_scope]
    execution = task_bot_runtime.create_execution(
        session_id=session_id,
        summary=summary,
        request_text=text,
        task_id=task_id,
        intent="chat_task",
        scope=scope_tokens,
        visibility=visibility,
        actor=TASK_MANAGER_AGENT,
        repo_root=repo_root_path,
    )
    execution_id = str(execution.get("execution_id") or "")

    try:
        task_bot_runtime.update_execution(
            execution_id,
            state="classified",
            progress_summary="Thomas handed the request to the task manager.",
            actor=TASK_MANAGER_AGENT,
            repo_root=repo_root_path,
        )

        added = _add_task_to_workboard(
            task_id=task_id,
            summary=summary,
            scope=resolved_scope,
            workboard_path=resolved_workboard,
        )
        if not added:
            task_bot_runtime.fail_execution(
                execution_id,
                actor=TASK_MANAGER_AGENT,
                summary="Dispatch failed before task could be mirrored to the workboard.",
                blocker="workboard_write_failed",
                repo_root=repo_root_path,
            )
            return DispatchResult(
                ok=False,
                task_id=task_id,
                execution_id=execution_id,
                error="Failed to add task to workboard",
            )

        task_bot_runtime.update_execution(
            execution_id,
            state="queued",
            progress_summary="Task queued for task-bot execution.",
            actor=TASK_MANAGER_AGENT,
            repo_root=repo_root_path,
        )

        messaged = _send_dispatch_message(
            task_id=task_id,
            summary=summary,
            workboard_path=resolved_workboard,
        )
        if not messaged:
            log.warning(
                "Task %s added to workboard but message send failed. Task manager will still pick it up on next poll cycle.",
                task_id,
            )
            task_bot_runtime.update_execution(
                execution_id,
                progress_summary="Task queued. Direct dispatch notice failed, waiting for manager poll cycle.",
                actor=TASK_MANAGER_AGENT,
                repo_root=repo_root_path,
            )
        else:
            dispatched_now, dispatched_payload, dispatched_error = _trigger_immediate_task_assignment(
                task_id=task_id,
                workboard_path=resolved_workboard,
                task_manager_agent=TASK_MANAGER_LOOP_AGENT,
            )
            if dispatched_now and isinstance(dispatched_payload, dict):
                assignments = list(dispatched_payload.get("assignments") or [])
                if assignments:
                    first_assignment = dict(assignments[0] or {})
                    owner = str(first_assignment.get("agent") or "").strip()
                    with contextlib.suppress(Exception):
                        task_bot_runtime.update_execution(
                            execution_id,
                            state="claimed",
                            claimed_owner=owner,
                            progress_summary=(
                                f"Task claimed by {owner}."
                                if owner
                                else "Task claimed by an available background worker."
                            ),
                            actor=TASK_MANAGER_LOOP_AGENT,
                            repo_root=repo_root_path,
                            force=True,
                        )
            elif dispatched_error:
                log.debug("Immediate task assignment trigger failed for %s: %s", task_id, dispatched_error)

        log.info(
            "Dispatched chat message to task manager: task_id=%s execution_id=%s summary=%s",
            task_id,
            execution_id,
            summary[:80],
        )
        return DispatchResult(ok=True, task_id=task_id, execution_id=execution_id)
    except Exception as exc:
        log.exception("Chat dispatch failed for task_id=%s", task_id)
        with contextlib.suppress(Exception):
            task_bot_runtime.fail_execution(
                execution_id,
                actor=TASK_MANAGER_AGENT,
                summary=f"Dispatch crashed: {type(exc).__name__}: {exc}",
                blocker="dispatch_exception",
                repo_root=repo_root_path,
            )
        return DispatchResult(
            ok=False,
            task_id=task_id,
            execution_id=execution_id,
            error=f"{type(exc).__name__}: {exc}",
        )


async def dispatch_async(
    text: str,
    session_id: str,
    *,
    scope: str = "",
    visibility: str = DEFAULT_VISIBILITY,
    workboard_path: Path | None = None,
    repo_root: Path | None = None,
    emit_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> DispatchResult:
    loop = asyncio.get_running_loop()

    if emit_event:
        with contextlib.suppress(Exception):
            await emit_event(
                {
                    "type": "task_dispatched",
                    "text": "Dispatching to task manager...",
                    "session_id": session_id,
                }
            )

    result = await loop.run_in_executor(
        None,
        lambda: dispatch_to_workboard(
            text,
            session_id,
            scope=scope,
            visibility=visibility,
            workboard_path=workboard_path,
            repo_root=repo_root,
        ),
    )

    if emit_event:
        try:
            if result.ok:
                await emit_event(
                    {
                        "type": "task_dispatched",
                        "text": f"Task {result.task_id} dispatched to task manager.",
                        "task_id": result.task_id,
                        "execution_id": result.execution_id,
                        "ok": True,
                    }
                )
            else:
                await emit_event(
                    {
                        "type": "task_dispatch_failed",
                        "text": f"Dispatch failed: {result.error}",
                        "task_id": result.task_id,
                        "execution_id": result.execution_id,
                        "ok": False,
                        "error": result.error,
                    }
                )
        except Exception:
            pass

    return result
