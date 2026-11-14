"""A default claim must not be refused because the seat row names a dead agent.

Measured 2026-10-03 (ten-agent run, no model calls): `claim.py --claim` with no
`--role` was refused for every new agent with
`claim <id> references unknown parent claude-work-lanes`. The board's
`## Task Manager` row named an agent that stopped on 2026-09-11 and holds no
claim; `claim_ops` derived `role=worker; parent=<that agent>` from the row and
the claims gate requires a parent to hold an active claim of its own.

The seat row is an offer, not a liveness proof. A parent that holds no claim
must not become anyone's parent; the newcomer proceeds solo.
"""

from __future__ import annotations

from pathlib import Path

import scripts.crew.workboard.claim as mod
from scripts.crew.workboard.claim_parent import claimed_agent_keys, parent_holds_a_claim

BOARD = """# Thomas Workboard

## Task Manager
- agent=ghost-manager; appointed_at=2026-09-11T00:00:00+00:00

## Agent Claims (Active)

{claims}

## Active Tasks

{tasks}

## Issues / Blockers

- none

## Up For Grabs

- none

## Supporting Docs (Not Plan Sources)

- docs/PROJECT_SCOPE.md
"""

LIVE_CLAIM = "- agent=ghost-manager; name=Ghost; role=parent; parent=none; scope=docs/ghost.md; task=GHOST-1"
LIVE_TASK = "- task_id=GHOST-1; agent=ghost-manager; scope=docs/ghost.md; summary=ghost; status=active"


def _board(tmp_path: Path, *, claims: str = "- none", tasks: str = "- none") -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(BOARD.format(claims=claims, tasks=tasks), encoding="utf-8")
    return path


def _claim(board: Path) -> int:
    return mod.run(
        [
            "--workboard",
            str(board),
            "--claim",
            "--agent",
            "new-agent",
            "--scope",
            "docs/new-fixture.md",
            "--task",
            "NEW-1",
            "--allow-presence-override",
            "--presence-override-reason",
            "claim fixture on a scratch board",
        ]
    )


def _new_agent_row(board: Path) -> str:
    claims = board.read_text(encoding="utf-8").split("## Agent Claims", 1)[1].split("\n## ", 1)[0]
    return next((line for line in claims.splitlines() if line.startswith("- agent=new-agent")), "")


def test_a_seat_row_naming_an_agent_with_no_claim_does_not_refuse_the_claim(tmp_path: Path) -> None:
    """The load-bearing case: this returned 1 before the fix."""
    board = _board(tmp_path)
    assert _claim(board) == 0
    row = _new_agent_row(board)
    assert row, "the claim must be on the board"
    assert "parent=ghost-manager" not in row, f"a dead seat holder must not become a parent: {row}"
    assert "role=solo" in row or "role=worker" not in row, row


def test_a_seat_holder_with_a_live_claim_is_still_the_parent(tmp_path: Path) -> None:
    """The fix must not turn every newcomer solo: a live manager still gets its workers."""
    board = _board(tmp_path, claims=LIVE_CLAIM, tasks=LIVE_TASK)
    assert _claim(board) == 0
    row = _new_agent_row(board)
    assert "role=worker" in row and "parent=ghost-manager" in row, row


def test_parent_holds_a_claim_reads_only_the_claims_section(tmp_path: Path) -> None:
    board = _board(tmp_path, claims=LIVE_CLAIM, tasks=LIVE_TASK)
    assert parent_holds_a_claim(board, "ghost-manager")
    assert parent_holds_a_claim(board, "GHOST-MANAGER"), "agent ids compare case-insensitively"
    assert not parent_holds_a_claim(board, "someone-else")
    # The Task Manager row and Active Tasks rows name the agent too; neither is a claim.
    no_claim = BOARD.format(claims="- none", tasks=LIVE_TASK)
    assert claimed_agent_keys(no_claim) == set()
    assert claimed_agent_keys(BOARD.format(claims=LIVE_CLAIM, tasks="- none")) == {"ghost-manager"}


def test_an_unreadable_board_answers_true_so_the_gate_decides(tmp_path: Path) -> None:
    assert parent_holds_a_claim(tmp_path / "missing.md", "ghost-manager") is True
