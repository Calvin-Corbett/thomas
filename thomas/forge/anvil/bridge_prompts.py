"""Prompt composition helpers for all evolve bridge dispatch paths."""

from __future__ import annotations

from typing import Any

from .forge_code_projects import is_task_born_project, workspace_is_unused


def _fresh_workspace_note(project_root: Any) -> str:
    """Name reality when the working folder was minted for this very task.

    Measured live (3x, 2026-08-05): a question like "look at the project I have
    selected..." asked with nothing selected lands in a brand-new empty folder
    minted seconds earlier -- and the model, told nothing about where it is
    standing, answers as if that empty folder were the user's chosen project.
    This is sight only: it adds a true sentence to the prompt when (and only
    when) the folder is a task-born mint that still holds nothing but .git and
    Thomas's own .thomas bookkeeping. It never restricts what the model may do
    there, and any error reads as "no note", never as a failed prompt.
    """
    if not project_root:
        return ""
    try:
        fresh = is_task_born_project(project_root) and workspace_is_unused(project_root)
    except (OSError, ValueError):
        return ""
    if not fresh:
        return ""
    return (
        "## Workspace\n"
        "This is a brand-new empty folder created for this task — nothing is "
        "selected and no existing project is open here. If the user asks about "
        '"the project I have selected", their currently open project, or files '
        "they expect to already exist, say plainly that no project is selected "
        "and this folder was just created empty for this conversation — do not "
        "present its emptiness as the contents of a project they chose, and do "
        "not invent contents. Building something new here is fine."
    )


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


def compose_headless_prompt(
    goal: str,
    *,
    definition: str = "",
    plan: str = "",
    history: Any = None,
    file_access: str = "project",
    guardrails: str = "guarded",
    autonomy_level: int = 3,
    project_root: Any = None,
) -> str:
    """Compose one turn for Thomas Code — a conversational coding ASSISTANT, not a
    forced build order.

    ``project_root`` (the working folder, when the dispatcher knows it) buys the
    model sight of one fact it cannot otherwise see: whether this folder is a
    freshly minted task-born workspace with nothing in it — so a question asked
    with no project selected gets an answer that names that reality instead of
    treating the empty mint as the user's chosen project.

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
        "reply or for real edits. During a longer edit task, give the user brief, plain-language "
        "progress updates at meaningful milestones (for example after inspection, implementation, "
        "and verification). Explain the outcome, not raw tool output or internal counters."
    ]
    workspace_note = _fresh_workspace_note(project_root)
    if workspace_note:
        parts.append(workspace_note)
    history_text = _format_history(history)
    if history_text:
        parts.append("## Conversation so far\n" + history_text)
    parts.append("## User\n" + goal.strip())
    if definition.strip():
        parts.append("## Success definition\n" + definition.strip())
    if plan.strip():
        parts.append("## Converged implementation plan\n" + plan.strip())
    access_rules = {
        "read_only": "read-only: inspect and plan, but do not write files",
        "workspace": "workspace: write only inside the selected Code workspace",
        "project": "project: write only inside the selected project",
        "pc": "PC: write inside the selected project or the user's home folders",
        "full": "full: write to non-system paths while preserving Thomas runtime protections",
    }
    guardrail_rules = {
        "open": "permissive: shell may be available after the route's explicit risky-action approval",
        "guarded": (
            "standard: shell runs inside the project folder; external or destructive "
            "actions require approval"
        ),
        "fortress": "strict: shell is unavailable, risky actions require approval, and tool calls are serialized",
    }
    access = str(file_access or "project").strip().lower()
    guard = str(guardrails or "guarded").strip().lower()
    parts.append(
        "## Enforced Code execution policy\n"
        f"File access = {access_rules.get(access, access_rules['project'])}.\n"
        f"Guardrails = {guardrail_rules.get(guard, guardrail_rules['guarded'])}.\n"
        f"Autonomy level = {max(1, min(4, int(autonomy_level)))}. "
        "Do not claim access or permissions broader than these enforced settings."
    )
    # This used to tell the model "you do not run shell or git yourself" and to leave
    # verification entirely to the engine. That instruction was the reason a one-line
    # undeclared-variable bug shipped: the model reviewed its work by READING it,
    # because reading was the only thing it could do. Now that the shell is available
    # inside the project folder, ask for the thing that actually catches bugs.
    parts.append(
        "When — and only when — the user asks you to build or change something, you are "
        "the EDIT and VERIFY steps of a reason→edit→verify loop. Make the file changes "
        "directly in the working tree (Read/Write/Edit), and then RUN WHAT YOU BUILT "
        "before you say it works: run the project's own test or build command if it has "
        "one, and otherwise exercise the thing you changed — start it, open it, or "
        "execute the script — and read the output. A file that parses is not a file "
        "that runs. If running it surfaces an error, fix it and run it again; that loop "
        "is the job, not an optional extra. Thomas's build engine also verifies your "
        "changed files afterwards and feeds failures back for another pass, but do not "
        "wait for it to find what you could have found yourself. Shell commands run "
        "inside the project folder. Do NOT create branches or commit. Do not modify "
        "protected files or gate scripts."
    )
    # Measured on a homepage build: verification scratch (a server log, a
    # verify-*.cjs probe) landed in the project root, appeared in CHANGED FILES
    # beside the user's real work with a Keep/Revert choice, and was swept into
    # the checkpoint commit. `.thomas/` is Thomas's own namespace and
    # `project_delta_since` keeps `.thomas/scratch/` out of every user-facing
    # change list, so scratch parked there is invisible end-to-end.
    parts.append(
        "Any scratch you need while verifying — probe scripts, server logs, one-off "
        "harnesses — goes under .thomas/scratch/ inside the project, never in the "
        "project root, and gets deleted when you finish. Scratch left anywhere else "
        "shows up in the user's changed-files list next to their real work."
    )
    # Measured on the same build: the final message described the delivered page
    # with entirely wrong specifics — it named three cats that appear nowhere in
    # the shipped file. The summary was written from memory of the plan, not
    # from the artifact. Guidance only: nothing filters or rejects the summary.
    parts.append(
        "Write your final summary AFTER re-reading the files you changed, and name "
        "only details that are actually in them — a name, a heading, a count you can "
        "point to. Prefer \"I re-checked <file>\" phrasing over recalling what you "
        "meant to build. A summary written from memory can describe content that "
        "never shipped."
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
        "Read/Write/Edit only; the engine re-runs the same check after your edit. Preserve "
        "the existing implementation: do not replace or truncate a substantial file into "
        "a stub to silence the verifier. Do not modify protected files or gate scripts."
    )
