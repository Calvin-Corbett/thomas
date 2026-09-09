"""Strap Praxis into a project: its own board and coordination dir, made on first use.

A fresh project has no ``plans/<name>/WORKBOARD.md`` and no
``runtime/coordination/``. Before this, the dispatcher logged an error and ran
the task with no coordination at all. Now the first task in a project sets the
environment up, the way ``git init`` does, and never touches a board that
already exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BOARD_TEMPLATE = """# {name} Workboard (Active)

Last updated: {today}

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


def ensure_praxis(project_root: Path) -> PraxisPaths:
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
    return PraxisPaths(root=root, name=name, board=board, coordination_dir=coord)
