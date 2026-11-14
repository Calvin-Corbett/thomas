"""Strap Praxis into a project: its own board and coordination dir, made on first use.

A fresh project has no ``plans/<name>/WORKBOARD.md`` and no
``runtime/coordination/``. Before this, the dispatcher logged an error and ran
the task with no coordination at all. Now the first task in a project sets the
environment up, the way ``git init`` does, and never touches a board that
already exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BOARD_TEMPLATE = """# {name} Workboard (Active)

Last updated: {today}

## Task Manager
- none

## Execution Status
- Active task plans:

## Problem Traceability

## Agent Claims

## Active Tasks

## Up For Grabs
- none

## Issues / Blockers

## Task Problems

## Agent Message Traffic

## Task Plans

## Inactive Agents
"""


@dataclass(frozen=True)
class PraxisPaths:
    root: Path
    name: str
    board: Path
    coordination_dir: Path


def project_name(project_root: Path) -> str:
    return (Path(project_root).resolve().name or "project").lower()


def board_path(project_root: Path) -> Path:
    root = Path(project_root).resolve()
    return root / "plans" / project_name(root) / "WORKBOARD.md"


def coordination_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / "runtime" / "coordination"


MANAGER_SECTION = "## Task Manager"
_MANAGER_ROW = re.compile(r"^- agent=(?P<agent>[^;]+);", re.MULTILINE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _section_bounds(text: str) -> tuple[int, int] | None:
    start = text.find(MANAGER_SECTION)
    if start < 0:
        return None
    body = start + len(MANAGER_SECTION)
    nxt = text.find("\n## ", body)
    return body, (nxt if nxt >= 0 else len(text))


def manager_of(board: Path) -> str:
    """Which agent holds the task-manager position, or empty if the seat is open."""

    try:
        text = Path(board).read_text(encoding="utf-8")
    except OSError:
        return ""
    bounds = _section_bounds(text)
    if bounds is None:
        return ""
    found = _MANAGER_ROW.search(text[bounds[0] : bounds[1]])
    return found.group("agent").strip() if found else ""


def appoint_manager(board: Path, agent: str) -> str:
    """Seat ``agent`` if the position is open. Returns whoever holds it after.

    Idempotent, and it never unseats a live holder: two agents arriving at once
    both end up agreeing on whoever got there first.
    """

    agent = str(agent or "").strip()
    if not agent:
        return manager_of(board)
    held = manager_of(board)
    if held:
        return held

    path = Path(board)
    text = path.read_text(encoding="utf-8")
    row = f"- agent={agent}; appointed_at={_now_iso()}"
    bounds = _section_bounds(text)
    if bounds is None:
        # A board written before this section existed. Add it rather than
        # refusing: an old project must not become unusable.
        text = text.rstrip("\n") + f"\n\n{MANAGER_SECTION}\n{row}\n"
    else:
        text = text[: bounds[0]] + f"\n{row}\n\n" + text[bounds[1] :].lstrip("\n")
    path.write_text(text, encoding="utf-8")
    return agent


def vacate_manager(board: Path, agent: str) -> bool:
    """Open the seat, but only at the request of whoever holds it."""

    if manager_of(board) != str(agent or "").strip():
        return False
    path = Path(board)
    text = path.read_text(encoding="utf-8")
    bounds = _section_bounds(text)
    if bounds is None:
        return False
    path.write_text(text[: bounds[0]] + "\n- none\n\n" + text[bounds[1] :].lstrip("\n"), encoding="utf-8")
    return True


def role_for(board: Path, agent: str) -> str:
    """The role this agent should hold. Never refuses; an empty seat is an offer.

    This is what makes dispatch fire: `bootstrap_claim` only dispatches when the
    role is ``parent``, and every agent has been arriving ``solo``.
    """

    held = manager_of(board)
    if not held or held == str(agent or "").strip():
        return "parent"
    return "worker"


def ensure_praxis(project_root: Path, *, agent: str | None = None) -> PraxisPaths:
    """Create the board and coordination dir if absent. Idempotent; never overwrites."""

    root = Path(project_root).resolve()
    name = project_name(root)
    board = board_path(root)
    coord = coordination_dir(root)
    coord.mkdir(parents=True, exist_ok=True)
    if not board.exists():
        board.parent.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        board.write_text(BOARD_TEMPLATE.format(name=name, today=today), encoding="utf-8")
    if agent:
        appoint_manager(board, agent)
    return PraxisPaths(root=root, name=name, board=board, coordination_dir=coord)
