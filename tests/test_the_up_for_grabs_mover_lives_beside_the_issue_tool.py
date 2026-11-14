"""The Up For Grabs mover lives in its own module so issue.py can be edited, and still behaves the same.

Proves scripts.crew.workboard.issue and scripts.crew.workboard.issue_up_for_grabs: issue.py is under the 800-line soft
limit that refuses every edit to a file not on the monolith baseline, ``issue.move_task_to_up_for_grabs`` forwards to the
module, it moves the task, and it writes through issue._validate_and_write so a stand-in for that function takes effect.
"""

from __future__ import annotations

from pathlib import Path

import scripts.crew.workboard.issue as issue

BOARD = (
    "# Thomas Workboard\n\n## Agent Claims (Active)\n\n- agent=someone; scope=thomas; task=work\n\n"
    "## Active Tasks\n\n- task_id=mover; agent=someone; scope=thomas; summary=work; status=active\n\n"
    "## Issues / Blockers\n\n- none\n\n## Up For Grabs\n\n- none\n"
)


def test_issue_py_is_under_the_soft_limit() -> None:
    lines = Path(issue.__file__).read_text(encoding="utf-8").count("\n")
    assert lines <= 800, f"issue.py is {lines} lines; the monolith guard refuses an edit to it above 800"


def test_the_mover_moves_the_task_and_drops_the_claim_nothing_else_holds(tmp_path: Path) -> None:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(BOARD, encoding="utf-8")
    ok, msg = issue.move_task_to_up_for_grabs(path, task_id="mover", reported_by="bot", summary=None)
    assert ok, msg
    text = path.read_text(encoding="utf-8")
    assert msg == "moved task `mover` to up-for-grabs"
    assert "task_id=mover; scope=thomas; summary=work; reported_by=bot" in text
    assert "agent=someone" not in text


def test_a_task_that_is_not_active_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(BOARD, encoding="utf-8")
    assert issue.move_task_to_up_for_grabs(path, task_id="ghost", reported_by="bot", summary=None) == (
        False,
        "active task `ghost` not found",
    )


def test_the_mover_writes_through_the_issue_tools_own_door(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(BOARD, encoding="utf-8")
    seen = []

    def stand_in(workboard_path, original_text, new_text, **kwargs):
        seen.append(new_text)
        return False, ["refused by the stand-in"]

    monkeypatch.setattr(issue, "_validate_and_write", stand_in)
    ok, msg = issue.move_task_to_up_for_grabs(path, task_id="mover", reported_by="bot", summary=None)
    assert not ok and "refused by the stand-in" in msg and len(seen) == 1
