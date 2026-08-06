"""An answer is never demoted to a failure by a tool that succeeded.

Live incident (2026-08-05, w2-code-explain): an explain run whose shell
listing was misclassified as a write came back as ``failed / exit 1`` with the
synthetic error "GPT gave an answer but a write-capable tool ran and no files
changed — review the answer; no edit landed" — burying a correct answer under
a fabricated failure. The classifier bug is fixed separately; THIS file pins
the verdict rule itself, per the owner's no-auto-reject rule:

* a run that produced an answer, in which git truth says NOTHING changed and
  EVERY tool result succeeded, files as the conversation outcome — with a
  VISIBLE neutral note ("a write-capable tool ran; no files changed") in the
  event stream, never an error that fails the run;
* genuine failed-edit signals still disqualify: any ``is_error`` tool result
  (a mutating tool that reported failure is exactly that) keeps the run a
  failure, with the answer still described as an answer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil.dispatch_agent_loop import dispatch_via_agent_loop
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY

NEUTRAL_NOTE = "a write-capable tool ran; no files changed"
ANSWER = "There isn't an application here yet — the repo has one baseline commit."


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


def _dispatch(repo: Path, events: list[dict], *, final_text: str = ANSWER):
    """Run the dispatcher over a scripted forge-event stream, capturing every
    event the dispatcher itself emits (so the neutral note is observable)."""
    captured: list[dict] = []

    def runner(_prompt, _cwd, _timeout, emit_event):
        for event in events:
            emit_event(event)
        if final_text:
            emit_event({FORGE_EVENT_KEY: "final", "text": final_text})
        return 0, final_text

    result = dispatch_via_agent_loop(
        "look at this project and tell me what it does",
        cwd=repo,
        dry_run=False,
        runner=runner,
        emit=captured.append,
        verify=False,
        token_check=lambda: True,
    )
    return result, captured


def _write_tool_events(*, is_error: bool = False) -> list[dict]:
    return [
        {FORGE_EVENT_KEY: "tool", "name": "fs.write_file", "text": "write app.py", "access": "write"},
        {
            FORGE_EVENT_KEY: "tool_result",
            "name": "fs.write_file",
            "text": "wrote" if not is_error else "permission denied",
            "is_error": is_error,
            "access": "write",
        },
    ]


def test_a_clean_write_capable_run_with_an_answer_is_not_a_failure(repo: Path) -> None:
    """The demotion itself: write-capable tool ran, every result succeeded,
    git says nothing changed, an answer exists — that is the outcome."""
    result, _ = _dispatch(repo, _write_tool_events())

    assert result.ok is True, result.reason
    assert result.returncode == 0
    assert "no edit landed" not in result.reason
    assert "review the answer" not in result.reason


def test_the_neutral_note_is_visible_in_the_events(repo: Path) -> None:
    result, captured = _dispatch(repo, _write_tool_events())

    notes = [e for e in captured if NEUTRAL_NOTE in str(e.get("text") or "")]
    assert notes, f"the neutral note must appear in the event stream; events={captured!r}"
    assert all(str(e.get(FORGE_EVENT_KEY)) != "error" for e in notes), "the note is a note, not an error"
    assert all(not e.get("is_error") for e in notes)
    assert result.ok is True


def test_no_synthetic_error_event_is_emitted_for_the_clean_case(repo: Path) -> None:
    _, captured = _dispatch(repo, _write_tool_events())

    error_events = [e for e in captured if str(e.get(FORGE_EVENT_KEY)) == "error"]
    assert not error_events, f"a clean answered run must not carry an error event: {error_events!r}"


def test_a_stamped_write_shell_command_with_clean_results_also_files_the_answer(repo: Path) -> None:
    events = [
        {FORGE_EVENT_KEY: "tool", "name": "shell.exec", "text": "del temp.txt", "access": "write"},
        {FORGE_EVENT_KEY: "tool_result", "name": "shell.exec", "text": "ok", "is_error": False, "access": "write"},
    ]
    result, _ = _dispatch(repo, events)

    assert result.ok is True, result.reason


def test_an_unnamed_clean_tool_result_no_longer_fails_the_answer(repo: Path) -> None:
    """Unseen names classify as write-capable — which, clean, is now a note,
    not a failure."""
    result, _ = _dispatch(repo, [{FORGE_EVENT_KEY: "tool_result", "text": "something"}])

    assert result.ok is True, result.reason


def test_a_failed_tool_result_still_disqualifies_the_run(repo: Path) -> None:
    """The kept control: a mutating tool that REPORTED FAILURE is a genuine
    failed-edit signal, and the run stays a failure."""
    result, _ = _dispatch(repo, _write_tool_events(is_error=True))

    assert result.ok is False, result.reason
    assert "answer" in result.reason.lower(), "the existing answer must still be named"


def test_a_clean_write_then_a_failed_call_still_disqualifies(repo: Path) -> None:
    events = _write_tool_events() + [
        {FORGE_EVENT_KEY: "tool_result", "name": "shell.exec", "text": "exit 1", "is_error": True, "access": "write"},
    ]
    result, _ = _dispatch(repo, events)

    assert result.ok is False, result.reason


def test_no_answer_and_no_change_is_still_nothing_to_review(repo: Path) -> None:
    result, _ = _dispatch(repo, _write_tool_events(), final_text="")

    assert result.ok is False
    assert "no answer" in result.reason.lower()


def test_a_read_only_run_keeps_its_own_wording_without_the_note(repo: Path) -> None:
    events = [
        {FORGE_EVENT_KEY: "tool", "name": "fs.read_file", "text": "read app.py", "access": "read"},
        {FORGE_EVENT_KEY: "tool_result", "name": "fs.read_file", "text": "VALUE = 1", "access": "read"},
    ]
    result, captured = _dispatch(repo, events)

    assert result.ok is True, result.reason
    assert not [e for e in captured if NEUTRAL_NOTE in str(e.get("text") or "")], (
        "a read-only run has no write-capable tool to note"
    )
