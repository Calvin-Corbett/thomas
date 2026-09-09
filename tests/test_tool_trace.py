"""Tests for the tool-call activity trace store (CAP-138).

Acceptance: store/query tool inputs, full outputs, duration, and cross-session
trace links.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.observability.tool_trace import ToolCall, ToolTraceStore


class FakeClock:
    """Deterministic, injectable clock returning preset float timestamps."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._i = 0

    def __call__(self) -> float:
        # Hold the last value once the script is exhausted.
        if self._i < len(self._values):
            v = self._values[self._i]
            self._i += 1
        else:
            v = self._values[-1]
        return v


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "trace.sqlite3"


def test_record_and_read_back_full_output_untruncated(db_path: Path) -> None:
    store = ToolTraceStore(db_path, clock=FakeClock([100.0]))
    big_output = {"lines": [f"row-{i}" for i in range(5000)], "blob": "x" * 20000}
    call = ToolCall(
        session_id="s1",
        trace_id="t1",
        tool_name="shell",
        tool_input={"cmd": "ls -la", "cwd": "/repo"},
        tool_output=big_output,
        span_id="span-1",
        started_at=100.0,
        ended_at=100.25,
    )
    call_id = store.record(call)

    got = store.get(call_id)
    assert got is not None
    assert got.session_id == "s1"
    assert got.trace_id == "t1"
    assert got.tool_name == "shell"
    assert got.tool_input == {"cmd": "ls -la", "cwd": "/repo"}
    # Full output preserved with no truncation.
    assert got.tool_output == big_output
    assert len(got.tool_output["blob"]) == 20000
    assert len(got.tool_output["lines"]) == 5000
    assert got.duration_ms == 250


def test_duration_computed_from_injected_clock(db_path: Path) -> None:
    # record_span reads the clock on enter and exit; 100.0 -> 100.5 => 500 ms.
    clock = FakeClock([100.0, 100.5])
    store = ToolTraceStore(db_path, clock=clock)
    with store.record_span(session_id="s1", trace_id="t1", tool_name="search", tool_input={"q": "hi"}) as span:
        span.output = {"hits": 3}

    calls = store.query_by_session("s1")
    assert len(calls) == 1
    assert calls[0].started_at == 100.0
    assert calls[0].ended_at == 100.5
    assert calls[0].duration_ms == 500
    assert calls[0].tool_output == {"hits": 3}


def test_query_by_session_tool_and_time_window(db_path: Path) -> None:
    store = ToolTraceStore(db_path, clock=FakeClock([0.0]))
    store.record(ToolCall("s1", "t1", "shell", tool_input="a", started_at=10.0))
    store.record(ToolCall("s1", "t1", "search", tool_input="b", started_at=20.0))
    store.record(ToolCall("s2", "t2", "shell", tool_input="c", started_at=30.0))

    by_session = store.query_by_session("s1")
    assert [c.tool_input for c in by_session] == ["a", "b"]

    by_tool = store.query_by_tool("shell")
    assert {c.session_id for c in by_tool} == {"s1", "s2"}
    assert [c.tool_input for c in by_tool] == ["a", "c"]

    window = store.query_by_time_window(15.0, 25.0)
    assert [c.tool_input for c in window] == ["b"]

    wide = store.query_by_time_window(10.0, 30.0)
    assert [c.tool_input for c in wide] == ["a", "b", "c"]


def test_cross_session_trace_link_returns_one_ordered_chain(db_path: Path) -> None:
    store = ToolTraceStore(db_path, clock=FakeClock([0.0]))
    # Session A opens trace T1.
    store.record(ToolCall("session-A", "T1", "plan", tool_input="root", started_at=1.0))
    # Session B runs under trace T2, which links back to T1 in session A.
    store.record(
        ToolCall(
            "session-B",
            "T2",
            "execute",
            tool_input="child",
            parent_trace_id="T1",
            started_at=2.0,
        )
    )
    # Unrelated trace in a third session must NOT be pulled in.
    store.record(ToolCall("session-C", "T9", "noise", tool_input="other", started_at=1.5))

    chain = store.query_trace("T1")
    assert [c.session_id for c in chain] == ["session-A", "session-B"]
    assert [c.trace_id for c in chain] == ["T1", "T2"]
    assert [c.tool_input for c in chain] == ["root", "child"]

    # Querying from the child trace yields the same cross-session chain.
    assert [c.call_id for c in store.query_trace("T2")] == [c.call_id for c in chain]


def test_round_trip_across_fresh_instance_same_path(db_path: Path) -> None:
    store = ToolTraceStore(db_path, clock=FakeClock([0.0]))
    call_id = store.record(
        ToolCall(
            "s1",
            "t1",
            "shell",
            tool_input={"cmd": "echo hi"},
            tool_output="hi\n",
            started_at=5.0,
            ended_at=5.1,
        )
    )

    # A brand-new instance on the same path must see the persisted call.
    reopened = ToolTraceStore(db_path, clock=FakeClock([0.0]))
    got = reopened.get(call_id)
    assert got is not None
    assert got.tool_input == {"cmd": "echo hi"}
    assert got.tool_output == "hi\n"
    assert got.duration_ms == 100
    assert [c.call_id for c in reopened.query_by_session("s1")] == [call_id]


def test_env_var_overrides_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / "from_env.sqlite3"
    monkeypatch.setenv("THOMAS_TOOL_TRACE_DB_PATH", str(env_path))
    store = ToolTraceStore(clock=FakeClock([0.0]))
    assert store.path == env_path
    store.record(ToolCall("s1", "t1", "shell", started_at=1.0))
    assert env_path.exists()
