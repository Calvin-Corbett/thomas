"""A copy holding a link that the hand-in would read through is refused, and the refusal names the link.

The hand-in staged a copy's whole change with ``git add --all`` (``green_checkout._stage_everything``), and git on
Windows follows a directory junction as if it were an ordinary folder. Measured on dev 144b1954 with git
2.52.0.windows.1: a junction a Build team made in its copy, pointing at a folder outside it, put that folder's
file into the hand-in patch as a new file, and wrote its content into the copy's git folder, which the cage's
account may read. The same happened with a junction inside a tracked file that had been turned into a folder.
Now a copy whose work folder, or a path the hand-in would read or did stage, is or passes through a symbolic link,
a junction or any other reparse point is refused, before git add stages anything and again in what it staged.
The refusal names the link, never a file behind it.

Not covered here: a process still running in the copy can make and remove a link between those checks and git add,
so content from behind it can reach green's git folder; see the ask's known limits.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server import green_checkout, precard

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are a Windows reparse point")
SECRET = b"owner secret, never the team's\n"


def _git(cwd: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blue = tmp_path / "blue"
    for rel, data in {"pkg/a.py": b"A = 1\n", "docs/old/notes.md": b"old notes\n"}.items():
        (blue / rel).parent.mkdir(parents=True, exist_ok=True)
        (blue / rel).write_bytes(data)
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)
    greens = tmp_path / "green"
    for folder in (greens / "work", greens / "git"):
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "owner-secret.txt").write_bytes(SECRET)
    green = green_checkout.create_green(blue=blue, execution_id="thomas-linked")
    return SimpleNamespace(green=green, outside=outside, tmp=tmp_path)


def _junction(link: Path, target: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))
    assert link.is_junction() and not link.is_symlink(), "a real junction, which is not a symbolic link"


def _secret_read_into(green: green_checkout.Green, tmp: Path) -> bool:
    """Whether the outside file's content reached green's git folder, which the cage's account may read."""
    hashed = subprocess.run(["git", "hash-object", "--stdin"], cwd=tmp, input=SECRET, capture_output=True, check=True)
    found = subprocess.run(
        ["git", f"--git-dir={green.git_dir}", "cat-file", "-e", hashed.stdout.decode().strip()], capture_output=True
    )
    return found.returncode == 0


@windows_only
@pytest.mark.parametrize("where", ["linked", "pkg/deeper/linked"])
def test_a_junction_inside_the_copy_is_refused_and_nothing_behind_it_is_read(
    world: SimpleNamespace, where: str
) -> None:
    link = world.green.work / where
    link.parent.mkdir(parents=True, exist_ok=True)
    _junction(link, world.outside)
    (world.green.work / "pkg" / "a.py").write_bytes(b"A = 2\n")  # the team's real change beside it

    for read in (green_checkout.green_patch, green_checkout.changed_paths, green_checkout.green_tree):
        with pytest.raises(green_checkout.GreenUnavailable) as refused:
            read(world.green)
        said = str(refused.value)
        assert f": {where} is or passes through a link" in said and "owner-secret" not in said, said

    assert not _secret_read_into(world.green, world.tmp)
    assert link.is_junction() and (world.outside / "owner-secret.txt").read_bytes() == SECRET


@windows_only
def test_a_tracked_file_that_became_a_folder_holding_a_junction_is_refused(world: SimpleNamespace) -> None:
    tracked = world.green.work / "pkg" / "a.py"
    tracked.unlink()
    tracked.mkdir()
    _junction(tracked / "inner", world.outside)

    with pytest.raises(green_checkout.GreenUnavailable) as refused:
        green_checkout.green_patch(world.green)

    said = str(refused.value)
    assert ": pkg/a.py/inner is or passes through a link" in said and "owner-secret" not in said, said
    assert not _secret_read_into(world.green, world.tmp)


@windows_only
def test_a_file_that_appears_behind_a_junction_before_git_add_is_refused_and_left_unstaged(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    (world.outside / "owner-secret.txt").unlink()  # the junction leads to an empty folder when the copy is listed
    _junction(world.green.work / "linked", world.outside)
    (world.green.work / "pkg" / "a.py").write_bytes(b"A = 2\n")
    real_git = green_checkout._git

    def a_file_appears_behind_the_junction_first(
        green: green_checkout.Green, *args: str
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("add",):
            (world.outside / "owner-secret.txt").write_bytes(SECRET)
        return real_git(green, *args)

    monkeypatch.setattr(green_checkout, "_git", a_file_appears_behind_the_junction_first)

    with pytest.raises(green_checkout.GreenUnavailable) as refused:
        green_checkout.green_patch(world.green)

    said = str(refused.value)
    assert ": linked is or passes through a link" in said and "owner-secret" not in said, said
    green = world.green
    staged = subprocess.run(
        ["git", f"--git-dir={green.git_dir}", f"--work-tree={green.work}", "ls-files", "--cached", "-z"],
        capture_output=True,
        check=True,
    )
    assert b"linked/" not in staged.stdout and b"pkg/a.py" in staged.stdout, staged.stdout


@windows_only
def test_a_work_folder_that_is_itself_a_junction_is_refused(world: SimpleNamespace) -> None:
    work = world.green.work
    work.rename(work.with_name(work.name + "-moved"))
    _junction(work, world.outside)

    with pytest.raises(green_checkout.GreenUnavailable) as refused:
        green_checkout.green_patch(world.green)

    assert str(work) in str(refused.value) and "link" in str(refused.value)
    assert not _secret_read_into(world.green, world.tmp)


@windows_only
def test_the_check_before_the_card_names_the_link_and_hands_in_nothing(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(precard.CHECK_ENV, "off")
    _junction(world.green.work / "linked", world.outside)

    checked = precard.check_before_card(world.green.execution_id)

    assert checked.state == precard.UNAVAILABLE and checked.patch == "" and checked.patch_sha256 == ""
    assert "linked is or passes through a link" in checked.line, checked.line
    assert "owner-secret" not in checked.line and "owner secret" not in checked.line, checked.line
    assert not _secret_read_into(world.green, world.tmp)


def test_a_plain_change_still_hands_in(world: SimpleNamespace) -> None:
    work = world.green.work
    (work / "pkg" / "a.py").write_bytes(b"A = 2\n")
    (work / "pkg" / "sub").mkdir()
    (work / "pkg" / "sub" / "b.py").write_bytes(b"B = 1\n")
    shutil.rmtree(work / "docs")  # a whole tracked folder taken out: its file is a deletion, with no folder left

    patch = green_checkout.green_patch(world.green)

    assert green_checkout.changed_status(world.green) == [
        ("D", "docs/old/notes.md"),
        ("M", "pkg/a.py"),
        ("A", "pkg/sub/b.py"),
    ]
    assert "+A = 2" in patch and "+B = 1" in patch and "deleted file mode" in patch
