"""Each file a Claude Code session edits is held for that session, so another session's commit cannot take its lines.

The hook (scripts/crew/brief/inflight_hook.py) runs after every Edit, Write, MultiEdit and NotebookEdit. It holds the file
for the session's own process, and tells the session at once when another live session holds the same file. A
session can hand its lines over with `inflight release --mine`. Real processes stand in for the sessions, since a hold
is a process.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.crew.brief import inflight, inflight_hook


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")
    (root / "src" / "page.html").write_text("<p>start</p>\n", encoding="utf-8")
    (root / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _session():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


@pytest.fixture
def first():
    proc = _session()
    yield proc.pid
    proc.kill()
    proc.wait()


@pytest.fixture
def second():
    proc = _session()
    yield proc.pid
    proc.kill()
    proc.wait()


def _edit(repo: Path, rel: str, text: str, session: int, monkeypatch, tool: str = "Edit") -> str:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, encoding="utf-8")
    monkeypatch.setenv("THOMAS_INFLIGHT_SESSION_PID", str(session))
    return inflight_hook.handle(
        {"tool_name": tool, "tool_input": {"file_path": str(repo / rel)}, "session_id": f"sess{session}"}
    )


def test_an_edited_file_is_held_for_the_session_that_edited_it(
    repo: Path, first: int, second: int, monkeypatch
) -> None:
    assert _edit(repo, "src/page.html", "<p>first's line</p>\n", first, monkeypatch) == ""

    held = inflight.held_by_others(repo, ["src/page.html"], me=second)

    assert [(h.path, h.pid) for h in held] == [("src/page.html", first)]
    assert "editing in Claude Code session" in held[0].why
    assert inflight.held_by_others(repo, ["src/page.html"], me=first) == []


def test_a_second_session_editing_the_same_file_is_told_who_holds_it(
    repo: Path, first: int, second: int, monkeypatch
) -> None:
    _edit(repo, "src/page.html", "<p>first's line</p>\n", first, monkeypatch)

    out = _edit(repo, "src/page.html", "<p>first's line</p>\n<p>second's line</p>\n", second, monkeypatch)

    note = json.loads(out)["hookSpecificOutput"]
    assert note["hookEventName"] == "PostToolUse"
    assert f"process {first}" in note["additionalContext"]
    assert "release --mine src/page.html" in note["additionalContext"]


def test_handing_lines_over_lets_the_other_session_commit_the_file(
    repo: Path, first: int, second: int, monkeypatch
) -> None:
    _edit(repo, "src/page.html", "<p>first's line</p>\n", first, monkeypatch)
    _edit(repo, "src/page.html", "<p>first's line</p>\n<p>second's line</p>\n", second, monkeypatch)
    assert inflight.held_by_others(repo, ["src/page.html"], me=second)

    monkeypatch.setenv("THOMAS_INFLIGHT_SESSION_PID", str(first))
    monkeypatch.chdir(repo)
    assert inflight.main(["release", "--mine", "src/page.html"]) == 0

    assert inflight.held_by_others(repo, ["src/page.html"], me=second) == []


def test_a_written_new_file_is_held_too(repo: Path, first: int, second: int, monkeypatch) -> None:
    _edit(repo, "src/new.js", "export const x = 1;\n", first, monkeypatch, tool="Write")

    assert [h.path for h in inflight.held_by_others(repo, ["src/new.js"], me=second)] == ["src/new.js"]


@pytest.mark.parametrize(
    "case",
    ["ignored file", "outside any repository", "a tool that does not edit", "no session above the hook"],
)
def test_nothing_is_held_when_there_is_nothing_to_hold(
    case: str, repo: Path, tmp_path: Path, first: int, second: int, monkeypatch
) -> None:
    if case == "ignored file":
        _edit(repo, "scratch/notes.md", "mine\n", first, monkeypatch)
    elif case == "outside any repository":
        loose = tmp_path / "loose" / "file.txt"
        loose.parent.mkdir()
        loose.write_text("x\n", encoding="utf-8")
        monkeypatch.setenv("THOMAS_INFLIGHT_SESSION_PID", str(first))
        assert inflight_hook.handle({"tool_name": "Edit", "tool_input": {"file_path": str(loose)}}) == ""
    elif case == "a tool that does not edit":
        _edit(repo, "src/page.html", "<p>changed</p>\n", first, monkeypatch, tool="Read")
    else:
        monkeypatch.setattr(inflight, "session_pid", lambda start=None: None)
        (repo / "src" / "page.html").write_text("<p>changed</p>\n", encoding="utf-8")
        inflight_hook.handle({"tool_name": "Edit", "tool_input": {"file_path": str(repo / "src" / "page.html")}})

    assert not inflight.folder(repo).is_dir() or not list(inflight.folder(repo).glob("*.json"))


def test_the_hook_never_stops_an_edit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", type("S", (), {"read": staticmethod(lambda: "{not json")})())

    assert inflight_hook.main() == 0
    assert "could not hold the edited file" in capsys.readouterr().err


def test_the_refusal_says_how_to_hand_lines_over(repo: Path, first: int, monkeypatch) -> None:
    _edit(repo, "src/page.html", "<p>first's line</p>\n", first, monkeypatch)
    monkeypatch.delenv("THOMAS_INFLIGHT_SESSION_PID")

    refused = inflight.refusal(repo, ["src/page.html"])

    assert refused and refused["blocker_class"] == "held_by_another_session"
    assert "release --mine" in refused["next_step"]
