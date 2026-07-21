"""Max-effort delegation runner with fail-closed proof and visible downgrade."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.server.chat_delegation_deliverable import (
    _artifacts_from_created,
    _build_result_summary,
    _snapshot_workspace_files,
    executability_warning,
)
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_exhaustive_observer import _ExhaustiveRunObserver
from thomas.server.chat_delegation_live_repo import (
    _live_repo_changes_are_docs_only,
    _live_repo_files_changed_since,
    _live_repo_result_summary,
    _live_repo_workspace_mtimes,
    _prompt_allows_docs_only_completion,
)
from thomas.server.chat_delegation_result_policy import worker_text_is_confirmed_answer
from thomas.server.chat_delegation_session import _execution_is_terminal, _normalize_record
from thomas.server.issue_ledger import record_issue
from thomas.server.work_connector_runtime import execution_work_context_id

log = logging.getLogger(__name__)


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
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    memory_enabled: bool = True,
    effort: str = "exhaustive",
    autonomy_level: int = 4,
    file_access: int | None = None,
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
    runtime_policy: dict[str, Any] | None = None,
) -> None:
    """Run Max quality gates and fall back only with an explicit downgrade receipt."""

    from thomas.server.exhaustive_runtime import (
        ExhaustivePassFailure,
        ExhaustiveQualityGateFailure,
        run_exhaustive_pipeline,
    )

    work = work_dir or repo_root
    live_repo_baseline = _live_repo_workspace_mtimes(repo_root) if requires_live_repo_change else {}
    observer = _ExhaustiveRunObserver(
        execution_id=execution_id,
        repo_root=repo_root,
        profile=profile,
        model_id=model_id,
        specialist_id=specialist_id,
        bot=bot,
        emitter=emitter,
    )

    try:
        ctx = await run_exhaustive_pipeline(
            app,
            prompt=prompt,
            instructions=instructions,
            work_dir=work,
            profile=profile,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            effort=effort,
            specialist_id=specialist_id,
            autonomy_level=autonomy_level,
            file_access=file_access,
            guardrails=guardrails,
            guardrail_modes=guardrail_modes,
            job_type="self_development" if requires_live_repo_change else None,
            memory_enabled=memory_enabled,
            runtime_policy=runtime_policy,
            work_context_id=execution_work_context_id(execution_id, repo_root),
            emit_stage=observer.on_stage,
            on_tool=observer.on_tool,
            on_model_runtime=observer.on_model_runtime,
            on_quality_review=observer.on_quality_review,
            should_cancel=observer.should_stop,
        )
        if _execution_is_terminal(execution_id, repo_root):
            raise asyncio.CancelledError
        if ctx.aborted:
            raise RuntimeError(f"exhaustive pipeline aborted: {ctx.aborted}")
        if not observer.model_runtime_receipts:
            raise RuntimeError("exhaustive pipeline completed without runtime receipts")
        if not (ctx.verified and ctx.review_passed):
            raise RuntimeError("exhaustive pipeline quality gates did not pass")

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

        answer_text = str(ctx.result or "").strip()
        task_rubric = getattr(ctx, "rubric", {})
        tools_required = bool(task_rubric.get("tools_required")) if isinstance(task_rubric, dict) else True
        answer_only = bool(not tools_required and not created and not observer.tools_used and answer_text)
        confirmed_answer = answer_only or worker_text_is_confirmed_answer([answer_text], prompt=prompt)
        if answer_only:
            current = task_bot_runtime.get_execution(execution_id, repo_root) or {}
            runtime_profile = dict(current.get("runtime_profile") or {})
            runtime_profile.update(
                {
                    "max_answer_only": True,
                    "max_verified_answer_text": answer_text[:64_000],
                }
            )
            task_bot_runtime.update_execution(
                execution_id,
                runtime_profile=runtime_profile,
                actor=bot.name,
                repo_root=repo_root,
                force=True,
            )

        if answer_only:
            result_summary = "Max answer passed fresh correctness, completeness, and robustness review."
        else:
            result_summary = (
                _live_repo_result_summary([ctx.result], created)
                if requires_live_repo_change
                else _build_result_summary([ctx.result], observer.tools_used, created, prompt=prompt)
                + executability_warning(work, created)
            )
        artifacts = _artifacts_from_created(created)
        if artifacts:
            task_bot_runtime.attach_proof(
                execution_id,
                artifacts=artifacts,
                summary=result_summary,
                status="verified",
                actor=bot.name,
                repo_root=repo_root,
            )
        verified_success = bool(created) or confirmed_answer
        task_bot_runtime.complete_execution(
            execution_id,
            actor=bot.name,
            summary=result_summary,
            repo_root=repo_root,
            verified_success=verified_success,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        # Record an evidence-free "done" (demoted to failed/no_evidence) so the
        # self-review sees it (core can't import the ledger — circular-import rule).
        if str((record or {}).get("blocker") or "") == "no_evidence":
            record_issue(
                surface="chat-worker",
                kind="no_evidence",
                message="completed without artifacts or a confirmed tool success",
                context={"execution_id": execution_id, "task": str(record.get("summary") or "")[:160]},
                repo_root=repo_root,
            )
        if str((record or {}).get("state") or "") == "completed":
            await emitter.completed(record, specialist_id=specialist_id, bot=bot, text=result_summary)
        else:
            await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=result_summary)
    except asyncio.CancelledError:
        # The supervisor may have already committed an external terminal state
        # (for example a watchdog failure). The worker thread can outlive its
        # cancelled to_thread future on Windows, so never let that late thread
        # overwrite the durable terminal record.
        if _execution_is_terminal(execution_id, repo_root):
            raise
        task_bot_runtime.fail_execution(
            execution_id,
            actor=bot.name,
            summary="Background execution cancelled.",
            blocker="cancelled",
            repo_root=repo_root,
        )
        raise
    except ExhaustiveQualityGateFailure:
        summary = "Max quality review did not pass after two remediation cycles. No result was presented as verified."
        task_bot_runtime.fail_execution(
            execution_id,
            actor=bot.name,
            summary=summary,
            blocker="max_quality_gates_failed",
            repo_root=repo_root,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=summary)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        failure_code = str(getattr(exc, "code", "quality_pipeline_failed"))
        failed_pass = {
            "pass_id": str(getattr(exc, "pass_id", "")),
            "role": str(getattr(exc, "role", "")),
            "code": failure_code,
            "exception_type": str(getattr(exc, "exception_type", "")),
        }
        failed_pass = {key: value for key, value in failed_pass.items() if value}
        if isinstance(exc, ExhaustivePassFailure):
            log.warning(
                "Exhaustive pass failed; falling back to single worker (code=%s pass=%s role=%s exception=%s)",
                failure_code,
                failed_pass.get("pass_id", "unknown"),
                failed_pass.get("role", "unknown"),
                failed_pass.get("exception_type", "none"),
            )
        else:
            log.warning("Exhaustive pipeline failed; falling back to single worker (%s)", type(exc).__name__)
        current = task_bot_runtime.get_execution(execution_id, repo_root) or {}
        runtime_profile = dict(current.get("runtime_profile") or {})
        runtime_profile.update(
            {
                "exhaustive_fallback": True,
                "exhaustive_fallback_reason": failure_code,
            }
        )
        if failed_pass:
            runtime_profile["exhaustive_failed_pass"] = failed_pass
        progress = "Max proof pipeline could not complete; continuing with a standard verified run."
        task_bot_runtime.update_execution(
            execution_id,
            runtime_profile=runtime_profile,
            progress_summary=progress,
            actor=bot.name,
            repo_root=repo_root,
            force=True,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)

        from thomas.server.chat_delegation_runner import _run_agent_worker

        await _run_agent_worker(
            app,
            execution_id=execution_id,
            prompt=prompt,
            specialist_id=specialist_id,
            bot=bot,
            emitter=emitter,
            instructions=(
                f"{instructions}\n\n"
                "The Max proof pipeline could not complete, so this is a standard verified run, "
                "not a Max-certified result. State that exact limitation at the start of the final answer."
            ),
            repo_root=repo_root,
            work_dir=work_dir,
            requires_live_repo_change=requires_live_repo_change,
            profile=profile,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            memory_enabled=memory_enabled,
            effort=effort,
            autonomy_level=autonomy_level,
            file_access=file_access,
            guardrails=guardrails,
            guardrail_modes=guardrail_modes,
            runtime_policy=runtime_policy,
        )
