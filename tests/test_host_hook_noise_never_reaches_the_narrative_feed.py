"""Host-machine plugin noise must never surface as a top-level UPDATE.

Measured 2026-08-05, code-network scenario. The product feed showed, as a
top-level UPDATE addressed to the owner::

    SessionEnd hook [python3 .../session-end-llma.py] failed: /usr/bin/bash:
    line 1: python3: command not found

That line is the OPERATOR'S Claude-Code plugin hook failing on the HOST — the
CLI prints it to stderr, ``_stream_cli`` merges stderr into stdout, the line is
not JSON, and the translator's defensive fallback files every non-JSON line as
``say``, which the UI renders as narrative UPDATE text.

The fix, pinned here: CLI-side hook/plugin infrastructure stderr is filed as an
``engine_debug`` event — a kind the UI's narrative set does not contain, so it
renders under Show details — with the raw line preserved verbatim. Filtered
from the story, never destroyed.

Same seam, second defect: when the Claude CLI is not logged in, its raw "Not
logged in — Please run /login" was the user-facing error — a dead end, since
Thomas owners do not run ``/login`` anywhere. The translation now names the
real situation and the two ways out (Anthropic key in Settings, or a ready
OpenAI model), keeping the CLI's own words as the attached detail.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY, translate_claude_event

REPO_ROOT = Path(__file__).resolve().parents[1]

# The measured leak, verbatim shape.
SESSION_END_LINE = (
    "SessionEnd hook [python3 /home/op/.claude/plugins/posthog/session-end-llma.py] "
    "failed: /usr/bin/bash: line 1: python3: command not found"
)

HOOK_LINES = (
    SESSION_END_LINE,
    "SessionStart hook [node ~/.claude/hooks/start.js] failed: node: not found",
    "PostToolUse:Edit hook [python3 lint.py] failed with non-blocking status code 1",
    "PreToolUse hook [check.sh] failed: permission denied",
    "Stop hook [notify.py] failed: exit 127",
)

# The narrative kinds unified_code_mode.js renders as story text; anything else
# lands under Show details. Mirrored (not imported — it is a JS constant) so a
# drift shows up as a failing assertion naming both sides.
NARRATIVE_EVENT_KINDS = {
    "approval",
    "disconnected",
    "done",
    "final",
    "insight",
    "planning",
    "say",
    "steering",
    "stopped",
    "stopping",
}


def test_hook_failure_lines_are_filed_as_technical_not_update() -> None:
    for line in HOOK_LINES:
        events = translate_claude_event(line)
        assert len(events) == 1, f"{line!r} produced {len(events)} events"
        event = events[0]
        assert event[FORGE_EVENT_KEY] not in NARRATIVE_EVENT_KINDS, (
            f"{line!r} was filed as {event[FORGE_EVENT_KEY]!r}, which the UI renders "
            "as narrative text — host plugin noise reached the owner's feed as an UPDATE"
        )
        assert event["text"] == line, (
            "the raw line must stay visible verbatim under Show details — "
            "filtered from the narrative, not destroyed"
        )


def test_the_narrative_kind_mirror_matches_the_ui() -> None:
    """The set above is a copy of a JS constant; hold the two in lockstep."""

    source = (
        REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"
    ).read_text(encoding="utf-8")
    match = re.search(r"NARRATIVE_EVENT_KINDS = new Set\(\[([^\]]+)\]\)", source)
    assert match, "unified_code_mode.js no longer declares NARRATIVE_EVENT_KINDS"
    js_kinds = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert js_kinds == NARRATIVE_EVENT_KINDS, (
        f"the JS narrative set drifted: js={sorted(js_kinds)} test={sorted(NARRATIVE_EVENT_KINDS)}"
    )


def test_ordinary_non_json_lines_still_become_say() -> None:
    """The defensive fallback must survive: only hook plumbing is rerouted."""

    events = translate_claude_event("Compiling 3 modules...")
    assert events == [{FORGE_EVENT_KEY: "say", "text": "Compiling 3 modules..."}]


def test_a_sentence_merely_mentioning_a_hook_is_not_rerouted() -> None:
    """Classification is structural (the CLI's own stderr shape), not a keyword

    scan over the model's prose — an agent explaining a git hook it just wrote
    must still reach the narrative."""

    line = "Added a pre-commit hook that runs ruff before every commit."
    events = translate_claude_event(line)
    assert events == [{FORGE_EVENT_KEY: "say", "text": line}]


def test_not_logged_in_result_becomes_a_thomas_actionable_error() -> None:
    raw = "Not logged in — Please run /login"
    events = translate_claude_event(
        json.dumps({"type": "result", "is_error": True, "result": raw})
    )
    assert len(events) == 1 and events[0][FORGE_EVENT_KEY] == "error"
    text = events[0]["text"]
    assert "signed in" in text and "Anthropic key" in text and "OpenAI" in text, (
        f"{text!r} does not tell a Thomas owner what the situation is or the two "
        "ways out (add an Anthropic key in Settings, or pick a ready OpenAI model)"
    )
    assert raw in text, "the CLI's own words must remain attached as the detail"


def test_a_raw_not_logged_in_stderr_line_is_also_mapped() -> None:
    raw = "Not logged in - Please run /login"
    events = translate_claude_event(raw)
    assert len(events) == 1 and events[0][FORGE_EVENT_KEY] == "error"
    assert "signed in" in events[0]["text"] and raw in events[0]["text"]


def test_dispatch_reason_names_the_login_situation_not_the_exit_code(tmp_path) -> None:
    """``claude exited 1`` was the run's whole verdict. The dispatcher saw the

    login failure stream past; the recorded reason must carry it."""

    import subprocess as sp

    from thomas.forge.anvil.dispatch_claude_cli import dispatch_via_claude_cli

    sp.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)

    def runner(cmd, cwd, timeout):
        return 1, json.dumps(
            {"type": "result", "is_error": True, "result": "Not logged in — Please run /login"}
        )

    result = dispatch_via_claude_cli(
        "build x", cwd=str(tmp_path), dry_run=False, runner=runner, claude_bin="claude"
    )
    assert not result.ok
    assert "signed in" in result.reason and "Anthropic key" in result.reason, (
        f"reason {result.reason!r} still reports only the exit, not the situation"
    )
