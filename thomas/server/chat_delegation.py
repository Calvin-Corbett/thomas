from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.agent.chat_dispatcher import dispatch_async
from thomas.agent.dispatch import should_dispatch
from thomas.core import task_bot_runtime
from thomas.marketplace.orchestrator.bot_roster import pick_bot_for_specialist
from thomas.server.app_keys import APP_CODEX_BRIDGE

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TASK_MANAGER_BACKEND = "task_manager"
PROVIDER_NATIVE_BACKEND = "provider_native"


class _DelegationEmitter:
    def __init__(self, emit_event: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._emit_event = emit_event

    async def started(self, record: dict[str, Any], *, specialist_id: str, bot: Any) -> None:
        await self._emit_event(
            {
                "type": "delegation_started",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": record.get("state", "queued"),
                "summary": record.get("summary", ""),
                "last_progress": record.get("last_progress", ""),
                "specialist_id": specialist_id,
                **bot.to_event_dict(),
            }
        )

    async def progress(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._emit_event(
            {
                "type": "delegation_progress",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": record.get("state", "executing"),
                "summary": record.get("summary", ""),
                "last_progress": text or record.get("last_progress", ""),
                "specialist_id": specialist_id,
                **bot.to_event_dict(),
            }
        )

    async def completed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        await self._emit_event(
            {
                "type": "delegation_completed",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": "completed",
                "summary": record.get("summary", ""),
                "last_progress": text or record.get("last_progress", ""),
                "specialist_id": specialist_id,
                **bot.to_event_dict(),
            }
        )

    async def failed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._emit_event(
            {
                "type": "delegation_failed",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": "failed",
                "summary": record.get("summary", ""),
                "last_progress": text,
                "specialist_id": specialist_id,
                **bot.to_event_dict(),
            }
        )


def _resolve_repo_root(repo_root: str | Path | None = None) -> Path:
    return (Path(repo_root).expanduser() if repo_root is not None else ROOT).resolve()


def _coerce_bridge(app: Any) -> Any | None:
    try:
        bridge_ref = app.get(APP_CODEX_BRIDGE)
    except Exception:
        return None
    if isinstance(bridge_ref, dict):
        return bridge_ref.get("bridge")
    return bridge_ref


def _summarize_prompt(prompt: str) -> str:
    text = " ".join(str(prompt or "").strip().split())
    if len(text) > 160:
        return text[:157] + "..."
    return text


def _infer_specialist(prompt: str) -> str:
    text = str(prompt or "").lower()
    if any(token in text for token in ("code", "bug", "endpoint", "api", "test", "refactor", "implement")):
        return "coding"
    if any(token in text for token in ("research", "find", "look up", "compare", "investigate")):
        return "research"
    if any(token in text for token in ("tool", "command", "run ", "install", "configure", "setup")):
        return "tools"
    return "reasoning"


def _normalize_record(payload: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(payload or {})
    summary = str(row.get("summary") or row.get("progress_summary") or "").strip()
    progress = str(row.get("progress_summary") or summary).strip()
    bot_id = str(row.get("bot_id") or "").strip()
    bot_name = str(row.get("bot_name") or "").strip() or (bot_id[:1].upper() + bot_id[1:] if bot_id else "")
    return {
        "execution_id": str(row.get("execution_id") or ""),
        "task_id": str(row.get("task_id") or ""),
        "session_id": str(row.get("conversation_id") or row.get("thread_id") or ""),
        "backend_type": str(row.get("backend_type") or TASK_MANAGER_BACKEND),
        "state": str(row.get("state") or "requested"),
        "summary": summary,
        "last_progress": progress,
        "bot_id": bot_id,
        "bot_name": bot_name,
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def session_active_delegations(
    session_id: str,
    *,
    repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    root = _resolve_repo_root(repo_root)
    rows = task_bot_runtime.list_executions(root, refresh=True)
    session_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("conversation_id") or "") != str(session_id or ""):
            continue
        execution_id = str(row.get("execution_id") or "")
        full = task_bot_runtime.get_execution(execution_id, root)
        session_rows.append(_normalize_record(full if isinstance(full, dict) else row))
    session_rows.sort(key=lambda item: (item.get("updated_at", ""), item.get("execution_id", "")), reverse=True)
    return session_rows


def build_active_task_digest(
    session_id: str,
    *,
    repo_root: str | Path | None = None,
    limit: int = 3,
) -> str:
    rows = session_active_delegations(session_id, repo_root=repo_root)
    if not rows:
        return ""
    lines = ["Background work in this chat:"]
    for row in rows[: max(1, int(limit or 1))]:
        bot = str(row.get("bot_id") or "worker").strip() or "worker"
        state = str(row.get("state") or "requested").replace("_", " ")
        backend = str(row.get("backend_type") or TASK_MANAGER_BACKEND).replace("_", " ")
        detail = str(row.get("last_progress") or row.get("summary") or "").strip()
        lines.append(f"- {bot} [{state} via {backend}]: {detail}")
    return "\n".join(lines)


async def start_background_delegation(
    app: Any,
    *,
    session_id: str,
    prompt: str,
    mode: str,
    recent_messages: list[dict[str, Any]] | None,
    emit_event: Callable[[dict[str, Any]], Awaitable[None]],
    repo_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode != "max" and not bool(force):
        return None

    current = session_active_delegations(session_id, repo_root=repo_root)
    decision = should_dispatch(
        prompt,
        recent_messages=recent_messages,
        active_tasks=current,
        mode=normalized_mode,
    )
    if decision.action != "dispatch":
        return None

    specialist_id = _infer_specialist(prompt)
    bot = pick_bot_for_specialist(specialist_id)
    emitter = _DelegationEmitter(emit_event)
    bridge = _coerce_bridge(app)

    if bridge is not None and bool(getattr(bridge, "is_running", False)):
        try:
            return await _start_provider_native_delegation(
                bridge,
                session_id=session_id,
                prompt=prompt,
                specialist_id=specialist_id,
                bot=bot,
                emitter=emitter,
                repo_root=repo_root,
            )
        except Exception as exc:
            log.warning("Provider-native delegation failed, falling back to task manager: %s", exc, exc_info=True)

    return await _start_task_manager_delegation(
        session_id=session_id,
        prompt=prompt,
        specialist_id=specialist_id,
        bot=bot,
        emitter=emitter,
        repo_root=repo_root,
    )


async def _start_task_manager_delegation(
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
) -> dict[str, Any] | None:
    root = _resolve_repo_root(repo_root)
    result = await dispatch_async(
        prompt,
        session_id,
        scope=specialist_id,
        visibility="background",
        repo_root=root,
    )
    if not result.ok:
        failed = {
            "execution_id": result.execution_id,
            "task_id": result.task_id,
            "session_id": session_id,
            "backend_type": TASK_MANAGER_BACKEND,
            "state": "failed",
            "summary": _summarize_prompt(prompt),
            "last_progress": result.error or "Background dispatch failed.",
        }
        await emitter.failed(failed, specialist_id=specialist_id, bot=bot, text=failed["last_progress"])
        return failed

    task_bot_runtime.update_execution(
        result.execution_id,
        bot_id=bot.id,
        backend_type=TASK_MANAGER_BACKEND,
        progress_summary="Queued for background execution.",
        actor="thomas-max-delegation",
        repo_root=root,
        force=True,
    )
    payload = task_bot_runtime.get_execution(result.execution_id, root)
    record = _normalize_record(payload)
    await emitter.started(record, specialist_id=specialist_id, bot=bot)
    return record


async def _start_provider_native_delegation(
    bridge: Any,
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    execution = task_bot_runtime.create_execution(
        session_id=session_id,
        summary=_summarize_prompt(prompt),
        intent="chat_task",
        scope=[specialist_id],
        visibility="background",
        bot_id=bot.id,
        actor="codex-bridge",
        backend_type=PROVIDER_NATIVE_BACKEND,
        repo_root=root,
    )
    execution_id = str(execution.get("execution_id") or "")
    task_bot_runtime.update_execution(
        execution_id,
        state="classified",
        progress_summary="Prepared for provider-native background execution.",
        actor="codex-bridge",
        repo_root=root,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="queued",
        progress_summary="Queued on the provider-native worker.",
        actor="codex-bridge",
        repo_root=root,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="claimed",
        claimed_owner=bot.name,
        actor=bot.name,
        repo_root=root,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="executing",
        progress_summary="Provider-native worker is running.",
        actor=bot.name,
        repo_root=root,
    )
    record = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
    await emitter.started(record, specialist_id=specialist_id, bot=bot)

    instructions = (
        "You are a background execution worker inside Thomas. "
        "Work the task directly. Use tools when needed. "
        "Do not address the end user conversationally. "
        "Focus on execution, concise progress, and completing the task."
    )

    asyncio.create_task(
        _run_provider_native_worker(
            bridge,
            execution_id=execution_id,
            prompt=prompt,
            specialist_id=specialist_id,
            bot=bot,
            emitter=emitter,
            instructions=instructions,
            repo_root=root,
        )
    )
    return record


async def _run_provider_native_worker(
    bridge: Any,
    *,
    execution_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    instructions: str,
    repo_root: Path,
) -> None:
    try:
        async for event in bridge.chat(
            prompt,
            cwd=str(repo_root),
            allow_tools=True,
            instructions=instructions,
        ):
            event_type = str(event.get("type") or "").strip()
            if event_type == "tool_start":
                tool_name = str(event.get("name") or "tool").strip() or "tool"
                progress = f"Using {tool_name}."
                task_bot_runtime.update_execution(
                    execution_id,
                    progress_summary=progress,
                    actor=bot.name,
                    repo_root=repo_root,
                    force=True,
                )
                record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
            elif event_type == "tool_output":
                progress = "Completed a tool step."
                task_bot_runtime.update_execution(
                    execution_id,
                    progress_summary=progress,
                    actor=bot.name,
                    repo_root=repo_root,
                    force=True,
                )
                record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
            elif event_type == "error":
                raise RuntimeError(str(event.get("error") or "provider-native delegation failed"))
            elif event_type == "done":
                task_bot_runtime.complete_execution(
                    execution_id,
                    actor=bot.name,
                    summary="Background execution completed.",
                    repo_root=repo_root,
                )
                record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                await emitter.completed(
                    record,
                    specialist_id=specialist_id,
                    bot=bot,
                    text="Background execution completed.",
                )
                return

        task_bot_runtime.complete_execution(
            execution_id,
            actor=bot.name,
            summary="Background execution completed.",
            repo_root=repo_root,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.completed(record, specialist_id=specialist_id, bot=bot, text="Background execution completed.")
    except Exception as exc:
        task_bot_runtime.fail_execution(
            execution_id,
            actor=bot.name,
            summary=f"Background execution failed: {exc}",
            blocker="provider_native_failed",
            repo_root=repo_root,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=f"Background execution failed: {exc}")
