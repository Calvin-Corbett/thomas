"""The words a Thomas project writes: its title, its commit subject, its change summary and its team notes.

Moved out of ``thomas_project`` unchanged on 2026-09-25, when that file reached the 800-line size rule and the
check before your card needed to change ``settle_if_finished``. ``thomas_project`` imports each name back
under its old one, so ``thomas_project._subject`` and the rest still work.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from thomas.forge.anvil import forge_code_store, run_channel_mcp
from thomas.server import green_checkout, green_handoff, green_size_rule

log = logging.getLogger(__name__)

# A conversation's folder-friendly title: long enough to recognise the
# request, short enough that it reads as a title rather than the request
# itself pasted back.
_TITLE_MAX_CHARS = 80

_SIBLINGS_SHOWN, _SIBLING_FILES_SHOWN = 8, 30


def short_title(request: str) -> str:
    first_line = next((line.strip() for line in str(request or "").splitlines() if line.strip()), "")
    if len(first_line) > _TITLE_MAX_CHARS:
        return first_line[:_TITLE_MAX_CHARS].rstrip() + "…"
    return first_line or "Thomas project"


def siblings_note(siblings: dict[str, list[str]]) -> str:
    """What the other running Thomas projects have changed so far, so two teams never make the same file blind."""
    if not siblings:
        return ""
    lines = [
        "Other Thomas projects are working in their own copies right now. Files they have changed so far (never "
        "create one of these blind; if you must change one too, keep your edit small so the two merge cleanly):"
    ]
    for execution_id, files in list(siblings.items())[:_SIBLINGS_SHOWN]:
        more = len(files) - _SIBLING_FILES_SHOWN
        shown = ", ".join(files[:_SIBLING_FILES_SHOWN]) + (f", +{more} more" if more > 0 else "")
        lines.append(f"- {execution_id}: {shown}")
    return "\n".join(lines)


_SUBJECT_MAX_CHARS = 72
_TITLE_LINE = re.compile(r"^\W*TITLE\W*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_DONE_LINE = re.compile(r"^\W*DONE\W*:\s*(.+)", re.IGNORECASE | re.MULTILINE | re.DOTALL)
# A Windows drive or UNC path, or a POSIX path of two or more parts: never part of a commit subject.
_PATH = re.compile(r"(?:\b[A-Za-z]:[\\/]|\\\\)[^\s,;)\"'`]*|(?<![\w.])/(?:[\w.-]+/)+[\w.-]*")
_FIRST_SENTENCE = re.compile(r"(?<=[.!?])\s")
_TEAM_SELF_REFERENCE = re.compile(r"\b(?:I|me|my|we|us|our)\b", re.IGNORECASE)
_FRAGMENT = re.compile(r"changelog\.d/([^/]+)\.md\Z")
_UNDERSCORE_EMPHASIS = re.compile(r"(?<!\w)(_{1,2})(?=\w)(.+?)(?<=\w)\1(?!\w)")
# Told to every Thomas project's team, after the request (round 2): the subject comes from their TITLE line.
TEAM_NOTES = (
    "Record this change in a new changelog.d/<short-name>.md fragment; never edit CHANGELOG.md directly. Keep every "
    "file you change within the repo's size rule (scripts/forge/gates/monolith_guard.py, limits in "
    f"{green_handoff.BASELINE}): a file not listed under allowed_large_files stays at 800 lines or fewer, and a "
    "listed one stays within its max_lines and grows by no more than its max_growth_lines. A .py file under "
    f"thomas/ over 800 lines ALSO needs a debt note recording it in {green_size_rule.ARCHITECTURE} ('<file>.py "
    "exceeds <N> lines'); an allowed_large_files waiver alone does not cover that half, and a file that has one "
    "but not the other breaks every commit after yours. That register is read both ways: if you bring a file a "
    "debt note calls oversized back under 800 lines, or delete one a note names, take it out of that note in the "
    "same change -- a note that no longer describes its file breaks every commit after yours too. Split a file "
    "that would "
    "pass that into modules with normal imports; a change that breaks the rule comes back to you before it is handed "
    "in. End your final reply with one line `TITLE: <what changed, under 70 characters, no file paths>`: it becomes "
    "the subject of the commit you ask to land."
)
# What the checks before your card found again and again in the first self-fix campaign (2026-09-25), told to
# every team up front: false sentences in 5 of 11 checked hand-ins, tests that passed with their fix removed,
# ruff problems no one had run ruff to see, and emptied files standing in for deletions.
LESSONS = (
    "Your copy has a shell with python, pytest and ruff on PATH: use it. Before you finish, run check.run on the "
    "test files that cover your change -- its own tests and the ones for the code you changed, at most 15 files in "
    "one call -- plus tests/test_architecture.py, and `ruff check` and `ruff format --check` on every file you "
    "changed; say in your final reply what you ran and what it printed. Do not run the whole suite or build your "
    "own wider test harness: the check before your card runs every test file that imports what you changed, in "
    "parallel, and sends back what fails.",
    "A new test must fail when the fix it proves is taken out. Take the fix out once, watch the test fail, put the "
    "fix back.",
    "Every sentence you add to a changelog fragment, docstring, comment or doc must be true of the code as it now "
    "stands. Check each claim in the shell before you write it.",
    f"Delete a file with {run_channel_mcp.DELETE_TOOL_NAME} where you have it; never leave an emptied file behind "
    "in place of a deletion.",
    "When your copy is behind dev the server merges dev in first and names the files that conflicted: resolve "
    "every conflict marker in them before anything else.",
    "Stop only processes you started, by id. Every Thomas project, the caged server and your shell run as one "
    "account, so killing whatever matches python, pytest or thomas ends other projects' runs; the shell refuses a "
    "stop by name or of a process your project did not start, and lists your own processes when it does.",
)
TEAM_NOTES = TEAM_NOTES + "\n\nLessons from earlier hand-ins:\n" + "\n".join(f"- {line}" for line in LESSONS)


def subject(turns: list[dict[str, Any]], files: list[str] | None = None) -> str:
    """Name the change from its team's TITLE, its first changelog fragment, or an impersonal reply sentence.

    A turns-only call still works for the chat's existing subject callers. A done check's first-person review
    must not become the name of an earlier change when no TITLE was supplied.
    """
    agents = [t for t in reversed(turns) if isinstance(t, dict) and t.get("role") == "agent"]
    replies = [forge_code_store.agent_reply_text(t) for t in agents]
    replies = [text for text, turn in zip(replies, agents) if text and text != str(turn.get("reason") or "").strip()]
    found = next((m.group(1) for m in (_TITLE_LINE.search(r) for r in replies) if m), "")
    if not found:
        for path in files or []:
            match = _FRAGMENT.fullmatch(path)
            if match and path != "changelog.d/README.md":
                name = match.group(1).replace("-", " ").replace("_", " ")
                found = name[:1].upper() + name[1:]
                break
    if not found:
        candidates = [m.group(1) for m in (_DONE_LINE.search(r) for r in replies) if m]
        candidates.extend(replies)
        for candidate in candidates:
            sentence = _FIRST_SENTENCE.split(candidate.strip(), maxsplit=1)[0]
            if sentence and not _TEAM_SELF_REFERENCE.search(sentence):
                found = sentence
                break
    plain = found.replace("`", "").replace("*", "")
    plain = _UNDERSCORE_EMPHASIS.sub(r"\2", plain)
    words = " ".join(_PATH.sub("", plain).split()).strip(" .:;,-#_")
    if len(words) > _SUBJECT_MAX_CHARS:
        words = words[:_SUBJECT_MAX_CHARS].rstrip() + "…"
    return words or "Thomas self-change"


def patch_files(execution_id: str) -> list[str]:
    """Every file in the green's patch -- what the landed commit will change -- or [] when it cannot be read."""
    green = green_checkout.find_green(execution_id)
    if not isinstance(green, green_checkout.Green):
        return []
    try:
        return green_checkout.changed_paths(green)
    except green_checkout.GreenUnavailable:
        log.warning("could not list green %s's changes for its summary", execution_id, exc_info=True)
        return []


def change_summary(turns: list[dict[str, Any]], last_agent: dict[str, Any], files: list[str] | None = None) -> str:
    """A summary fragment that names what actually changed.

    Fix round 2: settling on Autopilot's `done` decision used `last_agent`'s
    own `reason` unconditionally -- almost always "Thomas replied without
    changing files", the done check's OWN reply, for a patch that plainly
    changes files. `self_change_promoter.py` builds the landed commit's
    subject from this.

    Task 4 (NEW-1): round 2 then named only the LAST turn that changed files,
    so a patch that changed README.md in one pass and AGENTS.md in the next
    landed as "1 file(s) changed: AGENTS.md". Now it names every file in the
    green's patch (``files``, from `green_checkout.changed_paths`, the same
    list `settle` puts in the submission), else every file any turn changed,
    capped so a huge run does not make a huge subject line. It falls back to
    `last_agent`'s own reason only when nothing changed at all.
    """
    if not files:
        agents = [t for t in turns if isinstance(t, dict) and t.get("role") == "agent"]
        files = list(dict.fromkeys(str(f) for t in agents for f in (t.get("changed_files") or [])))
    if not files:
        return str(last_agent.get("reason") or "").strip()
    shown = ", ".join(files[:5]) + (f", +{len(files) - 5} more" if len(files) > 5 else "")
    return f"{len(files)} file(s) changed: {shown}"


__all__ = ["TEAM_NOTES", "change_summary", "patch_files", "short_title", "siblings_note", "subject"]
