"""Which Build run each conversation owns through a landed-code drain. Light, so a launch can record its own start."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

APP_DRAIN_RUNS = web.AppKey("landed_code_drain_runs", dict)


@dataclass(frozen=True)
class DrainRun:
    project_root: Path
    run_id: str
    request_id: str
    proc: Any = None


def track_start(app: Any, session: dict[str, Any]) -> None:
    """Replace pending ownership at launch, including starts admitted before a drain."""
    cid = str(session.get("conversation_id") or "")
    pending = app.get(APP_DRAIN_RUNS)
    if pending is not None:
        pending.pop(cid, None)
    if app.get("landed_code_drain") and cid and session.get("project_root") and session.get("run_id"):
        app.setdefault(APP_DRAIN_RUNS, {})[cid] = DrainRun(
            Path(session["project_root"]),
            str(session["run_id"]),
            str(session.get("request_id") or ""),
            session.get("proc"),
        )
