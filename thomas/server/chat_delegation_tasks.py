"""Pure formatting and reference resolution for delegated chat tasks."""

from __future__ import annotations

from typing import Any


def build_active_task_digest_from_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int = 3,
    default_backend: str,
) -> str:
    """Format active execution records for the chat model's task-control context."""

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
