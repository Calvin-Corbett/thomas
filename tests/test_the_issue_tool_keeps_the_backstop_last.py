"""The workboard issue tool leaves `audit-24h-backstop` the last Up For Grabs entry, whichever way a task is added.

Proves scripts.crew.workboard.issue and scripts.crew.workboard.issue_up_for_grabs (the mover and _validate_and_write, the
one door every board write goes through, brainstorm --dispatch included), checked against
scripts.crew.workboard.audit_backstop.

Before this, the command line moved a task in after the backstop and the merge-readiness check failed with "backstop
task `audit-24h-backstop` must be the last Up For Grabs entry".
"""

from __future__ import annotations

from pathlib import Path

import scripts.crew.workboard.audit_backstop as backstop
import scripts.crew.workboard.issue as issue
import scripts.crew.workboard.issue_up_for_grabs as issue_up_for_grabs

BOARD = (
    "# Thomas Workboard\n\n## Agent Claims (Active)\n\n- none\n\n## Active Tasks\n\n{active}\n\n"
    "## Issues / Blockers\n\n- none\n\n## Up For Grabs\n\n{grabs}\n"
)
BACKSTOP_LINE = (
    f"- task_id={backstop.BACKSTOP_TASK_ID}; scope={backstop.BACKSTOP_SCOPE}; "
    f"summary={backstop.BACKSTOP_SUMMARY}; reported_by={backstop.BACKSTOP_REPORTED_BY}"
)
LATE = "- task_id=late; scope=thomas; summary=late; reported_by=bot"


def _board(tmp_path: Path, *, active: str = "- none", grabs: str = BACKSTOP_LINE) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(BOARD.format(active=active, grabs=grabs), encoding="utf-8")
    return path


def _grab_ids(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = issue._find_up_for_grabs_section(lines)
    ids = []
    for idx in issue._bullet_indices(lines, start, end):
        _entry, fields, _err = issue._parse_up_for_grabs_line(idx + 1, lines[idx])
        ids.append(fields["task_id"])
    return ids


def test_the_issue_command_moves_a_task_in_before_the_backstop(tmp_path: Path) -> None:
    active = "- task_id=mover; agent=someone; scope=thomas; summary=work; status=active"
    path = _board(tmp_path, active=active)
    ok, msg = issue.move_task_to_up_for_grabs(path, task_id="mover", reported_by="bot", summary=None)
    assert ok, msg
    assert _grab_ids(path) == ["mover", backstop.BACKSTOP_TASK_ID]
    assert backstop._check(path) == (True, [])


def test_any_board_write_that_lands_a_task_after_the_backstop_is_put_in_order(tmp_path: Path) -> None:
    path = _board(tmp_path)
    original = path.read_text(encoding="utf-8")
    ok, violations = issue._validate_and_write(path, original, original.rstrip("\n") + "\n" + LATE + "\n")
    assert ok, violations
    assert _grab_ids(path) == ["late", backstop.BACKSTOP_TASK_ID]
    assert backstop._check(path) == (True, [])


def test_a_board_without_a_backstop_is_written_as_it_was_given(tmp_path: Path) -> None:
    path = _board(tmp_path, grabs="- task_id=a; scope=thomas; summary=a; reported_by=bot")
    original = path.read_text(encoding="utf-8")
    new_text = original.rstrip("\n") + "\n" + LATE + "\n"
    ok, violations = issue._validate_and_write(path, original, new_text)
    assert ok, violations
    assert path.read_text(encoding="utf-8") == new_text
    assert _grab_ids(path) == ["a", "late"]


def test_text_with_the_backstop_already_last_is_unchanged() -> None:
    text = BOARD.format(active="- none", grabs=LATE + "\n" + BACKSTOP_LINE)
    assert issue_up_for_grabs.backstop_last(text) == text


def test_text_with_no_up_for_grabs_section_is_unchanged() -> None:
    text = "# Thomas Workboard\n\n## Active Tasks\n\n- none\n"
    assert issue_up_for_grabs.backstop_last(text) == text


def test_only_the_backstop_moves_and_the_ending_is_kept() -> None:
    other = "- task_id=second; scope=thomas; summary=second; reported_by=bot"
    text = BOARD.format(active="- none", grabs="\n".join([BACKSTOP_LINE, LATE, other]))
    moved = issue_up_for_grabs.backstop_last(text)
    assert moved == BOARD.format(active="- none", grabs="\n".join([LATE, other, BACKSTOP_LINE]))
    assert moved.endswith("\n") and not moved.endswith("\n\n")


def test_a_write_the_gate_refuses_leaves_the_board_as_it_was(tmp_path: Path) -> None:
    path = _board(tmp_path, grabs=BACKSTOP_LINE + "\n" + LATE)
    original = path.read_text(encoding="utf-8")
    broken = original.replace("## Up For Grabs", "## Up For Grabs\n\n- not a task entry at all;;;")
    ok, _violations = issue._validate_and_write(path, original, broken)
    assert not ok
    assert path.read_text(encoding="utf-8") == original
