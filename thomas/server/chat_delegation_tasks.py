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
    """Resolve a digest reference, ordinal, or subject fragment to an execution id."""

    ref = str(task_ref or "").strip().lower().replace("[", "").replace("]", "")
    for token in ("task", "ref", "#", ":"):
        ref = ref.replace(token, "")
    ref = ref.strip()
    if not ref:
        return None
    matches: list[tuple[str, bool]] = []
    for row in rows:
        eid = str(row.get("execution_id") or "").lower()
        if not eid:
            continue
        terminal = str(row.get("state") or "").lower() in terminal_states
        if eid == ref or eid.endswith(ref) or ref.endswith(eid) or (len(ref) >= 4 and ref in eid):
            matches.append((str(row.get("execution_id") or ""), terminal))
    for eid, terminal in matches:
        if not terminal:
            return eid
    if matches:
        return matches[0][0]
    digits = "".join(ch for ch in ref if ch.isdigit())
    if digits and digits == ref and 1 <= int(digits) <= len(rows):
        return str(rows[int(digits) - 1].get("execution_id") or "") or None
    ref_words = [word for word in ref.replace("-", " ").replace("_", " ").split() if len(word) >= 3]
    for row in rows:
        subject = str(row.get("summary") or row.get("title") or "").lower()
        if subject and any(word in subject for word in ref_words):
            return str(row.get("execution_id") or "") or None
    return None
