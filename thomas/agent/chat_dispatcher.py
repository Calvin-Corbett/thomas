"""Chat Dispatcher: bridges /api/chat to the task-manager execution path.

Thomas stays the front door. This module is only the handoff from actionable
chat requests into the task-bot subsystem.

Compatibility note:
- Tasks are still mirrored onto WORKBOARD.md so existing scripts/agents keep working.
- Canonical live execution state lives in runtime/coordination/task_bots.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _ROOT / "scripts"
_DEFAULT_WORKBOARD = _ROOT / "plans" / "thomas" / "WORKBOARD.md"

CHAT_DISPATCHER_AGENT = "thomas"
TASK_MANAGER_AGENT = "task-manager-agent"
DEFAULT_VISIBILITY = "background"


@dataclass
class DispatchResult:
    ok: bool
    task_id: str
    execution_id: str = ""
    error: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_task_id(text: str) -> str:
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()[:4]
    slug = "-".join(words) if words else "task"
    suffix = secrets.token_hex(3)
    return f"chat-{slug}-{suffix}"


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
        from crew.workboard import message as workboard_message  # type: ignore

        return workboard_message


def _add_task_to_workboard(
    task_id: str,
    summary: str,
    scope: str = "",
    workboard_path: Path | None = None,
) -> bool:
    wb = workboard_path or _DEFAULT_WORKBOARD
    if not wb.exists():
        log.error("Workboard not found at %s", wb)
        return False

    lines = wb.read_text(encoding="utf-8").splitlines(keepends=True)
    new_line = (
        f"- task_id={task_id}; scope={scope or 'chat'}; "
        f"summary={summary}; status=up_for_grabs; "
        f"created_at={_now_iso()}; source=chat_dispatch\n"
    )

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
        wb = workboard_path or _DEFAULT_WORKBOARD
        lines = wb.read_text(encoding="utf-8").splitlines()
        msg_id = f"msg-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-chat-dispatch"
        result = wm._append_message(
            lines=lines,
            msg_id=msg_id,
            from_agent=CHAT_DISPATCHER_AGENT,
            to_agent=TASK_MANAGER_AGENT,
            task_id=task_id,
            kind="coordination",
            priority="p1",
            summary=f"New task from chat: {summary}",
            requested_action="dispatch",
        )
        if result is None:
            return False
        wb.write_text("\n".join(result) + "\n", encoding="utf-8")
        return True
    except Exception:
        # Broad catch: dispatch notices are best-effort; workboard mirroring already queued the task.
        log.exception("Failed to send dispatch message for task_id=%s", task_id)
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
    task_id = _make_task_id(text)
    summary = text[:200].replace("\n", " ").replace(";", ",").strip()
    if len(text) > 200:
        summary += "..."

    repo_root_path = Path(repo_root).resolve() if repo_root is not None else _ROOT
    scope_tokens = [scope] if str(scope or "").strip() else ["chat"]
    execution = task_bot_runtime.create_execution(
        session_id=session_id,
        summary=summary,
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
            scope=scope,
            workboard_path=workboard_path,
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
            workboard_path=workboard_path,
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

        log.info(
            "Dispatched chat message to task manager: task_id=%s execution_id=%s summary=%s",
            task_id,
            execution_id,
            summary[:80],
        )
        return DispatchResult(ok=True, task_id=task_id, execution_id=execution_id)
    except Exception as exc:
        # Broad catch: keep chat responsive while recording any dispatch boundary failure.
        log.exception("Chat dispatch failed for task_id=%s", task_id)
        try:
            task_bot_runtime.fail_execution(
                execution_id,
                actor=TASK_MANAGER_AGENT,
                summary=f"Dispatch crashed: {type(exc).__name__}: {exc}",
                blocker="dispatch_exception",
                repo_root=repo_root_path,
            )
        except Exception:
            # Broad catch: failure-recording is secondary and must not mask the original dispatch error.
            log.exception("Failed to mark dispatch execution %s as failed", execution_id)
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
        try:
            await emit_event(
                {
                    "type": "task_dispatched",
                    "text": "Dispatching to task manager...",
                    "session_id": session_id,
                }
            )
        except Exception:
            # Broad catch: caller-provided event hooks must not block dispatch.
            log.exception("Dispatch start event callback failed for session_id=%s", session_id)

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
            # Broad catch: caller-provided event hooks must not block returning the dispatch result.
            log.exception("Dispatch result event callback failed for task_id=%s", result.task_id)

    return result
