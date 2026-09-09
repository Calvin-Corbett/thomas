"""Tool-call activity trace store (CAP-138).

Durable record of every tool invocation with its full inputs, *untruncated*
outputs, wall/logical timestamps, computed duration, owning session, and a
trace/span identity. Supports querying by session, tool name, trace id, and
time window, plus **cross-session trace links**: a call may reference a parent
trace id that lives in a *different* session, and :meth:`ToolTraceStore.query_trace`
walks those links to return the whole connected chain as one ordered timeline.

Design notes
------------
* Persistence is SQLite so a fresh :class:`ToolTraceStore` opened on the same
  path sees previously recorded calls. The path is resolved from (in order) the
  explicit ``path`` argument, the ``THOMAS_TOOL_TRACE_DB_PATH`` environment
  variable, then the Thomas data dir.
* A single injected ``clock`` callable (``() -> float`` seconds) drives both the
  stored timestamps and the computed duration, which makes durations and
  time-window queries fully deterministic under test. It defaults to
  :func:`time.time`.
* Outputs are stored verbatim as JSON text with no size cap or truncation, so
  large tool results round-trip intact.

This module lives in the ``observability`` (infra) tier and only imports from
``core`` and the standard library.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

from thomas.core.config import resolve_thomas_data_dir

ENV_DB_PATH = "THOMAS_TOOL_TRACE_DB_PATH"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_id TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  span_id TEXT,
  parent_trace_id TEXT,
  tool_name TEXT NOT NULL,
  input_json TEXT,
  output_json TEXT,
  started_at REAL,
  ended_at REAL,
  duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id, id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool_name, id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_trace ON tool_calls(trace_id, id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_parent ON tool_calls(parent_trace_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_started ON tool_calls(started_at, id);
"""

# Sentinel so ``None`` remains a legal, distinguishable stored output value.
_UNSET = object()


def _to_json(value: Any) -> str:
    """Serialise ``value`` to JSON text, falling back to a repr wrapper.

    Never truncates. Non-serialisable leaves are coerced via ``str`` so the
    record still round-trips as valid JSON.
    """

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return json.dumps({"__unserializable_repr__": repr(value)})


def _from_json(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def resolve_tool_trace_db_path(path: str | Path | None = None) -> Path:
    """Resolve the trace DB path from the argument, env, then data dir."""

    if path:
        return Path(path)
    env = os.getenv(ENV_DB_PATH, "").strip()
    if env:
        return Path(env)
    return resolve_thomas_data_dir() / ".thomas" / "tool_trace.sqlite3"


@dataclass
class ToolCall:
    """A single recorded tool invocation.

    ``tool_input`` / ``tool_output`` hold the *full* native values; they are
    JSON-encoded on write and decoded on read. ``parent_trace_id`` optionally
    points at a trace in another session to form a cross-session chain.
    """

    session_id: str
    trace_id: str
    tool_name: str
    tool_input: Any = None
    tool_output: Any = None
    span_id: str | None = None
    parent_trace_id: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    duration_ms: int | None = None
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def resolved_duration_ms(self) -> int | None:
        """Duration in ms: explicit value, else computed from the timestamps."""

        if self.duration_ms is not None:
            return self.duration_ms
        if self.started_at is not None and self.ended_at is not None:
            return int(round((self.ended_at - self.started_at) * 1000))
        return None

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> ToolCall:
        return cls(
            session_id=row["session_id"],
            trace_id=row["trace_id"],
            tool_name=row["tool_name"],
            tool_input=_from_json(row["input_json"]),
            tool_output=_from_json(row["output_json"]),
            span_id=row["span_id"],
            parent_trace_id=row["parent_trace_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_ms=row["duration_ms"],
            call_id=row["call_id"],
        )


class _SpanRecorder:
    """Context manager that times a tool call via the store's injected clock.

    Enter reads the clock as the start time; exit reads it again as the end
    time, computes the duration, and persists the call. Set :attr:`output`
    (or call :meth:`set_output`) inside the block to record the result.
    """

    def __init__(
        self,
        store: ToolTraceStore,
        *,
        session_id: str,
        trace_id: str,
        tool_name: str,
        tool_input: Any,
        span_id: str | None,
        parent_trace_id: str | None,
    ) -> None:
        self._store = store
        self._call = ToolCall(
            session_id=session_id,
            trace_id=trace_id,
            tool_name=tool_name,
            tool_input=tool_input,
            span_id=span_id,
            parent_trace_id=parent_trace_id,
        )
        self._output: Any = _UNSET

    @property
    def call_id(self) -> str:
        return self._call.call_id

    @property
    def output(self) -> Any:
        return None if self._output is _UNSET else self._output

    @output.setter
    def output(self, value: Any) -> None:
        self._output = value

    def set_output(self, value: Any) -> None:
        self._output = value

    def __enter__(self) -> _SpanRecorder:
        self._call.started_at = self._store._now()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self._call.ended_at = self._store._now()
        if self._output is not _UNSET:
            self._call.tool_output = self._output
        self._call.duration_ms = self._call.resolved_duration_ms()
        self._store.record(self._call)
        return False  # never suppress exceptions


class ToolTraceStore:
    """Durable store of tool-call activity traces.

    Parameters
    ----------
    path:
        Explicit DB path. Overrides the env var and data-dir defaults.
    clock:
        ``() -> float`` seconds source used for timestamps and duration
        computation. Injectable for deterministic tests; defaults to
        :func:`time.time`.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._path = resolve_tool_trace_db_path(path)
        self._now: Callable[[], float] = clock or time.time
        self._ensure_schema()

    @property
    def path(self) -> Path:
        return self._path

    # -- persistence ------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self._path))
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        con = self._connect()
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()

    # -- recording --------------------------------------------------------
    def record(self, call: ToolCall) -> str:
        """Persist ``call`` (full input + output + duration + ids). Returns id.

        If ``started_at`` is unset it is stamped from the injected clock. The
        duration is filled from :meth:`ToolCall.resolved_duration_ms` when not
        already provided. The stored output is never truncated.
        """

        if call.started_at is None:
            call.started_at = self._now()
        if call.duration_ms is None:
            call.duration_ms = call.resolved_duration_ms()

        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO tool_calls (
                    call_id, session_id, trace_id, span_id, parent_trace_id,
                    tool_name, input_json, output_json,
                    started_at, ended_at, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    trace_id=excluded.trace_id,
                    span_id=excluded.span_id,
                    parent_trace_id=excluded.parent_trace_id,
                    tool_name=excluded.tool_name,
                    input_json=excluded.input_json,
                    output_json=excluded.output_json,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    duration_ms=excluded.duration_ms
                """,
                (
                    call.call_id,
                    call.session_id,
                    call.trace_id,
                    call.span_id,
                    call.parent_trace_id,
                    call.tool_name,
                    _to_json(call.tool_input),
                    _to_json(call.tool_output),
                    call.started_at,
                    call.ended_at,
                    call.duration_ms,
                ),
            )
            con.commit()
        finally:
            con.close()
        return call.call_id

    def record_span(
        self,
        *,
        session_id: str,
        trace_id: str,
        tool_name: str,
        tool_input: Any = None,
        span_id: str | None = None,
        parent_trace_id: str | None = None,
    ) -> _SpanRecorder:
        """Time a tool call with the injected clock and persist it on exit.

        Usage::

            with store.record_span(session_id=..., trace_id=..., tool_name=...,
                                    tool_input=payload) as span:
                span.output = run_tool(payload)
        """

        return _SpanRecorder(
            self,
            session_id=session_id,
            trace_id=trace_id,
            tool_name=tool_name,
            tool_input=tool_input,
            span_id=span_id,
            parent_trace_id=parent_trace_id,
        )

    # -- queries ----------------------------------------------------------
    def _rows_to_calls(self, rows: Iterable[sqlite3.Row]) -> list[ToolCall]:
        return [ToolCall._from_row(r) for r in rows]

    def get(self, call_id: str) -> ToolCall | None:
        """Fetch a single call by id, or ``None`` if absent."""

        con = self._connect()
        try:
            row = con.execute("SELECT * FROM tool_calls WHERE call_id = ?", (call_id,)).fetchone()
        finally:
            con.close()
        return ToolCall._from_row(row) if row is not None else None

    def query_by_session(self, session_id: str) -> list[ToolCall]:
        """All calls owned by ``session_id`` in recorded order."""

        con = self._connect()
        try:
            rows = con.execute(
                "SELECT * FROM tool_calls WHERE session_id = ? ORDER BY started_at, id",
                (session_id,),
            ).fetchall()
        finally:
            con.close()
        return self._rows_to_calls(rows)

    def query_by_tool(self, tool_name: str) -> list[ToolCall]:
        """All calls for ``tool_name`` in recorded order."""

        con = self._connect()
        try:
            rows = con.execute(
                "SELECT * FROM tool_calls WHERE tool_name = ? ORDER BY started_at, id",
                (tool_name,),
            ).fetchall()
        finally:
            con.close()
        return self._rows_to_calls(rows)

    def query_by_time_window(self, start: float, end: float) -> list[ToolCall]:
        """Calls whose ``started_at`` falls in ``[start, end]`` (inclusive)."""

        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT * FROM tool_calls
                WHERE started_at >= ? AND started_at <= ?
                ORDER BY started_at, id
                """,
                (start, end),
            ).fetchall()
        finally:
            con.close()
        return self._rows_to_calls(rows)

    def query_trace(self, trace_id: str) -> list[ToolCall]:
        """Return the full linked trace chain containing ``trace_id``.

        Follows ``parent_trace_id`` links in *both* directions to gather every
        trace id in the connected component, then returns all calls across those
        traces -- possibly spanning multiple sessions -- ordered by start time.
        """

        con = self._connect()
        try:
            edges = con.execute("SELECT DISTINCT trace_id, parent_trace_id FROM tool_calls").fetchall()
            linked = self._linked_trace_ids(trace_id, edges)
            placeholders = ",".join("?" for _ in linked)
            rows = con.execute(
                f"""
                SELECT * FROM tool_calls
                WHERE trace_id IN ({placeholders})
                ORDER BY started_at, id
                """,
                tuple(linked),
            ).fetchall()
        finally:
            con.close()
        return self._rows_to_calls(rows)

    @staticmethod
    def _linked_trace_ids(trace_id: str, edges: Iterable[sqlite3.Row]) -> list[str]:
        """Breadth-first walk of the parent/child trace graph from ``trace_id``.

        Builds an undirected adjacency between each trace and its parent trace,
        then returns the connected component containing ``trace_id`` (always
        including ``trace_id`` itself so isolated traces still resolve).
        """

        adjacency: dict[str, set[str]] = {}
        for row in edges:
            child = row["trace_id"]
            parent = row["parent_trace_id"]
            adjacency.setdefault(child, set())
            if parent:
                adjacency.setdefault(parent, set())
                adjacency[child].add(parent)
                adjacency[parent].add(child)

        seen: set[str] = {trace_id}
        queue: deque[str] = deque([trace_id])
        while queue:
            current = queue.popleft()
            for neighbour in adjacency.get(current, ()):  # noqa: SIM118
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        return sorted(seen)
