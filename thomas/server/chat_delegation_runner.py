from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.marketplace.specialists.reasoning_task_briefs import brief_scope as _brief_scope
from thomas.server.chat_delegation_artifact_verification import (
    _hidden_completion_review_passes,
    _reconcile_missing_marker_literals,
    _reconcile_requested_artifact_from_evidence,
    _requested_artifact_issues,
    _sanitize_terminal_summary,
)
from thomas.server.chat_delegation_deliverable import (
    _FAILURE_LANGUAGE_RE,
    _artifacts_from_created,
    _build_result_summary,
    _claims_action_success,
    _claims_file_creation,
    _resolve_created,
    _snapshot_workspace_files,
    _worker_summary_line,
    _WorkerFatal,
    _WorkerRetry,
    _workspace_mtimes,
    executability_warning,
    render_report_pdfs,
    runtime_executability_warning,
)
from thomas.server.chat_delegation_emitter import _DelegationEmitter, _ThreadsafeDelegationEmitter
from thomas.server.chat_delegation_exhaustive_runner import _run_exhaustive_worker
from thomas.server.chat_delegation_live_repo import (
    _LIVE_REPO_WRITE_TOOLS,
    _live_repo_changes_are_docs_only,
    _live_repo_files_changed_since,
    _live_repo_result_summary,
    _live_repo_workspace_mtimes,
    _prompt_allows_docs_only_completion,
    _with_live_repo_change_requirement,
)
from thomas.server.chat_delegation_result_policy import (
    should_finalize_exact_artifact_tool_result as _should_finalize_exact_artifact_tool_result,
)
from thomas.server.chat_delegation_result_policy import (
    worker_text_is_confirmed_answer as _worker_text_is_confirmed_answer,
)
from thomas.server.chat_delegation_session import (
    _TERMINAL_TASK_STATES,
    _execution_is_terminal,
    _heartbeat_age_s,
    _normalize_record,
    _worker_has_started_progress,
)
from thomas.server.chat_delegation_worker_config import (
    _WORKER_FIRST_EVENT_TIMEOUT_S,
    _WORKER_IDLE_EVENT_TIMEOUT_S,
    _WORKER_STREAM_CLOSE_TIMEOUT_S,
    _WORKER_WATCHDOG_GRACE_S,
    _replan_prompt,
    _self_recovery_attempts,
)
from thomas.server.issue_ledger import record_issue
from thomas.server.model_runtime_receipt import validate_model_runtime_receipt
from thomas.server.work_connector_runtime import execution_work_context_id
from thomas.server.worker_runtime import run_agent_worker_events

log = logging.getLogger(__name__)

# Progress lines are USER-FACING (the activity card under "Handed off to ...").
# Raw tool telemetry ("Finished fs.read_file; continuing.") reads like a stack
# trace to the owner; phrase every step like a teammate's status update.
_TOOL_PHRASES = {
    "fs.read_file": ("Reading files", "Read what I needed"),
    "fs.write_file": ("Writing the file", "Saved the file"),
    "fs.list_dir": ("Looking through the workspace", "Scanned the workspace"),
    "fs.search": ("Searching the workspace", "Searched the workspace"),
    "web.search": ("Searching the web", "Found some sources"),
    "web.fetch": ("Reading a web page", "Read the page"),
    "shell.exec": ("Running a command", "Command finished"),
    "ssh.exec": ("Running a remote command", "Remote command finished"),
}


def _tool_phrase(tool_name: str, *, done: bool = False, failed: bool = False) -> str:
    active, finished = _TOOL_PHRASES.get(str(tool_name or "tool"), ("Working on the next step", "Step finished"))
    if failed:
        return f"{active} hit a snag — trying another way."
    return f"{finished} — moving on." if done else f"{active}…"


_MAX_EFFORT_IDLE_EVENT_TIMEOUT_S = 360.0
# A worker that fails the same step this many times IN A ROW stops spinning
# "hit a snag" and hands control to the recovery machinery instead.
_MAX_CONSECUTIVE_SNAGS = 6


def _record_tool_outcome(
    tool_name: str,
    *,
    ok: bool,
    succeeded_tools: list[str],
    failed_tools: list[str],
) -> None:
    """Keep every failed action visible; a later same-named call is not proof of recovery."""
    target = succeeded_tools if ok else failed_tools
    if tool_name not in target:
        target.append(tool_name)


def _supervisor_worker_timeout_s(worker_kwargs: dict[str, Any], *, has_progress: bool) -> float:
    """Return a bounded watchdog window appropriate to the active worker tier."""

    base = _WORKER_IDLE_EVENT_TIMEOUT_S if has_progress else _WORKER_FIRST_EVENT_TIMEOUT_S
    effort = str(worker_kwargs.get("effort") or "").strip().lower()
    if has_progress and effort in {"max", "exhaustive"}:
        return max(base, _MAX_EFFORT_IDLE_EVENT_TIMEOUT_S)
    return base


async def _next_worker_event(stream: Any, *, saw_event: bool) -> dict[str, Any] | None:
    timeout_s = _WORKER_IDLE_EVENT_TIMEOUT_S if saw_event else _WORKER_FIRST_EVENT_TIMEOUT_S
    next_task = asyncio.create_task(stream.__anext__())
    done, _pending = await asyncio.wait({next_task}, timeout=max(0.001, float(timeout_s)))
    if done:
        try:
            return next_task.result()
        except StopAsyncIteration:
            return None

    def _consume_background_result(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("worker event stream background cleanup failed", exc_info=True)

    next_task.cancel()
    cancelled, _pending = await asyncio.wait({next_task}, timeout=_WORKER_STREAM_CLOSE_TIMEOUT_S)
    if cancelled:
        _consume_background_result(next_task)
    else:
        next_task.add_done_callback(_consume_background_result)
    await _close_worker_event_stream(stream, consume_result=_consume_background_result)
    phase = "first event" if not saw_event else "next event"
    raise _WorkerRetry(f"provider-native worker produced no {phase} within {timeout_s:g}s")


async def _close_worker_event_stream(
    stream: Any,
    *,
    consume_result: Callable[[asyncio.Task[Any]], None] | None = None,
) -> None:
    close = getattr(stream, "aclose", None)
    if callable(close):
        try:
            close_task = asyncio.ensure_future(close())
            closed, _pending = await asyncio.wait({close_task}, timeout=_WORKER_STREAM_CLOSE_TIMEOUT_S)
            if closed:
                if consume_result is not None:
                    consume_result(close_task)
                else:
                    close_task.result()
            else:
                close_task.cancel()
                if consume_result is not None:
                    close_task.add_done_callback(consume_result)
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("worker event stream close failed", exc_info=True)


def _run_worker_thread_entry(runner: Callable[..., Awaitable[None]], app: Any, kwargs: dict[str, Any]) -> None:
    asyncio.run(runner(app, **kwargs))


async def _run_agent_worker_supervised(
    runner: Callable[..., Awaitable[None]],
    app: Any,
    *,
    execution_id: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: Path,
    worker_kwargs: dict[str, Any],
) -> None:
    loop = asyncio.get_running_loop()
    threaded_kwargs = dict(worker_kwargs)
    threaded_kwargs["emitter"] = _ThreadsafeDelegationEmitter(emitter, loop)
    thread_task = asyncio.create_task(asyncio.to_thread(_run_worker_thread_entry, runner, app, threaded_kwargs))

    def _log_thread_result(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except (RuntimeError, OSError, ValueError, TypeError):
            log.warning("provider-native worker thread failed for %s", execution_id, exc_info=True)

    thread_task.add_done_callback(_log_thread_result)

    while True:
        record = task_bot_runtime.get_execution(execution_id, repo_root)
        if str((record or {}).get("state") or "").strip().lower() in _TERMINAL_TASK_STATES:
            return
        if task_bot_runtime.is_cancel_requested(execution_id, repo_root=repo_root):
            summary = "Cancelled by user."
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary=summary,
                blocker="cancelled",
                repo_root=repo_root,
            )
            failed = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
            try:
                await emitter.failed(failed, specialist_id=specialist_id, bot=bot, text=summary)
            except (RuntimeError, OSError, ValueError, TypeError):
                log.debug("provider-native cancellation emit failed for %s", execution_id, exc_info=True)
            if not thread_task.done():
                thread_task.cancel()
            return
        has_progress = _worker_has_started_progress(record)
        worker_timeout_s = _supervisor_worker_timeout_s(worker_kwargs, has_progress=has_progress)
        timeout_s = worker_timeout_s + _WORKER_WATCHDOG_GRACE_S
        age_s = _heartbeat_age_s(record)
        if age_s is not None and age_s >= timeout_s:
            phase = "further progress" if has_progress else "first event"
            summary = f"Background execution failed: provider-native worker produced no {phase} within {timeout_s:g}s."
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary=summary,
                blocker="provider_native_timeout",
                repo_root=repo_root,
            )
            failed = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
            try:
                await emitter.failed(failed, specialist_id=specialist_id, bot=bot, text=summary)
            except (RuntimeError, OSError, ValueError, TypeError):
                log.debug("provider-native timeout emit failed for %s", execution_id, exc_info=True)
            if not thread_task.done():
                thread_task.cancel()
            return
        if thread_task.done():
            await thread_task
            return
        poll_s = min(1.0, max(0.005, timeout_s / 4))
        done, _pending = await asyncio.wait({thread_task}, timeout=poll_s)
        if done:
            await thread_task
            return


async def _finalize_worker_completion(
    emitter: Any,
    execution_id: str,
    work_dir: Path | None,
    prompt: str,
    attempt_baseline: dict[str, tuple[int, int]],
    result_text_parts: list[str],
    tools_used: list[str],
    succeeded_tools: list[str],
    failed_tools: list[str],
    tool_outputs: dict[str, list[str]],
    bot: Any,
    specialist_id: str,
    repo_root: str | Path | None,
) -> None:
    """Finalize a normal worker with honest evidence and proof artifacts."""
    # Verification scopes to THIS worker's brief: the multi-task context block
    # names the OTHER workers' deliverables, and reading requirements out of it
    # failed every multi-task run ("missing" files that were never this job).
    scope_prompt = _brief_scope(prompt)
    created = _resolve_created(work_dir, attempt_baseline, result_text_parts, tools_used)
    created = _reconcile_requested_artifact_from_evidence(scope_prompt, work_dir, created, tool_outputs)
    created = _reconcile_missing_marker_literals(scope_prompt, work_dir, created)
    artifact_issues = _requested_artifact_issues(scope_prompt, work_dir, created, tool_outputs)
    if artifact_issues:
        raise _WorkerRetry("requested artifact verification failed: " + "; ".join(artifact_issues))
    _report_pdfs = await asyncio.to_thread(render_report_pdfs, work_dir, created)
    if _report_pdfs:
        created = list(created) + [p for p in _report_pdfs if p not in created]
    result_summary = _build_result_summary(
        result_text_parts,
        tools_used,
        created,
        succeeded_tools=succeeded_tools,
        failed_tools=failed_tools,
        prompt=scope_prompt,
    )
    result_summary = _sanitize_terminal_summary(result_summary, created)
    _exec_warnings = executability_warning(work_dir, created)
    _exec_warnings += await asyncio.to_thread(runtime_executability_warning, work_dir, created)
    result_summary += _exec_warnings
    verified_success = bool(created) or _worker_text_is_confirmed_answer(
        result_text_parts, prompt=scope_prompt, succeeded_tools=succeeded_tools, failed_tools=failed_tools
    )
    verified_success &= _hidden_completion_review_passes(
        scope_prompt, work_dir, created, result_summary, verified_success, failed_tools, succeeded_tools=succeeded_tools
    )
    artifacts = _artifacts_from_created(created)
    # The engine's own artifact verification just PASSED (issues would have
    # raised _WorkerRetry above, _hidden_completion_review_passes agreed, and
    # no executability warning fired). A leftover failure-flavored hedge from
    # the worker's prose then reads as a contradiction next to the "verified"
    # banner — the engine's verdict is authoritative, so it owns the summary.
    if created and verified_success and not _exec_warnings and _FAILURE_LANGUAGE_RE.search(result_summary):
        _names = ", ".join(Path(p).name for p in created[:5])
        result_summary = f"Created {_names} — verified by the engine's artifact checks."
    if artifacts and verified_success:
        try:
            task_bot_runtime.attach_proof(
                execution_id,
                artifacts=artifacts,
                summary=result_summary,
                status="verified",
                actor=bot.name,
                repo_root=repo_root,
            )
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            log.warning("Artifact proof persistence failed for %s (%s)", execution_id, type(exc).__name__)
            raise _WorkerRetry("artifact proof persistence failed") from exc
    completion_payload = task_bot_runtime.complete_execution(
        execution_id,
        actor=bot.name,
        summary=result_summary,
        repo_root=repo_root,
        verified_success=verified_success,
    )
    record_payload = (
        completion_payload
        if isinstance(completion_payload, dict)
        else task_bot_runtime.get_execution(execution_id, repo_root)
    )
    record = _normalize_record(record_payload)
    if str((record or {}).get("state") or "") == "completed" or (
        not isinstance(completion_payload, dict) and verified_success
    ):
        await emitter.completed(record, specialist_id=specialist_id, bot=bot, text=result_summary)
    else:
        await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=result_summary)


async def _finalize_live_repo_completion(
    emitter: Any,
    execution_id: str,
    repo_root: Path,
    prompt: str,
    attempt_baseline: dict[str, tuple[int, str]],
    result_text_parts: list[str],
    tools_used: list[str],
    succeeded_tools: list[str],
    failed_tools: list[str],
    bot: Any,
    specialist_id: str,
) -> None:
    changed = _live_repo_files_changed_since(repo_root, attempt_baseline)
    if not changed:
        write_tools_used = sorted({tool for tool in tools_used if tool in _LIVE_REPO_WRITE_TOOLS})
        if not write_tools_used:
            raise _WorkerRetry("self-development task changed no live repo files; no write tool was used")
        if failed_tools:
            raise _WorkerRetry(
                "self-development task changed no live repo files; transient failed tools seen: "
                + ", ".join(failed_tools[:3])
            )
        raise _WorkerRetry(
            "self-development task changed no live repo files; write tools used did not change counted files: "
            + ", ".join(write_tools_used[:3])
        )
    if _live_repo_changes_are_docs_only(changed) and not _prompt_allows_docs_only_completion(prompt):
        raise _WorkerRetry(
            "self-development task changed only documentation files; live code or test files must change"
        )
    result_summary = _live_repo_result_summary(result_text_parts, changed)
    if not _hidden_completion_review_passes(
        prompt, repo_root, changed, result_summary, True, failed_tools, succeeded_tools=succeeded_tools
    ):
        raise _WorkerRetry("self-development hidden completion review failed")
    artifacts = _artifacts_from_created(changed)
    if artifacts:
        try:
            task_bot_runtime.attach_proof(
                execution_id,
                artifacts=artifacts,
                summary=result_summary,
                status="verified",
                actor=bot.name,
                repo_root=repo_root,
            )
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            log.warning("Live-repo proof persistence failed for %s (%s)", execution_id, type(exc).__name__)
            raise _WorkerRetry("live-repo proof persistence failed") from exc
    task_bot_runtime.complete_execution(
        execution_id,
        actor=bot.name,
        summary=result_summary,
        repo_root=repo_root,
        verified_success=True,
    )
    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
    if str((record or {}).get("state") or "") == "completed":
        await emitter.completed(record, specialist_id=specialist_id, bot=bot, text=result_summary)
    else:
        await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=result_summary)


async def _run_agent_worker(
    app: Any,
    *,
    execution_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    instructions: str,
    repo_root: Path,
    work_dir: Path | None = None,
    requires_live_repo_change: bool = False,
    profile: str | None = None,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    memory_enabled: bool = True,
    effort: str = "diligent",
    autonomy_level: int = 4,
    file_access: int | None = None,
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
    runtime_policy: dict[str, Any] | None = None,
    preflight_events: list[dict[str, Any]] | None = None,
    preflight_baseline: dict[str, tuple[int, int]] | None = None,
) -> None:
    base_tools_used: list[str] = []
    base_succeeded_tools: list[str] = []
    base_failed_tools: list[str] = []
    base_tool_outputs: dict[str, list[str]] = {}
    for event in preflight_events or []:
        event_type = str(event.get("type") or "")
        tool_name = str(event.get("name") or "tool")
        if event_type == "tool_start":
            if tool_name not in base_tools_used:
                base_tools_used.append(tool_name)
            progress = f"Using {tool_name}â€¦"
        elif event_type == "tool_output":
            if event.get("ok") is False:
                if tool_name not in base_failed_tools:
                    base_failed_tools.append(tool_name)
                progress = _tool_phrase(tool_name, failed=True)
            else:
                if tool_name not in base_succeeded_tools:
                    base_succeeded_tools.append(tool_name)
                result_text = str(event.get("result_text") or "")
                if result_text:
                    base_tool_outputs.setdefault(tool_name, []).append(result_text)
                progress = _tool_phrase(tool_name, done=True)
        else:
            continue
        task_bot_runtime.update_execution(
            execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
    max_attempts = _self_recovery_attempts(autonomy_level)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        result_text_parts: list[str] = []
        tools_used = list(base_tools_used)
        succeeded_tools = list(base_succeeded_tools)
        failed_tools = list(base_failed_tools)
        tool_outputs = {name: list(values) for name, values in base_tool_outputs.items()}
        saw_event = False
        worker_runtime_received = False
        # Consecutive tool failures within THIS attempt: a worker that keeps
        # snagging must not spin "hit a snag" forever — cap it and let the
        # recovery machinery (or an honest failure) take over.
        consecutive_snags = 0
        progress = (
            "Preparing live repo change baseline."
            if requires_live_repo_change
            else "Preparing workspace change baseline."
        )
        task_bot_runtime.update_execution(
            execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
        attempt_baseline = (
            _live_repo_workspace_mtimes(repo_root) if requires_live_repo_change else _workspace_mtimes(work_dir)
        )
        attempt_prompt = prompt if attempt == 1 else _replan_prompt(prompt, last_error, attempt, max_attempts)
        # Fold in any follow-up instructions queued by the user mid-run.
        steer_notes = task_bot_runtime.take_pending_instructions(execution_id, repo_root=repo_root)
        if steer_notes:
            attempt_prompt += (
                "\n\nADDITIONAL INSTRUCTIONS FROM THE USER (mid-task — incorporate these):\n- "
                + "\n- ".join(steer_notes)
            )
        if requires_live_repo_change:
            attempt_prompt = _with_live_repo_change_requirement(attempt_prompt)
        event_stream = None
        try:
            event_stream = run_agent_worker_events(
                app,
                prompt=attempt_prompt,
                instructions=instructions,
                work_dir=work_dir or repo_root,
                profile=profile,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                effort=effort,
                role=specialist_id,
                session_id=f"{execution_id}-attempt-{attempt}",
                execution_id=execution_id,
                autonomy_level=autonomy_level,
                file_access=file_access,
                guardrails=guardrails,
                guardrail_modes=guardrail_modes,
                job_type="self_development" if requires_live_repo_change else None,
                memory_enabled=memory_enabled,
                work_context_id=execution_work_context_id(execution_id, repo_root),
                runtime_policy=runtime_policy,
            ).__aiter__()
            while True:
                event = await _next_worker_event(event_stream, saw_event=saw_event)
                if event is None:
                    break
                event_type = str(event.get("type") or "").strip()
                saw_event = True
                if _execution_is_terminal(execution_id, repo_root):
                    return
                # In-flight cancellation: honour user stop between steps.
                if task_bot_runtime.is_cancel_requested(execution_id, repo_root=repo_root):
                    task_bot_runtime.fail_execution(
                        execution_id,
                        actor=bot.name,
                        summary="Cancelled by user.",
                        blocker="cancelled",
                        repo_root=repo_root,
                    )
                    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                    await emitter.failed(record, specialist_id=specialist_id, bot=bot, text="Cancelled by user.")
                    return
                if event_type == "model_runtime":
                    runtime = validate_model_runtime_receipt(
                        event.get("runtime"),
                        requested_profile=str(profile or ""),
                        requested_model_id=str(model_id or ""),
                    )
                    if runtime is None:
                        raise _WorkerFatal("provider-native worker emitted an invalid model runtime receipt")
                    current = task_bot_runtime.get_execution(execution_id, repo_root) or {}
                    runtime_profile = dict(current.get("runtime_profile") or {})
                    runtime_profile["model_runtime"] = runtime
                    task_bot_runtime.update_execution(
                        execution_id,
                        runtime_profile=runtime_profile,
                        actor=bot.name,
                        repo_root=repo_root,
                        force=True,
                    )
                    worker_runtime_received = True
                elif event_type == "text":
                    chunk = str(event.get("text") or "")
                    if chunk:
                        result_text_parts.append(chunk)
                elif event_type == "progress":
                    progress = str(
                        event.get("text") or event.get("message") or "Provider-native worker is running."
                    ).strip()
                    if progress:
                        task_bot_runtime.update_execution(
                            execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
                        )
                        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                        await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
                elif event_type == "tool_start":
                    tool_name = str(event.get("name") or "tool").strip() or "tool"
                    if tool_name not in tools_used:
                        tools_used.append(tool_name)
                    progress = _tool_phrase(tool_name)
                    task_bot_runtime.update_execution(
                        execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
                    )
                    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                    await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
                elif event_type == "tool_output":
                    last_tool = str(event.get("name") or (tools_used[-1] if tools_used else "tool"))
                    # Track tool outcomes so a failed action isn't reported as success.
                    tool_ok = event.get("ok") is not False
                    _record_tool_outcome(
                        last_tool,
                        ok=tool_ok,
                        succeeded_tools=succeeded_tools,
                        failed_tools=failed_tools,
                    )
                    if not tool_ok:
                        consecutive_snags += 1
                        record_issue(
                            surface="chat-worker",
                            kind="tool_failure",
                            message=f"{last_tool} failed (streak {consecutive_snags})",
                            context={"execution_id": execution_id, "task": str(prompt or "")[:160]},
                            repo_root=repo_root,
                        )
                        if consecutive_snags >= _MAX_CONSECUTIVE_SNAGS:
                            raise _WorkerRetry(
                                f"{last_tool} failed {consecutive_snags} times in a row; changing approach"
                            )
                        progress = (
                            _tool_phrase(last_tool, failed=True)
                            if consecutive_snags == 1
                            else f"Still stuck on this step (try {consecutive_snags}) — rethinking the approach."
                        )
                    else:
                        consecutive_snags = 0
                        result_text = str(event.get("result_text") or "")
                        if result_text:
                            tool_outputs.setdefault(last_tool, []).append(result_text)
                        progress = _tool_phrase(last_tool, done=True)
                    task_bot_runtime.update_execution(
                        execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
                    )
                    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                    await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
                    if not requires_live_repo_change and _should_finalize_exact_artifact_tool_result(
                        prompt,
                        last_tool=last_tool,
                        succeeded_tools=succeeded_tools,
                        failed_tools=failed_tools,
                    ):
                        if not worker_runtime_received:
                            raise _WorkerRetry("provider-native worker model runtime receipt missing")
                        log.info("worker %s verifying exact artifact after file tool success", execution_id)
                        await _finalize_worker_completion(
                            emitter,
                            execution_id,
                            work_dir,
                            prompt,
                            attempt_baseline,
                            result_text_parts,
                            tools_used,
                            succeeded_tools,
                            failed_tools,
                            tool_outputs,
                            bot,
                            specialist_id,
                            repo_root,
                        )
                        return
                elif event_type == "error":
                    # Deterministic terminal states are non-retryable upstream.
                    if event.get("retryable") is False:
                        raise _WorkerFatal("provider-native worker reported a non-retryable error")
                    raise _WorkerRetry("provider-native worker reported a retryable error")
                elif event_type == "done":
                    if not worker_runtime_received:
                        raise _WorkerRetry("provider-native worker model runtime receipt missing")
                    if requires_live_repo_change:
                        await _finalize_live_repo_completion(
                            emitter,
                            execution_id,
                            repo_root,
                            prompt,
                            attempt_baseline,
                            result_text_parts,
                            tools_used,
                            succeeded_tools,
                            failed_tools,
                            bot,
                            specialist_id,
                        )
                    else:
                        await _finalize_worker_completion(
                            emitter,
                            execution_id,
                            work_dir,
                            prompt,
                            attempt_baseline,
                            result_text_parts,
                            tools_used,
                            succeeded_tools,
                            failed_tools,
                            tool_outputs,
                            bot,
                            specialist_id,
                            repo_root,
                        )
                    return

            # Stream ended without a terminal event — evidence gate decides success.
            if not worker_runtime_received:
                raise _WorkerRetry("provider-native worker model runtime receipt missing")
            if requires_live_repo_change:
                await _finalize_live_repo_completion(
                    emitter,
                    execution_id,
                    repo_root,
                    prompt,
                    attempt_baseline,
                    result_text_parts,
                    tools_used,
                    succeeded_tools,
                    failed_tools,
                    bot,
                    specialist_id,
                )
            else:
                await _finalize_worker_completion(
                    emitter,
                    execution_id,
                    work_dir,
                    prompt,
                    attempt_baseline,
                    result_text_parts,
                    tools_used,
                    succeeded_tools,
                    failed_tools,
                    tool_outputs,
                    bot,
                    specialist_id,
                    repo_root,
                )
            return
        except asyncio.CancelledError:
            # Server shutdown / connection loss — mark execution and re-raise.
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary="Background execution cancelled.",
                blocker="cancelled",
                repo_root=repo_root,
            )
            raise
        except (
            RuntimeError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            _WorkerRetry,
            _WorkerFatal,
        ) as exc:
            if not isinstance(exc, (_WorkerRetry, _WorkerFatal)):
                log.warning("Background worker run raised %s", type(exc).__name__)
                frames = traceback.extract_tb(exc.__traceback__)
                if frames:
                    frame = frames[-1]
                    site = f"{Path(frame.filename).name}:{frame.lineno}"
                    last_error = f"{type(exc).__name__} at {site}"
                else:
                    last_error = type(exc).__name__
            else:
                last_error = str(exc)
            # Non-retryable: fatal signals and setup errors before the first event.
            non_retryable = isinstance(exc, _WorkerFatal) or (not saw_event and not isinstance(exc, _WorkerRetry))
            if not non_retryable and attempt < max_attempts:
                progress = (
                    f"Hit a snag; diagnosing and trying another approach (attempt {attempt + 1} of {max_attempts})…"
                )
                try:
                    task_bot_runtime.update_execution(
                        execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
                    )
                    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                    await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
                except (RuntimeError, OSError, ValueError, TypeError):
                    log.debug("self-recovery progress emit failed for %s", execution_id, exc_info=True)
                log.info("worker %s attempt %d failed (%s); retrying", execution_id, attempt, last_error[:120])
                continue
            # Out of attempts — fail honestly.
            record_issue(
                surface="chat-worker",
                kind="worker_failed",
                message=f"out of attempts: {last_error}"[:300],
                context={"execution_id": execution_id, "task": str(prompt or "")[:160], "attempts": str(max_attempts)},
                repo_root=repo_root,
            )
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary=f"Background execution failed: {last_error}",
                blocker="provider_native_failed",
                repo_root=repo_root,
            )
            record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
            await emitter.failed(
                record, specialist_id=specialist_id, bot=bot, text=f"Background execution failed: {last_error}"
            )
            return
        finally:
            if event_stream is not None:
                await _close_worker_event_stream(event_stream)
