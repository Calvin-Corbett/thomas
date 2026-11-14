"""A Thomas project's hand-in never carries Thomas's coordination state.

Every copy runs the tooling that keeps the board: the startup router and the automatic checks write
``plans/thomas/WORKBOARD.md`` and log failures under ``plans/thomas/problems/``. The hand-in staged everything in the
copy, so on 2026-09-27 a web-size change came to your card carrying a board timestamp and two "Surface parity gate"
failure entries the copy's own checks had logged, none of it the team's work; landing it would put one copy's
bookkeeping over the live board. Those paths are left out of every hand-in; the copy keeps them on disk.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.server import green_checkout

BOARD = "plans/thomas/WORKBOARD.md"
PROBLEM = "plans/thomas/problems/audit/PROBLEM.md"


def _git(cwd: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> green_checkout.Green:
    blue = tmp_path / "blue"
    for rel, text in {"pkg/a.py": "A = 1\n", BOARD: "board\n", PROBLEM: "# audit\n"}.items():
        (blue / rel).parent.mkdir(parents=True, exist_ok=True)
        (blue / rel).write_text(text, encoding="utf-8")
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)
    greens = tmp_path / "green"
    for folder in (greens / "work", greens / "git"):
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    return green_checkout.create_green(blue=blue, execution_id="thomas-board")


def test_the_board_and_the_problem_logs_stay_out_of_the_hand_in(green: green_checkout.Green) -> None:
    (green.work / "pkg" / "a.py").write_text("A = 2\n", encoding="utf-8")  # the team's change
    (green.work / BOARD).write_text("board, touched by the startup router\n", encoding="utf-8")
    (green.work / PROBLEM).write_text("# audit\n### a failure the copy's checks logged\n", encoding="utf-8")
    new_log = green.work / "plans" / "thomas" / "problems" / "fresh" / "PROBLEM.md"
    new_log.parent.mkdir(parents=True)
    new_log.write_text("# a problem the copy opened\n", encoding="utf-8")

    assert green_checkout.changed_paths(green) == ["pkg/a.py"]
    patch = green_checkout.green_patch(green)
    assert "pkg/a.py" in patch and "plans/thomas" not in patch
    assert (green.work / BOARD).read_text(encoding="utf-8").startswith("board, touched")  # the copy keeps it


def test_a_copy_that_changed_only_the_board_hands_in_nothing(green: green_checkout.Green) -> None:
    (green.work / BOARD).write_text("board, touched\n", encoding="utf-8")

    assert green_checkout.changed_paths(green) == []
