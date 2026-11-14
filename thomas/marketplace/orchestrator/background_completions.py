"""Background task status and durable completion-announcement tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


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


def _mark_completion_reported(execution_id: str, repo_root: str | None = None) -> None:
    """Persist that a completion was announced in chat, so it is not re-announced
    after a server restart. Best-effort: a persistence failure must never break the
    chat turn — the in-memory set still dedups within this process.

    repo_root is the root the row was read from (its ``ledger_root``), so the mark lands
    on that record. Without it the record is looked up across your projects, which
    cannot tell two records with the same id apart."""
    try:
        from thomas.core import task_bot_runtime

        task_bot_runtime.update_execution(
            execution_id,
            reported_to_chat_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            repo_root=repo_root or None,
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
        ledger_root = str(row.get("ledger_root") or "").strip()
        if ledger_root:
            _mark_completion_reported(exec_id, repo_root=ledger_root)
        else:
            _mark_completion_reported(exec_id)  # a row that does not say where it was read from


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
