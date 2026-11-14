"""Pushing dev after a landing: clean worktree, hooks on, nothing forced, a refusal is said plainly.

Proves: scripts.crew.brief.push_dev, scripts.crew.brief.push_claim.

Every remote here is a bare repository in tmp_path. Nothing touches a real remote or a real branch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from scripts.crew.brief import push_claim, push_dev


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def pair(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(tmp_path, "init", "-q", "-b", "dev", str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    git(work, "remote", "add", "dev-origin", str(remote))
    (work / "a.txt").write_text("1\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "first")
    return work, remote


def hook(work: Path, body: str) -> None:
    path = work / ".git" / "hooks" / "pre-push"
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


def push(work: Path) -> push_dev.PushResult:
    return push_dev.push_landed(work, agent="claude", base_env={"PATH": os.environ["PATH"]})


def test_the_tip_is_pushed_and_the_worktree_is_gone(pair) -> None:
    work, remote = pair
    result = push(work)
    assert result.status == "pushed" and result.pushed
    assert git(remote, "rev-parse", "dev") == git(work, "rev-parse", "dev")
    assert git(work, "worktree", "list").count("\n") == 0


def test_the_hooks_run_in_a_clean_worktree_with_the_push_claim_env(pair, tmp_path) -> None:
    work, _remote = pair
    seen = tmp_path / "seen.txt"
    hook(work, f'pwd > "{seen.as_posix()}"; echo "$AGENT_ID|$THOMAS_WORKBOARD_SCOPE_FALLBACK" >> "{seen.as_posix()}"')
    (work / "dirty.txt").write_text("uncommitted\n")
    assert push(work).status == "pushed"
    lines = seen.read_text().splitlines()
    assert Path(lines[0]).resolve() != work.resolve()
    assert not (Path(lines[0]) / "dirty.txt").exists()
    assert lines[1] == f"claude|{push_claim.PUSH_SCOPE}"


def test_a_failing_hook_stops_the_push_and_says_so(pair) -> None:
    work, remote = pair
    hook(work, 'echo "claim gate said no" >&2; exit 1')
    result = push(work)
    assert result.status == "blocked" and not result.pushed and result.exit_code == 1
    assert "claim gate said no" in result.message
    assert git(remote, "branch", "--list") == ""


def test_a_remote_that_refuses_the_branch_is_left_alone(pair) -> None:
    work, remote = pair
    refuse = remote / "hooks" / "pre-receive"
    refuse.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n", encoding="utf-8", newline="\n")
    refuse.chmod(0o755)
    result = push(work)
    assert result.status == "refused" and not result.pushed and result.exit_code == 0
    assert "refused" in result.message
    assert git(remote, "branch", "--list") == ""
    assert git(work, "worktree", "list").count("\n") == 0


def test_a_branch_already_on_the_remote_starts_no_worktree(pair, monkeypatch) -> None:
    work, _remote = pair
    assert push(work).status == "pushed"
    git(work, "fetch", "-q", "dev-origin")
    calls: list[tuple] = []
    real = push_dev._git

    def spy(root, *args, **kw):
        calls.append(args)
        return real(root, *args, **kw)

    monkeypatch.setattr(push_dev, "_git", spy)
    assert push(work).status == "up_to_date"
    assert not any(a[:2] == ("worktree", "add") for a in calls)


def test_no_remote_pushes_nothing(pair) -> None:
    work, _remote = pair
    git(work, "remote", "remove", "dev-origin")
    assert push(work).status == "no_remote"


def test_a_push_is_never_forced_and_never_skips_the_hooks(pair, monkeypatch) -> None:
    work, _remote = pair
    pushes: list[tuple] = []
    real = push_dev._git

    def spy(root, *args, **kw):
        if args and args[0] == "push":
            pushes.append(args)
        return real(root, *args, **kw)

    monkeypatch.setattr(push_dev, "_git", spy)
    push(work)
    assert len(pushes) == 1
    flat = " ".join(pushes[0])
    for banned in ("--no-verify", "--force", "-f", "--force-with-lease", "--delete"):
        assert banned not in pushes[0], flat


def test_a_second_push_while_one_runs_does_nothing(pair) -> None:
    work, _remote = pair
    lock = push_dev._take_lock(work)
    assert lock is not None
    try:
        assert push(work).status == "busy"
    finally:
        lock.unlink()
