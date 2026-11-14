"""A PowerShell formatting cmdlet in a directory listing is not a mutation.

Live incident (2026-08-05, w2-code-explain, conversation
``fc_20260806T001153_ff51a9``): "look at the project I have selected and tell
me what it does" ran a read-only PowerShell directory listing that Thomas
classified ``access='write' basis='command'`` while ``git status`` in the SAME
run classified ``'read'``. The persisted transcript records tool RESULTS only
(never the command), but the recorded output — a table with the custom column
order ``Mode Length LastWriteTime Name`` — pins the command family: a
``Get-ChildItem ... | Format-Table ...`` pipeline, and that command reproduces
the exact recorded misclassification against the rule as it stood.

Root cause: the newly-added Windows mutation verbs (``del``, ``rd``,
``format``, ...) ended in a bare ``\\b``, and ``-`` is a word boundary — so the
disk-format verb ``format`` matched inside PowerShell's read-only
``Format-Table`` / ``Format-List`` cmdlets. The verbs must end at a real
token end (whitespace, a ``/`` switch, or end of command), not merely at any
non-word character.
"""

from __future__ import annotations

import pytest

from thomas.agent.loop_tool_protocol import tool_call_access
from thomas.core.events import EventType
from thomas.forge.anvil.dispatch_agent_loop import _AgentLoopForgeTranslator
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY

# The measured run's listing command: reproduces the recorded output shape
# (custom column order) and the recorded access='write' misclassification.
MEASURED_LISTING = "Get-ChildItem -Force | Format-Table Mode,Length,LastWriteTime,Name"


def test_the_measured_run_listing_command_is_a_read() -> None:
    assert tool_call_access("shell.exec", {"command": MEASURED_LISTING}) == ("read", "command")


@pytest.mark.parametrize(
    "command",
    [
        MEASURED_LISTING,
        "dir",
        "Get-ChildItem -Force",
        "type file.txt",
        # paths whose characters contain mutation-verb substrings
        "dir C:\\Users\\corbe",
        "type model.delta.json",
        "type C:\\Users\\corbe\\model.delta.json",
        # more of the Format-* cmdlet family, piped with and without spaces
        "Get-ChildItem | Sort-Object Name | Format-List",
        "Get-ChildItem|Format-Wide",
        "Get-Date -Format yyyy-MM-dd",
        # git reads that share letters with mutating verbs
        "git status --short",
        "git log --format=%H --oneline -5",
    ],
)
def test_read_only_commands_classify_read(command: str) -> None:
    assert tool_call_access("shell.exec", {"command": command}) == ("read", "command")


@pytest.mark.parametrize(
    "command",
    [
        "del x.txt",
        "rd /s dir",
        "rd/s build",  # cmd allows switch concatenation without a space
        "Remove-Item x.txt",
        "Rename-Item a.txt b.txt",
        "ren a.txt b.txt",
        "move a.txt b.txt",
        "format d:",
        "Format-Volume -DriveLetter D",
        "git add .",
    ],
)
def test_real_mutations_still_classify_write(command: str) -> None:
    assert tool_call_access("shell.exec", {"command": command}) == ("write", "command")


def test_the_translator_stamps_the_measured_listing_as_read() -> None:
    """The exact stream shape the loop emits live: the command text arrives
    ONLY in the arg deltas, and the stamped access must say read."""
    captured: list[dict] = []
    translator = _AgentLoopForgeTranslator(captured.append)
    for event_type, data in [
        (EventType.TOOL_CALL_START, {"tool_id": "1", "tool_name": "shell.exec"}),
        (
            EventType.TOOL_CALL_ARGS_DELTA,
            {"tool_id": "1", "delta": '{"command": "' + MEASURED_LISTING.replace("\\", "\\\\") + '"}'},
        ),
        (EventType.TOOL_CALL_END, {"tool_id": "1"}),
        (
            EventType.TOOL_RESULT,
            {"tool_id": "1", "tool_name": "shell.exec", "result": "Mode Length LastWriteTime Name", "ok": True},
        ),
    ]:
        translator.feed(event_type.value, data)
    translator.close()

    tool_events = [e for e in captured if e.get(FORGE_EVENT_KEY) == "tool_result"]
    assert tool_events, "the shell call must reach the forge stream"
    assert tool_events[0].get("access") == "read"
    assert tool_events[0].get("access_basis") == "command"
