"""A scoped commit never takes lines another live session wrote into the same file and has not committed.

On 2026-11-06 a Build-header commit (4d1f99cfc) listed chat.html and carried a voice landing's uncommitted line with it,
because commit.py takes whole files from the working copy. A writer now holds its files (scripts/crew/brief/inflight.py)
and commit.py refuses a held file until its holder has committed it. These walk real processes, since a hold is
the process that wrote the files.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


commit = _load("agent_commit_inflight", ROOT / "scripts" / "crew" / "brief" / "commit.py")
from scripts.crew.brief import inflight  # noqa: E402

CLAIM = "agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")
    _write(root / "src" / "app.py", 'print("init")\n')
    _write(root / "src" / "other.py", 'print("init")\n')
    _write(root / "CHANGELOG.md", "# Changelog\n")
    _write(
        root / "plans" / "thomas" / "WORKBOARD.md",
        "# Workboard\n\n## Agent Claims\n- " + CLAIM + "\n\n## Active Tasks\n"
        "- task_id=TASK-1; agent=codex; scope=src; summary=Scoped commit; status=in_progress\n\n"
        "## Up For Grabs\n- none\n\n## Issues / Blockers\n- none\n",
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


@pytest.fixture
def another_session():
    """A live process that is not this test and not one of its parents: another session, as far as a hold can tell."""
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield sleeper.pid
    sleeper.kill()
    sleeper.wait()


def _commit(repo: Path, include: tuple[str, ...] = ()):
    return commit.commit_scoped_changes(
        message="feat: my change",
        agent="codex",
        include_paths=include,
        dry_run=True,
        repo_root=repo,
        workboard_path=repo / "plans" / "thomas" / "WORKBOARD.md",
        local_gate_commands=(("ok", (sys.executable, "-c", "print('gate ok')")),),
    )


def test_a_file_another_live_session_wrote_is_refused_and_says_who_and_why(repo: Path, another_session: int) -> None:
    _write(repo / "src" / "app.py", 'print("the other session\'s line")\n')
    inflight.hold(repo, ["src/app.py"], pid=another_session, why="landing the voice change", agent="claude")

    result = _commit(repo)

    assert result.ok is False
    assert result.blocker_class == "held_by_another_session"
    assert "src/app.py" in result.message
    assert "landing the voice change" in result.message
    assert str(another_session) in result.message
    assert "Wait" in (result.next_step or "")


def test_a_file_nobody_holds_still_commits_while_another_is_held(repo: Path, another_session: int) -> None:
    _write(repo / "src" / "app.py", 'print("held")\n')
    _write(repo / "src" / "other.py", 'print("mine")\n')
    inflight.hold(repo, ["src/app.py"], pid=another_session, why="landing", agent="claude")

    result = _commit(repo, include=("src/other.py",))

    assert result.ok is True, result.message
    assert result.selected_paths == ("src/other.py",)


def test_the_committers_own_hold_is_no_obstacle(repo: Path) -> None:
    _write(repo / "src" / "app.py", 'print("mine")\n')
    inflight.hold(repo, ["src/app.py"], pid=os.getpid(), why="my own landing")

    assert _commit(repo).ok is True


def test_a_hold_counts_as_the_committers_when_the_holder_is_its_parent(repo: Path) -> None:
    """A landing tool holds its files and runs commit.py as its child, which must still commit them."""
    _write(repo / "src" / "app.py", 'print("mine")\n')
    inflight.hold(repo, ["src/app.py"], pid=os.getpid(), why="my own landing")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert inflight.held_by_others(repo, ["src/app.py"], me=child.pid) == []
    finally:
        child.kill()
        child.wait()


def test_a_hold_whose_process_has_ended_counts_for_nothing_and_is_cleared(repo: Path) -> None:
    _write(repo / "src" / "app.py", 'print("left behind")\n')
    ended = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    inflight.hold(repo, ["src/app.py"], pid=ended.pid, why="a landing that crashed")
    ended.kill()
    ended.wait()

    assert _commit(repo).ok is True
    assert list(inflight.folder(repo).glob("*.json")) == []


def test_a_hold_whose_lines_are_already_committed_counts_for_nothing(repo: Path, another_session: int) -> None:
    _write(repo / "src" / "app.py", 'print("landed")\n')
    inflight.hold(repo, ["src/app.py"], pid=another_session, why="landing")
    _git(repo, "commit", "-qam", "the holder landed it")
    _write(repo / "src" / "app.py", 'print("my next change")\n')

    assert _commit(repo).ok is True


def test_release_drops_the_hold(repo: Path, another_session: int) -> None:
    _write(repo / "src" / "app.py", 'print("held")\n')
    inflight.hold(repo, ["src/app.py"], pid=another_session, why="landing")
    inflight.release(repo, pid=another_session)

    assert _commit(repo).ok is True


def test_holding_for_a_process_that_is_not_running_is_refused(repo: Path) -> None:
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()
    with pytest.raises(ValueError, match="not running"):
        inflight.hold(repo, ["src/app.py"], pid=ended.pid, why="too late")


def test_a_hold_ends_when_its_lines_were_committed_even_if_the_file_changed_again(
    repo: Path, another_session: int
) -> None:
    """On 2026-11-09 a session held thomas/server/app_lifecycle.py from 09:19. It committed those lines at 10:00 and
    the file was committed again at 11:16. The hold was compared with the newest commit only, so it read "not committed
    yet" for the rest of the day, and a commit that only deleted eight lines elsewhere was refused for it."""
    _write(repo / "src" / "app.py", 'print("the holder wrote this")\n')
    inflight.hold(repo, ["src/app.py"], pid=another_session, why="editing")
    _git(repo, "add", "src/app.py")
    _git(repo, "commit", "-q", "-m", "the holder commits what it wrote")
    _write(repo / "src" / "app.py", 'print("a later change to the same file")\n')
    _git(repo, "add", "src/app.py")
    _git(repo, "commit", "-q", "-m", "the file changes again")
    assert inflight.held_by_others(repo, ["src/app.py"]) == []


def test_a_hold_whose_lines_were_never_committed_still_holds_after_other_commits(
    repo: Path, another_session: int
) -> None:
    _write(repo / "src" / "app.py", 'print("the holder wrote this and has not committed it")\n')
    inflight.hold(repo, ["src/app.py"], pid=another_session, why="editing")
    _write(repo / "src" / "other.py", 'print("someone else commits another file")\n')
    _git(repo, "add", "src/other.py")
    _git(repo, "commit", "-q", "-m", "an unrelated commit")
    assert [held.path for held in inflight.held_by_others(repo, ["src/app.py"])] == ["src/app.py"]
