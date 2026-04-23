from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.agent.chat_dispatcher import dispatch_async
from thomas.agent.dispatch import should_dispatch
from thomas.core import task_bot_runtime
from thomas.core.benchmark_lane import benchmark_single_agent_enabled, resolve_benchmark_repo_root
from thomas.marketplace.orchestrator.bot_roster import pick_bot_for_specialist

ROOT = Path(__file__).resolve().parents[2]
TASK_MANAGER_BACKEND = "task_manager"
_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "couple": 2,
    "few": 3,
}
_MULTI_AGENT_COUNT_RE = re.compile(
    r"(?:spawn|start|launch|run|create|use)\s+"
    r"(?:exactly\s+)?(?:a\s+)?(?P<count>\d+|one|two|three|four|five|couple|few)\s+"
    r"(?:real\s+|live\s+|tiny\s+|distinct\s+|lightweight\s+|small\s+|task\s+)*"
    r"(?:sub[- ]?agents?|agents?|helpers?|workers?)",
    re.I,
)


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
    default_root = Path(repo_root).expanduser() if repo_root is not None else ROOT
    resolved = resolve_benchmark_repo_root(default_root)
    return resolved if resolved is not None else default_root.resolve()


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
    if any(token in text for token in ("tool", "command", "run ", "install", "configure", "setup", "set up")):
        return "tools"
    return "reasoning"


def _requested_delegate_count(prompt: str) -> int:
    text = str(prompt or "").strip().lower()
    if not text:
        return 1
    match = _MULTI_AGENT_COUNT_RE.search(text)
    if not match:
        return 1
    raw = str(match.group("count") or "").strip().lower()
    if raw.isdigit():
        value = int(raw)
    else:
        value = _COUNT_WORDS.get(raw, 1)
    return max(1, min(5, int(value or 1)))


def _helper_prompt(prompt: str, *, helper_index: int, helper_count: int, bot_name: str) -> str:
    if helper_count <= 1:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        f"[Helper assignment]\n"
        f"You are helper {helper_index} of {helper_count} ({bot_name}). "
        f"Take a distinct slice of the work from the other helpers, avoid duplicating them, "
        f"and report concise progress."
    ).strip()


def _normalize_record(payload: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(payload or {})
    summary = str(row.get("summary") or row.get("progress_summary") or "").strip()
    progress = str(row.get("progress_summary") or summary).strip()
    bot_id = str(row.get("bot_id") or "").strip()
    bot_name = str(row.get("bot_name") or "").strip() or (bot_id[:1].upper() + bot_id[1:] if bot_id else "")
    session_id = str(row.get("session_id") or row.get("conversation_id") or row.get("thread_id") or "").strip()
    return {
        "execution_id": str(row.get("execution_id") or ""),
        "task_id": str(row.get("task_id") or ""),
        "session_id": session_id,
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
    session_key = str(session_id or "").strip()
    rows = task_bot_runtime.list_executions(root, refresh=True)
    session_rows: list[dict[str, Any]] = []
    for row in rows:
        row_session_id = str(row.get("session_id") or row.get("conversation_id") or row.get("thread_id") or "").strip()
        if row_session_id != session_key:
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
    _ = app
    if benchmark_single_agent_enabled():
        return None
    normalized_mode = str(mode or "").strip().lower()
    forced = bool(force)
    if normalized_mode != "max" and not forced:
        return None

    current = session_active_delegations(session_id, repo_root=repo_root)
    decision = should_dispatch(
        prompt,
        recent_messages=recent_messages,
        active_tasks=current,
        mode=normalized_mode,
    )
    if decision.action != "dispatch" and not forced:
        return None

    specialist_id = _infer_specialist(prompt)
    emitter = _DelegationEmitter(emit_event)
    delegate_count = _requested_delegate_count(prompt) if forced else 1

    if delegate_count > 1:
        exclude: set[str] = set()
        records: list[dict[str, Any]] = []
        for index in range(delegate_count):
            bot = pick_bot_for_specialist(specialist_id, exclude=set(exclude))
            exclude.add(bot.id)
            helper_prompt = _helper_prompt(
                prompt,
                helper_index=index + 1,
                helper_count=delegate_count,
                bot_name=bot.name,
            )
            record = await _start_task_manager_delegation(
                session_id=session_id,
                prompt=helper_prompt,
                specialist_id=specialist_id,
                bot=bot,
                emitter=emitter,
                repo_root=repo_root,
            )
            if record:
                records.append(record)
        return records or None

    bot = pick_bot_for_specialist(specialist_id)
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
