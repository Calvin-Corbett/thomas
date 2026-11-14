"""Every board tool that adds an Up For Grabs task leaves `audit-24h-backstop` last.

Proves: scripts.crew.workboard.backstop_order, scripts.crew.workboard.chat_dispatch_io,
scripts.crew.workboard.claim_cleanup,
scripts.crew.workboard.claim_evidence_sweep, scripts.crew.tasks.sweep.

Before this, the tools appended after the backstop and the merge-readiness check
failed with "backstop task `audit-24h-backstop` must be the last Up For Grabs entry".
"""

from __future__ import annotations

from pathlib import Path

import scripts.crew.workboard.audit_backstop as backstop
import scripts.crew.workboard.backstop_order as order
from scripts.crew.workboard import chat_dispatch_io

BOARD = (
    "# Thomas Workboard\n\n"
    "## Agent Claims (Active)\n\n"
    "- none\n\n"
    "## Active Tasks\n\n"
    "{active}\n\n"
    "## Issues / Blockers\n\n"
    "- none\n\n"
    "## Up For Grabs\n\n"
    "{grabs}\n"
)
BACKSTOP_LINE = (
    f"- task_id={backstop.BACKSTOP_TASK_ID}; scope={backstop.BACKSTOP_SCOPE}; "
    f"summary={backstop.BACKSTOP_SUMMARY}; reported_by={backstop.BACKSTOP_REPORTED_BY}"
)


def _board(tmp_path: Path, *, active: str = "- none", grabs: str = BACKSTOP_LINE) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(BOARD.format(active=active, grabs=grabs), encoding="utf-8")
    return path


def _grab_ids(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = order.workboard_issue._find_up_for_grabs_section(lines)
    ids = []
    for idx in order.workboard_issue._bullet_indices(lines, start, end):
        _entry, fields, _err = order.workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])
        ids.append(fields["task_id"])
    return ids


def test_a_chat_task_is_queued_before_the_backstop(tmp_path: Path) -> None:
    path = _board(tmp_path)
    ok, _msg = chat_dispatch_io.queue_task(path, task_id="chat-one", summary="first")
    assert ok
    ok, _msg = chat_dispatch_io.queue_task(path, task_id="chat-two", summary="second")
    assert ok
    assert _grab_ids(path) == ["chat-one", "chat-two", backstop.BACKSTOP_TASK_ID]
    assert backstop._check(path) == (True, [])


def test_a_board_without_a_backstop_still_appends_at_the_end(tmp_path: Path) -> None:
    path = _board(tmp_path, grabs="- task_id=a; scope=thomas; summary=a; reported_by=bot")
    ok, _msg = chat_dispatch_io.queue_task(path, task_id="b", summary="b")
    assert ok
    assert _grab_ids(path) == ["a", "b"]
    assert order.keep_backstop_last(path) == (True, "backstop already last")
    assert _grab_ids(path) == ["a", "b"]


def test_moving_an_active_task_to_up_for_grabs_keeps_the_backstop_last(tmp_path: Path) -> None:
    active = "- task_id=mover; agent=someone; scope=thomas; summary=work; status=active"
    path = _board(tmp_path, active=active)
    ok, msg = order.move_task_to_up_for_grabs(path, task_id="mover", reported_by="bot", summary=None)
    assert ok, msg
    assert _grab_ids(path) == ["mover", backstop.BACKSTOP_TASK_ID]
    assert backstop._check(path) == (True, [])


def test_a_drifted_board_is_put_back_in_order(tmp_path: Path) -> None:
    grabs = BACKSTOP_LINE + "\n- task_id=late; scope=thomas; summary=late; reported_by=bot"
    path = _board(tmp_path, grabs=grabs)
    assert backstop._check(path)[0] is False
    ok, msg = order.keep_backstop_last(path)
    assert ok, msg
    assert _grab_ids(path) == ["late", backstop.BACKSTOP_TASK_ID]
    assert backstop._check(path) == (True, [])


def test_no_board_tool_moves_a_task_to_up_for_grabs_without_the_order_step() -> None:
    root = Path(__file__).resolve().parents[1] / "scripts"
    callers = []
    for path in root.rglob("*.py"):
        if not path.is_file() or path.name in {"issue.py", "backstop_order.py"}:
            continue
        if "workboard_issue.move_task_to_up_for_grabs(" in path.read_text(encoding="utf-8", errors="replace"):
            callers.append(path.name)
    assert callers == []
