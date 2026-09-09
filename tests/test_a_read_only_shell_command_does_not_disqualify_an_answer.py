"""A shell command that only reads is not evidence of a failed edit.

Live incident (2026-08-05, code-explain scenario): "look at this project and
tell me what it does" produced the model's correct final answer, and Thomas
filed the run as FAILED with a fabricated exit 1. The read-only relaxation in
``dispatch_via_agent_loop`` requires every named tool to be an inspection
tool, and ``shell.exec`` is not in ``_CODE_INSPECTION_TOOLS`` — even when the
command it ran was a directory listing. The repo already classifies shell
commands by CONTENT (``_shell_command_is_mutation``); the dispatch verdict
just never consulted it.

The user-facing wording then compounded the misfile: "GPT ran but made NO
repo changes (no-op) — nothing to review" — for an explain ask, no changes is
CORRECT and the thing to review (the answer) existed.

These tests drive the REAL translator with the REAL AgentEvent stream shapes
(``tool_call_start`` + ``tool_call_args_delta`` + ``tool_result``), because
the command text only ever appears in the streaming arg deltas — the executed
``TOOL_RESULT`` event carries no arguments.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.agent.loop_tool_protocol import tool_call_access
from thomas.core.events import EventType
from thomas.forge.anvil.dispatch_agent_loop import (
    _AgentLoopForgeTranslator,
    dispatch_via_agent_loop,
)
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    for args in (["init", "--initial-branch=main"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@x", "commit", "-m", "base"],
        capture_output=True,
        check=False,
    )
    return root


def _shell_call(
    tool_id: str, command: str, result: str = "output", *, ok: bool = True
) -> list[tuple[EventType, dict]]:
    """One shell.exec call as the loop actually streams it: the command text
    arrives ONLY in the arg deltas; the executed result event has no args."""
    return [
        (EventType.TOOL_CALL_START, {"tool_id": tool_id, "tool_name": "shell.exec"}),
        (EventType.TOOL_CALL_ARGS_DELTA, {"tool_id": tool_id, "delta": '{"command": "' + command + '"}'}),
        (EventType.TOOL_CALL_END, {"tool_id": tool_id}),
        (EventType.TOOL_RESULT, {"tool_id": tool_id, "tool_name": "shell.exec", "result": result, "ok": ok}),
    ]


def _dispatch(repo: Path, agent_events: list[tuple[EventType, dict]], *, final_text: str):
    """Dispatch with a runner that drives the REAL translator over the given
    AgentEvent stream, exactly as ``_agent_loop_pass_async`` does live."""

    def runner(_prompt, _cwd, _timeout, emit_event):
        translator = _AgentLoopForgeTranslator(emit_event)
        for event_type, data in agent_events:
            translator.feed(event_type.value, data)
        translator.feed(EventType.AGENT_DONE.value, {"text": final_text})
        translator.close()
        return translator.rc, translator.final_text

    return dispatch_via_agent_loop(
        "look at this project and tell me what it does",
        cwd=repo,
        dry_run=False,
        runner=runner,
        verify=False,
        token_check=lambda: True,
    )


ANSWER = "It is a small Python project that keeps one value in app.py."


def test_an_explain_run_with_a_readonly_shell_command_is_an_answer(repo: Path) -> None:
    """The measured P0: 'dir' reads, it does not write. A run of one read-only
    shell command plus a final answer and no file changes IS the answer."""
    result = _dispatch(repo, _shell_call("1", "dir"), final_text=ANSWER)

    assert result.ok is True, result.reason
    assert result.returncode == 0
    assert "NO repo changes" not in result.reason
    assert "nothing to review" not in result.reason


def test_a_readonly_type_command_also_counts_as_inspection(repo: Path) -> None:
    events = _shell_call("1", "type app.py", result="VALUE = 1")
    result = _dispatch(repo, events, final_text=ANSWER)

    assert result.ok is True, result.reason


def test_a_failed_deleting_shell_command_still_disqualifies_the_run(repo: Path) -> None:
    """The control the relaxation must not remove: 'del x' that REPORTED
    FAILURE is a genuine failed edit, and a failed edit that changed nothing
    is still a failure. (A mutation that succeeded while git truth says
    nothing changed now files as the answer with a visible note instead —
    see test_an_answer_after_a_clean_write_capable_run_is_filed_not_failed.)"""
    result = _dispatch(
        repo,
        _shell_call("1", "del x", result="Could Not Find x", ok=False),
        final_text="Removed the file.",
    )

    assert result.ok is False, result.reason


def test_a_mixed_run_with_one_failed_mutating_command_stays_disqualified(repo: Path) -> None:
    events = _shell_call("1", "dir") + _shell_call("2", "del app.py", result="Access is denied.", ok=False)
    result = _dispatch(repo, events, final_text="Listed and deleted.")

    assert result.ok is False, result.reason


def test_an_unseen_command_that_reported_failure_stays_strict(repo: Path) -> None:
    """No arg deltas arrived, so the command content is invisible and the call
    classifies as write-capable. When that call also REPORTED failure, the
    conservative verdict stands: the run is a failed edit, not an answer."""
    events = [
        (EventType.TOOL_RESULT, {"tool_id": "1", "tool_name": "shell.exec", "result": "boom", "ok": False}),
    ]
    result = _dispatch(repo, events, final_text=ANSWER)

    assert result.ok is False, result.reason


def test_the_failure_wording_never_calls_an_answer_nothing_to_review(repo: Path) -> None:
    """Even when a run is rightly filed as a failed edit, an answer that
    exists must be described as an answer — not as 'nothing to review'."""
    result = _dispatch(
        repo,
        _shell_call("1", "del x", result="Access is denied.", ok=False),
        final_text="I removed x as requested.",
    )

    assert result.ok is False
    assert "nothing to review" not in result.reason
    assert "answer" in result.reason.lower()


def test_no_answer_and_no_change_is_still_reported_as_nothing(repo: Path) -> None:
    """The 'nothing to review' wording is reserved for the case where it is
    true: no changes AND no answer text."""
    result = _dispatch(repo, _shell_call("1", "del x"), final_text="")

    assert result.ok is False
    assert "no answer" in result.reason.lower()


# ── the classification decision must be visible in the emitted events ──


def _translate(events: list[tuple[EventType, dict]]) -> list[dict]:
    captured: list[dict] = []
    translator = _AgentLoopForgeTranslator(captured.append)
    for event_type, data in events:
        translator.feed(event_type.value, data)
    translator.close()
    return captured


def test_the_tool_result_event_records_how_the_call_was_classified() -> None:
    out = _translate(_shell_call("1", "dir"))
    tool_events = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool_result"]

    assert tool_events, "the shell call must reach the forge stream"
    assert tool_events[0].get("access") == "read"
    assert tool_events[0].get("access_basis") == "command"


def test_a_mutating_command_is_recorded_as_write() -> None:
    out = _translate(_shell_call("1", "del x"))
    tool_events = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool_result"]

    assert tool_events[0].get("access") == "write"
    assert tool_events[0].get("access_basis") == "command"


def test_an_unseen_command_is_recorded_as_write_with_its_reason() -> None:
    out = _translate(
        [(EventType.TOOL_RESULT, {"tool_id": "1", "tool_name": "shell.exec", "result": "x", "ok": True})]
    )
    tool_events = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool_result"]

    assert tool_events[0].get("access") == "write"
    assert tool_events[0].get("access_basis") == "command-unseen"


# ── the shared classifier, so every verdict site can reuse one rule ──


def test_tool_call_access_classifies_by_command_content() -> None:
    assert tool_call_access("shell.exec", {"command": "dir"}) == ("read", "command")
    assert tool_call_access("shell.exec", {"command": "type app.py"}) == ("read", "command")
    assert tool_call_access("shell.exec", {"command": "git status --short"}) == ("read", "command")
    assert tool_call_access("shell.exec", {"command": "del x"}) == ("write", "command")
    assert tool_call_access("shell.exec", {"command": "rd /s /q build"}) == ("write", "command")
    assert tool_call_access("shell.exec", {"command": "move a.py b.py"}) == ("write", "command")


def test_tool_call_access_fails_toward_write_when_the_command_is_invisible() -> None:
    assert tool_call_access("shell.exec", None) == ("write", "command-unseen")
    assert tool_call_access("shell.exec", {}) == ("write", "command-unseen")


def test_tool_call_access_keeps_the_fixed_tool_lists() -> None:
    assert tool_call_access("fs.read_file", None) == ("read", "name")
    assert tool_call_access("fs.write_file", None) == ("write", "name")
    assert tool_call_access("some.new_tool", None) == ("write", "unknown-tool")
