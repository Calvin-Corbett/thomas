from __future__ import annotations

import asyncio
import dataclasses
import logging
import platform as _platform
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.agent.chat_dispatcher import dispatch_async
from thomas.agent.dispatch import should_dispatch
from thomas.agent.instruction_contract import apply_root_instructions
from thomas.core import task_bot_runtime
from thomas.core.file_access import READ_ONLY, clamp_file_access_level
from thomas.core.task_titling import derive_task_title
from thomas.marketplace.orchestrator.bot_roster import pick_bot_for_specialist
from thomas.server import chat_delegation_live_repo as _live_repo_module
from thomas.server import chat_delegation_runner as _runner_module
from thomas.server.app_keys import APP_CONFIG, APP_TOOLS
from thomas.server.chat_delegation_canvas import (
    canvas_finish,
    canvas_start,
    is_canvas_task,
    run_canvas_worker,
)
from thomas.server.chat_delegation_canvas_completion import complete_canvas_delivery
from thomas.server.chat_delegation_canvas_worker import _CanvasCancelled
from thomas.server.chat_delegation_deliverable import (  # noqa: F401
    _FAILURE_LANGUAGE_RE,
    _build_result_summary,
    _claimed_filenames,
    _claims_action_success,
    _claims_file_creation,
    _files_changed_since,
    _handoff_block,
    _resolve_created,
    _snapshot_workspace_files,
    _worker_summary_line,
    _WorkerFatal,
    _WorkerRetry,
    _workspace_mtimes,
    executability_warning,
    prompt_needs_handoff,
    quality_tier_clause,
    render_report_pdfs,
    runtime_executability_warning,
)
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_live_repo import (  # noqa: F401
    _live_repo_files_changed_since,
    _live_repo_workspace_mtimes,
    _prompt_targets_live_thomas_repo,
    _with_live_repo_change_requirement,
)
from thomas.server.chat_delegation_runner import (  # noqa: F401
    _next_worker_event,
)
from thomas.server.chat_delegation_session import (  # noqa: F401
    _TERMINAL_TASK_STATES,
    _heartbeat_age_s,
    _normalize_record,
    _resolve_repo_root,
    _worker_has_started_progress,
    session_active_delegations,
)
from thomas.server.chat_delegation_tasks import (
    build_active_task_digest_from_rows,
    resolve_active_task_ref_from_rows,
)
from thomas.server.chat_delegation_worker_config import (  # noqa: F401
    _WORKER_FIRST_EVENT_TIMEOUT_S,
    _WORKER_IDLE_EVENT_TIMEOUT_S,
    PROVIDER_NATIVE_BACKEND,
    TASK_MANAGER_BACKEND,
    _agent_worker_permission_block,
    _agent_worker_runtime_profile,
    _helper_prompt,
    _infer_specialist,
    _replan_prompt,
    _requested_delegate_count,
    _requested_delegate_items,
    _self_recovery_attempts,
)
from thomas.server.chat_delegation_workspace import ensure_task_workspace as _ensure_task_workspace
from thomas.server.chat_delegation_workspace import prompt_allows_workspace_seed
from thomas.server.chat_delegation_workspace import seed_workspace_from_previous as _seed_workspace_from_previous
from thomas.server.issue_ledger import record_issue
from thomas.server.model_runtime_receipt import validate_model_runtime_receipt
from thomas.server.worker_runtime import _explicit_browser_preflight, run_agent_worker_events

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


def _sync_runner_legacy_globals() -> None:
    """Keep old chat_delegation monkeypatch surfaces effective after the module split."""
    _runner_module.run_agent_worker_events = run_agent_worker_events
    _runner_module._WORKER_FIRST_EVENT_TIMEOUT_S = _WORKER_FIRST_EVENT_TIMEOUT_S
    _runner_module._WORKER_IDLE_EVENT_TIMEOUT_S = _WORKER_IDLE_EVENT_TIMEOUT_S
    _runner_module._replan_prompt = _replan_prompt
    _runner_module._self_recovery_attempts = _self_recovery_attempts
    _runner_module._workspace_mtimes = _workspace_mtimes
    _live_repo_module._workspace_mtimes = _workspace_mtimes
    _runner_module._live_repo_workspace_mtimes = _live_repo_module._live_repo_workspace_mtimes


async def _run_agent_worker(*args: Any, **kwargs: Any) -> None:
    _sync_runner_legacy_globals()
    return await _runner_module._run_agent_worker(*args, **kwargs)


async def _run_agent_worker_supervised(*args: Any, **kwargs: Any) -> None:
    _sync_runner_legacy_globals()
    return await _runner_module._run_agent_worker_supervised(*args, **kwargs)


async def _run_exhaustive_worker(*args: Any, **kwargs: Any) -> None:
    _sync_runner_legacy_globals()
    return await _runner_module._run_exhaustive_worker(*args, **kwargs)


def build_active_task_digest(session_id: str, *, repo_root: str | Path | None = None, limit: int = 6) -> str:
    rows = session_active_delegations(session_id, repo_root=repo_root)
    return build_active_task_digest_from_rows(rows, limit=limit, default_backend=TASK_MANAGER_BACKEND)


def resolve_active_task_ref(session_id: str, task_ref: str, *, repo_root: str | Path | None = None) -> str | None:
    rows = session_active_delegations(session_id, repo_root=repo_root)
    return resolve_active_task_ref_from_rows(rows, task_ref, terminal_states=_TERMINAL_TASK_STATES)


def apply_task_update(
    session_id: str,
    task_ref: str,
    update: str = "",
    *,
    cancel: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    eid = resolve_active_task_ref(session_id, task_ref, repo_root=repo_root)
    if not eid:
        return {"ok": False, "error": f"No running task matches reference '{task_ref}'."}
    root = _resolve_repo_root(repo_root)
    try:
        if cancel:
            task_bot_runtime.request_cancel(eid, actor="user", repo_root=root)
            return {"ok": True, "execution_id": eid, "action": "cancel"}
        text = str(update or "").strip()
        if not text:
            return {"ok": False, "error": "No update instruction was provided."}
        task_bot_runtime.steer_execution(eid, text, actor="user", repo_root=root)
        return {"ok": True, "execution_id": eid, "action": "steer"}
    except ValueError as exc:
        return {"ok": False, "execution_id": eid, "error": str(exc)}
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}


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
    autonomy_level: int = 4,
    file_access: int | None = None,
    profile: str | None = None,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    effort: str = "diligent",
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
    session_llm: Any = None,
    surface: str | None = None,
    work_context_id: str = "",
    memory_enabled: bool = True,
    runtime_policy: dict[str, Any] | None = None,
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
    delegate_items = _requested_delegate_items(prompt)
    delegate_count = len(delegate_items) or (_requested_delegate_count(prompt) if forced else 1)

    if delegate_count > 1:
        exclude: set[str] = set()
        records: list[dict[str, Any]] = []
        for index in range(delegate_count):
            assigned_item = delegate_items[index] if delegate_items else ""
            item_specialist_id = _infer_specialist(assigned_item) if assigned_item else specialist_id
            bot = pick_bot_for_specialist(item_specialist_id, exclude=set(exclude))
            exclude.add(bot.id)
            helper_prompt = _helper_prompt(
                prompt,
                helper_index=index + 1,
                helper_count=delegate_count,
                bot_name=bot.name,
                assigned_item=assigned_item,
            )
            try:
                # Each explicit deliverable gets its own provider-native worker and
                # workspace.  The task-manager queue needs a separate poller and can
                # otherwise sit forever in a standalone local server, which made the
                # UI claim a handoff without ever producing the requested files.
                record = await _start_agent_worker_delegation(
                    app,
                    session_id=session_id,
                    prompt=helper_prompt,
                    specialist_id=item_specialist_id,
                    bot=bot,
                    emitter=emitter,
                    repo_root=repo_root,
                    autonomy_level=autonomy_level,
                    file_access=file_access,
                    recent_messages=recent_messages,
                    profile=profile,
                    model_id=model_id,
                    reasoning_effort=reasoning_effort,
                    effort=effort,
                    guardrails=guardrails,
                    guardrail_modes=guardrail_modes,
                    display_title=assigned_item,
                    group_expected_count=delegate_count,
                    work_context_id=work_context_id,
                    memory_enabled=memory_enabled,
                    runtime_policy=runtime_policy,
                )
            except (RuntimeError, OSError, ValueError, TypeError) as exc:
                log.warning("Parallel agent worker failed: %s", exc, exc_info=True)
                record = (
                    None
                    if (work_context_id or runtime_policy)
                    else await _start_task_manager_delegation(
                        session_id=session_id,
                        prompt=helper_prompt,
                        specialist_id=item_specialist_id,
                        bot=bot,
                        emitter=emitter,
                        repo_root=repo_root,
                        group_expected_count=delegate_count,
                        memory_enabled=memory_enabled,
                        fallback_reason="The primary worker could not start. Thomas switched this item to Task Manager.",
                    )
                )
            if record:
                records.append(record)
        return records or None

    bot = pick_bot_for_specialist(specialist_id)

    _declared = str(surface or "").strip().lower()
    if _declared == "canvas":
        _want_canvas = _wants_canvas_delegation(prompt)
    elif _declared == "task":
        _want_canvas = False
    else:
        _want_canvas = _wants_canvas_delegation(prompt)
    effective_file_access = clamp_file_access_level(file_access if file_access is not None else 1)
    if _want_canvas and _agent_worker_permission_block(
        prompt, targets_live_repo=False, file_access=effective_file_access
    ):
        _want_canvas = False
    if _want_canvas:
        try:
            return await _start_canvas_worker_delegation(
                session_id=session_id,
                prompt=prompt,
                specialist_id=specialist_id,
                bot=bot,
                emitter=emitter,
                repo_root=repo_root,
                profile=profile,
                model_id=model_id,
                session_llm=session_llm,
                memory_enabled=memory_enabled,
                file_access=file_access,
                runtime_policy=runtime_policy,
                recent_messages=recent_messages,
            )
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            log.warning("Canvas worker failed, falling back to agent worker: %s", exc, exc_info=True)

    try:
        return await _start_agent_worker_delegation(
            app,
            session_id=session_id,
            prompt=prompt,
            specialist_id=specialist_id,
            bot=bot,
            emitter=emitter,
            repo_root=repo_root,
            autonomy_level=autonomy_level,
            file_access=file_access,
            recent_messages=recent_messages,
            profile=profile,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            effort=effort,
            guardrails=guardrails,
            guardrail_modes=guardrail_modes,
            work_context_id=work_context_id,
            memory_enabled=memory_enabled,
            runtime_policy=runtime_policy,
        )
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        log.warning("Agent worker delegation failed: %s", exc, exc_info=True)
        if work_context_id or runtime_policy:
            return None

    return await _start_task_manager_delegation(
        session_id=session_id,
        prompt=prompt,
        specialist_id=specialist_id,
        bot=bot,
        emitter=emitter,
        repo_root=repo_root,
        memory_enabled=memory_enabled,
        fallback_reason="The primary worker could not start. Thomas switched the task to Task Manager.",
    )


async def _start_task_manager_delegation(
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
    group_expected_count: int = 1,
    memory_enabled: bool = True,
    fallback_reason: str = "",
) -> dict[str, Any] | None:
    root = _resolve_repo_root(repo_root)
    runtime_profile = {
        "group_expected_count": max(1, int(group_expected_count or 1)),
        "memory_enabled": memory_enabled,
        "fallback_from": "provider_native_worker" if fallback_reason else "",
    }
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
            "runtime_profile": runtime_profile,
        }
        await emitter.failed(failed, specialist_id=specialist_id, bot=bot, text=failed["last_progress"])
        return failed

    task_bot_runtime.update_execution(
        result.execution_id,
        bot_id=bot.id,
        backend_type=TASK_MANAGER_BACKEND,
        runtime_profile=runtime_profile,
        progress_summary=fallback_reason or "Queued for background execution.",
        actor="thomas-max-delegation",
        repo_root=root,
        force=True,
    )
    payload = task_bot_runtime.get_execution(result.execution_id, root)
    record = _normalize_record(payload)
    await emitter.started(record, specialist_id=specialist_id, bot=bot)
    return record


_CANVAS_FOLLOWUP_RE = re.compile(
    r"\b(re-?run|re-?do|re-?generate|re-?make|re-?create|regenerate|again|"
    r"same\s+(?:chart|graph|plot|data|thing|one)|"
    r"add\s+(?:a\s+|another\s+)?(?:row|column|bar|series|point|month|entry|value|slice|wedge)|"
    r"update\s+(?:the\s+|that\s+|this\s+)?(?:chart|graph|plot)|"
    r"(?:that|this|the)\s+(?:chart|graph|plot))\b",
    re.I,
)


# Route chart RE-runs ("rerun the chart", "redo the graph", "chart again") to the
# canvas specialist, not the generic agent worker. Requires a rerun verb AND a
# chart word so a non-chart "run it again" is never misrouted.
_CANVAS_RERUN_RE = re.compile(
    r"\b(?:re-?run|re-?do|re-?generate|re-?make|re-?create|regenerate|redraw|remake|update)\b"
    r"[^.?!]{0,30}\b(?:chart|graph|plot|bar|pie|line|donut|scatter)\b"
    r"|\b(?:chart|graph|plot)\b[^.?!]{0,20}\bagain\b",
    re.I,
)


def _wants_canvas_delegation(prompt: str) -> bool:
    """A fresh chart request OR a referential chart re-run belongs on the canvas."""
    return is_canvas_task(prompt) or bool(_CANVAS_RERUN_RE.search(str(prompt or "")))


def _canvas_worker_prompt(prompt: str, recent_messages: list[dict[str, Any]] | None) -> str:
    """Prepend recent-conversation handoff to a referential canvas follow-up.

    A follow-up like "rerun the chart" / "add a row" carries no data of its own;
    without the prior turns the worker gets an empty workspace and asks the user
    to re-paste the numbers. Reuses the curation (_handoff_block) proven on the
    agent-worker path. Charts have no "wrong build" bleed risk (they simply
    re-plot data), so the referential gate is broader than the conservative
    agent-worker one — it also catches chart-specific edits like "rerun the
    chart" and "add a row".
    """
    text = str(prompt or "")
    referential = prompt_needs_handoff(prompt) or bool(_CANVAS_FOLLOWUP_RE.search(text))
    if not referential:
        return prompt
    handoff = _handoff_block(recent_messages)
    return f"{prompt}\n\n{handoff}" if handoff else prompt


def _record_canvas_issue(execution_id: str, prompt: str, blocker: str, repo_root: Any) -> None:
    """Record a canvas failure to the issue ledger so the self-review sees it.

    Canvas failures previously called fail_execution without ever touching the
    ledger, so /api/issues and /api/self-review were blind to them — a chart that
    renders then dies in review left no ledger trace. record_issue is fail-silent.
    """
    record_issue(
        surface="chat-worker",
        kind="canvas_failed",
        message=f"canvas failed: {blocker}"[:300],
        context={
            "execution_id": str(execution_id),
            "task": str(prompt or "")[:160],
            "blocker": blocker,
        },
        repo_root=repo_root,
    )


async def _start_canvas_worker_delegation(
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
    profile: str | None = None,
    model_id: str | None = None,
    session_llm: Any = None,
    memory_enabled: bool = True,
    file_access: int | None = None,
    runtime_policy: dict[str, Any] | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Stream a reviewed HTML document to Canvas, then persist its deliverable."""
    from thomas.server.chat_runtime_policy import tool_policy_from_payload

    tool_policy = tool_policy_from_payload((runtime_policy or {}).get("tools"))
    if tool_policy is not None and not tool_policy.allow_file_write:
        raise PermissionError("allow_file_write policy denied Canvas artifact delivery")
    effective_file_access = clamp_file_access_level(file_access if file_access is not None else 1)
    if effective_file_access == READ_ONLY:
        raise PermissionError("read_only file access denied Canvas artifact delivery")
    root = _resolve_repo_root(repo_root)
    # A referential follow-up ("rerun the chart", "add a row") lands here as a
    # fresh execution with an empty workspace. Thread the recent conversation
    # into the WORKER prompt (not the title/execution) so it can re-extract the
    # prior data instead of asking the user to paste the numbers again.
    worker_prompt = _canvas_worker_prompt(prompt, recent_messages)
    execution = task_bot_runtime.create_execution(
        session_id=session_id,
        summary=derive_task_title(prompt),
        intent="chat_task",
        scope=[specialist_id],
        visibility="background",
        bot_id=bot.id,
        actor="thomas-canvas",
        backend_type=PROVIDER_NATIVE_BACKEND,
        runtime_profile={
            "backend_type": PROVIDER_NATIVE_BACKEND,
            "canvas": True,
            "memory_enabled": memory_enabled,
            "requested_profile": str(profile or ""),
            "requested_model_id": str(model_id or ""),
            "file_access": effective_file_access,
        },
        repo_root=root,
    )
    execution_id = str(execution.get("execution_id") or "")
    canvas_start(execution_id, title=derive_task_title(prompt))
    task_bot_runtime.update_execution(
        execution_id,
        state="executing",
        claimed_owner=bot.name,
        progress_summary="Drawing it on the canvas…",
        actor=bot.name,
        repo_root=root,
        force=True,
    )
    record = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
    await emitter.started(record, specialist_id=specialist_id, bot=bot)

    async def _progress(text: str) -> None:
        task_bot_runtime.update_execution(
            execution_id, progress_summary=text, actor=bot.name, repo_root=root, force=True
        )
        rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
        await emitter.progress(rec, specialist_id=specialist_id, bot=bot, text=text)

    async def _run() -> None:
        worker_runtime: dict[str, Any] = {}

        def _record_runtime(receipt: dict[str, Any]) -> None:
            worker_runtime.update(receipt)

        try:
            html = await run_canvas_worker(
                execution_id=execution_id,
                prompt=worker_prompt,
                root=root,
                profile=profile,
                model_id=model_id,
                session_llm=session_llm,
                emit_progress=_progress,
                record_runtime=_record_runtime,
                runtime_policy=runtime_policy,
            )
        except _CanvasCancelled:
            # Stopping because the user asked is not a failure, and must not be
            # reported as one. Before this the flag was never read at all: the
            # run continued, the record stayed in `executing` indefinitely, and
            # the chat could only repeat its last status while the user asked
            # again and again what was happening.
            summary = "Cancelled by user."
            canvas_finish(execution_id, "failed")
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary=summary,
                blocker="cancelled",
                repo_root=root,
            )
            rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
            await emitter.failed(rec, specialist_id=specialist_id, bot=bot, text=summary)
            return
        except Exception as exc:  # noqa: BLE001 - surface as a failed card, don't crash anything
            log.exception("Canvas worker failed for %s (%s)", execution_id, type(exc).__name__)
            canvas_finish(execution_id, "failed")
            safe_error = "Canvas generation failed before a verified result was produced."
            _record_canvas_issue(execution_id, prompt, "canvas_failed", root)
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary=safe_error,
                blocker="canvas_failed",
                repo_root=root,
            )
            rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
            await emitter.failed(rec, specialist_id=specialist_id, bot=bot, text=safe_error)
            return
        validated_runtime = validate_model_runtime_receipt(
            worker_runtime,
            requested_profile=str(profile or ""),
            requested_model_id=str(model_id or ""),
        )
        if validated_runtime is None:
            _record_canvas_issue(execution_id, prompt, "model_runtime_missing", root)
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary="Canvas worker failed: model runtime receipt missing.",
                blocker="model_runtime_missing",
                repo_root=root,
            )
            rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
            await emitter.failed(rec, specialist_id=specialist_id, bot=bot, text="Model runtime receipt missing.")
            return
        current = task_bot_runtime.get_execution(execution_id, root) or {}
        runtime_profile = dict(current.get("runtime_profile") or {})
        runtime_profile["model_runtime"] = validated_runtime
        task_bot_runtime.update_execution(
            execution_id,
            runtime_profile=runtime_profile,
            actor=bot.name,
            repo_root=root,
            force=True,
        )
        try:
            rec, summary = complete_canvas_delivery(
                execution_id=execution_id,
                prompt=worker_prompt,
                html=html,
                actor=bot.name,
                repo_root=root,
                workspace_for=_ensure_task_workspace,
                file_access=effective_file_access,
                allowed_paths=tool_policy.allowed_paths if tool_policy is not None else (),
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            canvas_finish(execution_id, "failed")
            _record_canvas_issue(execution_id, prompt, "canvas_review_failed", root)
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary=f"Canvas review failed: {exc}",
                blocker="canvas_review_failed",
                repo_root=root,
            )
            rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
            await emitter.failed(rec, specialist_id=specialist_id, bot=bot, text=str(exc))
            return
        await emitter.completed(
            rec,
            specialist_id=specialist_id,
            bot=bot,
            text=summary,
        )

    asyncio.create_task(_run())
    return record


async def _start_agent_worker_delegation(
    app: Any,
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
    autonomy_level: int = 4,
    file_access: int | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
    profile: str | None = None,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    effort: str = "diligent",
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
    display_title: str = "",
    group_expected_count: int = 1,
    work_context_id: str = "",
    memory_enabled: bool = True,
    runtime_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    targets_live_repo = _prompt_targets_live_thomas_repo(prompt)
    effective_file_access = clamp_file_access_level(file_access if file_access is not None else 1)
    runtime_profile = _agent_worker_runtime_profile(
        autonomy_level=autonomy_level,
        file_access=file_access,
        effort=effort,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        guardrails=guardrails,
        requires_live_repo_change=targets_live_repo,
    )
    runtime_profile["group_expected_count"] = max(1, int(group_expected_count or 1))
    runtime_profile["memory_enabled"] = bool(memory_enabled)
    runtime_profile["requested_profile"] = str(profile or "")
    runtime_profile["requested_model_id"] = str(model_id or "")
    if work_context_id:
        runtime_profile["work_context_id"] = str(work_context_id)
    execution = task_bot_runtime.create_execution(
        session_id=session_id,
        # Display title for the task card — a real name for the work, not a raw prompt truncation.
        summary=derive_task_title(display_title or prompt),
        intent="chat_task",
        scope=[specialist_id],
        visibility="background",
        bot_id=bot.id,
        actor="thomas-worker",
        backend_type=PROVIDER_NATIVE_BACKEND,
        runtime_profile=runtime_profile,
        repo_root=root,
    )
    execution_id = str(execution.get("execution_id") or "")

    permission_block = _agent_worker_permission_block(
        prompt, targets_live_repo=targets_live_repo, file_access=effective_file_access
    )
    if permission_block is not None:
        blocker, summary = permission_block
        task_bot_runtime.fail_execution(
            execution_id,
            actor=bot.name,
            summary=summary,
            blocker=blocker,
            repo_root=root,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
        await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=summary)
        return record
    task_bot_runtime.update_execution(
        execution_id,
        state="classified",
        progress_summary="Prepared for provider-native background execution.",
        actor="thomas-worker",
        repo_root=root,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="queued",
        progress_summary="Queued on the provider-native worker.",
        actor="thomas-worker",
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

    # Normal deliverables run in a clean per-task workspace; self-development uses the
    # live checkout directly and is gated later on actual source-file changes.
    work_dir = root if targets_live_repo else _ensure_task_workspace(execution_id)
    if not targets_live_repo and prompt_allows_workspace_seed(prompt):
        # Follow-ups reference the previous deliverable ("add a 6th row to it")
        # — the new worker must SEE that file, not ask the user to upload it.
        _seeded = _seed_workspace_from_previous(work_dir, session_id, exclude_execution_id=execution_id, repo_root=root)
        if _seeded:
            # Copying is permissive; INSTRUCTING is not. "Modify those files in
            # place" is a directive, and aiming it at a request that only might
            # be a follow-up is how a worker ends up editing a chart when it was
            # asked for something new. So the strict follow-up gate still
            # decides whether the files are an order or merely available.
            names = ", ".join(_seeded[:8])
            prompt = (
                f"{prompt}\n\n[The workspace already contains the earlier deliverable(s): "
                f"{names}. Modify those files in place.]"
                if prompt_needs_handoff(prompt)
                else f"{prompt}\n\n[Earlier files from this conversation are already in the workspace: "
                f"{names}. Use or edit them only if this request refers to them.]"
            )

    _os_name = _platform.system() or "this"
    _shell_hint = (
        "Windows (shell commands run in cmd.exe / PowerShell — do NOT use Unix-only "
        "commands like printf, touch, or cat)"
        if _os_name.lower().startswith("win")
        else _os_name
    )
    instructions = (
        "You are a background worker completing the user's task. "
        f"Your working directory is a fresh, empty workspace: {work_dir}. "
        "It is NOT a source repository — there are no repo rules, startup routers, "
        "or coordination checks to run here, so do not look for them. Create files "
        "ONLY when the user explicitly requests an artifact, file, document, app, "
        "game, or code deliverable. For answer-only analysis, recommendations, or "
        "research, do not inspect the empty workspace and do not create files; return "
        "the complete substantive answer as text. "
        f"You are running on {_shell_hint}. "
        "HARD RULE — creating or editing files: you MUST use the `fs.write_file` "
        "tool (pass `path` and `content`); writing to a nested path creates the "
        "folders for you. Use `fs.list_dir` to inspect and `fs.read_file` to read. "
        "WEB CAPABILITY - browser tools are available for web tasks. Use "
        "`browser.open` with an http(s) URL, then `browser.extract` with a CSS "
        "selector to read specific page content. Use `browser.click`, "
        "`browser.type`, `browser.screenshot`, and `browser.close` when the task "
        "needs them. Never claim that browsing is outside your capabilities while "
        "these registered browser tools are available; call the appropriate tool "
        "and report any real tool error honestly. "
        "EXECUTION FIDELITY - follow an explicitly ordered tool sequence in the "
        "user's prompt, preserve exact requested filenames, and treat successful "
        "tool results as authoritative input to later steps. Never put bracketed "
        "placeholders or invented values into an artifact when a prior tool result "
        "supplies the real value. Read back the exact requested artifact and correct "
        "filename or content mismatches before finishing. "
        "NEVER use shell commands such as printf, echo, touch, cat, tee, or heredocs "
        "to create or write files — they are unreliable and fail on this OS. Reserve "
        "the `shell.exec` tool ONLY for running programs/builds, and when you do, use "
        "commands valid for the OS above. Use relative paths inside the workspace. "
        "MAKE IT HAPPEN — never dead-end on a missing capability. If the task needs "
        "an integration, device, account, or service Thomas has no built-in tool for "
        "(smart home, calendar, email send, a specific API, hardware), do NOT reply "
        "that it 'isn't configured' and stop, and do NOT pretend the real-world action "
        "happened. Instead BUILD the capability toward it: create a real, working "
        "artifact — a control panel/dashboard, an integration script, or a client "
        "wired to the standard protocol for that thing (e.g. Home Assistant REST API "
        "and webhooks for smart home, iCal/CalDAV for calendars, a documented HTTP "
        "client for an API) — plus a short SETUP section stating the ONE thing the "
        "user must connect to go live (their hub URL + access token, their account "
        "link, an API key). The user supplies their own credentials in their own app; "
        "never ask for or embed secrets. Deliver the bridge so the user just plugs in "
        "their devices. Only report an honest blocker when even building the bridge is "
        "impossible, and say specifically what you built and what remains. "
        "Do not address the user conversationally. For an artifact task, end with a "
        "one-line summary of what you built and the main file name(s). For an "
        "answer-only task, return the requested answer itself, not a readiness notice. "
        + quality_tier_clause(effort, autonomy_level)
    )
    if targets_live_repo:
        instructions = (
            "You are a background worker doing Thomas self-development in the live "
            f"Thomas repo: {work_dir}. This IS a source repository. Inspect the live "
            "code before changing it, keep edits tightly scoped, and do not claim "
            "success unless live repo files were actually changed and verified. "
            f"You are running on {_shell_hint}. "
            "HARD RULE - creating or editing files: use `fs.write_file` for ordinary "
            "project files. For protected Thomas runtime paths, use "
            "`fs.write_protected_file` with a clear reason; if native authorization is "
            "unavailable or denied, report that blocker honestly instead of writing a "
            "sandbox substitute. NEVER use shell commands such as printf, echo, touch, "
            "cat, tee, redirection, or heredocs to create or edit files. Reserve "
            "`shell.exec` ONLY for read-only inspection commands and tests/builds. "
            "Browser tools are available for web research: use `browser.open` with "
            "an http(s) URL and `browser.extract` with a CSS selector instead of "
            "claiming that browsing is outside your capabilities. "
            "Follow explicitly ordered tool steps and exact filenames; use real tool "
            "results rather than placeholders, then read back and correct the exact "
            "requested artifact before finishing. "
            "If you cannot modify the live repo, create "
            f"`runtime/self_development/{execution_id}/SELF_DEVELOPMENT_REPORT.md` "
            "explaining the blocker, but do not say the requested fix is done. "
            "Do not address the user conversationally. End with a one-line summary of "
            "the live files changed and verification run, or the blocker encountered. "
            + quality_tier_clause(effort, autonomy_level)
        )

    # Forward a curated slice of chat only when the task leans on prior dialogue
    # ("make it blue"). Self-contained requests get no handoff — feeding earlier turns
    # made the worker build the wrong thing (a Pong request produced a starfield).
    handoff = _handoff_block(recent_messages) if prompt_needs_handoff(prompt) else ""
    if handoff:
        instructions = f"{instructions}\n\n{handoff}"

    # Honor the same root instruction contract on delegated workers as the main
    # agent surface: resolve project instructions rooted at the worker's cwd and
    # fold them into its system prompt. Empty workspaces degrade cleanly (no-op).
    instructions = apply_root_instructions(instructions, cwd=work_dir)

    preflight_events: list[dict[str, Any]] = []
    preflight_evidence = ""
    preflight_baseline: dict[str, tuple[int, int]] | None = None
    explicit_recipe = all(
        name in prompt.casefold() for name in ("browser.open", "browser.extract", "fs.write_file", "fs.read_file")
    )
    app_config = app.get(APP_CONFIG) if hasattr(app, "get") else None
    from thomas.server.chat_runtime_policy import PolicyToolRegistryView, tool_policy_from_payload

    worker_tool_policy = tool_policy_from_payload((runtime_policy or {}).get("tools"))
    if explicit_recipe and app_config is not None and not targets_live_repo:
        from thomas.server.app_helpers import _build_tools

        preflight_baseline = _workspace_mtimes(work_dir)
        scoped_config = dataclasses.replace(
            app_config,
            tools=dataclasses.replace(
                app_config.tools,
                sandbox_root=str(work_dir),
                allow_shell=True,
                file_access=effective_file_access,
            ),
        )
        preflight_tools = _build_tools(scoped_config)
        if worker_tool_policy is not None:
            preflight_tools = PolicyToolRegistryView(preflight_tools, worker_tool_policy, base_root=work_dir or root)
        preflight_events, preflight_evidence = await _explicit_browser_preflight(prompt, preflight_tools)
    elif not explicit_recipe:
        app_tools = app.get(APP_TOOLS) if hasattr(app, "get") else None
        if app_tools is not None and not targets_live_repo:
            if worker_tool_policy is not None:
                app_tools = PolicyToolRegistryView(app_tools, worker_tool_policy, base_root=work_dir or root)
            preflight_events, preflight_evidence = await _explicit_browser_preflight(prompt, app_tools)
    worker_prompt = prompt
    if preflight_evidence:
        worker_prompt += (
            "\n\n[Verified explicit browser results - use these exact values in later steps]\n" + preflight_evidence
        )

    from thomas.server.exhaustive_runtime import is_exhaustive

    runner = _run_exhaustive_worker if is_exhaustive(effort) else _run_agent_worker
    worker_kwargs: dict[str, Any] = {
        "execution_id": execution_id,
        "prompt": worker_prompt,
        "specialist_id": specialist_id,
        "bot": bot,
        "instructions": instructions,
        "repo_root": root,
        "work_dir": work_dir,
        "requires_live_repo_change": targets_live_repo,
        "profile": profile,
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
        "effort": effort,
        "autonomy_level": autonomy_level,
        "file_access": file_access,
        "guardrails": guardrails,
        "guardrail_modes": guardrail_modes,
        "memory_enabled": memory_enabled,
        "runtime_policy": dict(runtime_policy or {}),
    }
    if runner is _run_agent_worker:
        worker_kwargs["preflight_events"] = preflight_events
        worker_kwargs["preflight_baseline"] = preflight_baseline
    asyncio.create_task(
        _run_agent_worker_supervised(
            runner,
            app,
            execution_id=execution_id,
            specialist_id=specialist_id,
            bot=bot,
            emitter=emitter,
            repo_root=root,
            worker_kwargs=worker_kwargs,
        )
    )
    return record
