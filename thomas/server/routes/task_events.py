"""Task event bridge: streams task-bot lifecycle events to the chat UI.

Runtime-first behavior:
- Prefer canonical task-bot execution state in runtime/coordination/task_bots.
- Fall back to WORKBOARD.md for compatibility during migration.
- Mirror workboard task status changes back into the runtime record when one
  exists for the watched task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.core.benchmark_lane import resolve_benchmark_repo_root, resolve_benchmark_workboard_path

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_WORKBOARD = _ROOT / "plans" / "thomas" / "WORKBOARD.md"
_POLL_INTERVAL = 2.0
_MAX_WATCH_DURATION = 600.0


def _resolved_repo_root() -> Path:
    resolved = resolve_benchmark_repo_root(_ROOT)
    return resolved if resolved is not None else _ROOT


def _resolved_workboard_path(workboard_path: Path | None = None) -> Path:
    default_path = workboard_path if workboard_path is not None else _DEFAULT_WORKBOARD
    resolved = resolve_benchmark_workboard_path(default_path)
    return resolved if resolved is not None else default_path


def _parse_task_line(line: str) -> dict[str, str] | None:
    line = line.strip()
    if not line.startswith("- "):
        return None
    parts = line[2:].split(";")
    result: dict[str, str] = {}
    for part in parts:
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        result[key.strip()] = value.strip()
    return result if result.get("task_id") else None


def _find_task_status(workboard_path: Path, task_id: str) -> dict[str, str] | None:
    if not workboard_path.exists():
        return None
    text = workboard_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        parsed = _parse_task_line(line)
        if parsed and parsed.get("task_id") == task_id:
            return parsed
    return None


def _find_task_messages(
    workboard_path: Path,
    task_id: str,
    *,
    since_iso: str | None = None,
) -> list[dict[str, str]]:
    if not workboard_path.exists():
        return []

    text = workboard_path.read_text(encoding="utf-8")
    messages: list[dict[str, str]] = []
    in_traffic = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Agent Message Traffic"):
            in_traffic = True
            continue
        if in_traffic and stripped.startswith("## "):
            break
        if not in_traffic or not stripped.startswith("- msg_id="):
            continue
        parts = stripped[2:].split(";")
        msg: dict[str, str] = {}
        for part in parts:
            part = part.strip()
            if "=" not in part:
                continue
            key, _, value = part.partition("=")
            msg[key.strip()] = value.strip()
        if msg.get("task_id") != task_id:
            continue
        if since_iso and msg.get("created_at", "") <= since_iso:
            continue
        messages.append(msg)
    return messages


def _status_to_event_type(status: str) -> str:
    return {
        "requested": "task_dispatched",
        "classified": "task_dispatched",
        "queued": "task_dispatched",
        "claimed": "task_claimed",
        "executing": "task_progress",
        "awaiting_proof": "task_progress",
        "verified": "task_progress",
        "completed": "task_complete",
        "blocked": "task_blocked",
        "failed": "task_failed",
        "abandoned": "task_failed",
        "up_for_grabs": "task_dispatched",
        "in_progress": "task_progress",
        "review": "task_progress",
        "done": "task_complete",
        "cancelled": "task_failed",
    }.get(status, "task_progress")


def _runtime_status_message(row: dict[str, Any]) -> str:
    state = str(row.get("state") or "")
    task_id = str(row.get("task_id") or "")
    owner = str(row.get("claimed_owner") or "").strip()
    summary = str(row.get("progress_summary") or row.get("summary") or task_id).strip()
    blocker = str(row.get("blocker") or "").strip()
    owner_text = f" by {owner}" if owner else ""
    return {
        "requested": f"Task registered for execution: {summary}",
        "classified": f"Task classified for task-bot routing: {summary}",
        "queued": f"Task queued for task-bot execution: {summary}",
        "claimed": f"Task claimed{owner_text}: {summary}",
        "executing": f"Task running{owner_text}: {summary}",
        "awaiting_proof": f"Task awaiting proof{owner_text}: {summary}",
        "verified": f"Task verified{owner_text}: {summary}",
        "completed": f"Task complete{owner_text}: {summary}",
        "blocked": f"Task blocked{owner_text}: {blocker or summary}",
        "failed": f"Task failed{owner_text}: {blocker or summary}",
        "abandoned": f"Task abandoned{owner_text}: {summary}",
    }.get(state, f"Task status{owner_text}: {summary}")


def _legacy_status_message(status: str, agent: str, summary: str) -> str:
    agent_text = f" by {agent}" if agent else ""
    return {
        "up_for_grabs": f"Task posted to workboard: {summary}",
        "in_progress": f"Task claimed{agent_text}: {summary}",
        "review": f"Task in review{agent_text}: {summary}",
        "done": f"Task complete{agent_text}: {summary}",
        "blocked": f"Task blocked{agent_text}: {summary}",
        "cancelled": f"Task cancelled: {summary}",
    }.get(status, f"Task status{agent_text}: {summary}")


async def watch_task(
    task_id: str,
    *,
    emit_event: Callable[[dict[str, Any]], Awaitable[None]],
    workboard_path: Path | None = None,
    poll_interval: float = _POLL_INTERVAL,
    max_duration: float = _MAX_WATCH_DURATION,
) -> None:
    wb = _resolved_workboard_path(workboard_path)
    repo_root = _resolved_repo_root()
    start_time = asyncio.get_event_loop().time()
    last_runtime_state = ""
    last_runtime_summary = ""
    last_runtime_blocker = ""
    last_legacy_status = "up_for_grabs"
    last_message_ts = ""

    log.info("Starting task watch for %s", task_id)
    try:
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_duration:
                await emit_event(
                    {
                        "type": "task_timeout",
                        "text": f"Task {task_id} is still running. Check observability for live execution state.",
                        "task_id": task_id,
                    }
                )
                break

            runtime_row = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: task_bot_runtime.find_by_task_id(task_id, repo_root=repo_root),
            )
            if isinstance(runtime_row, dict):
                state = str(runtime_row.get("state") or "")
                summary = str(runtime_row.get("progress_summary") or runtime_row.get("summary") or "")
                blocker = str(runtime_row.get("blocker") or "")
                if state != last_runtime_state or summary != last_runtime_summary or blocker != last_runtime_blocker:
                    await emit_event(
                        {
                            "type": _status_to_event_type(state),
                            "text": _runtime_status_message(runtime_row),
                            "task_id": task_id,
                            "execution_id": str(runtime_row.get("execution_id") or ""),
                            "status": state,
                            "agent": str(runtime_row.get("claimed_owner") or ""),
                        }
                    )
                    last_runtime_state = state
                    last_runtime_summary = summary
                    last_runtime_blocker = blocker
                    if state in {"completed", "failed", "abandoned"}:
                        break
            else:
                task_info = await asyncio.get_event_loop().run_in_executor(None, lambda: _find_task_status(wb, task_id))
                if task_info:
                    legacy_status = task_info.get("status", "unknown")
                    if legacy_status != last_legacy_status:
                        await emit_event(
                            {
                                "type": _status_to_event_type(legacy_status),
                                "text": _legacy_status_message(
                                    legacy_status,
                                    task_info.get("agent", ""),
                                    task_info.get("summary", ""),
                                ),
                                "task_id": task_id,
                                "status": legacy_status,
                                "agent": task_info.get("agent", ""),
                            }
                        )
                        last_legacy_status = legacy_status
                        if legacy_status in {"done", "cancelled"}:
                            break

            new_messages = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda since_iso=last_message_ts: _find_task_messages(wb, task_id, since_iso=since_iso),
            )
            for msg in new_messages:
                msg_summary = msg.get("summary", "")
                msg_from = msg.get("from", "")
                msg_ts = msg.get("created_at", "")
                await emit_event(
                    {
                        "type": "task_progress",
                        "text": f"[{msg_from}] {msg_summary}",
                        "task_id": task_id,
                        "message_kind": msg.get("kind", "status"),
                        "from_agent": msg_from,
                    }
                )
                runtime_row = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: task_bot_runtime.find_by_task_id(task_id, repo_root=repo_root),
                )
                if isinstance(runtime_row, dict):
                    with_context = str(msg_summary or runtime_row.get("progress_summary") or task_id)
                    with contextlib.suppress(OSError, RuntimeError, ValueError, TypeError):
                        task_bot_runtime.update_execution(
                            str(runtime_row.get("execution_id") or ""),
                            progress_summary=with_context,
                            heartbeat=True,
                            actor=msg_from,
                            repo_root=repo_root,
                            force=True,
                        )
                if msg_ts > last_message_ts:
                    last_message_ts = msg_ts

            task_info = await asyncio.get_event_loop().run_in_executor(None, lambda: _find_task_status(wb, task_id))
            runtime_row = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: task_bot_runtime.find_by_task_id(task_id, repo_root=repo_root),
            )
            if task_info and isinstance(runtime_row, dict):
                with contextlib.suppress(OSError, RuntimeError, ValueError, TypeError):
                    task_bot_runtime.sync_task_state(
                        task_id=task_id,
                        workboard_status=str(task_info.get("status") or ""),
                        actor=str(task_info.get("agent") or ""),
                        summary=str(task_info.get("summary") or ""),
                        claimed_owner=str(task_info.get("agent") or ""),
                        repo_root=repo_root,
                    )

            await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        log.info("Task watch cancelled for %s", task_id)
    except Exception as exc:
        log.exception("Task watch error for %s", task_id)
        with contextlib.suppress(OSError, RuntimeError, ValueError, TypeError):
            await emit_event(
                {
                    "type": "task_failed",
                    "text": f"Error watching task: {exc}",
                    "task_id": task_id,
                    "error": str(exc),
                }
            )
