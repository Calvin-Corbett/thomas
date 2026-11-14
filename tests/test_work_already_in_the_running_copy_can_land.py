"""Work that already sits in the running copy exactly as it would land can land; other uncommitted work still cannot.

You said on 2026-09-26: "WE HAVE A LOT OF WORK NOT ALL CONSOLIDATED. MAKE THE RATCHET MECHANISM WORK THROUGH THOMAS
AND GET EVERYTHING ON SAME PAGE". 75 changes sat uncommitted in the running copy, left by agent sessions that had
stopped. They were snapshotted to refs/salvage/uncommitted-2026-09-26/* so the ratchet can prove and land them, but
the promoter refused any change touching a file the running copy has changed (``blue_dirty``), and here the change IS
what the running copy holds, so that work could never land. A path whose file and index already hold exactly what
would land now passes (``already_in_running_copy``); a failed landing leaves those files alone when it puts dev back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

from tests.green_support import git
from tests.sleep_support import skip_sleeps
from tests.test_a_self_fix_lands_only_when_you_approve import Asker, _promoter, _submit, blue, pins  # noqa: F401


def _status(repo: Path) -> str:
    # Plain git with this machine's own line-ending settings, as the landing test beside this one does.
    return subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout


def test_work_already_in_the_running_copy_lands_and_leaves_it_clean(blue: Path, pins: Path) -> None:  # noqa: F811
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-salvage", {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "NEW = 1\n"})
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")  # the same work, uncommitted
    (blue / "thomas" / "new.py").write_text("NEW = 1\n", encoding="utf-8")  # the same new file, untracked

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert git(blue, "rev-parse", f"{outcome.commit_sha}^") == before
    assert git(blue, "show", "dev:thomas/new.py") == "NEW = 1"
    assert _status(blue) == ""


def test_different_uncommitted_work_is_still_refused_and_kept(blue: Path, pins: Path) -> None:  # noqa: F811
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-mixed", {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "NEW = 1\n"})
    (blue / "thomas" / "new.py").write_text("NEW = 1\n", encoding="utf-8")  # already there: not the problem
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 'someone else'\n", encoding="utf-8")

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "refused" and "uncommitted work in thomas/fix_me.py" in outcome.detail, outcome.detail
    assert "new.py" not in outcome.detail
    assert git(blue, "rev-parse", "dev") == before
    assert "someone else" in (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8")


def test_a_file_whose_index_or_disk_holds_something_else_is_not_already_there(blue: Path) -> None:  # noqa: F811
    target = blue / "thomas" / "fix_me.py"
    changes = [("M", "thomas/fix_me.py")]
    target.write_text("VALUE = 2\n", encoding="utf-8")
    git(blue, "add", "thomas/fix_me.py")
    lands = git(blue, "write-tree")  # the tree that would land
    assert checks.already_in_running_copy(blue, "HEAD", lands, changes) == frozenset({"thomas/fix_me.py"})

    target.write_text("VALUE = 'staged by someone'\n", encoding="utf-8")
    git(blue, "add", "thomas/fix_me.py")
    target.write_text("VALUE = 2\n", encoding="utf-8")  # the disk matches, the index holds other work
    assert checks.already_in_running_copy(blue, "HEAD", lands, changes) == frozenset()

    git(blue, "add", "thomas/fix_me.py")
    target.write_text("VALUE = 'being edited'\n", encoding="utf-8")  # the index matches, the disk does not
    assert checks.already_in_running_copy(blue, "HEAD", lands, changes) == frozenset()


@pytest.fixture
def salvaged(tmp_path: Path) -> tuple[Path, str, str]:
    """A running copy whose uncommitted work (one modified file, one untracked) is exactly the commit to land."""
    repo = tmp_path / "running"
    repo.mkdir()

    def run(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    run("init", "-q", "-b", "dev")
    for key, value in (("user.name", "T"), ("user.email", "t@t"), ("core.autocrlf", "false")):
        run("config", key, value)
    (repo / "kept.py").write_bytes(b"x = 1\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    parent = run("rev-parse", "HEAD")
    (repo / "kept.py").write_bytes(b"x = 2\n")
    (repo / "notes.md").write_bytes(b"salvaged\n")
    run("add", "-A")
    tree = run("write-tree")
    run("reset", "-q")  # back to uncommitted: kept.py modified, notes.md untracked
    return repo, parent, run("commit-tree", tree, "-p", parent, "-m", "salvage")


CHANGES = [("M", "kept.py"), ("A", "notes.md")]


def _the_update_fails(monkeypatch: pytest.MonkeyPatch, commit: str) -> None:
    """The running copy cannot be updated to *commit* (every try), so land() puts dev back."""
    real = checks.run_git

    def run_git(where, *args, **kwargs):
        if args[:2] == ("checkout", commit):
            return subprocess.CompletedProcess(["git", *args], 1, "", "error: simulated")
        return real(where, *args, **kwargs)

    monkeypatch.setattr(checks, "run_git", run_git)
    skip_sleeps(monkeypatch)


def test_a_failed_landing_keeps_the_work_that_was_already_there(salvaged, monkeypatch) -> None:
    repo, parent, commit = salvaged
    already = checks.already_in_running_copy(repo, parent, f"{commit}^{{tree}}", CHANGES)
    assert already == frozenset({"kept.py", "notes.md"})
    _the_update_fails(monkeypatch, commit)

    with pytest.raises(checks.Refused, match="dev was put back"):
        checks.land(repo, "dev", commit, parent, CHANGES, already)

    assert (repo / "kept.py").read_bytes() == b"x = 2\n" and (repo / "notes.md").read_bytes() == b"salvaged\n"


def test_without_it_the_same_failure_would_have_erased_that_work(salvaged, monkeypatch) -> None:
    """The control: the rollback puts the old version back over an edit it is not told held the change already."""
    repo, parent, commit = salvaged
    _the_update_fails(monkeypatch, commit)

    with pytest.raises(checks.Refused, match="dev was put back"):
        checks.land(repo, "dev", commit, parent, CHANGES)

    assert (repo / "kept.py").read_bytes() == b"x = 1\n", "the uncommitted edit is gone"
