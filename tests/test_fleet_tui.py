"""CAP-099 acceptance -- fleet-native TUI.

Proves the exact acceptance line offline against a hermetic in-memory fleet
source and a recording dispatch sink:

  * NAVIGATE moves selection and re-renders,
  * PEEK shows detail without changing attach state,
  * ATTACH marks the run attached and REPLY dispatches to it via the sink,
  * the task graph renders nodes + edges reflecting dependencies,
  * an empty fleet renders cleanly.
"""

from __future__ import annotations

import pytest

from thomas.cli.fleet_tui import (
    AgentInfo,
    CallbackDispatch,
    FleetTUI,
    InMemoryFleetSource,
    RecordingDispatch,
    ReplyError,
    RunDetail,
    TaskInfo,
    build_state,
)


def _fleet() -> InMemoryFleetSource:
    agents = [
        AgentInfo(agent_id="planner", role="Planner", status="running", run_id="run-p"),
        AgentInfo(agent_id="coder", role="Coder", status="running", run_id="run-c"),
    ]
    tasks = [
        TaskInfo(task_id="T1", title="design", status="done", agent_id="planner", run_id="run-p"),
        TaskInfo(
            task_id="T2",
            title="implement",
            status="running",
            agent_id="coder",
            run_id="run-c",
            depends_on=("T1",),
        ),
        TaskInfo(task_id="T3", title="review", status="blocked", agent_id="coder", depends_on=("T2",)),
    ]
    runs = [
        RunDetail(run_id="run-p", agent_id="planner", task_id="T1", status="done", summary="plan ready"),
        RunDetail(
            run_id="run-c",
            agent_id="coder",
            task_id="T2",
            status="running",
            summary="writing module",
            transcript=("started", "editing files"),
        ),
    ]
    return InMemoryFleetSource(build_state(agents, tasks, runs))


# ---------------------------------------------------------------------------
# NAVIGATE
# ---------------------------------------------------------------------------


def test_navigate_moves_selection_and_rerenders():
    tui = FleetTUI(_fleet())
    first_row = tui.selected_row()
    assert first_row is not None and first_row.ref_id == "planner"
    frame0 = tui.render()

    frame1 = tui.navigate("down")
    moved = tui.selected_row()
    assert moved is not None and moved.ref_id == "T1"
    # The rendered frame changed: the selection marker moved.
    assert frame1 != frame0
    assert "> " in frame1

    # Wrap-around: up from the top row lands on the last row.
    tui.navigate("top")
    tui.navigate("up")
    bottom = tui.selected_row()
    assert bottom is not None and bottom.ref_id == "T3"


def test_navigate_rejects_unknown_direction():
    tui = FleetTUI(_fleet())
    with pytest.raises(ValueError):
        tui.navigate("sideways")


# ---------------------------------------------------------------------------
# PEEK -- shows detail without changing attach state
# ---------------------------------------------------------------------------


def test_peek_shows_detail_without_attaching():
    tui = FleetTUI(_fleet())
    tui.navigate("down")  # T1 -> run-p
    assert tui.selected_run_id() == "run-p"

    frame = tui.peek()
    assert tui.peek_run_id == "run-p"
    assert tui.attached_run_id is None  # peek must not attach
    assert "-- PEEK" in frame
    assert "plan ready" in frame
    assert "-- ATTACHED" not in frame


# ---------------------------------------------------------------------------
# ATTACH + REPLY -- attach marks run, reply dispatches via the sink
# ---------------------------------------------------------------------------


def test_attach_marks_run_and_reply_dispatches_to_sink():
    sink = RecordingDispatch()
    tui = FleetTUI(_fleet(), dispatch=sink)
    # Select the coder's running task (T2 -> run-c).
    tui.navigate("bottom")  # T3
    tui.navigate("up")  # T2
    assert tui.selected_run_id() == "run-c"

    frame = tui.attach()
    assert tui.attached_run_id == "run-c"
    assert "-- ATTACHED" in frame
    assert "attached: run-c" in frame

    tui.reply("focus on the retry path")
    assert sink.sent == [("run-c", "focus on the retry path")]


def test_reply_without_attach_raises():
    sink = RecordingDispatch()
    tui = FleetTUI(_fleet(), dispatch=sink)
    with pytest.raises(ReplyError):
        tui.reply("hello?")
    assert sink.sent == []


def test_callback_dispatch_forwards_to_real_callable():
    received: list[tuple[str, str]] = []
    tui = FleetTUI(_fleet(), dispatch=CallbackDispatch(lambda rid, msg: received.append((rid, msg))))
    tui.navigate("top")  # planner -> run-p
    tui.attach()
    tui.reply("wrap up")
    assert received == [("run-p", "wrap up")]


def test_peek_then_attach_are_independent():
    tui = FleetTUI(_fleet())
    tui.navigate("down")  # T1 / run-p
    tui.peek()
    tui.navigate("bottom")  # T3
    tui.navigate("up")  # T2 / run-c
    tui.attach()
    # Peek target stays on the earlier run; attach reflects the later one.
    assert tui.peek_run_id == "run-p"
    assert tui.attached_run_id == "run-c"
    frame = tui.render()
    assert "-- PEEK" in frame and "-- ATTACHED" in frame


# ---------------------------------------------------------------------------
# LIVE TASK GRAPH -- nodes + edges reflecting dependencies
# ---------------------------------------------------------------------------


def test_task_graph_renders_nodes_and_dependency_edges():
    tui = FleetTUI(_fleet())
    frame = tui.render()
    assert "-- TASK GRAPH" in frame
    # Every task is a node.
    for task_id in ("T1", "T2", "T3"):
        assert task_id in frame
    # Edges reflect declared dependencies.
    assert "T1 -> T2" in frame
    assert "T2 -> T3" in frame
    # No spurious edge for the root.
    assert "-> T1" not in frame


def test_graph_reflects_updated_snapshot():
    source = _fleet()
    tui = FleetTUI(source)
    assert "T4" not in tui.render()
    state = source.snapshot()
    new_tasks = state.tasks + (TaskInfo(task_id="T4", title="ship", status="pending", depends_on=("T3",)),)
    source.set_state(build_state(state.agents, new_tasks, state.runs))
    frame = tui.render()
    assert "T4" in frame
    assert "T3 -> T4" in frame


# ---------------------------------------------------------------------------
# EMPTY FLEET -- renders cleanly
# ---------------------------------------------------------------------------


def test_empty_fleet_renders_cleanly():
    tui = FleetTUI(InMemoryFleetSource())
    frame = tui.render()
    assert "agents: 0" in frame
    assert "tasks: 0" in frame
    assert "(no agents or tasks)" in frame
    assert "(no tasks)" in frame
    assert tui.selected_row() is None
    # Navigation on an empty fleet is a no-op, not a crash.
    assert tui.navigate("down") == frame
    assert tui.peek() == frame  # nothing to peek
    assert tui.attached_run_id is None
