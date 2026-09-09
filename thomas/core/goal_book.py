"""Goals: standing requirements that live with a project until someone closes them.

You asked for goals next to the requests that come and go ("you can make
goals"). A request is one turn's contract; a goal is the item the contract
carries on every turn until it is retired. They are stored beside the project
(``.thomas/goals.json``), bounded, and read by ``acceptance_learning`` so the
judge holds each turn to them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

MAX_OPEN_GOALS = 30
MAX_GOAL_CHARS = 300
_VERSION = 1


def goals_path(workspace: str | Path) -> Path:
    return Path(workspace) / ".thomas" / "goals.json"


def _read(workspace: str | Path) -> list[dict[str, Any]]:
    path = goals_path(workspace)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    goals = data.get("goals") if isinstance(data, dict) else None
    return [g for g in (goals or []) if isinstance(g, dict) and str(g.get("text") or "").strip()]


def _write(workspace: str | Path, goals: list[dict[str, Any]]) -> None:
    path = goals_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _VERSION, "goals": goals}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def list_goals(workspace: str | Path, *, include_done: bool = False) -> list[dict[str, Any]]:
    goals = _read(workspace)
    return [dict(g) for g in goals if include_done or not g.get("done")]


def open_goals(workspace: str | Path) -> list[dict[str, Any]]:
    return list_goals(workspace, include_done=False)


def add_goal(workspace: str | Path, text: str) -> dict[str, Any]:
    """Add a goal. Raises ValueError for an empty, over-long, duplicate or over-budget goal."""
    clean = " ".join(str(text or "").split())
    if not clean:
        raise ValueError("a goal needs words")
    if len(clean) > MAX_GOAL_CHARS:
        raise ValueError(f"a goal is at most {MAX_GOAL_CHARS} characters")
    goals = _read(workspace)
    for g in goals:
        if str(g.get("text") or "").strip().lower() != clean.lower():
            continue
        if not g.get("done"):
            raise ValueError(f"that goal is already standing as {g.get('id')}")
        # Restating a retired goal reopens it under its own id: the project
        # keeps one record per goal instead of a duplicate per restatement.
        g.update({"done": False, "closed_at": None, "note": "", "reopened_at": _now()})
        _write(workspace, goals)
        return dict(g)
    if sum(1 for g in goals if not g.get("done")) >= MAX_OPEN_GOALS:
        raise ValueError(f"at most {MAX_OPEN_GOALS} open goals; close one first")
    taken = {str(g.get("id")) for g in goals}
    number = len(goals) + 1
    while f"g{number}" in taken:
        number += 1
    goal = {"id": f"g{number}", "text": clean, "created_at": _now(), "done": False, "closed_at": None, "note": ""}
    goals.append(goal)
    _write(workspace, goals)
    return dict(goal)


def close_goal(workspace: str | Path, goal_id: str, *, note: str = "") -> bool:
    """Retire a standing goal (it no longer applies). Returns False when no open goal has that id."""
    goals = _read(workspace)
    for g in goals:
        if str(g.get("id")) == str(goal_id) and not g.get("done"):
            g["done"] = True
            g["closed_at"] = _now()
            g["note"] = " ".join(str(note or "").split())[:MAX_GOAL_CHARS]
            _write(workspace, goals)
            return True
    return False


def contract_rows(workspace: str | Path) -> list[dict[str, Any]]:
    """Open goals as rows for ``build_contract(learned=...)``: judged requirements."""
    rows: list[dict[str, Any]] = []
    for g in open_goals(workspace):
        text = str(g.get("text") or "").strip()
        rows.append(
            {
                "item_id": f"goal:{g.get('id')}",
                "kind": "requirement",
                "description": (
                    f"Standing goal (stays open; check that it still holds after this turn's work): {text}"
                ),
                "source": "goal",
                "target": text,
            }
        )
    return rows
