"""Every project has a task manager, and the first agent to arrive becomes it.

Thomas already has the assignment layer: `scripts/crew/tasks/manager.py` can sync
the board, sweep inactive agents, auto-start tasks and dispatch idle agents, and
it is wired into bootstrap, the startup router and the presence monitor. It has
never run. Three breaks, each sufficient alone:

  1. `ensure_praxis` creates a board and appoints nobody.
  2. Every agent arrives `solo` (measured: three live agents, all solo, zero
     claims by the manager identity).
  3. `bootstrap_claim.py` only dispatches when `role == "parent"`.

So agents race for claims instead of being assigned work, and that race is what
deadlocks a shared checkout.

These tests cover the first two breaks at their source. The load-bearing case is
`test_a_missing_manager_is_resolved_by_appointing_one`: a gate whose failure mode
is refusal would deadlock the first agent in every new project, which is the
exact shape of bug this design removes.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core.praxis_scaffold import (
    appoint_manager,
    ensure_praxis,
    manager_of,
    role_for,
    vacate_manager,
)


def _board(tmp_path: Path, agent: str | None = None) -> Path:
    return ensure_praxis(tmp_path, agent=agent).board


def test_a_scaffolded_project_appoints_its_first_agent(tmp_path: Path):
    board = _board(tmp_path, agent="first-agent")
    assert manager_of(board) == "first-agent"


def test_a_second_agent_does_not_displace_the_first(tmp_path: Path):
    board = _board(tmp_path, agent="first-agent")
    ensure_praxis(tmp_path, agent="second-agent")
    assert manager_of(board) == "first-agent", "appointment is idempotent, like the board itself"


def test_the_first_agent_is_parent_and_later_ones_are_workers(tmp_path: Path):
    """This is what makes dispatch fire: `do_dispatch` requires role == parent."""
    board = _board(tmp_path, agent="first-agent")
    assert role_for(board, "first-agent") == "parent"
    assert role_for(board, "second-agent") == "worker"


def test_a_missing_manager_is_resolved_by_appointing_one(tmp_path: Path):
    """The gate must never be able to block all work.

    Built the other way round -- refuse until a manager appears -- it would
    deadlock the first agent in every new project.
    """
    board = _board(tmp_path)
    assert manager_of(board) == "", "a board with no agent has no manager yet"
    assert role_for(board, "lone-agent") == "parent", "the lone agent becomes it, rather than being refused"
    assert appoint_manager(board, "lone-agent") == "lone-agent"
    assert manager_of(board) == "lone-agent"


def test_scaffolding_without_an_agent_still_works(tmp_path: Path):
    """ensure_praxis is called from paths that have no agent to appoint."""
    paths = ensure_praxis(tmp_path)
    assert paths.board.exists()
    assert manager_of(paths.board) == ""


def test_an_existing_board_is_never_rewritten(tmp_path: Path):
    """The scaffold's contract: never touch a board that already exists."""
    board = _board(tmp_path, agent="first-agent")
    board.write_text(board.read_text(encoding="utf-8") + "\nhand written line\n", encoding="utf-8")
    ensure_praxis(tmp_path, agent="second-agent")
    assert "hand written line" in board.read_text(encoding="utf-8")
    assert manager_of(board) == "first-agent"


def test_a_vacated_position_is_taken_by_the_next_arrival(tmp_path: Path):
    """Handover: the sweep vacates a dead manager, the next agent becomes it."""
    board = _board(tmp_path, agent="first-agent")
    assert vacate_manager(board, "first-agent") is True
    assert manager_of(board) == ""
    assert role_for(board, "second-agent") == "parent"
    assert appoint_manager(board, "second-agent") == "second-agent"


def test_only_the_holder_can_be_vacated(tmp_path: Path):
    """One agent must not be able to unseat another by asking."""
    board = _board(tmp_path, agent="first-agent")
    assert vacate_manager(board, "someone-else") is False
    assert manager_of(board) == "first-agent"


def test_appointment_survives_a_board_that_predates_the_section(tmp_path: Path):
    """Existing projects have boards with no Task Manager section at all."""
    board = _board(tmp_path)
    text = board.read_text(encoding="utf-8")
    text = text.replace("## Task Manager\n- none\n\n", "")
    board.write_text(text, encoding="utf-8")
    assert "## Task Manager" not in board.read_text(encoding="utf-8")
    assert appoint_manager(board, "late-comer") == "late-comer"
    assert manager_of(board) == "late-comer"
