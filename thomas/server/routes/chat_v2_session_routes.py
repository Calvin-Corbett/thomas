"""Session lifecycle and delegation receipt endpoints for Chat V2."""

from __future__ import annotations

import asyncio
import logging
import re as _re
import sqlite3
from collections.abc import Awaitable, Callable

# timezone.utc, not datetime.UTC: the UTC alias is Python 3.11+ and this repo
# still supports 3.10 — the failed import silently unregistered EVERY Chat V2
# route on 3.10 (fail-closed 404s instead of guarded 401s).
from datetime import datetime, timezone

UTC = timezone.utc
from functools import wraps
from typing import Any

from aiohttp import web

from thomas.chat.session_store import SessionStore
from thomas.core import task_bot_runtime
from thomas.core.action_receipt import delegated_action_receipt
from thomas.marketplace.orchestrator.registry import SpecialistRegistry
from thomas.server.chat_delegation import apply_task_update, session_active_delegations
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE, APP_SPECIALIST_REGISTRY
from thomas.server.routes.chat_v2_support import _evict_session_llm

try:
    from thomas.server.app_keys import APP_MEMORY
except ImportError:
    APP_MEMORY = None

log = logging.getLogger(__name__)


def guard_chat_v2_read(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    require_api_access: Callable[[web.Request], None],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    if not callable(require_api_access):
        raise TypeError("require_api_access must be callable")

    @wraps(handler)
    async def guarded(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        return await handler(request)

    return guarded


async def handle_session_get(request: web.Request) -> web.Response:
    sid = request.match_info["session_id"]
    session_store: SessionStore = request.app[APP_SESSION_STORE]
    conversation = await session_store.load(sid)
    if conversation is None:
        return web.json_response({"error": "Session not found"}, status=404)
    return web.json_response({"session_id": sid, "conversation": conversation.to_dict()})


async def handle_session_export(request: web.Request) -> web.Response:
    sid = request.match_info["session_id"]
    session_store: SessionStore = request.app[APP_SESSION_STORE]
    conversation = await session_store.load(sid)
    if conversation is None:
        return web.json_response({"error": "Session not found"}, status=404)
    meta = await session_store.load_meta(sid)
    payload = {
        "schema_version": "thomas.chat.export.v1",
        "exported_at": datetime.now(UTC).isoformat(),
        "session_id": sid,
        "conversation": conversation.to_dict(),
        "meta": meta.to_dict() if meta is not None else None,
    }
    response = web.json_response(payload)
    response.headers["Content-Disposition"] = f'attachment; filename="thomas-chat-{sid}.json"'
    return response


async def handle_session_truncate(request: web.Request) -> web.Response:
    """Cut a session back to its first N messages (edit-and-resend support).

    Editing an already-sent message forks the conversation at that point: the
    client truncates the stored history, then sends the edited text as the
    next turn. The live per-session LLM is evicted so stale context can't
    leak the removed turns back in.
    """
    sid = request.match_info["session_id"]
    try:
        body = await request.json()
    except (ValueError, TypeError):
        body = {}
    keep = max(0, int((body or {}).get("keep_messages") or 0))
    session_store: SessionStore = request.app[APP_SESSION_STORE]
    conversation = await session_store.load(sid)
    if conversation is None:
        return web.json_response({"error": "Session not found"}, status=404)
    msgs = conversation.get_messages()
    if keep >= len(msgs):
        return web.json_response({"session_id": sid, "kept": len(msgs), "removed": 0})
    from thomas.chat.conversation import ConversationManager

    trimmed = ConversationManager(messages=msgs[:keep])
    await session_store.save(sid, trimmed, force=True)
    await _evict_session_llm(request.app, sid)
    return web.json_response({"session_id": sid, "kept": keep, "removed": len(msgs) - keep})


async def handle_session_delete(request: web.Request) -> web.Response:
    sid = request.match_info["session_id"]
    session_store: SessionStore = request.app[APP_SESSION_STORE]
    deleted = await session_store.delete(sid)
    memory_purge: dict[str, Any] = {"completed": False, "forgotten": False}
    app_memory = request.app.get(APP_MEMORY) if APP_MEMORY is not None else None
    forget_thread = getattr(app_memory, "forget_thread", None)
    if callable(forget_thread):
        try:
            memory_purge = {"completed": True, **dict(await asyncio.to_thread(forget_thread, sid))}
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
            memory_purge = {"completed": False, "forgotten": False, "error": type(exc).__name__}
    await _evict_session_llm(request.app, sid)
    # The background-task records too. Deleting a chat reported a clean sweep
    # including a memory purge, and left these behind -- task summaries, progress
    # text and produced-file paths, still served at the same address. 17
    # conversations on this machine were already in that state: chat gone, data
    # not. Best effort: failing to sweep them must not fail the delete.
    tasks_removed = 0
    try:
        tasks_removed = await asyncio.to_thread(task_bot_runtime.delete_session_executions, sid)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning("could not remove task records for deleted session %s: %s", sid, exc)
    return web.json_response(
        {
            "deleted": deleted,
            "session_id": sid,
            "memory_purge": memory_purge,
            "task_records_removed": tasks_removed,
        }
    )


# The step timeline is USER-FACING. Backend transition summaries carry internal
# lifecycle jargon ("Provider-native worker is initializing", "workspace change
# baseline"); rewrite those to plain language so "see what the agent did" reads
# like a person's log, not a stack trace.
_INTERNAL_STEP_RE = _re.compile(
    r"provider-native|background execution|workspace change baseline|"
    r"initializ|queued on|is running|is initializing|start gate|"
    r"prepared for|recording|reconcil|attribution|receipt",
    _re.I,
)


def _humanize_step_summary(summary: str) -> str:
    text = str(summary or "").strip()
    if not text:
        return ""
    if _INTERNAL_STEP_RE.search(text):
        return "Getting started"
    # Strip any leading bracket tag like "[worker] " noise.
    return _re.sub(r"^\s*\[[^\]]+\]\s*", "", text).strip()


async def handle_delegation_detail(request: web.Request) -> web.Response:
    """Return one delegation's step-by-step timeline for the expandable card.

    Surfaces the durable `transitions[]` history (timestamped, humanized step
    summaries) plus current state/progress/steer queue — so clicking an agent
    shows what it actually did, not a single line.
    """
    sid = str(request.match_info.get("session_id", "") or "").strip()
    exec_id = str(request.match_info.get("execution_id", "") or "").strip()
    if not sid or not exec_id:
        return web.json_response({"ok": False, "error": "invalid_reference"}, status=400)
    row = task_bot_runtime.get_execution(exec_id) or {}
    owner = str(row.get("conversation_id") or "").strip()
    if owner and owner != sid:
        return web.json_response({"ok": False, "error": "session_mismatch"}, status=403)
    if not row:
        return web.json_response({"ok": False, "error": "not_found"}, status=404)
    transitions = row.get("transitions") if isinstance(row.get("transitions"), list) else []
    steps: list[dict[str, str]] = []
    last_summary = ""
    for t in transitions:
        if not isinstance(t, dict):
            continue
        summary = _humanize_step_summary(str(t.get("summary") or "").strip())
        if not summary or summary == last_summary:
            continue  # skip empties + collapse consecutive duplicates
        last_summary = summary
        steps.append(
            {
                "summary": summary,
                "state": str(t.get("state") or "").strip(),
                "actor": str(t.get("actor") or "").strip(),
                "blocker": str(t.get("blocker") or "").strip(),
                "at": str(t.get("occurred_at") or "").strip(),
            }
        )
    pending = [str(p).strip() for p in (row.get("pending_instructions") or []) if str(p).strip()]
    # Files a run left behind when it did not succeed. Reported separately from
    # proof so a surface can offer them without implying the task completed --
    # recording them and never showing them would lose the work just as surely.
    salvaged = [str(p).strip() for p in (row.get("salvaged_artifacts") or []) if str(p).strip()]
    return web.json_response(
        {
            "ok": True,
            "execution_id": exec_id,
            "state": str(row.get("state") or "").strip(),
            "bot_name": str(row.get("bot_name") or row.get("bot_id") or "").strip(),
            "last_progress": str(row.get("progress_summary") or "").strip(),
            "steps": steps,
            "pending_instructions": pending,
            "salvaged_artifacts": salvaged,
        }
    )


async def handle_steer_delegation(
    request: web.Request,
    *,
    task_update: Any = apply_task_update,
) -> web.Response:
    """Send a steering message to a RUNNING delegation (jump in / take over)."""
    sid = str(request.match_info.get("session_id", "") or "").strip()
    exec_id = str(request.match_info.get("execution_id", "") or "").strip()
    if not sid or not exec_id:
        return web.json_response({"ok": False, "error": "invalid_reference"}, status=400)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        body = {}
    text = str((body or {}).get("message") or "").strip()
    if not text:
        return web.json_response({"ok": False, "error": "empty_message"}, status=400)
    result = task_update(sid, exec_id, update=text)
    return web.json_response(result, status=200 if bool(result.get("ok")) else 404)


async def handle_session_delegations(
    request: web.Request,
    *,
    active_delegations: Any = session_active_delegations,
) -> web.Response:
    sid = request.match_info["session_id"]
    delegations = []
    for raw in active_delegations(sid):
        row = dict(raw or {})
        if not isinstance(row.get("receipt"), dict):
            row["receipt"] = delegated_action_receipt(row, session_id=sid).to_dict()
        delegations.append(row)
    return web.json_response({"session_id": sid, "delegations": delegations})


async def handle_cancel_delegation(
    request: web.Request,
    *,
    task_update: Any = apply_task_update,
) -> web.Response:
    """Request cancellation of one running delegation owned by this chat session."""
    sid = str(request.match_info.get("session_id", "") or "").strip()
    exec_id = str(request.match_info.get("execution_id", "") or "").strip()
    if not sid or not exec_id:
        return web.json_response({"ok": False, "error": "invalid_task_reference"}, status=400)
    result = task_update(sid, exec_id, cancel=True)
    return web.json_response(result, status=200 if bool(result.get("ok")) else 404)


async def handle_mark_delegation_reported(request: web.Request) -> web.Response:
    """Mark one session-owned delegation as already announced in chat."""
    sid = str(request.match_info.get("session_id", "") or "").strip()
    exec_id = str(request.match_info.get("execution_id", "") or "").strip()
    if not sid or not exec_id:
        return web.json_response(
            {"session_id": sid, "execution_id": exec_id, "ok": False, "error": "invalid_task_reference"},
            status=400,
        )
    try:
        row = task_bot_runtime.get_execution(exec_id)
        if not isinstance(row, dict) or not row:
            return web.json_response(
                {"session_id": sid, "execution_id": exec_id, "ok": False, "error": "execution_not_found"},
                status=404,
            )
        owner = str(row.get("conversation_id") or "").strip()
        if not owner or owner != sid:
            return web.json_response(
                {"session_id": sid, "execution_id": exec_id, "ok": False, "error": "session_mismatch"},
                status=403,
            )
        task_bot_runtime.update_execution(
            exec_id,
            reported_to_chat_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        log.warning("mark-reported failed for execution %s", exec_id, exc_info=True)
        return web.json_response(
            {"session_id": sid, "execution_id": exec_id, "ok": False, "error": "report_update_failed"},
            status=503,
        )
    return web.json_response({"session_id": sid, "execution_id": exec_id, "ok": True})


async def handle_specialists_list(request: web.Request) -> web.Response:
    registry: SpecialistRegistry = request.app[APP_SPECIALIST_REGISTRY]
    specialists = []
    for specialist in registry.all_specialists:
        health = await specialist.check_health()
        specialists.append(
            {
                "id": specialist.specialist_id,
                "description": specialist.description,
                "healthy": health.healthy,
                "message": health.message,
                "capabilities": sorted(specialist.capabilities),
            }
        )
    return web.json_response({"specialists": specialists})


__all__ = [
    "guard_chat_v2_read",
    "handle_cancel_delegation",
    "handle_mark_delegation_reported",
    "handle_session_delegations",
    "handle_session_delete",
    "handle_session_export",
    "handle_delegation_detail",
    "handle_session_get",
    "handle_session_truncate",
    "handle_steer_delegation",
    "handle_specialists_list",
]
