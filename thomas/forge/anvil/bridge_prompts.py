"""Prompt composition helpers for all evolve bridge dispatch paths."""

from __future__ import annotations

from typing import Any

from thomas.core import cage_account
from thomas.core.autonomy import AUTOPILOT_BLOCKED_RULE

from .forge_code_projects import is_task_born_project, workspace_is_unused
from .forge_code_settings import CAGED_SHELL, direct_shell_allowed

CAGED_SHELL_SYNTAX = (
    "shell.exec hands your command line to Windows cmd.exe as typed, not to bash. "
    "In cmd.exe ';' does not separate commands: it reaches the first program as part "
    "of its arguments, which then fails with a usage error or a path that does not "
    "exist, or quietly runs only that first program. Independent commands go in "
    "separate calls, which you can make side by side in one step; a command that "
    "depends on the one before it is joined to it with &&, which runs the next one "
    "only when the previous one succeeded. A ';' inside a double-quoted argument, "
    'as in python -c "import sys; print(sys.argv)", is part of that argument and is fine. '
    "Single quotes are ordinary characters in cmd.exe, not quotes: an argument "
    "that holds spaces or wildcards goes in double quotes, as in "
    'git log --all --oneline --grep="project list" or git branch -a --list "*hold*".'
)


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


def build_pass_clock_note(timeout: int | None) -> str:
    """Return per-pass clock guidance only when a positive limit is known."""
    if timeout is None or timeout <= 0:
        return ""
    minutes, seconds = divmod(int(timeout), 60)
    duration = (
        f"{minutes} minute{'s' if minutes != 1 else ''}"
        if minutes
        else f"{seconds} second{'s' if seconds != 1 else ''}"
    )
    if minutes and seconds:
        duration += f" and {seconds} second{'s' if seconds != 1 else ''}"
    return (
        f"This Build pass has {duration} before it is stopped, finished or not. "
        "Start long test runs early; if one will not finish in time, stop waiting and finish "
        "with what you have verified, saying what is still unrun."
    )


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
    check_run_available: bool = False,
    timeout: int | None = None,
    lead_tools_available: bool = False,
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

    ``check_run_available`` is True only when the caller registers the
    ``check.run`` tool for this run (the GPT engine at live-edit policy); the
    prompt names that tool only then, so it never claims a tool it lacks.
    ``lead_tools_available`` is the same promise for ``plan.update`` and
    ``ask.user``, which the agent-loop lead has only on a run launched with a
    control folder (``run_control``).
    """
    parts = [
        "You are Thomas, a capable, direct builder working for the person who wrote to you. "
        "A greeting, a question or small talk gets a short, plain reply: no tools, no plan, no "
        "reading files. Read and edit files only when asked to build, fix or change something. "
        "On longer work, say what matters in plain words, not raw tool output."
    ]
    workspace_note = _fresh_workspace_note(project_root)
    if workspace_note:
        parts.append(workspace_note)
    history_text = _format_history(history)
    if history_text:
        parts.append("## Conversation so far\n" + history_text)
    parts.append("## User\n" + goal.strip())
    if clock_note := build_pass_clock_note(timeout):
        parts.append("## Build pass clock\n" + clock_note)
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
    access = str(file_access or "project").strip().lower()
    guard = str(guardrails or "guarded").strip().lower()
    autonomy = max(1, min(4, int(autonomy_level)))
    allow_direct_shell = direct_shell_allowed(
        autonomy_level=autonomy,
        file_access=access,
        guardrails=guard,
    )
    caged = allow_direct_shell and cage_account.running_as_cage_account()
    guardrail_rules = {
        "open": (
            f"permissive: {CAGED_SHELL}"
            if caged
            else "permissive: an unsandboxed host shell starts in the selected project "
            "because the request explicitly selected Open"
            if allow_direct_shell
            else "permissive setting selected, but direct shell is unavailable under the current access policy"
        ),
        "guarded": (
            f"standard: {CAGED_SHELL}"
            if caged
            else "standard: direct shell is unavailable; bounded engine verification runs after edits"
        ),
        "fortress": (
            "strict: direct shell is unavailable, bounded engine verification runs after edits, "
            "and tool calls are serialized"
        ),
    }
    parts.append(
        "## Enforced Code execution policy\n"
        f"File access = {access_rules.get(access, access_rules['project'])}.\n"
        f"Guardrails = {guardrail_rules.get(guard, guardrail_rules['guarded'])}.\n"
        f"Autonomy level = {autonomy}. "
        "Do not claim access or permissions broader than these enforced settings."
    )
    if int(autonomy_level) >= 5:  # Autopilot: finished is done, and a blocker it cannot clear is named for it
        parts.append("## Autopilot: when you finish, and when something stops you\n" + AUTOPILOT_BLOCKED_RULE)
    # Keep the prompt aligned with the actual capability boundary. Guarded and
    # fortress edit without a direct shell and consume engine-verifier receipts;
    # Open exposes the host shell only when autonomy and file access permit it,
    # and must say that boundary plainly.
    parts.append(
        "When asked to build or change something, make the edits directly in the working tree "
        "(Read/Write/Edit), then RUN WHAT YOU BUILT before you say it works: the project's own "
        "test or build command, or start it, open it, execute it, and read the output. A file "
        "that parses is not a file that runs. If it errors, fix it and run it again. Thomas's "
        "engine also verifies your changed files afterwards, but do not wait for it to find what "
        "you could have found. Shell commands run inside the project folder. Do NOT create "
        "branches or commit. Do not modify protected files or gate scripts."
    )
    if allow_direct_shell:
        parts[-1] = parts[-1].replace(
            "Shell commands run inside the project folder.",
            f"You have a shell: {CAGED_SHELL}. Use it to run the tests, ruff and git yourself."
            if caged
            else "The direct shell is an unsandboxed host process that starts in the selected project; "
            "it is enabled only because this request explicitly selected Open, and commands can "
            "leave that project.",
        )
        if check_run_available:
            parts[-1] += (
                " You also have check.run, which runs the project's tests (pytest), ruff check, "
                "ruff format --check and read-only git status/diff/log. Run the project's relevant "
                "tests before you say you are done. Ruff checks Python files only: never pass HTML, "
                "CSS, JavaScript, or other non-Python files to Ruff. Run pytest only when the project "
                "has Python tests; use its actual build/test command or browser interaction for web work."
            )
            if caged:
                parts[-1] += " " + CAGED_SHELL_SYNTAX
    else:
        parts[-1] = (
            "When the user asks you to build or change something, make the file changes directly "
            "with Read/Write/Edit. Direct shell is unavailable under this execution policy. Thomas's "
            "bounded verifier runs after the edit pass and feeds failures into the next edit pass; "
            "use those receipts instead of claiming you ran commands yourself. Do NOT create "
            "branches or commit. Do not modify protected files or gate scripts."
        )
        if check_run_available:
            parts[-1] += (
                " You DO have the check.run tool: it runs the project's tests (pytest on test paths, "
                "node ids, or -k selections), ruff check, ruff format --check, and read-only git "
                "status/diff/log, inside the project folder. Before you say you are done, use check.run "
                "for applicable checks, read the result, and fix what fails. Ruff checks Python files "
                "only: never pass HTML, CSS, JavaScript, or other non-Python files to Ruff. Run pytest "
                "only when the project has Python tests. For static web work, exercise the page with "
                "web.playtest when available and read the bounded engine's web-verification receipts. "
                "Do not invent a Python test suite or run an irrelevant parser to fill a checklist. "
                "check.run runs only those checks; any other command is "
                "unavailable because shell.exec is not one of your tools. Claim only the checks "
                "check.run actually ran."
            )
    # What the person reads while the run works. The first words they see used to
    # be a finding about the folder ("The workspace is empty as expected"), which
    # reads as noise; they want to hear what is about to be built.
    parts.append(
        "Reply first: before any tool call, one or two short sentences saying what you are about "
        'to do, e.g. "On it. I\'ll build Pong as one page and test it in a browser." Never open '
        "by announcing that you are checking the workspace, or that it is empty or fresh; an empty "
        "folder is the normal start. While you work, speak only when it helps (a decision, a "
        "finding, a change of plan), in a sentence or two. For a job bigger than a quick edit, add "
        "roughly how long it will take or the main stages. Say in one short sentence when a stage "
        "finishes, something surprises you, or a long wait is ahead (tests, a helper), and that "
        "you will say when it is done; never go silent for several tool calls. "
        "When the person sends a message "
        "mid-run, acknowledge it in one short sentence first, then act on it. Finish with what "
        "you built and how to use it."
    )
    # The Build screen shows the plan as its Steps card and puts a question to
    # the person as a card they answer; messages they send mid-run arrive as
    # their next turn (run_control). Named only when the run has those tools.
    if lead_tools_available:
        parts.append(
            "For work with three or more steps, call plan.update at the start and whenever a step "
            "starts or finishes (owner = the helper doing it, empty for your own). Use ask.user only "
            "for a decision that is the person's to make (taste, scope, a trade-off), with two to "
            "four options and your recommendation; never to ask permission to continue or to confirm "
            "what you can check yourself. Their messages arrive as your next message in this run."
        )
    # The pre-card repair rounds most often find passing-on-dev tests broken by
    # the change; the remaining recurring misses are dev applicability, size,
    # newly added tests and Ruff formatting. Ask for those checks before hand-in,
    # not only after the engine's bounded verifier or the second look finds them.
    parts.append(
        "For a Python change, before hand-in run the tests that import the changed modules and "
        "every test file you edited, the repository's architecture tests, ruff check and ruff "
        "format --check on changed files, and its size gate. Where there is a dev landing branch, "
        "check your change still applies to its tip; if you cannot check, say so. Compare a "
        "failing test with the unchanged target branch before calling it pre-existing. Prove a "
        "new regression test by removing the fix, watching it fail, then restoring it. Never "
        "weaken tests or gates to get green. Name any check you could not run as unverified."
    )
    # Measured on a homepage build: verification scratch (a server log, a
    # verify-*.cjs probe) landed in the project root, appeared in CHANGED FILES
    # beside the user's real work with a Keep/Revert choice, and was swept into
    # the checkpoint commit. `.thomas/` is Thomas's own namespace and
    # `project_delta_since` keeps `.thomas/scratch/` out of every user-facing
    # change list, so scratch parked there is invisible end-to-end.
    parts.append(
        "Put verification scratch (probe scripts, server logs) under .thomas/scratch/ in the "
        "project, never the project root, and delete it when you finish."
    )
    # Measured on the same build: the final message described the delivered page
    # with entirely wrong specifics — it named three cats that appear nowhere in
    # the shipped file. The summary was written from memory of the plan, not
    # from the artifact. Guidance only: nothing filters or rejects the summary.
    parts.append(
        "Write your final message AFTER re-reading the files you changed, and say only details that "
        "are true of them. The final message is a short, plain note to the person, in their terms: "
        "what you made and how to use it (the controls, what to try first), two or three sentences "
        "and a short list at most. It is not a report. Do not name files unless the person must "
        'know one, do not say "I re-checked ..." or list what you tested, and do not use em dashes '
        "or ::: fences. If the finish rule asks for EVIDENCE and VERIFY lines, put them on their "
        "own lines at the very end; the screen hides them from the person."
    )
    return "\n\n".join(parts)


def compose_fix_prompt(goal: str, failure: str, *, timeout: int | None = None) -> str:
    """Compose the EDIT prompt for a fix pass after verification failed.

    Carries the original goal plus the REAL failure output from the engine's
    verification subprocess so the builder fixes the specific breakage. Stays
    edit-only and bounded — the engine re-verifies after this pass.
    """
    tail = str(failure or "").strip()[-1500:]
    clock_note = build_pass_clock_note(timeout)
    return (
        f"Build task dispatched by Thomas-evolve (FIX pass):\n\n{goal.strip()}\n\n"
        + "Your previous edit did NOT pass verification. Thomas's build engine ran a real "
        "check on the changed files and it FAILED with this output:\n\n"
        f"{tail}\n\n"
        "Fix the changed files so this check passes. You are an edit-only builder — "
        "Read/Write/Edit only; the engine re-runs the same check after your edit. Preserve "
        "the existing implementation: do not replace or truncate a substantial file into "
        "a stub to silence the verifier. Do not modify protected files or gate scripts."
        + (f"\n\n## Build pass clock\n{clock_note}" if clock_note else "")
    )


def pin_your_messages(prompt: str, messages: list[str]) -> str:
    """``prompt`` with every message the person sent the lead earlier in this run, still in force.

    A message arrives mid-pass as the lead's next turn (run_control), and each pass starts from an empty
    conversation, so a later pass -- a fix, a continue after the wall clock -- would otherwise work from the
    original goal alone while the screen shows the message as read. No message: ``prompt`` unchanged.
    """
    texts = [str(text).strip() for text in messages if str(text or "").strip()]
    if not texts:
        return prompt
    listed = "\n".join(f"{n}. " + text.replace("\n", "\n   ") for n, text in enumerate(texts, start=1))
    return (
        f"{prompt}\n\n## Messages the person sent you during this run\n"
        "You read these in an earlier pass of this run. They still apply: follow them over the request above "
        f"where they differ, and a later message over an earlier one.\n\n{listed}"
    )
