"""A run that changed no files can still have answered the question.

Live incident (WORKBOARD run fc_20260722T230347_56d7ad): a read-only
inspect-and-explain request produced a correct five-bullet answer, and Thomas
reported it as a failure with a fabricated exit 1, hiding the answer. Any tool
call at all -- including ``fs.read_file``, which such a request must make to
answer -- disqualified the run.

The relaxation must not let an incomplete write request pass, so these cover
both directions.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil.dispatch_agent_loop import dispatch_via_agent_loop
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY
from thomas.server.routes.evolve_agent_runtime import _confirmed_conversation_reply


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


def _dispatch(repo: Path, events: list[dict], *, writes: str = ""):
    """Run the dispatcher with a scripted event stream and optional file write."""

    def runner(_prompt, cwd, _timeout, emit_event):
        for event in events:
            emit_event(event)
        if writes:
            (Path(cwd) / writes).write_text("changed\n", encoding="utf-8")
        return 0, "done"

    return dispatch_via_agent_loop(
        "inspect and explain this project",
        cwd=repo,
        dry_run=False,
        runner=runner,
        verify=False,
        token_check=lambda: True,
    )


def _answer(text: str = "Here is what the project does, in five points.") -> dict:
    return {FORGE_EVENT_KEY: "final", "text": text}


def test_a_read_only_answer_is_a_success(repo: Path) -> None:
    result = _dispatch(
        repo,
        [
            {FORGE_EVENT_KEY: "tool", "name": "fs.read_file", "text": "read app.py"},
            {FORGE_EVENT_KEY: "tool_result", "text": "VALUE = 1"},
            {FORGE_EVENT_KEY: "tool", "name": "code.search", "text": "search"},
            _answer(),
        ],
    )

    assert result.ok is True, result.reason
    assert result.returncode == 0
    assert "NO repo changes" not in result.reason


def test_a_write_that_reported_failure_is_still_a_failure(repo: Path) -> None:
    """The guard the relaxations must not remove: the agent tried to edit, the
    tool REPORTED failure, and nothing changed — an incomplete build, not an
    answer. (A write whose every result succeeded while git says nothing
    changed now files as the answer with a visible neutral note — see
    test_an_answer_after_a_clean_write_capable_run_is_filed_not_failed.)"""
    result = _dispatch(
        repo,
        [
            {FORGE_EVENT_KEY: "tool", "name": "fs.read_file", "text": "read"},
            {FORGE_EVENT_KEY: "tool", "name": "fs.write_file", "text": "write app.py"},
            {FORGE_EVENT_KEY: "tool_result", "name": "fs.write_file", "text": "denied", "is_error": True},
            _answer("I updated the file."),
        ],
    )

    assert result.ok is False, result.reason


def test_unnamed_tool_activity_that_reported_failure_stays_strict(repo: Path) -> None:
    """Only ``tool`` carries a name. Without one the call classifies as
    write-capable, and when it also reported failure the strict verdict is
    kept rather than guessed at."""
    result = _dispatch(
        repo,
        [{FORGE_EVENT_KEY: "tool_result", "text": "boom", "is_error": True}, _answer()],
    )

    assert result.ok is False, result.reason


def test_an_unknown_tool_is_treated_as_capable_of_writing(repo: Path) -> None:
    """Unknown names still classify as write-capable: a clean run files the
    answer WITH the visible write-capable note, never as a plain read-only
    answer — the classification stays conservative even though the verdict no
    longer demotes a clean run."""
    captured: list[dict] = []

    def runner(_prompt, _cwd, _timeout, emit_event):
        emit_event({FORGE_EVENT_KEY: "tool", "name": "some.new_tool", "text": "?"})
        emit_event(_answer())
        return 0, "done"

    result = dispatch_via_agent_loop(
        "inspect and explain this project",
        cwd=repo,
        dry_run=False,
        runner=runner,
        emit=captured.append,
        verify=False,
        token_check=lambda: True,
    )

    assert result.ok is True, result.reason
    assert any("write-capable tool ran" in str(e.get("text") or "") for e in captured), captured


def test_a_real_edit_still_succeeds(repo: Path) -> None:
    result = _dispatch(
        repo,
        [
            {FORGE_EVENT_KEY: "tool", "name": "fs.write_file", "text": "write"},
            _answer("Updated app.py."),
        ],
        writes="app.py",
    )

    assert result.ok is True, result.reason
    assert result.changed_files


def test_no_tools_at_all_is_unchanged_behaviour(repo: Path) -> None:
    result = _dispatch(repo, [_answer("It is a small Python project.")])

    assert result.ok is True, result.reason


# The SUBPROCESS Code path re-derives the same verdict from the persisted
# transcript, in a third place. It kept the old strict rule after the two
# dispatchers were fixed, so a read-only run taking that route was still
# recorded as "no change made" with the answer buried under it.
def _transcript(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


def _tool(name: str) -> dict:
    return {FORGE_EVENT_KEY: "tool", "name": name, "text": f"used {name}"}


def test_transcript_verdict_accepts_a_read_only_answer() -> None:
    text = _transcript(
        _tool("fs.read_file"),
        {FORGE_EVENT_KEY: "tool_result", "text": "VALUE = 1"},
        _tool("code.search"),
        {FORGE_EVENT_KEY: "final", "text": "Here is what the project does."},
    )

    assert _confirmed_conversation_reply(text) is True


def test_transcript_verdict_still_rejects_an_attempted_edit() -> None:
    # The genuine failed-edit shape: the write REPORTED failure. A clean
    # write-capable run is no longer disqualified (contract settled 2026-08-05
    # -- the caller has already established from git truth that nothing
    # changed, so the tool's name alone is not evidence of failure).
    text = _transcript(
        _tool("fs.read_file"),
        _tool("fs.write_file"),
        {FORGE_EVENT_KEY: "tool_result", "text": "disk full", "is_error": True},
        {FORGE_EVENT_KEY: "final", "text": "I updated the file."},
    )

    assert _confirmed_conversation_reply(text) is False


def test_transcript_verdict_stays_strict_without_tool_names() -> None:
    """tool_result carries no name, so a transcript of only those cannot prove
    the run was read-only and keeps the previous behaviour."""
    text = _transcript(
        {FORGE_EVENT_KEY: "tool_result", "text": "something"},
        {FORGE_EVENT_KEY: "final", "text": "An answer."},
    )

    assert _confirmed_conversation_reply(text) is False


def test_all_three_verdict_sites_agree_on_a_read_only_run(repo: Path) -> None:
    """The point of the change: the same run must not be judged differently
    depending on which execution route it happened to take."""
    events = [
        _tool("fs.read_file"),
        {FORGE_EVENT_KEY: "final", "text": "Here is what the project does."},
    ]

    in_process = _dispatch(repo, events)

    assert in_process.ok is True, in_process.reason
    assert _confirmed_conversation_reply(_transcript(*events)) is True


# The relaxation above was INERT in production for its first hours: it needs a
# tool name, and the only forge event the agent loop actually produces around a
# tool is tool_result, whose name the translator was dropping. Events.tool_start
# has no callers anywhere in the repo, so the TOOL_START branch never runs.
# These drive the REAL AgentEvent types through the real translator.
def _translate(events: list) -> list[dict]:
    from thomas.forge.anvil.dispatch_agent_loop import _AgentLoopForgeTranslator

    captured: list[dict] = []
    translator = _AgentLoopForgeTranslator(captured.append)
    for kind, data in events:
        translator.feed(kind.value, data)
    translator.close()
    return captured


def test_the_real_tool_result_event_carries_its_tool_name() -> None:
    """The name has to survive translation, or every downstream check that asks
    whether a run only read gets an anonymous event and assumes the worst."""
    from thomas.core.events import EventType

    out = _translate(
        [
            (EventType.TOOL_RESULT, {"tool_id": "1", "tool_name": "fs.read_file", "result": "x", "ok": True}),
            (EventType.AGENT_DONE, {"text": "Here is how it works."}),
        ]
    )

    tool_events = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool_result"]
    assert tool_events, "the loop emits TOOL_RESULT; it must reach the forge stream"
    assert tool_events[0].get("name") == "fs.read_file"


def test_a_real_read_only_transcript_is_judged_an_answer() -> None:
    """End to end through the shapes production actually emits: no synthetic
    'tool' events, only TOOL_RESULT, which is all the agent loop ever sends."""
    from thomas.core.events import EventType

    out = _translate(
        [
            (EventType.TOOL_RESULT, {"tool_id": "1", "tool_name": "fs.read_file", "result": "x", "ok": True}),
            (EventType.TOOL_RESULT, {"tool_id": "2", "tool_name": "code.search", "result": "y", "ok": True}),
            (EventType.AGENT_DONE, {"text": "It keeps score in a variable."}),
        ]
    )

    assert _confirmed_conversation_reply(_transcript(*out)) is True


def test_a_real_write_transcript_is_still_not_an_answer() -> None:
    from thomas.core.events import EventType

    out = _translate(
        [
            (EventType.TOOL_RESULT, {"tool_id": "1", "tool_name": "fs.read_file", "result": "x", "ok": True}),
            (EventType.TOOL_RESULT, {"tool_id": "2", "tool_name": "fs.write_file", "result": "ok", "ok": False}),
            (EventType.AGENT_DONE, {"text": "Updated it."}),
        ]
    )

    # ok=False on the write is what keeps this a failure; a CLEAN successful
    # write whose net change is nothing (idempotent re-write) files as the
    # answer it produced -- see the clean-write test below.
    assert _confirmed_conversation_reply(_transcript(*out)) is False


def test_a_read_access_stamp_on_a_shell_tool_does_not_disqualify_the_answer() -> None:
    # The agent-loop translator stamps access ("read"/"write") on tool events,
    # classifying shell.exec by its command. The runtime recorder must honor
    # the stamp: without it, an explain run whose shell ran `dir` was filed as
    # a fabricated exit-1 failure even after the loop learned better.
    text = _transcript(
        {"fc": "tool", "name": "shell.exec", "access": "read"},
        {"fc": "tool_result", "text": "dir listing"},
        {"fc": "final", "text": "This folder is empty. Want to pick a project?"},
    )
    assert _confirmed_conversation_reply(text) is True


def test_a_write_stamp_with_a_failed_result_still_disqualifies() -> None:
    # The stamp outranks the name, and a write-capable tool that FAILED is the
    # genuine failed-edit shape this predicate exists to catch.
    text = _transcript(
        {"fc": "tool", "name": "fs.write_file", "access": "write"},
        {"fc": "tool_result", "text": "permission denied", "is_error": True},
        {"fc": "final", "text": "Done."},
    )
    assert _confirmed_conversation_reply(text) is False


def test_a_clean_write_capable_run_that_answered_is_an_answer() -> None:
    # Same contract as dispatch_agent_loop/dispatch_claude_cli: git truth says
    # nothing changed (the caller checked), every result succeeded, the answer
    # arrived -- the tool's NAME is not evidence of failure.
    text = _transcript(
        {"fc": "tool", "name": "shell.exec", "access": "write"},
        {"fc": "tool_result", "text": "ok", "is_error": False},
        {"fc": "final", "text": "Here is what the project does."},
    )
    assert _confirmed_conversation_reply(text) is True
