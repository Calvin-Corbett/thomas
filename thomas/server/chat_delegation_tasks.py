"""Pure formatting and reference resolution for delegated chat tasks."""

from __future__ import annotations

from typing import Any

# A task in one of these states is over. Nothing can be steered or stopped, and
# nothing further will happen to it.
_FINISHED_TASK_STATES = frozenset(
    {"completed", "verified", "failed", "abandoned", "cancelled", "canceled", "done"}
)


def build_active_task_digest_from_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int = 3,
    default_backend: str,
) -> str:
    """Format still-running execution records for the chat model's task context.

    Finished work is filtered out here because the rows arrive unfiltered:
    session_active_delegations returns EVERY execution for the session despite
    its name. The header tells the model these are things it can stop, so a
    completed task in the list is a standing instruction to lie -- one of this
    user's sessions holds 28 tasks, all finished, and every single turn was told
    three of them were running and could be cancelled. That is the mechanism
    behind "your task is still running" answers about work that finished days
    ago, and behind steer and cancel commands landing on a corpse. It also spent
    roughly 700 tokens a turn saying so.
    """

    if not rows:
        return ""
    rows = [row for row in rows if str(row.get("state") or "").strip().lower() not in _FINISHED_TASK_STATES]
    if not rows:
        return ""
    lines = ["Background work in this chat: to change or stop a RUNNING one, call update_task with its [task <ref>]:"]
    for row in rows[: max(1, int(limit or 1))]:
        bot = str(row.get("bot_id") or "worker").strip() or "worker"
        state = str(row.get("state") or "requested").replace("_", " ")
        backend = str(row.get("backend_type") or default_backend).replace("_", " ")
        ref = str(row.get("execution_id") or "").strip()
        subject = str(row.get("summary") or row.get("title") or "").strip()
        progress = str(row.get("last_progress") or "").strip()
        detail = (
            f"{subject} (status: {progress})"
            if subject and progress and progress.lower() not in subject.lower()
            else subject or progress or "starting up"
        )
        lines.append(f"- [task {ref}] {bot} [{state} via {backend}]: {detail}")
    return "\n".join(lines)


def resolve_active_task_ref_from_rows(
    rows: list[dict[str, Any]],
    task_ref: str,
    *,
    terminal_states: frozenset[str] | set[str],
) -> str | None:
    """Resolve only an exact execution id or the digest's ``[task <id>]`` form."""

    ref = str(task_ref or "").strip()
    if ref.startswith("[") and ref.endswith("]"):
        ref = ref[1:-1].strip()
    if ref.lower().startswith("task "):
        ref = ref[5:].strip()
    if not ref:
        return None
    normalized = ref.casefold()
    for row in rows:
        eid = str(row.get("execution_id") or "").strip()
        if not eid:
            continue
        if eid.casefold() == normalized:
            return eid
    _ = terminal_states  # terminal handling belongs to the structured update operation
    return None
