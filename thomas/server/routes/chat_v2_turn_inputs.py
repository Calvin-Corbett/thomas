"""What one chat turn must read before it can open its reply stream.

Three reads, all of them disk and git, measured 2026-09-24 on the live board:
the session's delegations (218-303 ms), their digest, and the project catalog
(0.50-0.57 s per turn, four git spawns). They ran on the server's event loop, so
every other tab and card waited for them.

They belong together, and they belong HERE -- before ``response.prepare()``:

* Off the loop is the point, but ``await off_loop(...)`` is a real suspension.
  Doing it after the stream is prepared hands the loop back with the response
  headers already on the wire, so the request is answered while the turn is
  still gathering its inputs, and anything that held the world still for the
  request (a test's patch, a client acting on headers) has already moved on.
* The delegation board is read ONCE for the whole turn. The route used to ask
  for it twice, once for the prompt and once beside the brain call, and nothing
  between those two points can change it: the callbacks that start delegations
  are only defined in between, never called.

On 2026-09-29 Chat said no self-development projects were running while three
were. Every turn now gives the model the project count and lets it decide when
to call self.projects; no word list selects the turns that receive this fact.
"""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from dataclasses import dataclass
from typing import Any

from thomas.core.event_loop_offload import off_loop
from thomas.server.chat_delegation import build_active_task_digest, session_active_delegations
from thomas.server.praxis.project_context import build_project_catalog_context

log = logging.getLogger(__name__)
SELF_PROJECTS_FRESH_S = 30.0
SELF_PROJECTS_WAIT_S = 2.0
SELF_PROJECTS_UNAVAILABLE = (
    "[Your own projects] Your own project list is unavailable right now; "
    "do not say none are running. Call self.projects to read it."
)


@dataclass
class _ProjectStatus:
    line: str = ""
    ended: float = 0.0
    task: asyncio.Task[str] | None = None


_self_project_status: weakref.WeakKeyDictionary[Any, _ProjectStatus] = weakref.WeakKeyDictionary()


def _read_self_projects_report(running: set[str]) -> dict[str, Any]:
    from thomas.server.routes.self_project_routes import read_projects

    return read_projects(None, running, changed_files=False)


def self_projects_line(report: dict[str, Any]) -> str:
    """Count projects by state in first-seen order, without claiming partial reads are complete."""
    counts: dict[str, int] = {}
    for row in report["projects"]:
        state = str(row["state"])
        counts[state] = counts.get(state, 0) + 1
    words = ", ".join(f"{count} {state}" for state, count in counts.items()) or "none"
    line = (
        f"[Your own projects] Your self-change projects right now: {words}. Call self.projects for each one's details."
    )
    if report["unreadable"]:
        line += " Some of their copies could not be read, so this may be missing some; do not say none are running."
    return line


async def self_projects_status(app: Any) -> str:
    """Share a bounded wait and one cached disk read across turns of this app."""
    status = _self_project_status.setdefault(app, _ProjectStatus())
    if status.line and time.monotonic() - status.ended < SELF_PROJECTS_FRESH_S:
        return status.line
    if status.task is None or status.task.done():
        from thomas.server.routes.self_project_routes import running_projects

        running = running_projects(app)

        async def read() -> str:
            try:
                report = await asyncio.to_thread(_read_self_projects_report, running)
                line = self_projects_line(report)
            except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
                log.warning("Could not read Thomas's self-change projects: %s", exc)
                line = SELF_PROJECTS_UNAVAILABLE
            status.line, status.ended, status.task = line, time.monotonic(), None
            return line

        status.task = asyncio.create_task(read())
    try:
        return await asyncio.wait_for(asyncio.shield(status.task), timeout=SELF_PROJECTS_WAIT_S)
    except asyncio.TimeoutError:
        return SELF_PROJECTS_UNAVAILABLE


@dataclass(frozen=True)
class TurnInputs:
    """The three reads, gathered once."""

    delegations: list[dict[str, Any]]
    task_digest: str
    project_catalog: str
    self_projects: str = ""

    @property
    def turn_digest(self) -> str:
        return "\n\n".join(part for part in (self.task_digest, self.self_projects) if part)


async def gather_turn_inputs(session_id: str, prompt: str, *, can_build: bool, app: Any = None) -> TurnInputs:
    """Read the turn's inputs in worker threads, leaving the loop free."""
    delegations = await off_loop("chat.session_delegations", session_active_delegations, session_id)
    digest = await off_loop("chat.task_digest", build_active_task_digest, session_id) if delegations else ""
    catalog = await off_loop("chat.project_catalog", build_project_catalog_context, prompt) if can_build else ""
    projects = await self_projects_status(app) if app is not None else ""
    return TurnInputs(delegations=delegations, task_digest=digest, project_catalog=catalog, self_projects=projects)


__all__ = ["TurnInputs", "gather_turn_inputs"]
