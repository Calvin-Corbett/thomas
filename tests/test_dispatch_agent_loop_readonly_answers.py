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

import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil.dispatch_agent_loop import dispatch_via_agent_loop
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


def test_a_write_that_changed_nothing_is_still_a_failure(repo: Path) -> None:
    """The guard this relaxation must not remove: the agent tried to edit and
    produced nothing, which is an incomplete build, not an answer."""
    result = _dispatch(
        repo,
        [
            {FORGE_EVENT_KEY: "tool", "name": "fs.read_file", "text": "read"},
            {FORGE_EVENT_KEY: "tool", "name": "fs.write_file", "text": "write app.py"},
            _answer("I updated the file."),
        ],
    )

    assert result.ok is False, result.reason


def test_unnamed_tool_activity_stays_strict(repo: Path) -> None:
    """Only ``tool`` carries a name. Without one we cannot tell reading from
    writing, so the previous strict behaviour is kept rather than guessed at."""
    result = _dispatch(repo, [{FORGE_EVENT_KEY: "tool_result", "text": "something"}, _answer()])

    assert result.ok is False, result.reason


def test_an_unknown_tool_is_treated_as_capable_of_writing(repo: Path) -> None:
    result = _dispatch(
        repo,
        [{FORGE_EVENT_KEY: "tool", "name": "some.new_tool", "text": "?"}, _answer()],
    )

    assert result.ok is False, result.reason


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
