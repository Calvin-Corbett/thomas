"""Gates that are provable no-ops for a given selection. Stdlib only.

A gate is skipped here only when it can be shown, from the selection alone, that it would exit 0. Never because it
passed before, and never from a marker anything could write: a skip that comes from a record is a way to plant a pass.

Both gates below compare ``HEAD:<file>`` with ``:<file>`` (the temporary index). The index is HEAD plus the selected
paths, so a file that is not selected reads the same on both sides:

* ``workboard_evidence`` looks at ``done`` transitions in WORKBOARD.md. Identical board text on both sides has none.
* ``problem_closure`` looks at resolving incidents. Its candidates are the board's ``problem=`` paths plus changed
  PROBLEM.md files. Identical text on both sides for every one of them is ``already-resolved-unchanged`` at best, so it
  always ``continue``s. (Measured 2026-10-07: 3.3 s of the 26 s ladder, ~55 ``git show`` processes.)

The skip turns itself back on the moment the selection touches the board, a PROBLEM.md, or a path some board entry
names as its ``problem=`` file.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

BOARD = "plans/thomas/WORKBOARD.md"
PROBLEMS_PREFIX = "plans/thomas/problems/"
_PROBLEM_FIELD = re.compile(r"problem\s*=\s*([^;\r\n]+)", re.IGNORECASE)


def _norm(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/").lower()


def problem_paths(board_text: str) -> set[str]:
    """Every path a ``problem=`` field names, read loosely on purpose: a superset only makes the gate run more often."""
    found: set[str] = set()
    for raw in _PROBLEM_FIELD.findall(board_text or ""):
        value = raw.strip()
        found.add(_norm(value))
        found.add(_norm(value.strip("`").strip()))
    found.discard("")
    return found


def provable_noops(selected_paths: Iterable[str], board_text: Callable[[], str | None]) -> dict[str, str]:
    """Gate name -> why it cannot refuse this selection. ``board_text`` reads the base's board, and only when needed."""
    selected = {_norm(path) for path in selected_paths}
    if _norm(BOARD) in selected:  # compared the way every selected path is: case-blind
        return {}
    skips = {"workboard_evidence": "the board is not selected: no done transition can differ from HEAD"}
    problem_file_selected = any(p.startswith(PROBLEMS_PREFIX) and p.endswith("/problem.md") for p in selected)
    if not problem_file_selected and not (selected & problem_paths(board_text() or "")):
        skips["problem_closure"] = "no selected path is the board, a PROBLEM.md, or a board entry's problem file"
    return skips
