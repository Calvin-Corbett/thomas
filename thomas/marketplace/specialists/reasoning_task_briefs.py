"""Per-worker instruction briefs for chat send_task dispatches."""

from __future__ import annotations

from typing import Any

# The shared-context block appended to multi-task briefs. Artifact
# verification must scope to the text BEFORE this marker: the context names
# the OTHER workers' deliverables, and treating those as this worker's
# requirements failed every multi-task run ("missing exact requested
# artifact" for files that were never this worker's job).
TASK_CONTEXT_MARKER = "[Context — the user's full request"


def brief_scope(prompt: str) -> str:
    """Return only THIS worker's brief (strip the shared-context block)."""
    text = str(prompt or "")
    idx = text.find(TASK_CONTEXT_MARKER)
    return text[:idx].rstrip() if idx >= 0 else text


def build_send_task_instructions(
    prompt: str | None,
    args: dict[str, Any],
    title: str,
    *,
    multi_dispatch: bool,
) -> str:
    """Compose the instructions a dispatched worker receives.

    A single dispatch trusts the model-authored structured instructions. The
    model has the full conversation and can resolve follow-ups such as "you
    pick" into the actual deliverable; replacing that brief with only the
    latest raw turn destroys the subject and caused graphs to become games.

    A multi-part ask ("do A and B") arrives as SEVERAL send_task calls in one
    turn. Forwarding the full raw prompt to each worker made every worker
    build EVERYTHING (7 duplicate deliverables for one two-part ask,
    exec-173a10415d7f). With multiple dispatches each worker gets its own
    brief and the raw ask rides along as labelled context only.
    """

    raw_ask = str(prompt or "").strip()
    per_task = str(args.get("instructions") or "").strip()
    if multi_dispatch:
        brief = per_task or title
        if raw_ask:
            return (
                f"{brief}\n\n[Context — the user's full request, of which THIS task "
                f"is one part. Build ONLY this task's deliverable.]\n{raw_ask}"
            )
        return brief
    return per_task or raw_ask or title
