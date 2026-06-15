from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.agent.chat_dispatcher import dispatch_async
from thomas.agent.dispatch import should_dispatch
from thomas.core import task_bot_runtime
from thomas.core.task_titling import derive_task_title
from thomas.marketplace.orchestrator.bot_roster import pick_bot_for_specialist
from thomas.server.app_keys import APP_CODEX_BRIDGE

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TASK_MANAGER_BACKEND = "task_manager"
PROVIDER_NATIVE_BACKEND = "provider_native"
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
    return (Path(repo_root).expanduser() if repo_root is not None else ROOT).resolve()


def _ensure_task_workspace(execution_id: str) -> Path:
    """Create and return a clean per-task workspace OUTSIDE the source repo.

    User deliverables are built here (e.g. a pac-man HTML file). Keeping it outside
    the Thomas repo avoids the dev guardrails that block writes inside the repo.
    """
    safe_id = "".join(ch for ch in str(execution_id or "") if ch.isalnum() or ch in "-_") or "task"
    base = Path.home() / ".thomas" / "workspaces" / safe_id
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fall back to a repo-local runtime dir if home isn't writable.
        base = (ROOT / "runtime" / "workspaces" / safe_id).resolve()
        base.mkdir(parents=True, exist_ok=True)
    return base


def _coerce_bridge(app: Any) -> Any | None:
    try:
        bridge_ref = app.get(APP_CODEX_BRIDGE)
    except Exception:
        return None
    if isinstance(bridge_ref, dict):
        return bridge_ref.get("bridge")
    return bridge_ref


async def _ensure_bridge(app: Any) -> Any | None:
    bridge = _coerce_bridge(app)
    if bridge is not None and bool(getattr(bridge, "is_running", False)):
        return bridge

    try:
        bridge_ref = app.get(APP_CODEX_BRIDGE)
    except Exception:
        bridge_ref = None

    if not isinstance(bridge_ref, dict):
        return None

    lock = bridge_ref.get("_start_lock")
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        bridge_ref["_start_lock"] = lock

    async with lock:
        bridge = bridge_ref.get("bridge")
        if bridge is None:
            try:
                from thomas.codex.bridge import CodexBridge

                bridge = CodexBridge()
                bridge_ref["bridge"] = bridge
            except Exception as exc:
                log.debug("Codex bridge bootstrap unavailable: %s", exc)
                return None

        try:
            if not bool(getattr(bridge, "is_running", False)):
                await bridge.start()
            account = await bridge.check_auth()
        except Exception as exc:
            log.debug("Codex bridge startup skipped: %s", exc)
            return None

        if not bool(getattr(account, "logged_in", False)):
            return None

        return bridge


def _build_result_summary(result_text_parts: list[str], tools_used: list[str]) -> str:
    """Condense a background worker's actual output into a result line for chat.

    Prefers the worker's own final words (what it reports it did / produced). Falls
    back to naming the tools it ran, then to a generic completion line. This is what
    the user sees as the finished-task result, so it must reflect real output — never
    a fabricated success.
    """
    text = " ".join("".join(result_text_parts).split()).strip()
    if text:
        if len(text) > 600:
            text = text[:597] + "..."
        return text
    if tools_used:
        names = ", ".join(tools_used[:5])
        return f"Done. Worked the task using: {names}."
    return "Background execution completed."


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
    bridge = await _ensure_bridge(app)
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

    if bridge is not None:
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
            "summary": derive_task_title(prompt),
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
        # Display title for the task card — a real name for the work, not a raw
        # prompt truncation. The worker still receives the full `prompt` below.
        summary=derive_task_title(prompt),
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

    # Run the worker in a CLEAN per-task workspace OUTSIDE the Thomas source repo.
    # Running in the repo root made the worker trip Thomas's own dev guardrails
    # (startup router / "worktree is dirty" / shell rejecting reads), so user
    # deliverables like "make me a pac-man game" could never write files. A fresh
    # empty directory has no AGENTS.md/CLAUDE.md/git, so the worker just builds.
    work_dir = _ensure_task_workspace(execution_id)

    instructions = (
        "You are a background worker building a deliverable for the user. "
        f"Your working directory is a fresh, empty workspace: {work_dir}. "
        "It is NOT a source repository — there are no repo rules, startup routers, "
        "or coordination checks to run here, so do not look for them. Just build "
        "what was asked directly: create whatever files are needed in this folder. "
        "Use tools as needed. Do not address the user conversationally. "
        "When done, end with a one-line summary of what you built and the main file "
        "name(s) so it can be shown back in chat."
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
            work_dir=work_dir,
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
    work_dir: Path | None = None,
) -> None:
    # Accumulate the worker's actual output text and the tools it used so the
    # completed task carries a REAL result (what the bot did / produced) instead
    # of a generic "Background execution completed." The chat surfaces this back
    # to the user — both on the live task card (frontend polls delegations) and
    # in the next-turn context digest so Thomas reports the finished work.
    result_text_parts: list[str] = []
    tools_used: list[str] = []
    try:
        async for event in bridge.chat(
            prompt,
            cwd=str(work_dir or repo_root),
            allow_tools=True,
            instructions=instructions,
        ):
            event_type = str(event.get("type") or "").strip()
            if event_type == "text":
                chunk = str(event.get("text") or "")
                if chunk:
                    result_text_parts.append(chunk)
            elif event_type == "tool_start":
                tool_name = str(event.get("name") or "tool").strip() or "tool"
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                progress = f"Using {tool_name}…"
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
                last_tool = tools_used[-1] if tools_used else "tool"
                progress = f"Finished {last_tool}; continuing."
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
                result_summary = _build_result_summary(result_text_parts, tools_used)
                task_bot_runtime.complete_execution(
                    execution_id,
                    actor=bot.name,
                    summary=result_summary,
                    repo_root=repo_root,
                )
                record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                await emitter.completed(
                    record,
                    specialist_id=specialist_id,
                    bot=bot,
                    text=result_summary,
                )
                return

        result_summary = _build_result_summary(result_text_parts, tools_used)
        task_bot_runtime.complete_execution(
            execution_id,
            actor=bot.name,
            summary=result_summary,
            repo_root=repo_root,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.completed(record, specialist_id=specialist_id, bot=bot, text=result_summary)
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
