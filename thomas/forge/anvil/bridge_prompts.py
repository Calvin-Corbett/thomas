"""Prompt composition helpers for all evolve bridge dispatch paths."""
from __future__ import annotations

from typing import Any


def compose_claude_prompt(goal: str, *, definition: str = "", plan: str = "", branch_only: bool = True) -> str:
    """Build the prompt that will be typed into Claude Code."""
    parts = [f"Build task dispatched by Thomas-evolve:\n\n{goal.strip()}"]
    if definition.strip():
        parts.append("## Success definition\n" + definition.strip())
    if plan.strip():
        parts.append("## Converged implementation plan\n" + plan.strip())
    if branch_only:
        parts.append(
            "IMPORTANT: Work on a NEW git branch. Run the tests. Then STOP before merging to "
            "dev/main — leave the change for review by Thomas's fail-closed promotion gate. "
            "Do not modify protected files or gate scripts."
        )
    return "\n\n".join(parts)


def _format_history(history: Any) -> str:
    """Render prior conversation turns as a compact ``Who: text`` transcript.

    ``history`` is a list of ``{"role": "user"|"assistant", "text": str}`` (the
    cleaned natural-language turns, NOT raw tool/forge-event noise). Each turn is
    bounded so a long session can never blow up the prompt; empty turns drop out.
    """
    lines: list[str] = []
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        who = "User" if str(turn.get("role") or "").lower() == "user" else "Thomas"
        lines.append(f"{who}: {text[:1500]}")
    return "\n\n".join(lines[-12:])  # keep the most recent turns; bound prompt size


def compose_headless_prompt(goal: str, *, definition: str = "", plan: str = "", history: Any = None) -> str:
    """Compose one turn for Thomas Code — a conversational coding ASSISTANT, not a
    forced build order.

    The agent decides, turn by turn, whether the message wants a plain reply (a
    greeting, a question, small talk) or real file edits (a build/fix/change
    request). It is NEVER forced to edit: a chat message yields a chat reply with
    zero file changes and no repo exploration. There is no intent classifier and
    no keyword gate — the model already knows how to do both, exactly like Claude
    Code answering "hi" normally and only editing when you ask it to build.

    When it DOES edit it is still edit-only (no shell/git) and the engine then
    runs a REAL verification over the changed files — the EDIT step of a
    reason→edit→verify loop. ``history`` (prior user/assistant turns) is woven in
    so a follow-up like "explain what you just did" sees the conversation.
    """
    parts = [
        "You are Thomas Code, an engineering assistant working directly in THIS "
        "repository. Chat and answer questions normally, like a thoughtful colleague. "
        "Use your file tools (Read/Edit/Write/Glob/Grep) to read, edit, or create "
        "files ONLY when the user actually asks you to build, edit, fix, refactor, or "
        "change something. For a greeting, a question, or small talk, just reply in "
        "plain language — do NOT read or edit any files, and do NOT explore the repo. "
        "You decide, turn by turn, whether this message calls for a conversational "
        "reply or for real edits."
    ]
    history_text = _format_history(history)
    if history_text:
        parts.append("## Conversation so far\n" + history_text)
    parts.append("## User\n" + goal.strip())
    if definition.strip():
        parts.append("## Success definition\n" + definition.strip())
    if plan.strip():
        parts.append("## Converged implementation plan\n" + plan.strip())
    parts.append(
        "When — and only when — the user asks you to build or change something, you are "
        "an edit-only builder and the EDIT step of a reason→edit→verify loop: make the "
        "file changes directly in the working tree (Read/Write/Edit; you do not run "
        "shell or git yourself). After your edits, Thomas's build engine runs a REAL "
        "verification on the files you changed (it byte-compiles and imports the changed "
        "modules, and executes a changed test file with pytest); if that check fails the "
        "engine feeds the failure back for another edit pass. Do NOT create branches or "
        "commit. Do not modify protected files or gate scripts."
    )
    return "\n\n".join(parts)


def compose_fix_prompt(goal: str, failure: str) -> str:
    """Compose the EDIT prompt for a fix pass after verification failed.

    Carries the original goal plus the REAL failure output from the engine's
    verification subprocess so the builder fixes the specific breakage. Stays
    edit-only and bounded — the engine re-verifies after this pass.
    """
    tail = str(failure or "").strip()[-1500:]
    return (
        f"Build task dispatched by Thomas-evolve (FIX pass):\n\n{goal.strip()}\n\n"
        "Your previous edit did NOT pass verification. Thomas's build engine ran a real "
        "check on the changed files and it FAILED with this output:\n\n"
        f"{tail}\n\n"
        "Fix the changed files so this check passes. You are an edit-only builder — "
        "Read/Write/Edit only; the engine re-runs the same check after your edit. Do not "
        "modify protected files or gate scripts."
    )
