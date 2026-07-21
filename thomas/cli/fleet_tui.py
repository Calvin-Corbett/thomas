"""CAP-099 -- Fleet-native TUI over an injectable fleet-state source.

A terminal UI for driving a fleet of agent runs. It renders to a plain text
*frame* (a ``str``) so the renderer is pure and snapshot-testable; nothing here
touches ``curses``, a live terminal, or any process. The five fleet actions are
modelled as pure state transitions over an immutable ``FleetState`` snapshot:

    NAVIGATE   -- move the selection cursor across agents and tasks
    PEEK       -- show a run's detail without attaching to it
    ATTACH     -- attach to the selected run, foregrounding it
    REPLY      -- inline reply / steer to the attached run via a dispatch sink
    TASK GRAPH -- render the fleet's task dependency graph (nodes + edges)

External edges are behind injectable adapters:

  * ``FleetSource`` -- yields the current ``FleetState``. The default
    :class:`InMemoryFleetSource` is a real implementation backed by an
    in-memory snapshot; a live wiring would adapt the swarm/run store to the
    same protocol. Tests inject the in-memory source as a hermetic fake.
  * ``ReplyDispatch`` -- receives ``reply(run_id, message)`` calls. The default
    :class:`CallbackDispatch` forwards to a real callable; tests inject
    :class:`RecordingDispatch` to capture dispatches offline.

stdlib-only. No network, no clock, no global state.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

__all__ = [
    "AgentInfo",
    "TaskInfo",
    "RunDetail",
    "FleetState",
    "FleetSource",
    "InMemoryFleetSource",
    "ReplyDispatch",
    "CallbackDispatch",
    "RecordingDispatch",
    "Row",
    "FleetTUI",
    "ReplyError",
]

# ---------------------------------------------------------------------------
# Immutable fleet-state model
# ---------------------------------------------------------------------------

_STATUS_GLYPH = {
    "pending": ".",
    "blocked": "x",
    "ready": "o",
    "running": ">",
    "done": "*",
    "failed": "!",
    "cancelled": "-",
}


def _glyph(status: str) -> str:
    return _STATUS_GLYPH.get(status, "?")


@dataclasses.dataclass(frozen=True)
class AgentInfo:
    """A single agent in the fleet."""

    agent_id: str
    role: str = ""
    status: str = "idle"
    run_id: str | None = None


@dataclasses.dataclass(frozen=True)
class TaskInfo:
    """A task node in the fleet's task graph."""

    task_id: str
    title: str = ""
    status: str = "pending"
    agent_id: str | None = None
    run_id: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class RunDetail:
    """Detail for a single run, shown by PEEK / ATTACH."""

    run_id: str
    agent_id: str | None = None
    task_id: str | None = None
    status: str = "running"
    summary: str = ""
    transcript: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class FleetState:
    """Immutable snapshot of the whole fleet."""

    agents: tuple[AgentInfo, ...] = ()
    tasks: tuple[TaskInfo, ...] = ()
    runs: tuple[RunDetail, ...] = ()

    def run(self, run_id: str | None) -> RunDetail | None:
        if run_id is None:
            return None
        for detail in self.runs:
            if detail.run_id == run_id:
                return detail
        return None


# ---------------------------------------------------------------------------
# Injectable adapters
# ---------------------------------------------------------------------------


@runtime_checkable
class FleetSource(Protocol):
    """Yields the current fleet snapshot."""

    def snapshot(self) -> FleetState: ...


class InMemoryFleetSource:
    """Real ``FleetSource`` backed by an in-memory snapshot.

    Doubles as the hermetic fake for tests. ``set_state`` swaps the snapshot so
    a test (or a live poller) can drive successive frames.
    """

    def __init__(self, state: FleetState | None = None) -> None:
        self._state = state if state is not None else FleetState()

    def snapshot(self) -> FleetState:
        return self._state

    def set_state(self, state: FleetState) -> None:
        self._state = state


class ReplyError(RuntimeError):
    """Raised when a REPLY is attempted with no attached run."""


@runtime_checkable
class ReplyDispatch(Protocol):
    """Sink for inline replies / steering messages to a run."""

    def reply(self, run_id: str, message: str) -> None: ...


class CallbackDispatch:
    """Real dispatch that forwards ``reply`` to an injected callable."""

    def __init__(self, sink) -> None:
        self._sink = sink

    def reply(self, run_id: str, message: str) -> None:
        self._sink(run_id, message)


class RecordingDispatch:
    """Hermetic fake dispatch: records every ``reply`` call in order."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def reply(self, run_id: str, message: str) -> None:
        self.sent.append((run_id, message))


# ---------------------------------------------------------------------------
# Selection rows -- the flat navigable list over agents + tasks
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Row:
    """One navigable line: an agent header or a task under it."""

    kind: str  # "agent" | "task"
    ref_id: str  # agent_id or task_id
    run_id: str | None
    label: str
    status: str


def _build_rows(state: FleetState) -> tuple[Row, ...]:
    """Flatten the fleet into an ordered, navigable list of rows.

    Agents appear in declaration order, each immediately followed by the tasks
    assigned to it. Tasks with no owning agent (or whose agent is absent) are
    grouped under a trailing ``(unassigned)`` section so every task is
    reachable by NAVIGATE.
    """
    rows: list[Row] = []
    tasks_by_agent: dict[str | None, list[TaskInfo]] = {}
    for task in state.tasks:
        tasks_by_agent.setdefault(task.agent_id, []).append(task)

    known_agent_ids = {a.agent_id for a in state.agents}
    for agent in state.agents:
        rows.append(
            Row(
                kind="agent",
                ref_id=agent.agent_id,
                run_id=agent.run_id,
                label=agent.role or agent.agent_id,
                status=agent.status,
            )
        )
        for task in tasks_by_agent.get(agent.agent_id, ()):
            rows.append(
                Row(
                    kind="task",
                    ref_id=task.task_id,
                    run_id=task.run_id,
                    label=task.title or task.task_id,
                    status=task.status,
                )
            )

    orphan_tasks: list[TaskInfo] = []
    for agent_id, tasks in tasks_by_agent.items():
        if agent_id not in known_agent_ids:
            orphan_tasks.extend(tasks)
    if orphan_tasks:
        rows.append(Row(kind="agent", ref_id="", run_id=None, label="(unassigned)", status="idle"))
        for task in orphan_tasks:
            rows.append(
                Row(
                    kind="task",
                    ref_id=task.task_id,
                    run_id=task.run_id,
                    label=task.title or task.task_id,
                    status=task.status,
                )
            )
    return tuple(rows)


# ---------------------------------------------------------------------------
# The TUI controller -- pure state transitions + a pure renderer
# ---------------------------------------------------------------------------

_WIDTH = 64


def _rule(title: str = "") -> str:
    if not title:
        return "-" * _WIDTH
    prefix = f"-- {title} "
    return prefix + "-" * max(0, _WIDTH - len(prefix))


class FleetTUI:
    """Fleet-native TUI controller.

    Holds only view state (selection cursor, peek target, attached run). All
    fleet facts come from the injected ``FleetSource`` on demand, so a frame
    always reflects the latest snapshot. Every action returns the freshly
    rendered frame for convenient snapshot testing.
    """

    def __init__(self, source: FleetSource, dispatch: ReplyDispatch | None = None) -> None:
        self._source = source
        self._dispatch = dispatch if dispatch is not None else RecordingDispatch()
        self._cursor = 0
        self._peek_run_id: str | None = None
        self._attached_run_id: str | None = None

    # -- introspection ---------------------------------------------------

    @property
    def dispatch(self) -> ReplyDispatch:
        return self._dispatch

    @property
    def attached_run_id(self) -> str | None:
        return self._attached_run_id

    @property
    def peek_run_id(self) -> str | None:
        return self._peek_run_id

    @property
    def cursor(self) -> int:
        return self._cursor

    def rows(self) -> tuple[Row, ...]:
        return _build_rows(self._source.snapshot())

    def selected_row(self) -> Row | None:
        rows = self.rows()
        if not rows:
            return None
        idx = self._clamp(self._cursor, len(rows))
        return rows[idx]

    def selected_run_id(self) -> str | None:
        row = self.selected_row()
        return row.run_id if row is not None else None

    # -- actions (pure state transitions) --------------------------------

    def navigate(self, direction: str) -> str:
        """Move the selection cursor. ``direction`` in {"up","down","top","bottom"}."""
        rows = self.rows()
        n = len(rows)
        if n == 0:
            self._cursor = 0
            return self.render()
        cur = self._clamp(self._cursor, n)
        if direction == "down":
            cur = (cur + 1) % n
        elif direction == "up":
            cur = (cur - 1) % n
        elif direction == "top":
            cur = 0
        elif direction == "bottom":
            cur = n - 1
        else:
            raise ValueError(f"unknown navigate direction: {direction!r}")
        self._cursor = cur
        return self.render()

    def peek(self) -> str:
        """Show the selected run's detail without attaching to it."""
        self._peek_run_id = self.selected_run_id()
        return self.render()

    def attach(self) -> str:
        """Attach to the selected run, foregrounding it."""
        run_id = self.selected_run_id()
        if run_id is not None:
            self._attached_run_id = run_id
        return self.render()

    def detach(self) -> str:
        """Drop the current attachment (background the run)."""
        self._attached_run_id = None
        return self.render()

    def reply(self, message: str) -> str:
        """Dispatch an inline reply / steer to the attached run.

        Raises :class:`ReplyError` if nothing is attached -- REPLY targets the
        foregrounded run, so an attach must precede it.
        """
        if self._attached_run_id is None:
            raise ReplyError("no run is attached; ATTACH before REPLY")
        self._dispatch.reply(self._attached_run_id, message)
        return self.render()

    # -- rendering (pure) ------------------------------------------------

    def render(self) -> str:
        state = self._source.snapshot()
        rows = _build_rows(state)
        lines: list[str] = []
        lines.append(_rule("FLEET"))
        attached = self._attached_run_id or "(none)"
        lines.append(f"agents: {len(state.agents)}   tasks: {len(state.tasks)}   attached: {attached}")
        lines.append(_rule())
        lines.extend(self._render_rows(rows))
        lines.append(_rule("TASK GRAPH"))
        lines.extend(self._render_graph(state))
        detail = state.run(self._peek_run_id)
        if detail is not None:
            lines.append(_rule("PEEK"))
            lines.extend(self._render_detail(detail))
        attached_detail = state.run(self._attached_run_id)
        if attached_detail is not None:
            lines.append(_rule("ATTACHED"))
            lines.extend(self._render_detail(attached_detail))
        lines.append(_rule())
        return "\n".join(lines)

    def _render_rows(self, rows: Sequence[Row]) -> list[str]:
        if not rows:
            return ["  (no agents or tasks)"]
        idx = self._clamp(self._cursor, len(rows))
        out: list[str] = []
        for i, row in enumerate(rows):
            marker = ">" if i == idx else " "
            if row.kind == "agent":
                out.append(f"{marker} [{_glyph(row.status)}] {row.label}")
            else:
                out.append(f"{marker}    [{_glyph(row.status)}] {row.label} ({row.ref_id})")
        return out

    def _render_graph(self, state: FleetState) -> list[str]:
        if not state.tasks:
            return ["  (no tasks)"]
        out: list[str] = []
        for task in state.tasks:
            node = f"  ({_glyph(task.status)}) {task.task_id}"
            if task.title:
                node += f"  {task.title}"
            out.append(node)
            for dep in task.depends_on:
                out.append(f"      {dep} -> {task.task_id}")
        return out

    def _render_detail(self, detail: RunDetail) -> list[str]:
        out = [
            f"  run: {detail.run_id}   status: {detail.status}",
            f"  agent: {detail.agent_id or '-'}   task: {detail.task_id or '-'}",
        ]
        if detail.summary:
            out.append(f"  {detail.summary}")
        for line in detail.transcript:
            out.append(f"    | {line}")
        return out

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _clamp(idx: int, length: int) -> int:
        if length <= 0:
            return 0
        if idx < 0:
            return 0
        if idx >= length:
            return length - 1
        return idx


def build_state(
    agents: Iterable[AgentInfo] = (),
    tasks: Iterable[TaskInfo] = (),
    runs: Iterable[RunDetail] = (),
) -> FleetState:
    """Convenience constructor that freezes iterables into a ``FleetState``."""
    return FleetState(agents=tuple(agents), tasks=tuple(tasks), runs=tuple(runs))
