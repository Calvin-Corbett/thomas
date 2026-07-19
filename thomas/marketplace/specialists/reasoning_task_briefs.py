"""Per-worker instruction briefs for chat send_task dispatches."""

from __future__ import annotations

from typing import Any


def build_send_task_instructions(
    prompt: str | None,
    args: dict[str, Any],
    title: str,
    *,
    multi_dispatch: bool,
) -> str:
    """Compose the instructions a dispatched worker receives.

    Single dispatch forwards the USER'S RAW request, not the model's reworded
    version — the chat layer is told it "can't build", so its rewordings hedge
    or mangle the ask while the task manager reads the original correctly.
    (Calvin, 2026-06-26.)

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
    return raw_ask or per_task or title
