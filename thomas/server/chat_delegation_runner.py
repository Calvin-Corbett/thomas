from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
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
from thomas.server.chat_delegation_live_repo import (
    _LIVE_REPO_WRITE_TOOLS,
    _live_repo_changes_are_docs_only,
    _live_repo_files_changed_since,
    _live_repo_result_summary,
    _live_repo_workspace_mtimes,
    _prompt_allows_docs_only_completion,
    _with_live_repo_change_requirement,
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
    _replan_prompt,
    _self_recovery_attempts,
)
from thomas.server.worker_runtime import run_agent_worker_events

log = logging.getLogger(__name__)


def _worker_text_is_confirmed_answer(result_text_parts: list[str]) -> bool:
    worker_line = _worker_summary_line(result_text_parts)
    if not worker_line:
        return False
    if _FAILURE_LANGUAGE_RE.search(worker_line):
        return False
    if _claims_file_creation(worker_line) or _claims_action_success(worker_line):
        return False
    return True


async def _next_worker_event(stream: Any, *, saw_event: bool) -> dict[str, Any] | None:
    timeout_s = _WORKER_IDLE_EVENT_TIMEOUT_S if saw_event else _WORKER_FIRST_EVENT_TIMEOUT_S
    try:
        return await asyncio.wait_for(stream.__anext__(), timeout=max(0.001, float(timeout_s)))
    except StopAsyncIteration:
        return None
    except asyncio.TimeoutError as exc:
        close = getattr(stream, "aclose", None)
        if callable(close):
            try:
                await close()
            except (RuntimeError, OSError, ValueError, TypeError):
                log.debug("worker event stream close failed after timeout", exc_info=True)
        phase = "first event" if not saw_event else "next event"
        raise _WorkerRetry(f"provider-native worker produced no {phase} within {timeout_s:g}s") from exc


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
        has_progress = _worker_has_started_progress(record)
        timeout_s = _WORKER_IDLE_EVENT_TIMEOUT_S if has_progress else _WORKER_FIRST_EVENT_TIMEOUT_S
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
    attempt_baseline: dict[str, tuple[int, int]],
    result_text_parts: list[str],
    tools_used: list[str],
    succeeded_tools: list[str],
    failed_tools: list[str],
    bot: Any,
    specialist_id: str,
    repo_root: str | Path | None,
) -> None:
    """Terminal-exit path for normal (non-live-repo) worker runs.

    Builds an honest result summary, attaches produced files as proof artifacts,
    then completes only with real evidence — no evidence means failed, not faked.
    """
    created = _resolve_created(work_dir, attempt_baseline, result_text_parts, tools_used)
    # Render Markdown report deliverables to PDF off the event loop (launches Chromium).
    _report_pdfs = await asyncio.to_thread(render_report_pdfs, work_dir, created)
    if _report_pdfs:
        created = list(created) + [p for p in _report_pdfs if p not in created]
    result_summary = _build_result_summary(
        result_text_parts,
        tools_used,
        created,
        succeeded_tools=succeeded_tools,
        failed_tools=failed_tools,
    )
    result_summary += executability_warning(work_dir, created)
    result_summary += await asyncio.to_thread(runtime_executability_warning, work_dir, created)
    artifacts = _artifacts_from_created(created)
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
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("attach_proof failed for %s", execution_id, exc_info=True)
    verified_success = bool(created) or bool(succeeded_tools) or _worker_text_is_confirmed_answer(result_text_parts)
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
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("attach_proof failed for %s", execution_id, exc_info=True)
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
    effort: str = "diligent",
    autonomy_level: int = 4,
    file_access: int | None = None,
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
) -> None:
    # Each attempt accumulates worker output and tool outcomes so the completed task
    # carries a real result. At max autonomy the worker gets bounded replan retries.
    max_attempts = _self_recovery_attempts(autonomy_level)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        result_text_parts: list[str] = []
        tools_used: list[str] = []
        succeeded_tools: list[str] = []
        failed_tools: list[str] = []
        saw_event = False
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
        # Snapshot BEFORE this attempt so we only report files this attempt touched.
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
        try:
            event_stream = run_agent_worker_events(
                app,
                prompt=attempt_prompt,
                instructions=instructions,
                work_dir=work_dir or repo_root,
                profile=profile,
                effort=effort,
                role=specialist_id,
                session_id=execution_id,
                execution_id=execution_id,
                autonomy_level=autonomy_level,
                file_access=file_access,
                guardrails=guardrails,
                guardrail_modes=guardrail_modes,
                job_type="self_development" if requires_live_repo_change else None,
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
                if event_type == "text":
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
                    progress = f"Using {tool_name}…"
                    task_bot_runtime.update_execution(
                        execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
                    )
                    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                    await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
                elif event_type == "tool_output":
                    last_tool = str(event.get("name") or (tools_used[-1] if tools_used else "tool"))
                    # Track tool outcomes so a failed action isn't reported as success.
                    if event.get("ok") is False:
                        if last_tool not in failed_tools:
                            failed_tools.append(last_tool)
                        progress = f"{last_tool} failed; continuing."
                    else:
                        if last_tool in failed_tools:
                            failed_tools.remove(last_tool)
                        if last_tool not in succeeded_tools:
                            succeeded_tools.append(last_tool)
                        progress = f"Finished {last_tool}; continuing."
                    task_bot_runtime.update_execution(
                        execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
                    )
                    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
                    await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
                elif event_type == "error":
                    err_msg = str(event.get("error") or "provider-native delegation failed")
                    # Deterministic terminal states are non-retryable upstream.
                    if event.get("retryable") is False:
                        raise _WorkerFatal(err_msg)
                    raise _WorkerRetry(err_msg)
                elif event_type == "done":
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
                            attempt_baseline,
                            result_text_parts,
                            tools_used,
                            succeeded_tools,
                            failed_tools,
                            bot,
                            specialist_id,
                            repo_root,
                        )
                    return

            # Stream ended without a terminal event — evidence gate decides success.
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
                    attempt_baseline,
                    result_text_parts,
                    tools_used,
                    succeeded_tools,
                    failed_tools,
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
                log.warning("Background worker run raised %s: %s", type(exc).__name__, exc, exc_info=True)
                frames = traceback.extract_tb(exc.__traceback__)
                if frames:
                    frame = frames[-1]
                    site = f"{Path(frame.filename).name}:{frame.lineno}"
                    last_error = f"{type(exc).__name__}: {exc} at {site}"
                else:
                    last_error = f"{type(exc).__name__}: {exc}"
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


async def _run_exhaustive_worker(
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
    effort: str = "exhaustive",
    autonomy_level: int = 4,
    file_access: int | None = None,
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
) -> None:
    """Run a task at Exhaustive Effort through the full pipeline (build -> verify ->
    adversarial review -> bounded remediation). Falls back to single worker on error.
    """
    from thomas.server.exhaustive_runtime import run_exhaustive_pipeline

    tools_used: list[str] = []
    work = work_dir or repo_root
    live_repo_baseline = _live_repo_workspace_mtimes(repo_root) if requires_live_repo_change else {}

    async def _on_tool(name: str) -> None:
        if name not in tools_used:
            tools_used.append(name)
        progress = f"Using {name}…"
        task_bot_runtime.update_execution(
            execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)

    async def _on_stage(event: dict[str, Any]) -> None:
        progress = f"Exhaustive: {str(event.get('stage') or '').replace('_', ' ')}…"
        task_bot_runtime.update_execution(
            execution_id, progress_summary=progress, actor=bot.name, repo_root=repo_root, force=True
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)

    try:
        ctx = await run_exhaustive_pipeline(
            app,
            prompt=prompt,
            instructions=instructions,
            work_dir=work,
            profile=profile,
            effort=effort,
            specialist_id=specialist_id,
            autonomy_level=autonomy_level,
            file_access=file_access,
            guardrails=guardrails,
            guardrail_modes=guardrail_modes,
            job_type="self_development" if requires_live_repo_change else None,
            emit_stage=_on_stage,
            on_tool=_on_tool,
        )
        if ctx.aborted:
            raise RuntimeError(f"exhaustive pipeline aborted: {ctx.aborted}")
        created = (
            _live_repo_files_changed_since(repo_root, live_repo_baseline)
            if requires_live_repo_change
            else _snapshot_workspace_files(work)
        )
        if requires_live_repo_change and not created:
            raise RuntimeError("exhaustive self-development changed no live repo files")
        if (
            requires_live_repo_change
            and _live_repo_changes_are_docs_only(created)
            and not _prompt_allows_docs_only_completion(prompt)
        ):
            raise RuntimeError(
                "exhaustive self-development changed only documentation files; live code or test files must change"
            )
        result_summary = (
            _live_repo_result_summary([ctx.result], created)
            if requires_live_repo_change
            else _build_result_summary([ctx.result], tools_used, created) + executability_warning(work, created)
        )
        artifacts = _artifacts_from_created(created)
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
            except (RuntimeError, OSError, ValueError, TypeError):
                log.debug("attach_proof failed for %s", execution_id, exc_info=True)
        # Pipeline completing without abort and returning a result IS evidence of real work.
        verified_success = bool(created) or bool(tools_used) or bool(str(ctx.result or "").strip())
        task_bot_runtime.complete_execution(
            execution_id,
            actor=bot.name,
            summary=result_summary,
            repo_root=repo_root,
            verified_success=verified_success,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        if str((record or {}).get("state") or "") == "completed":
            await emitter.completed(record, specialist_id=specialist_id, bot=bot, text=result_summary)
        else:
            await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=result_summary)
    except asyncio.CancelledError:
        task_bot_runtime.fail_execution(
            execution_id,
            actor=bot.name,
            summary="Background execution cancelled.",
            blocker="cancelled",
            repo_root=repo_root,
        )
        raise
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        log.warning("Exhaustive pipeline failed; falling back to single worker: %s", exc, exc_info=True)
        await _run_agent_worker(
            app,
            execution_id=execution_id,
            prompt=prompt,
            specialist_id=specialist_id,
            bot=bot,
            emitter=emitter,
            instructions=instructions,
            repo_root=repo_root,
            work_dir=work_dir,
            requires_live_repo_change=requires_live_repo_change,
            profile=profile,
            effort=effort,
            autonomy_level=autonomy_level,
            file_access=file_access,
            guardrails=guardrails,
            guardrail_modes=guardrail_modes,
        )
