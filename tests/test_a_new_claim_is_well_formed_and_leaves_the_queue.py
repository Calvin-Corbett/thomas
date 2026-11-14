"""A claim made without naming a role must be a valid claim, and must leave the queue.

Two defects in the claim path, both found by claude-perf from autoclaim's own
refusals on 2026-09-10, both harmless in practice only because the validator
refused to write the broken board:

1. A role derived from the board could be `worker` with no parent. Once a task
   manager is seated, `role_for` offers a newcomer `worker`, but the parent was
   never filled in, so the claim was built as `role=worker; parent=none` -- which
   the claim validator rejects. A new agent arriving at a seated board could not
   claim anything without naming its role by hand.
2. Claiming a queued task added it to Active Tasks and left it in Up For Grabs, so
   the validator refused the whole write with "task_id appears in both active tasks
   and up-for-grabs". `_remove_up_for_grabs_entry` existed for exactly this and had
   no caller anywhere.
"""

from __future__ import annotations

from pathlib import Path

import scripts.crew.workboard.claim as mod

SKELETON = """# Thomas Workboard

## Task Manager
{manager}

## Agent Claims (Active)

- agent=manager-agent; name=Manager; role=parent; parent=none; scope=docs/manager-fixture.md; task=MANAGE-1

## Active Tasks

- task_id=MANAGE-1; agent=manager-agent; scope=docs/manager-fixture.md; summary=manage; status=active

## Issues / Blockers

- none

## Up For Grabs

{grabs}

## Supporting Docs (Not Plan Sources)

- docs/PROJECT_SCOPE.md
"""

SEATED = "- agent=manager-agent; appointed_at=2026-09-10T00:00:00+00:00"
QUEUED = "- task_id=QUEUED-1; scope=docs/queued-fixture.md; summary=queued work; reported_by=manager-agent"


def _board(tmp_path: Path, *, manager: str, grabs: str) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(SKELETON.format(manager=manager, grabs=grabs), encoding="utf-8")
    return path


def _claim(board: Path, scope: str, task: str) -> int:
    return mod.run(
        [
            "--workboard",
            str(board),
            "--claim",
            "--agent",
            "new-agent",
            "--scope",
            scope,
            "--task",
            task,
            "--allow-presence-override",
            "--presence-override-reason",
            "claim fixture on a scratch board",
        ]
    )


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def _row(text: str) -> str:
    """The new agent's CLAIM row, looked up only under Agent Claims.

    An agent that takes an open seat also gets a `- agent=<id>;` row under Task
    Manager, and that section sits above Agent Claims on the board. Matching the
    first such line anywhere picked up the seat instead of the claim.
    """
    claims = _section(text, "## Agent Claims")
    return next((line for line in claims.splitlines() if line.startswith("- agent=new-agent")), "")


def test_a_worker_derived_from_the_board_names_the_manager_as_its_parent(tmp_path: Path) -> None:
    """The load-bearing case for defect 1."""
    board = _board(tmp_path, manager=SEATED, grabs="- none")
    assert _claim(board, "docs/new-fixture.md", "NEW-1") == 0
    row = _row(board.read_text(encoding="utf-8"))
    assert "role=worker" in row
    assert "parent=manager-agent" in row, f"a worker must name who it works under: {row}"


def test_claiming_a_queued_task_takes_it_out_of_up_for_grabs(tmp_path: Path) -> None:
    """The load-bearing case for defect 2."""
    board = _board(tmp_path, manager="- none", grabs=QUEUED)
    assert _claim(board, "docs/queued-fixture.md", "QUEUED-1") == 0
    text = board.read_text(encoding="utf-8")
    assert "task_id=QUEUED-1" in _section(text, "## Active Tasks")
    assert "task_id=QUEUED-1" not in _section(text, "## Up For Grabs")


def test_a_claim_for_a_task_that_was_never_queued_still_lands(tmp_path: Path) -> None:
    """The common case: nothing to remove from the queue is not a failure."""
    board = _board(tmp_path, manager="- none", grabs="- none")
    assert _claim(board, "docs/fresh-fixture.md", "FRESH-1") == 0
    assert "task_id=FRESH-1" in _section(board.read_text(encoding="utf-8"), "## Active Tasks")


def test_the_first_agent_still_takes_an_open_seat(tmp_path: Path) -> None:
    """Protection must not weaken: with no manager seated, the newcomer becomes it."""
    board = _board(tmp_path, manager="- none", grabs="- none")
    assert _claim(board, "docs/first-fixture.md", "FIRST-1") == 0
    assert "role=parent" in _row(board.read_text(encoding="utf-8"))
