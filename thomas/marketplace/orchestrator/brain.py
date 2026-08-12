"""OrchestratorBrain — Thomas's model-owned conversation engine.

Every ordinary chat turn reaches Thomas's reasoning model. The model may
answer directly or invoke a structured capability such as ``send_task``;
deterministic code validates those calls but never infers intent from prose.

Architecture synthesised from:
    - OpenAI Agents SDK: explicit handoffs with schema validation
    - Google DeepMind: contract-first delegation, 4.4x error reduction
    - Microsoft Agent Framework: graph-based execution state
    - Anthropic Claude SDK: brain + specialist model
    - CrewAI: controlled hierarchies with allowed_agents
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from thomas.agent.response_tone import strip_sandbox_links
from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.memory_layers import MemoryContext, MemoryCoordinator
from thomas.chat.thinking import ThinkingTracker
from thomas.core.autonomy import chat_delegation_directive
from thomas.marketplace.orchestrator.protocol import (
    CapabilityToken,
    DelegationContract,
    DelegationPhase,
    DelegationResult,
    RouteDecision,
    SpecialistStatus,
)
from thomas.marketplace.orchestrator.registry import SpecialistRegistry

log = logging.getLogger(__name__)


def _chat_failure_message(error: str | None) -> str:
    """Turn provider failures into useful guidance without leaking internals."""
    detail = str(error or "").strip().lower()
    # Remember a rejected credential so /api/health can report that chat is
    # broken, instead of every message rediscovering it independently.
    try:
        from thomas.core.model_auth_health import looks_like_auth_failure, record_auth_failure

        if looks_like_auth_failure(detail):
            record_auth_failure(detail=str(error or ""))
    except (ImportError, ModuleNotFoundError, OSError, ValueError, TypeError):  # pragma: no cover
        pass
    if "oauth" in detail and ("not connected" in detail or "sign in" in detail):
        return "The ChatGPT model isn't connected yet. Choose the Local model or sign in through Easy Setup."
    # An expired or revoked sign-in kills EVERY model, so the generic
    # "choose another model" advice below sends people hunting through the model
    # list for a problem no model can solve. Say what actually happened.
    if any(
        token in detail
        for token in (
            "token refresh failed",
            "invalid_grant",
            "http 401",
            "status 401",
            "unauthorized",
        )
    ):
        return (
            "Your ChatGPT sign-in has expired, so the ChatGPT-backed models can't be reached. "
            "Run `codex login` in a terminal to sign in again — or switch to the Local model, "
            "which doesn't need that sign-in."
        )
    if "rate-limit" in detail or "rate limit" in detail or "status 429" in detail:
        return "The selected model is temporarily rate-limited. Please wait a moment or choose another model."
    if any(token in detail for token in ("connection", "connecterror", "timed out", "timeout")):
        return "I couldn't reach the selected model. I retried once; please check that it is running and try again."
    return "I couldn't get an answer from the selected model. I retried once; please try again or choose another model."


_STATUS_ACTIVE_STATES = {"queued", "requested", "classified", "claimed", "executing", "running", "in_progress"}
_STATUS_COMPLETED_STATES = {"completed", "verified"}
_STATUS_FAILED_STATES = {"failed", "abandoned", "cancelled"}
# How many rows of each terminal bucket the status summary shows. The status branch
# marks reported only the completions WITHIN this window (see _displayed_completion_ids),
# so a fresh completion crowded past it is never marked-but-not-shown.
_STATUS_BUCKET_CAP = 5


def _bucket_background_rows(
    active_tasks: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows into (active, completed, failed, other) buckets, preserving input
    order. Shared by the status summary and the displayed-id computation so the set of
    completions we MARK reported can never drift from the set we actually SHOW."""
    rows = [dict(row or {}) for row in list(active_tasks or []) if isinstance(row, dict)]
    active_rows: list[dict[str, Any]] = []
    completed_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    other_rows: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("state") or "").strip().lower()
        if state in _STATUS_ACTIVE_STATES:
            active_rows.append(row)
        elif state in _STATUS_COMPLETED_STATES:
            completed_rows.append(row)
        elif state in _STATUS_FAILED_STATES:
            failed_rows.append(row)
        else:
            other_rows.append(row)
    return active_rows, completed_rows, failed_rows, other_rows


def _summarize_background_status(active_tasks: list[dict[str, Any]] | None) -> str:
    rows = [row for row in list(active_tasks or []) if isinstance(row, dict)]
    if not rows:
        return "No background work is running in this thread."

    active_rows, completed_rows, failed_rows, other_rows = _bucket_background_rows(active_tasks)

    def _detail(row: dict[str, Any]) -> str:
        summary = str(row.get("summary") or "").strip()
        progress = str(row.get("last_progress") or "").strip()
        state = str(row.get("state") or "unknown").replace("_", " ").strip()
        if summary and progress and progress != summary:
            return f"{summary} ({state}: {progress})"
        if summary:
            return f"{summary} ({state})"
        if progress:
            return f"{progress} ({state})"
        return state

    # Report EVERY relevant bucket, not just the first one — a finished task must still
    # be surfaced even while another task is running, and a blocked/awaiting-proof row
    # must not be dropped just because completed/failed rows coexist (the old early
    # `return` swallowed both classes).
    lines: list[str] = []
    if active_rows:
        lines.append("Background work is still running in this thread.")
        for row in active_rows[:2]:
            lines.append(f"- {_detail(row)}")
    if completed_rows:
        lines.append("Finished:" if active_rows else "Background work has completed in this thread.")
        for row in completed_rows[:_STATUS_BUCKET_CAP]:
            lines.append(f"- {_detail(row)}")
    if failed_rows:
        lines.append(
            "Finished with issues:"
            if (active_rows or completed_rows)
            else "Background work finished with issues in this thread."
        )
        for row in failed_rows[:_STATUS_BUCKET_CAP]:
            lines.append(f"- {_detail(row)}")
    if other_rows:
        # Blocked / awaiting-proof / paused work. Label it "Needs attention:" when it
        # sits alongside other buckets, else fall back to the mixed-outcomes line.
        lines.append(
            "Needs attention:"
            if (active_rows or completed_rows or failed_rows)
            else "Background work in this thread has mixed outcomes."
        )
        for row in other_rows[:_STATUS_BUCKET_CAP]:
            lines.append(f"- {_detail(row)}")
    # `rows` is non-empty (guarded above) so at least one bucket produced lines.
    return "\n".join(lines)


def _displayed_completion_ids(active_tasks: list[dict[str, Any]] | None) -> set[str]:
    """Execution-ids of the completed/verified rows the status summary ACTUALLY shows
    (its completed-bucket window). The status branch marks a fresh completion reported
    only if it is in this set, so a completion crowded past the window stays unreported
    and is delivered on a later turn instead of being silently lost."""
    _, completed_rows, _, _ = _bucket_background_rows(active_tasks)
    out: set[str] = set()
    for row in completed_rows[:_STATUS_BUCKET_CAP]:
        eid = str(row.get("execution_id") or "").strip()
        if eid:
            out.add(eid)
    return out


# Per-session record of which finished background tasks Thomas has already told the
# user about, so he reports each completion exactly once ("comes back with it when
# it's done") instead of repeating it every turn. Process-local; resets on restart,
# which is fine — completions are only interesting right after they land.
_reported_completions: dict[str, set[str]] = {}

_COMPLETED_STATES = {"completed", "verified"}
# Failures flow through the SAME report-once machinery as completions so Thomas
# finds out a task FAILED and reacts in his own voice (Calvin: "when Thomas fails it
# just fails" — nothing reached the chat layer). cancelled is user-initiated, so it
# is intentionally excluded (the user already knows).
_FAILED_STATES = {"failed", "abandoned"}
_FINISHED_STATES = _COMPLETED_STATES | _FAILED_STATES


def _mark_completion_reported(execution_id: str) -> None:
    """Persist that a completion was announced in chat, so it is not re-announced
    after a server restart. Best-effort: a persistence failure must never break the
    chat turn — the in-memory set still dedups within this process."""
    try:
        from thomas.core import task_bot_runtime

        task_bot_runtime.update_execution(
            execution_id,
            reported_to_chat_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
    # The runtime ledger is a JSON file: a missing execution record raises
    # FileNotFoundError and a read/write fault raises OSError; a rejected state
    # transition, an unparseable ledger, or a bad row shape raise
    # ValueError/LookupError/TypeError; the lazy import can raise ImportError.
    # Dedup is still correct without the flag -- the in-memory set holds for this
    # process -- so none of these may break the chat turn.
    except (ImportError, OSError, ValueError, LookupError, TypeError, AttributeError):
        log.debug("Could not persist reported_to_chat flag for %s", execution_id, exc_info=True)


def _collect_unreported_completions(session_id: str, active_tasks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return rows for background tasks that JUST finished and have NOT yet been
    reported to chat — WITHOUT marking them reported.

    Marking is deferred to _mark_completions_reported, called only AFTER a handler
    has actually delivered the note. This is the fix for the "mark before deliver"
    loss: previously the note was marked reported at compute time, so any branch
    that didn't deliver (e.g. the status branch) silently dropped the completion
    forever. A pure query here makes that class of bug structurally impossible.
    """
    rows = [dict(r or {}) for r in list(active_tasks or []) if isinstance(r, dict)]
    if not rows:
        return []
    seen = _reported_completions.setdefault(str(session_id or ""), set())
    fresh: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("state") or "").strip().lower()
        exec_id = str(row.get("execution_id") or "").strip()
        if not exec_id or state not in _FINISHED_STATES:
            continue
        # Dedup is durable: skip if already announced in THIS process (in-memory set)
        # OR persisted as reported in the ledger (survives a restart between the
        # worker finishing and the user's next message).
        if exec_id in seen or str(row.get("reported_to_chat_at") or "").strip():
            continue
        fresh.append(row)
    # Cap per turn so the note/summary can show EVERY completion we then mark reported —
    # marking more than we display would re-introduce the "marked-but-not-delivered" loss.
    # Any overflow stays unreported and surfaces on the next turn.
    return fresh[:5]


def _build_completion_note(fresh: list[dict[str, Any]]) -> str:
    """Build the one-time context note for freshly-finished tasks (or '' if none).

    Covers BOTH outcomes: a completed task (share the result) and a FAILED one (say
    honestly, in your own voice, that it didn't work and why — never pretend it
    succeeded). The worker did the work, not you."""
    if not fresh:
        return ""
    any_failed = any(str(r.get("state") or "").strip().lower() in _FAILED_STATES for r in fresh)
    header = (
        "[Background work just finished — tell the user about it in your own natural "
        "voice. For anything that COMPLETED, share the result. For anything that FAILED, "
        "say plainly that it didn't work (and why, if the reason is given) — do NOT "
        "pretend it succeeded. A worker handled it, so don't claim you did it yourself.]"
        if any_failed
        else "[Background work just finished — tell the user, in your own natural voice, "
        "that it's done and share the result. Do not say you did it yourself; a "
        "worker handled it.]"
    )
    lines = [header]
    for row in fresh:  # already capped in _collect_unreported_completions
        lines.append(f"- {_completion_detail(row)}")
    return "\n".join(lines)


def _mark_completions_reported(session_id: str, fresh: list[dict[str, Any]]) -> None:
    """Mark the given completions reported — in-memory (this process) AND durably
    in the ledger (survives restart). Called only AFTER a handler has delivered the
    note, so the 'mark before deliver' loss cannot happen."""
    if not fresh:
        return
    seen = _reported_completions.setdefault(str(session_id or ""), set())
    for row in fresh:
        exec_id = str(row.get("execution_id") or "").strip()
        if not exec_id:
            continue
        seen.add(exec_id)
        _mark_completion_reported(exec_id)


# Generic/placeholder progress lines that are NOT a real deliverable — never shown as
# a "Result:" (MR4: the multi-delegate/task-manager path leaves a "Queued…" sentinel).
_GENERIC_PROGRESS = {
    "background execution completed.",
    "queued for background execution.",
    "queued on the provider-native worker.",
    "task queued for task-bot execution.",
    "provider-native worker is running.",
}


def _completion_detail(row: dict[str, Any]) -> str:
    """Render one finished task. Completed -> 'Bot finished: "ask". Result: ...';
    failed -> 'Bot's task "ask" FAILED. Reason: ...' so the model reports it honestly."""
    bot = str(row.get("bot_name") or row.get("bot_id") or "A worker").strip() or "A worker"
    ask = str(row.get("summary") or "").strip()
    receipt = row.get("receipt") if isinstance(row.get("receipt"), dict) else {}
    evidence = receipt.get("evidence") if isinstance(receipt.get("evidence"), dict) else {}
    proof = evidence.get("proof") if isinstance(evidence.get("proof"), dict) else {}
    result = str(proof.get("summary") or evidence.get("last_progress") or row.get("last_progress") or "").strip()
    state = str(row.get("state") or "").strip().lower()
    if state in _FAILED_STATES:
        reason = str(receipt.get("error") or result or row.get("blocker") or "").strip()
        detail = f'{bot}’s task "{ask}" FAILED.' if ask else f"{bot}’s task FAILED."
        if reason and reason.lower() not in _GENERIC_PROGRESS:
            detail += f" Reason: {reason}"
        return detail
    detail = f'{bot} finished: "{ask}".' if ask else f"{bot} finished a task."
    if result and result.lower() not in _GENERIC_PROGRESS:
        detail += f" Result: {result}"
    return detail


def _completion_delivery_line(note: str) -> str:
    """Turn a completion note into a plain user-facing line for non-LLM reply paths."""
    bullets = [ln[2:].strip() for ln in str(note or "").splitlines() if ln.strip().startswith("- ")]
    bullets = [b for b in bullets if b]
    if not bullets:
        return ""
    if len(bullets) == 1:
        return f"Quick update — {bullets[0]}"
    return "Quick update — " + " ".join(bullets)


# Default token budgets by mode
_MODE_BUDGETS = {
    "fast": 1_500,
    "auto": 4_000,
    "thinking": 8_000,
    "max": 16_000,
}


class OrchestratorBrain:
    """Pure orchestrator that delegates all work to specialists.

    Parameters
    ----------
    config:
        Thomas AppConfig.
    llm:
        LLM client for the brain's own reasoning (routing, synthesis).
    memory_engine:
        Thomas's MemoryEngine instance.
    registry:
        SpecialistRegistry with all available specialists.
    """

    def __init__(
        self,
        config: Any,
        llm: Any,
        memory_engine: Any,
        registry: SpecialistRegistry,
        runtime_policy: Any = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.memory_engine = memory_engine
        self.registry = registry
        self.runtime_policy = runtime_policy

    async def process_message(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        *,
        mode: str = "auto",
        autonomy_level: int = 3,
        token_economy: str = "optimal",
        images: list[dict[str, Any]] | None = None,
        is_first_message: bool = False,
        active_task_digest: str = "",
        active_tasks: list[dict[str, Any]] | None = None,
        send_task: Any = None,
        update_task: Any = None,
        operate: Any = None,
        work_onboarding_update: Any = None,
        display_prompt: str | None = None,
    ) -> ConversationManager:
        """Process one model-owned user turn.

        Thomas's reasoning model sees the conversation and structured task
        context, then chooses whether to answer or call a capability. No
        argument here selects a semantic route -- see CONTRIBUTING_AI.md,
        "Semantic Intent Ownership".
        """
        # is_first_message is caller state, not a control: it reports whether
        # this turn opens the thread and promises nothing about routing. The
        # brain does not need it (the same fact is readable off `conversation`),
        # but thomas/server/routes/chat_v2.py still passes it, so it stays
        # accepted until that caller drops it. Removing it here alone would
        # raise TypeError on every live chat turn.
        #
        # The two route-forcing arguments that used to sit beside it --
        # dispatch_actionable and background_ack_only -- are gone. They were
        # remains of the deleted prompt-word routing: the logic went, the
        # parameters stayed, so the signature advertised control it did not
        # provide (dispatch_actionable=False never prevented a dispatch).
        # Honouring them was not an open product choice. Both select a semantic
        # route before the model is consulted, which "Semantic Intent Ownership"
        # forbids, and no caller in thomas/ passed either -- the chat_v2 route
        # is pinned to never pass them by
        # test_auto_mode_low_autonomy_keeps_actionable_request_inline.
        _ = is_first_message
        turn_start = time.monotonic()

        # Private/project context may enrich the model prompt, but history must
        # preserve exactly what the user typed. Callers opt into a separate
        # display prompt so internal context never reappears as a user message.
        conversation = conversation.append_message("user", display_prompt if display_prompt is not None else prompt)

        # Compute any just-finished background work once, then make it model
        # context. This is factual state enrichment, not an intent classifier.
        # CRITICAL: only MARK a completion reported AFTER the chosen handler has
        # actually delivered it (the _mark_completions_reported calls below), never at
        # compute time — otherwise a branch that doesn't deliver would silently lose
        # the completion forever.
        fresh_completions = _collect_unreported_completions(session_id, active_tasks)
        completion_note = _build_completion_note(fresh_completions)

        conversation = await self._handle_casual(
            session_id=session_id,
            conversation=conversation,
            prompt=prompt,
            dispatcher=dispatcher,
            mode=mode,
            autonomy_level=autonomy_level,
            token_economy=token_economy,
            turn_start=turn_start,
            reply_kind="conversation",
            active_task_digest=active_task_digest,
            send_task=send_task,
            update_task=update_task,
            operate=operate,
            work_onboarding_update=work_onboarding_update,
            completion_note=completion_note,
            images=images,
        )
        _mark_completions_reported(session_id, fresh_completions)
        return conversation

    async def _handle_background_status(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        turn_start: float,
        active_tasks: list[dict[str, Any]] | None = None,
        completion_note: str = "",
    ) -> ConversationManager:
        # The status summary below already reports completed work directly from
        # active_tasks; completion_note is accepted so the central per-turn dedup
        # (computed in process_message) covers this branch and a finished task is
        # not re-announced on the next casual turn.
        _ = completion_note
        final_text = _summarize_background_status(active_tasks)
        chunk_size = 80
        for i in range(0, len(final_text), chunk_size):
            await dispatcher.emit_text(final_text[i : i + chunk_size])

        conversation = conversation.append_message(
            "assistant",
            final_text,
            metadata={"specialists": ["reasoning"], "mode": "background_status"},
        )

        try:
            memory_coord = MemoryCoordinator(
                self.memory_engine,
                session_id,
                context_budget=_MODE_BUDGETS.get("fast", 1_500),
                policy=getattr(self.runtime_policy, "memory", None),
            )
            await memory_coord.capture_episode(
                turn_number=conversation.length // 2,
                user_message=prompt,
                assistant_response=final_text[:500],
                thinking="background_status",
                tool_calls=[],
                specialist="reasoning",
            )
        except Exception as exc:
            log.debug("Background status episode capture skipped: %s", exc)

        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary="background_status",
            total_thinking_ms=0,
            iterations=1,
            tool_calls=0,
            tokens_used=0,
            specialists_used=["reasoning"],
            total_elapsed_ms=elapsed,
        )

        return conversation

    async def _handle_casual(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        mode: str,
        autonomy_level: int,
        token_economy: str,
        turn_start: float,
        reply_kind: str = "casual",
        active_task_digest: str = "",
        send_task: Any = None,
        update_task: Any = None,
        operate: Any = None,
        work_onboarding_update: Any = None,
        completion_note: str = "",
        images: list[dict[str, Any]] | None = None,
    ) -> ConversationManager:
        """Handle direct Thomas replies without visible delegation."""
        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get("fast", 1_500),
            policy=getattr(self.runtime_policy, "memory", None),
        )

        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )
        # Always make the model aware of live background tasks whenever any exist (the
        # digest is only built when there ARE active tasks). This used to be gated behind
        # a status-intent regex, which left the model BLIND to its own running tasks on
        # any other phrasing — so "stop/cancel that task" found nothing to cancel and
        # Thomas falsely reported "nothing is running". Awareness is context, not a
        # keyword trigger: give it every turn and let the model decide organically whether
        # to steer, cancel, report on, or ignore the work. (chat sweep, 2026-06-27)
        if active_task_digest:
            memory_ctx.working = f"{memory_ctx.working}\n\n{active_task_digest}".strip()
        # When a background task just finished, make the MODEL aware of it by injecting
        # the note into its context, so it reports the result in its OWN words instead
        # of contradicting itself ("Quick update — finished" followed by "I don't have
        # the result back" — the exact bug from when the note was shown only to the
        # user, never to the model). The note text itself tells the model to relay the
        # worker's result without taking credit. Every visible reply stays model-authored
        # (Calvin's no-canned-replies law); the deterministic line is reserved for the
        # non-model paths below (memory recall / model failure) where no model runs.
        if completion_note:
            memory_ctx.working = f"{memory_ctx.working}\n\n{completion_note}".strip()
        delivered_prefix = _completion_delivery_line(completion_note) if completion_note else ""

        result = await self._dispatch_single(
            session_id=session_id,
            specialist_id="reasoning",
            prompt=prompt,
            conversation=conversation,
            memory_ctx=memory_ctx,
            dispatcher=dispatcher,
            thinking=ThinkingTracker(),
            mode=mode,
            autonomy_level=autonomy_level,
            token_economy=token_economy,
            stream_text_events=True,
            send_task=send_task,
            update_task=update_task,
            operate=operate,
            work_onboarding_update=work_onboarding_update,
            images=images,
        )

        final_text = result.content if result.ok else _chat_failure_message(result.error)
        if result.ok:
            # The model authored the reply (and, with the completion note in its
            # context above, the finished-work report is part of it). It already
            # streamed via the specialist — no canned prefix added.
            saved_text = final_text
        else:
            # The model failed, so fall back to delivering any finished-work note
            # deterministically — a completed task must never be silently lost on an
            # error turn.
            if delivered_prefix:
                await dispatcher.emit_text(delivered_prefix + "\n\n")
            chunk_size = 80
            for i in range(0, len(final_text), chunk_size):
                await dispatcher.emit_text(final_text[i : i + chunk_size])
            saved_text = f"{delivered_prefix}\n\n{final_text}".strip() if delivered_prefix else final_text
        conversation = conversation.append_message(
            "assistant",
            saved_text,
            metadata={"specialists": ["reasoning"], "mode": reply_kind},
        )

        result_tool_calls = list(getattr(result, "tool_calls", []) or [])
        await memory_coord.capture_episode(
            turn_number=conversation.length // 2,
            user_message=prompt,
            assistant_response=final_text[:500],
            thinking=reply_kind,
            tool_calls=result_tool_calls,
            specialist="reasoning",
        )

        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary=reply_kind,
            total_thinking_ms=0,
            iterations=1,
            tool_calls=len(result_tool_calls),
            tokens_used=result.tokens_used,
            specialists_used=["reasoning"],
            total_elapsed_ms=elapsed,
        )

        return conversation

    async def _handle_actionable(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        mode: str,
        autonomy_level: int,
        token_economy: str,
        turn_start: float,
        images: list[dict[str, Any]] | None = None,
        completion_note: str = "",
    ) -> ConversationManager:
        """Handle actionable messages — route to specialists, dispatch work.

        No canned acknowledgment is emitted: the only user-visible text is the
        specialist's actual model output. (Calvin: an instantaneous templated
        reply isn't the AI replying — it defeats the point.) The work:

        1. Route to best specialist(s) via LLM classification
        2. Dispatch specialist work
        3. Stream the real results as they complete
        4. Thomas stays responsive for follow-up messages

        This is the core of the dispatch-first architecture.
        """
        thinking = ThinkingTracker()
        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get(mode, 4_000),
            policy=getattr(self.runtime_policy, "memory", None),
        )

        # ── Refresh memory ────────────────────────────────────────
        thinking.start(DelegationPhase.PLANNING.value)
        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )
        # If a background task just finished, report it before handling this new
        # actionable ask, so a completed task surfaces even when the user's next
        # message is itself a fresh request. The specialist also gets the note in
        # context; the deterministic line guarantees delivery because an actionable
        # specialist won't reliably volunteer a prior task's completion on its own.
        # Deliver any just-finished background work as a factual notification before
        # handling this new actionable ask, so a completed task surfaces even when the
        # user's next message is itself a fresh request. We do NOT also inject it into
        # the specialist's context — that would double-report (the specialist would
        # restate what this line already delivered). This is a status notification of
        # OTHER work (like the accepted in-thread completion bubble), not a canned ack
        # of the current request.
        actionable_completion_prefix = _completion_delivery_line(completion_note) if completion_note else ""
        if actionable_completion_prefix:
            await dispatcher.emit_text(actionable_completion_prefix + "\n\n")
        has_recalled_memory = bool(memory_ctx.episodic or memory_ctx.semantic)
        if has_recalled_memory:
            await dispatcher.emit_memory_refresh(
                layer="all",
                total_tokens=memory_ctx.total_tokens,
            )

        # ── Route to specialists ──────────────────────────────────
        thinking.append("Using Thomas's model-owned conversation path...")
        route = RouteDecision(
            specialists=["reasoning"],
            parallel=False,
            reasoning="Structured model tools own downstream selection",
            confidence=1.0,
        )
        thinking.append(f"Route: {route.reasoning}")
        thinking.end()

        for event in thinking.events():
            await dispatcher.emit(event)

        # ── Delegate to specialists ───────────────────────────────
        all_results: list[DelegationResult] = []
        specialists_used: list[str] = []

        if route.parallel and len(route.specialists) > 1:
            all_results = await self._dispatch_parallel(
                session_id=session_id,
                specialists=route.specialists,
                prompt=prompt,
                conversation=conversation,
                memory_ctx=memory_ctx,
                dispatcher=dispatcher,
                thinking=thinking,
                mode=mode,
                autonomy_level=autonomy_level,
                token_economy=token_economy,
                images=images,
            )
        else:
            for specialist_id in route.specialists:
                result = await self._dispatch_single(
                    session_id=session_id,
                    specialist_id=specialist_id,
                    prompt=prompt,
                    conversation=conversation,
                    memory_ctx=memory_ctx,
                    dispatcher=dispatcher,
                    thinking=thinking,
                    mode=mode,
                    autonomy_level=autonomy_level,
                    token_economy=token_economy,
                    images=images,
                )
                all_results.append(result)
                if result.ok:
                    specialists_used.append(specialist_id)

        # ── Synthesise response ───────────────────────────────────
        final_text = await self._synthesise(
            prompt=prompt,
            results=all_results,
            memory_ctx=memory_ctx,
            mode=mode,
        )

        # FIX (2026-03-18): Safety net — strip any leaked routing JSON from
        # the response. If the specialist or routing LLM accidentally returned
        # internal JSON (e.g. {"specialists":...}), remove it before streaming.
        if final_text:
            import re as _re

            final_text = _re.sub(
                r'\{"specialists"\s*:\s*\[.*?\]\s*,\s*"parallel"\s*:.*?\}',
                "",
                final_text,
            ).strip()

        # Stream the specialist's actual response
        chunk_size = 80
        for i in range(0, len(final_text), chunk_size):
            await dispatcher.emit_text(final_text[i : i + chunk_size])

        # Fold the finished-work notification (already streamed above, if any) into
        # history so it persists. Never a canned ack of the current request.
        full_response = (
            f"{actionable_completion_prefix}\n\n{final_text}".strip() if actionable_completion_prefix else final_text
        )

        # ── Update conversation ───────────────────────────────────
        conversation = conversation.append_message(
            "assistant",
            full_response,
            metadata={
                "specialists": specialists_used,
                "thinking_ms": thinking.total_ms,
                "mode": mode,
                "token_economy": str(token_economy or "optimal"),
            },
        )

        # ── Capture episode ───────────────────────────────────────
        tool_calls = []
        for r in all_results:
            tool_calls.extend(r.tool_calls)

        await memory_coord.capture_episode(
            turn_number=conversation.length // 2,
            user_message=prompt,
            assistant_response=full_response[:500],
            thinking=thinking.total_text[:300],
            tool_calls=tool_calls,
            specialist=", ".join(specialists_used),
        )

        # ── Emit done ─────────────────────────────────────────────
        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary=thinking.summary(),
            total_thinking_ms=thinking.total_ms,
            iterations=sum(r.iterations for r in all_results),
            tool_calls=len(tool_calls),
            tokens_used=sum(r.tokens_used for r in all_results),
            specialists_used=specialists_used,
            total_elapsed_ms=elapsed,
        )

        return conversation

    # ── internal methods ─────────────────────────────────────────

    async def _dispatch_single(
        self,
        session_id: str,
        specialist_id: str,
        prompt: str,
        conversation: ConversationManager,
        memory_ctx: MemoryContext,
        dispatcher: EventDispatcher,
        thinking: ThinkingTracker,
        mode: str,
        autonomy_level: int,
        token_economy: str,
        stream_text_events: bool = False,
        send_task: Any = None,
        update_task: Any = None,
        operate: Any = None,
        work_onboarding_update: Any = None,
        images: list[dict[str, Any]] | None = None,
    ) -> DelegationResult:
        """Dispatch to a single specialist with contract + token."""
        specialist = self.registry.get(specialist_id)
        if specialist is None:
            return DelegationResult(
                specialist_id=specialist_id,
                status=SpecialistStatus.FAILED,
                error=f"Specialist '{specialist_id}' not found",
            )

        # Memory is THOMAS'S OWN capability — he stores/recalls inline, never via a task
        # (Calvin's law). Wire remember/recall callbacks straight to the memory engine.
        #
        # Explicit "remember X" facts MUST survive into future conversations, so they go to a
        # STABLE durable thread (not the ephemeral per-conversation session, which a new chat
        # never queries) with etype "user_fact" → role "user" — which makes them eligible for
        # profile extraction + global fact promotion. Recall then searches the current session,
        # this durable store, and the global/profile layer. Without this a remembered fact was
        # a session-scoped "system note" that vanished on the next chat (cross-session loss).
        runtime_memory = getattr(self.runtime_policy, "memory", None)
        _mem = self.memory_engine if bool(getattr(runtime_memory, "enabled", True)) else None
        _mem_thread = str(session_id or "default")
        _user_mem_thread = "user_memory"

        async def _remember_cb(*, text: str) -> bool:
            """Store a user-dictated fact durably. Returns True ONLY if actually saved."""
            if _mem is None:
                return False
            payload = str(text or "").strip()
            if not payload:
                return False
            include_thread = bool(getattr(runtime_memory, "include_thread", True))
            include_global = bool(getattr(runtime_memory, "include_global", True))
            include_profile = bool(getattr(runtime_memory, "include_profile", True))
            if not any((include_thread, include_global, include_profile)):
                return False
            target_thread = _user_mem_thread if include_global or include_profile else _mem_thread
            try:
                eid = _mem.add_event(
                    thread=target_thread,
                    etype="user_fact",
                    text=payload,
                    metadata={"source": "user_remember", "origin_session": _mem_thread},
                )
                if include_global:
                    try:
                        _mem.auto_promote_event_memory(
                            thread_id=target_thread,
                            etype="user_fact",
                            text=payload,
                            source_episode_id=int(eid) if eid else None,
                        )
                    except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                        log.debug("remember promotion failed", exc_info=True)
                return True
            # Same memory-store surface the promotion catch above names, plus
            # AttributeError for an engine missing add_event. Returning False is
            # load-bearing: reasoning.py only claims "Saved to your memory" when
            # this returns True, so a failure here must stay a False, not a raise.
            except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                log.debug("remember failed", exc_info=True)
                return False

        async def _recall_cb(*, query: str) -> str:
            if _mem is None:
                return ""
            try:
                include_thread = bool(getattr(runtime_memory, "include_thread", True))
                include_global = bool(getattr(runtime_memory, "include_global", True))
                include_profile = bool(getattr(runtime_memory, "include_profile", True))
                if not any((include_thread, include_global, include_profile)):
                    return ""
                setter = getattr(_mem, "set_thread_memory_policy", None)
                if callable(setter):
                    setter(
                        _mem_thread,
                        include_thread=include_thread,
                        include_global=include_global,
                        include_profile=include_profile,
                        pins_only=bool(getattr(runtime_memory, "pins_only", False)),
                        max_results=int(getattr(runtime_memory, "retrieval_top_k", 5) or 5),
                        max_pack_tokens=int(getattr(runtime_memory, "context_budget", 1200) or 1200),
                    )
                res = _mem.retrieve(query=str(query or ""), thread=_mem_thread)
                return str(getattr(res, "text", None) or res or "").strip()
            # Retrieval hits the same store as the write path above (OSError,
            # sqlite3.Error, RuntimeError), plus the int() coercions of the
            # runtime memory policy (TypeError/ValueError), a policy setter or
            # retrieve() the engine does not implement (AttributeError), and a
            # missing key in whatever it returns (LookupError). An empty string
            # is the honest answer for all of them.
            except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                log.debug("recall failed", exc_info=True)
                return ""

        # Create contract
        runtime_tools = getattr(self.runtime_policy, "tools", None)
        runtime_quality = getattr(self.runtime_policy, "quality", None)
        max_iterations = int(getattr(runtime_quality, "max_agent_iterations", 0) or 10)
        contract = DelegationContract(
            specialist_id=specialist_id,
            task_description=prompt[:500],
            allowed_tools=specialist.capabilities,
            timeout_seconds=float(getattr(runtime_tools, "tool_timeout_s", 120) or 120),
            max_iterations=max_iterations,
            input_context={
                "memory": memory_ctx.to_system_injection(),
                "mode": mode,
                "token_economy": str(token_economy or "optimal"),
                "system_instructions": str(getattr(self.runtime_policy, "instruction_context", lambda: "")() or ""),
                "profile_type": str(getattr(self.runtime_policy, "profile_type", "adaptive") or "adaptive"),
                "review_depth": str(getattr(self.runtime_policy, "review_depth", "adaptive") or "adaptive"),
                # The send_task callback (organic, no-regex dispatch). When present,
                # the reasoning model can hand work off via the send_task tool.
                "send_task": send_task,
                # The update_task callback: the model re-directs a RUNNING task (steer
                # or cancel), picking the right one by ref instead of a blind guess.
                "update_task": update_task,
                # Thomas's bounded direct-action callback. The server owns the
                # allowlist, policy runner, audit, and post-action readback proof.
                "operate": operate,
                # Work onboarding state is a model-authored structured call.
                # Browser/runtime code validates the envelope but never parses
                # either participant's prose to infer workflow state.
                "work_onboarding_update": work_onboarding_update,
                # Thomas's OWN memory — store/recall inline, never a task.
                "remember": _remember_cb,
                "recall": _recall_cb,
                # Autonomy reaches the MODEL here (not just the token): the level +
                # its ask-vs-hand-off directive, so "Max autonomy" actually changes
                # behavior instead of the model getting identical instructions at
                # every level. See thomas/core/autonomy.chat_delegation_directive.
                "autonomy": {
                    "level": int(autonomy_level),
                    "directive": chat_delegation_directive(autonomy_level),
                },
                "images": list(images or []),
            },
        )

        # Issue capability token. The reasoning specialist is Thomas's conversation
        # and control layer: it may read the repo, use Thomas-owned memory/task controls,
        # and call the bounded server-owned operator. It never receives raw write/shell
        # tools. Other specialists keep their declared capabilities.
        if specialist_id == "reasoning":
            allowed_tools = {
                "fs.read_file",
                "fs.list_dir",
                "fs.search",
                "skills.list",
                "skills.use",
                "send_task",
                "update_task",
                "remember",
                "recall",
                "operate",
            }
        else:
            allowed_tools = set(specialist.capabilities)
        token = CapabilityToken(
            specialist_id=specialist_id,
            session_id=session_id,
            allowed_tools=allowed_tools,
            autonomy_level=autonomy_level,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

        # Emit delegation event
        thinking.start(DelegationPhase.DELEGATING.value)
        thinking.append(f"Delegating to {specialist_id}...")
        await dispatcher.emit_delegation(
            specialist_id=specialist_id,
            task=prompt[:200],
            contract_id=contract.contract_id,
        )
        await dispatcher.emit_agent_activity(
            agent_id=specialist_id,
            status="running",
            current_task=prompt[:100],
        )

        # Execute specialist
        start = time.monotonic()
        result = DelegationResult(
            contract_id=contract.contract_id,
            specialist_id=specialist_id,
        )

        try:
            content_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            specialist_thinking: list[str] = []
            iterations = 0

            # A provider can fail before producing a single token (for example a
            # transient local-model connection reset). One retry is safe only while
            # nothing visible or effectful has happened. This prevents a momentary
            # pre-output failure from becoming the opaque "Sorry" response while also
            # ensuring tools and partial answers are never replayed.
            for attempt in range(2):
                result.error = None
                content_parts = []
                tool_calls = []
                specialist_thinking = []
                iterations = 0
                retry_safe = True

                async for event in specialist.execute(
                    contract=contract,
                    token=token,
                    prompt=prompt,
                    conversation_context=conversation.get_context_window(max_tokens=8_000),
                    memory_context=memory_ctx.to_system_injection(),
                ):
                    event_type = event.get("type", "")

                    # Pass through events to frontend
                    if event_type == "text":
                        chunk = str(event.get("text", "") or "")
                        content_parts.append(chunk)
                        if chunk:
                            retry_safe = False
                        if stream_text_events and chunk:
                            await dispatcher.emit_text(chunk)
                    elif event_type == "thinking":
                        specialist_thinking.append(event.get("text", ""))
                    elif event_type in ("tool_start", "tool_result", "tool_args"):
                        retry_safe = False
                        await dispatcher.emit(event)
                        if event_type == "tool_result":
                            tool_calls.append(event)
                    elif event_type == "done":
                        iterations = event.get("iterations", 0)
                    elif event_type == "error":
                        result.error = event.get("error", "Unknown specialist error")
                    else:
                        # Unknown specialist events may represent a real side effect
                        # (task_request/task_update), so never replay after one.
                        retry_safe = False

                if result.error is not None and retry_safe and attempt == 0:
                    log.warning(
                        "Specialist %s failed before output; retrying once: %s",
                        specialist_id,
                        result.error,
                    )
                    await asyncio.sleep(0)
                    continue
                break

            if result.error is not None:
                log.error("Specialist %s returned an error: %s", specialist_id, result.error)

            elapsed = int((time.monotonic() - start) * 1000)
            # Drop broken sandbox/local-path links the model may have inlined
            # (e.g. [Download](sandbox:/mnt/data/x.pdf)); the real deliverable
            # ships as an attached artifact card.
            result.content = strip_sandbox_links("".join(content_parts))
            result.tool_calls = tool_calls
            result.thinking = "\n".join(specialist_thinking)
            result.elapsed_ms = elapsed
            result.iterations = iterations
            result.status = SpecialistStatus.COMPLETED if result.error is None else SpecialistStatus.FAILED

            # Validate output against contract
            thinking.start(DelegationPhase.VALIDATING.value)
            if contract.validate_output({"content": result.content}):
                thinking.append(f"{specialist_id} completed successfully ({elapsed}ms)")
            else:
                thinking.append(f"{specialist_id} output failed contract validation")
                result.status = SpecialistStatus.FAILED
            thinking.end()

        except asyncio.TimeoutError:
            result.status = SpecialistStatus.TIMEOUT
            result.error = f"Specialist {specialist_id} timed out after {contract.timeout_seconds}s"
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
        except Exception as exc:
            result.status = SpecialistStatus.FAILED
            result.error = str(exc)
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
            log.error("Specialist %s failed: %s", specialist_id, exc)

        # Emit agent completion status
        await dispatcher.emit_agent_activity(
            agent_id=specialist_id,
            status=result.status.value,
            elapsed_ms=result.elapsed_ms,
        )

        self.registry.record_execution(specialist_id)
        thinking.end()

        return result

    async def _dispatch_parallel(
        self,
        session_id: str,
        specialists: list[str],
        prompt: str,
        conversation: ConversationManager,
        memory_ctx: MemoryContext,
        dispatcher: EventDispatcher,
        thinking: ThinkingTracker,
        mode: str,
        autonomy_level: int,
        token_economy: str,
        images: list[dict[str, Any]] | None = None,
    ) -> list[DelegationResult]:
        """Dispatch to multiple specialists in parallel."""
        thinking.start(DelegationPhase.DELEGATING.value)
        thinking.append(f"Parallel dispatch to: {', '.join(specialists)}")
        thinking.end()

        tasks = [
            self._dispatch_single(
                session_id=session_id,
                specialist_id=sid,
                prompt=prompt,
                conversation=conversation,
                memory_ctx=memory_ctx,
                dispatcher=dispatcher,
                thinking=thinking,
                mode=mode,
                autonomy_level=autonomy_level,
                token_economy=token_economy,
                images=images,
            )
            for sid in specialists
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[DelegationResult] = []
        for r in results:
            if isinstance(r, DelegationResult):
                final.append(r)
            elif isinstance(r, Exception):
                final.append(
                    DelegationResult(
                        status=SpecialistStatus.FAILED,
                        error=str(r),
                    )
                )
        return final

    async def _synthesise(
        self,
        prompt: str,
        results: list[DelegationResult],
        memory_ctx: MemoryContext,
        mode: str,
    ) -> str:
        """Synthesise specialist outputs into a coherent response.

        For single-specialist results, pass through directly.
        For multi-specialist results, use the brain's LLM to merge.
        """
        # Filter to successful results with actual content
        ok_results = [r for r in results if r.ok and r.content and r.content.strip()]

        if not ok_results:
            # All failed or produced empty content — build a helpful error
            errors = [r.error for r in results if not r.ok and r.error]
            if errors:
                return "I encountered issues processing your request. " + " ".join(errors[:3])
            # Edge case: specialist "succeeded" but returned empty content
            return (
                "I received your message but wasn't able to generate a response. "
                "Could you try rephrasing or asking in a different way?"
            )

        if len(ok_results) == 1:
            text = ok_results[0].content
            # Guard: if the specialist returned raw JSON (e.g. from a
            # confused model), don't pass it through as the response.
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed_json = json.loads(stripped)
                    # It IS valid JSON — the model responded with JSON
                    # instead of natural text. Try to extract useful content
                    # rather than showing the user a confusing error.
                    # FIX (2026-03-18): Previously returned "unexpected format"
                    # error. Now extracts text from JSON or passes through.
                    log.warning(
                        "Specialist returned raw JSON instead of text: %s",
                        stripped[:200],
                    )
                    # Try common response field names
                    if isinstance(parsed_json, dict):
                        for key in ("response", "content", "text", "answer", "message", "result"):
                            if key in parsed_json:
                                extracted = str(parsed_json[key]).strip()
                                if extracted:
                                    return extracted
                    # No extractable field — pass through the raw text
                    # (better than a dead-end error message)
                    return text
                except (ValueError, TypeError):
                    pass  # Not valid JSON — normal text that happens to start with {
            return text

        # Multiple results — synthesise with LLM
        parts = []
        for r in ok_results:
            parts.append(f"[{r.specialist_id}]: {r.content}")

        synthesis_prompt = (
            f"The user asked: {prompt[:300]}\n\n"
            f"Multiple specialists produced these results:\n\n"
            + "\n\n---\n\n".join(parts)
            + "\n\nSynthesise these into a single, coherent response."
        )

        try:
            messages = [
                {"role": "system", "content": "You synthesise multiple specialist outputs into one coherent response."},
                {"role": "user", "content": synthesis_prompt},
            ]
            return await self._call_llm(messages, max_tokens=2_000)
        except Exception as exc:
            log.warning("Synthesis LLM call failed: %s", exc)
            # Fallback: concatenate
            return "\n\n".join(r.content for r in ok_results)

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 1_000,
    ) -> str:
        """Call the brain's LLM (for routing, synthesis, etc.).

        Wraps Thomas's LLM client with error handling.
        Note: max_tokens is accepted for caller convenience but Thomas's
        LLMClient reads the limit from model config, not per-call args.
        """
        try:
            if hasattr(self.llm, "chat"):
                response = await self.llm.chat(messages=messages)
                # LLMClient.chat() returns a dict with "text" key
                if isinstance(response, dict):
                    return str(response.get("text", ""))
                if hasattr(response, "content"):
                    return str(response.content)
                return str(response)
            elif hasattr(self.llm, "complete"):
                prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
                response = await self.llm.complete(prompt=prompt_text)
                return str(response)
            else:
                log.error("LLM client has no chat() or complete() method")
                return ""
        except Exception as exc:
            log.error("Brain LLM call failed: %s", exc)
            raise
