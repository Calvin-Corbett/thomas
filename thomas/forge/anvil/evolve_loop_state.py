"""State model + persistence for the self-recursive evolve loop.

Split from the runner so each file stays small. Holds the loop's budget, the
durable state object, JSON persistence, and the cross-process control flag the
dashboard uses to pause a subprocess-launched loop between iterations.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evolve_supervisor import DEFAULT_POSTURE

from .evolve_planner import CATEGORIES, EvolveGoal

logger = logging.getLogger(__name__)

# Loop lifecycle states.
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_DONE = "done"
STATUS_STOPPED = "stopped"
STATUS_ERROR = "error"

EventSink = Callable[[dict[str, Any]], None]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Persistence locations
# ---------------------------------------------------------------------------


def loop_root(project_root: Path) -> Path:
    return Path(project_root) / ".thomas" / "evolve" / "loop"


def _state_path(project_root: Path) -> Path:
    return loop_root(project_root) / "state.json"


def _events_path(project_root: Path) -> Path:
    return loop_root(project_root) / "events.jsonl"


def _control_path(project_root: Path) -> Path:
    return loop_root(project_root) / "control.json"


def read_control(project_root: Path) -> dict[str, Any]:
    """Cross-process control flags (e.g. a pause request from the dashboard)."""
    path = _control_path(project_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.debug("evolve loop control file read failed (non-fatal): %s", path, exc_info=True)
        return {}


def write_control(project_root: Path, **flags: Any) -> Path:
    path = _control_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(flags, ensure_ascii=False), encoding="utf-8")
    return path


def clear_control(project_root: Path) -> None:
    path = _control_path(project_root)
    try:
        path.unlink()
    except OSError:
        logger.debug("evolve loop control file removal failed (non-fatal): %s", path, exc_info=True)


def append_event(project_root: Path, event: dict[str, Any], sink: EventSink | None) -> None:
    event = {"at": now_iso(), **event}
    try:
        path = _events_path(project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("evolve loop event log write failed (non-fatal): %s", exc)
    if sink is not None:
        try:
            sink(event)
        except Exception as exc:  # noqa: BLE001 - a bad sink must not kill the loop
            logger.debug("evolve loop event sink raised (non-fatal): %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Budget + state
# ---------------------------------------------------------------------------


@dataclass
class LoopBudget:
    """Bounds on a single loop run. 0 means 'unbounded on this axis'."""

    max_iterations: int = 6
    max_promotions: int = 4
    max_wall_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_iterations": int(self.max_iterations),
            "max_promotions": int(self.max_promotions),
            "max_wall_seconds": float(self.max_wall_seconds),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> LoopBudget:
        payload = dict(payload or {})
        return cls(
            max_iterations=int(payload.get("max_iterations") or 0),
            max_promotions=int(payload.get("max_promotions") or 0),
            max_wall_seconds=float(payload.get("max_wall_seconds") or 0.0),
        )


@dataclass
class EvolveLoopState:
    status: str = STATUS_IDLE
    posture: str = DEFAULT_POSTURE.value
    focus: str = ""
    categories: list[str] = field(default_factory=lambda: list(CATEGORIES))
    iteration: int = 0
    budget: LoopBudget = field(default_factory=LoopBudget)
    counters: dict[str, int] = field(
        default_factory=lambda: {"promoted": 0, "held": 0, "rejected": 0, "failed": 0, "planned": 0}
    )
    current: dict[str, Any] | None = None
    backlog: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    last_error: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "posture": self.posture,
            "focus": self.focus,
            "categories": list(self.categories),
            "iteration": self.iteration,
            "budget": self.budget.to_dict(),
            "counters": dict(self.counters),
            "current": self.current,
            "backlog": list(self.backlog),
            "history": list(self.history),
            "pending_approvals": list(self.pending_approvals),
            "signals": dict(self.signals),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "last_error": self.last_error,
            "run_id": self.run_id,
            "pending_count": len([p for p in self.pending_approvals if p.get("status") == "pending"]),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvolveLoopState:
        payload = dict(payload or {})
        state = cls(
            status=str(payload.get("status") or STATUS_IDLE),
            posture=str(payload.get("posture") or DEFAULT_POSTURE.value),
            focus=str(payload.get("focus") or ""),
            categories=[str(c) for c in (payload.get("categories") or list(CATEGORIES))],
            iteration=int(payload.get("iteration") or 0),
            budget=LoopBudget.from_dict(payload.get("budget")),
            current=payload.get("current"),
            backlog=list(payload.get("backlog") or []),
            history=list(payload.get("history") or []),
            pending_approvals=list(payload.get("pending_approvals") or []),
            signals=dict(payload.get("signals") or {}),
            started_at=str(payload.get("started_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            last_error=str(payload.get("last_error") or ""),
            run_id=str(payload.get("run_id") or ""),
        )
        counters = payload.get("counters")
        if isinstance(counters, dict):
            state.counters.update({k: int(v) for k, v in counters.items() if isinstance(v, (int, float))})
        return state


def load_loop_state(project_root: Path) -> EvolveLoopState:
    path = _state_path(project_root)
    if not path.exists():
        return EvolveLoopState()
    try:
        return EvolveLoopState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load evolve loop state, starting fresh: %s", exc)
        return EvolveLoopState()


def save_loop_state(project_root: Path, state: EvolveLoopState) -> Path:
    state.updated_at = now_iso()
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Record builders (shaping a goal + finished session into persisted records)
# ---------------------------------------------------------------------------


def make_pending_approval(goal: EvolveGoal, session: dict[str, Any], reason: str) -> dict[str, Any]:
    delta = dict(session.get("delta") or {})
    return {
        "id": f"hold-{uuid.uuid4().hex[:8]}",
        "goal": goal.to_dict(),
        "session_id": str(session.get("session_id") or ""),
        "title": goal.title,
        "category": goal.category,
        "risk_tier": goal.risk_tier,
        "changed_count": int(delta.get("changed_count") or 0),
        "changed_files": list(delta.get("changed_files") or [])[:40],
        "diff_path": str(session.get("diff_path") or ""),
        "rationale": goal.rationale,
        "reason": reason,
        "created_at": now_iso(),
        "status": "pending",
    }


def history_item(
    *,
    iteration: int,
    goal: EvolveGoal,
    session: dict[str, Any],
    decision_dict: dict[str, Any],
    promoted: bool,
) -> dict[str, Any]:
    delta = dict(session.get("delta") or {})
    return {
        "iteration": iteration,
        "goal_id": goal.id,
        "title": goal.title,
        "category": goal.category,
        "risk_tier": goal.risk_tier,
        "session_id": str(session.get("session_id") or ""),
        "session_status": str(session.get("status") or ""),
        "changed_count": int(delta.get("changed_count") or 0),
        "decision": decision_dict,
        "promoted": bool(promoted),
        "diff_path": str(session.get("diff_path") or ""),
        "at": now_iso(),
    }
