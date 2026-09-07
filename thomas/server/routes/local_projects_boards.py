"""The user-level index over every Praxis board.

Each registry entry - a repo, a generated deliverable - owns the board at its
``root_path``; the user's own board in the data dir sits at the head. "What is
Thomas doing for me" reads this index and each board, not one shared board.
Read-only: a board is made on a project's first task, never by listing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.core.praxis_scaffold import board_path
from thomas.core.project_root import user_praxis_root


def _board_entry(root: Path) -> dict[str, Any]:
    board = board_path(root)
    return {"root_path": str(root), "board": str(board), "exists": board.is_file()}


def boards_index(projects: list[dict[str, Any]], *, user_root: Path | None = None) -> dict[str, Any]:
    root = Path(user_root) if user_root is not None else user_praxis_root()
    rows: list[dict[str, Any]] = []
    for project in projects:
        raw = str(project.get("root_path") or "").strip()
        if not raw:
            continue
        rows.append(
            {
                "id": str(project.get("id") or ""),
                "name": str(project.get("name") or ""),
                "kind": str(project.get("kind") or ""),
                **_board_entry(Path(raw)),
            }
        )
    return {"user_board": _board_entry(root), "projects": rows}
