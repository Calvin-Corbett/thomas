"""A copy that takes dev in hands in only its team's change.

On 2026-09-27 the ChatGPT sign-in project (thomas-0501acb65578) ran out of repair rounds without its change ever
reaching a card. Two faults, one after the other:

* The server's merge of dev into the copy failed: "Entry 'plans/thomas/WORKBOARD.md' not uptodate. Cannot merge."
  A hand-in keeps Thomas's board and problem logs out of the team's change by putting them back in the index only,
  so on disk they differ from it, and git will not move a file whose disk copy differs. Dev changes the board with
  nearly every landing. The board on disk is now put back first: a copy's board is never handed in.
* The round then told the team to run ``git merge <dev>`` itself, and it did. That moved the copy onto dev but not
  the base its hand-in is diffed against, so every later hand-in carried all of dev's commits since the copy was
  made (93 files) and could never apply. A copy whose HEAD already holds a newer commit of dev now stands on it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.server import green_checkout, green_rebase

BOARD = "plans/thomas/WORKBOARD.md"
BASE = {"a.txt": "one\ntwo\nthree\n", BOARD: "# Board\n- task one\n", "plans/thomas/problems/p1/PROBLEM.md": "p1\n"}
TEAM_A = "one\ntwo from the team\nthree\n"


def _git(cwd: Path, *args: str) -> str:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _in_green(green: green_checkout.Green, *args: str) -> str:
    return _git(green.work, f"--git-dir={green.git_dir}", f"--work-tree={green.work}", *args)


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for Thomas's own checkout, on dev, with a board and a problem log like the real one."""
    root = tmp_path / "blue"
    _write(root, dict(BASE))
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(root, *args)
    for folder in (tmp_path / "green" / "work", tmp_path / "green" / "git"):  # a green root that exists gets no ACLs
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green"))
    return root


def _move_dev(blue: Path, files: dict[str, str]) -> str:
    _write(blue, files)
    _git(blue, "add", "-A")
    _git(blue, "commit", "-q", "-m", "another landing")
    return _git(blue, "rev-parse", "dev")


def _changed(patch: str) -> list[str]:
    return sorted(line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git a/"))


def test_dev_merges_in_when_the_copy_and_dev_both_changed_the_board(blue: Path) -> None:
    green = green_checkout.create_green(blue=blue, execution_id="thomas-board0001")
    _write(green.work, {"a.txt": TEAM_A, BOARD: "# Board\n- task one\n- the copy's own claim\n"})
    _write(green.work, {"plans/thomas/problems/p2/PROBLEM.md": "logged in the copy\n"})
    dev = _move_dev(blue, {BOARD: "# Board\n- task one\n- a landing's claim\n", "dev.txt": "from dev\n"})

    merged = green_rebase.rebase_onto_dev(green.execution_id)

    assert (merged.ok, merged.failed) == (True, ""), merged
    assert _in_green(green, "rev-parse", "HEAD") == dev
    found = green_checkout.find_green(green.execution_id)
    assert found is not None and found.base == dev
    assert (green.work / BOARD).read_text(encoding="utf-8") == "# Board\n- task one\n- a landing's claim\n"
    assert _changed(green_checkout.green_patch(found)) == ["a.txt"], "only the team's change, never the board"


def test_a_copy_the_team_merged_dev_into_hands_in_only_its_change(blue: Path) -> None:
    green = green_checkout.create_green(blue=blue, execution_id="thomas-merged0001")
    _write(green.work, {"a.txt": TEAM_A, "send.py": "COLOUR = 'blue'\n"})
    dev = _move_dev(blue, {"dev.txt": "from dev\n", "b.txt": "b\n"})

    _in_green(green, "merge", "-q", dev)  # what a repair round tells the team to do when the server's merge failed

    found = green_checkout.find_green(green.execution_id)
    assert found is not None and found.base == dev, "the copy stands on the dev it took in"
    assert _changed(green_checkout.green_patch(found)) == ["a.txt", "send.py"]
    again = green_checkout.find_green(green.execution_id)
    assert again is not None and again.base == dev, "and the record says so"


def test_a_team_that_committed_before_merging_still_hands_in_only_its_change(blue: Path) -> None:
    green = green_checkout.create_green(blue=blue, execution_id="thomas-merged0002")
    _write(green.work, {"a.txt": TEAM_A})
    _in_green(green, "add", "-A")
    _in_green(green, "commit", "-q", "-m", "the team's work")
    dev = _move_dev(blue, {"dev.txt": "from dev\n"})

    _in_green(green, "merge", "-q", "--no-edit", dev)

    found = green_checkout.find_green(green.execution_id)
    assert found is not None and found.base == dev
    assert _changed(green_checkout.green_patch(found)) == ["a.txt"]


def test_a_copy_that_never_took_dev_in_keeps_its_base(blue: Path) -> None:
    green = green_checkout.create_green(blue=blue, execution_id="thomas-merged0003")
    _write(green.work, {"a.txt": TEAM_A})
    _in_green(green, "add", "-A")
    _in_green(green, "commit", "-q", "-m", "the team's work")
    _move_dev(blue, {"dev.txt": "from dev\n"})

    found = green_checkout.find_green(green.execution_id)

    assert found is not None and found.base == green.base, "dev moving on is not the copy taking it in"
    assert _changed(green_checkout.green_patch(found)) == ["a.txt"]
