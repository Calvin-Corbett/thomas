"""Where a Code run lives in app state, and how to read it.

Two things that used to sit inside ``evolve_agent_routes``: the keys the run
occupies on the aiohttp app, and the per-conversation registry that turns those
keys into "which runs are alive right now". They moved down here when the Code
handlers were split across sibling modules -- a sibling that needs to answer
for a run would otherwise have had to import the routes module back, and the
routes module imports the siblings.

The keys are plain strings rather than ``web.AppKey`` on purpose: tests seed
them directly (``app[APP_EVOLVE_AGENT_TASK] = proc``) and a typed key would
make that seeding depend on importing the exact key object.

The registry is the parallel-runs model. Each conversation gets one slot,
``{"session": ..., "drain": ...}``, and the legacy single-slot keys keep
mirroring the MOST RECENT run so consumers written before parallel runs still
work. "Alive" deliberately means running OR still recording its result: a run
whose process has exited but whose transcript is still being drained has not
finished, and treating it as finished is what let a second run start on top of
it.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from .evolve_agent_runtime import _recording_active

APP_EVOLVE_AGENT_TASK = "evolve_agent_task"
APP_EVOLVE_AGENT_DRAIN = "evolve_agent_drain"
APP_EVOLVE_AGENT_SESSION = "evolve_agent_session"
APP_EVOLVE_AGENT_CONVO = "evolve_agent_convo"
APP_EVOLVE_AGENT_SNAPSHOT = "evolve_agent_snapshot"
APP_EVOLVE_AGENT_MODEL = "evolve_agent_model"
APP_EVOLVE_AGENT_PROJECT = "evolve_agent_project"
APP_EVOLVE_AGENT_SETTINGS = "evolve_agent_settings"
APP_EVOLVE_AGENT_APPROVALS = "evolve_agent_approvals"
APP_EVOLVE_AGENT_LOCK = "evolve_agent_lock"
# Per-conversation run registry: dict[conversation_id -> {"session": ..., "drain": ...}].
APP_EVOLVE_AGENT_RUNS = "evolve_agent_runs"


def runs(app: web.Application) -> dict[str, dict[str, Any]]:
    """The live registry, created on first use."""
    registry = app.get(APP_EVOLVE_AGENT_RUNS)
    if not isinstance(registry, dict):
        registry = {}
        app[APP_EVOLVE_AGENT_RUNS] = registry
    return registry


def slot_running(slot: dict[str, Any] | None) -> bool:
    """True while this slot's build subprocess is still alive."""
    proc = ((slot or {}).get("session") or {}).get("proc")
    return proc is not None and proc.returncode is None


def slot_active(slot: dict[str, Any] | None) -> bool:
    """True while this slot is running OR still recording its result."""
    return slot_running(slot) or _recording_active((slot or {}).get("drain"))


def prune_runs(app: web.Application) -> dict[str, dict[str, Any]]:
    """Drop finished slots and return the registry."""
    registry = runs(app)
    for key in [key for key, slot in registry.items() if not slot_active(slot)]:
        registry.pop(key, None)
    return registry


def slot_for_run_id(app: web.Application, run_id: str) -> dict[str, Any] | None:
    """Find the slot a specific run_id belongs to, if it is still registered."""
    wanted = str(run_id or "").strip()
    if not wanted:
        return None
    for slot in runs(app).values():
        if str((slot.get("session") or {}).get("run_id") or "") == wanted:
            return slot
    return None
