"""Behavioral tests for the production flow graph and its registered tools."""

from __future__ import annotations

import pytest

from thomas.flows.core import Edge, ExecutionContext, Flow, FlowExecutor, Node, NodeType
from thomas.flows.tools import FlowDesignTool, FlowExecutionTool, register_flows_tools
from thomas.server import tool_extensions
from thomas.tools.registry import ToolRegistry


def _linear_flow(*, action_count: int = 1) -> Flow:
    flow = Flow("linear", "Linear flow")
    previous = flow.add_node(NodeType.START, "Start")
    for index in range(action_count):
        current = flow.add_node(NodeType.ACTION, f"Action {index + 1}")
        flow.add_edge(previous, current)
        previous = current
    end = flow.add_node(NodeType.END, "End")
    flow.add_edge(previous, end)
    return flow


def test_tests_import_the_production_flow_types() -> None:
    assert Flow.__module__ == "thomas.flows.core"
    assert FlowExecutor.__module__ == "thomas.flows.core"
    assert FlowDesignTool.__module__ == "thomas.flows.tools"


@pytest.mark.parametrize(
    ("node_type", "value"),
    [
        (NodeType.START, "start"),
        (NodeType.END, "end"),
        (NodeType.ACTION, "action"),
        (NodeType.DECISION, "decision"),
        (NodeType.MERGE, "merge"),
    ],
)
def test_node_types_are_the_values_exposed_by_the_design_tool(node_type: NodeType, value: str) -> None:
    assert node_type.value == value


def test_node_and_edge_serialization_uses_the_public_graph_shape() -> None:
    node = Node("review", NodeType.ACTION, "Review", config={"owner": "ops"})
    edge = Edge("edge_1", "start", "review", label="next", condition="approved")

    assert node.to_dict() == {
        "node_id": "review",
        "node_type": "action",
        "name": "Review",
        "config": {"owner": "ops"},
    }
    assert edge.to_dict() == {
        "edge_id": "edge_1",
        "source": "start",
        "target": "review",
        "label": "next",
        "condition": "approved",
    }


def test_add_node_tracks_generated_ids_start_and_end_nodes() -> None:
    flow = Flow("approval", "Approval")

    start = flow.add_node(NodeType.START, "Start")
    end = flow.add_node(NodeType.END, "Done", node_id="finished")

    assert start == "node_1"
    assert end == "finished"
    assert flow.start_node == start
    assert flow.end_nodes == [end]


def test_add_node_rejects_duplicate_ids() -> None:
    flow = Flow("duplicate", "Duplicate")
    flow.add_node(NodeType.ACTION, "First", node_id="same")

    with pytest.raises(ValueError, match="already exists"):
        flow.add_node(NodeType.ACTION, "Second", node_id="same")


@pytest.mark.parametrize(("source", "target"), [("missing", "end"), ("start", "missing")])
def test_add_edge_rejects_unknown_endpoints(source: str, target: str) -> None:
    flow = Flow("bad-edge", "Bad edge")
    flow.add_node(NodeType.START, "Start", node_id="start")
    flow.add_node(NodeType.END, "End", node_id="end")

    with pytest.raises(ValueError, match="Source or target node not found"):
        flow.add_edge(source, target)


def test_graph_queries_return_only_edges_for_the_requested_node() -> None:
    flow = Flow("branch", "Branch")
    start = flow.add_node(NodeType.START, "Start")
    decision = flow.add_node(NodeType.DECISION, "Choose")
    left = flow.add_node(NodeType.ACTION, "Left")
    right = flow.add_node(NodeType.ACTION, "Right")
    merge = flow.add_node(NodeType.MERGE, "Merge")
    end = flow.add_node(NodeType.END, "End")
    first = flow.add_edge(start, decision)
    flow.add_edge(decision, left, label="left")
    flow.add_edge(decision, right, label="right")
    flow.add_edge(left, merge)
    flow.add_edge(right, merge)
    flow.add_edge(merge, end)

    assert [edge.edge_id for edge in flow.get_outgoing_edges(start)] == [first]
    assert {edge.source_node for edge in flow.get_incoming_edges(merge)} == {left, right}


def test_validate_requires_a_start_node() -> None:
    flow = Flow("no-start", "No start")
    flow.add_node(NodeType.END, "End")

    assert flow.validate() == (False, "No start node defined")


def test_validate_requires_an_end_node() -> None:
    flow = Flow("no-end", "No end")
    flow.add_node(NodeType.START, "Start")

    assert flow.validate() == (False, "No end nodes defined")


def test_validate_reports_unreachable_nodes() -> None:
    flow = _linear_flow()
    orphan = flow.add_node(NodeType.ACTION, "Orphan")

    valid, error = flow.validate()

    assert valid is False
    assert error == f"Unreachable nodes: {{{orphan!r}}}"


def test_valid_flow_stats_and_serialization_describe_the_live_graph() -> None:
    flow = _linear_flow(action_count=2)

    assert flow.validate() == (True, None)
    assert flow.get_stats() == {
        "flow_id": "linear",
        "nodes": 4,
        "edges": 3,
        "start_node": "node_1",
        "end_nodes": 1,
        "is_valid": True,
    }
    serialized = flow.to_dict()
    assert serialized["flow_id"] == "linear"
    assert [node["node_type"] for node in serialized["nodes"]] == ["start", "action", "action", "end"]
    assert [(edge["source"], edge["target"]) for edge in serialized["edges"]] == [
        ("node_1", "node_2"),
        ("node_2", "node_3"),
        ("node_3", "node_4"),
    ]


def test_execution_context_starts_with_independent_state() -> None:
    first = ExecutionContext("one", "flow")
    second = ExecutionContext("two", "flow")

    first.variables["changed"] = True
    first.visited_nodes.append("start")

    assert second.variables == {}
    assert second.visited_nodes == []


def test_executor_rejects_a_duplicate_injected_execution_id() -> None:
    executor = FlowExecutor(_linear_flow())
    executor.create_execution(execution_id="external")

    with pytest.raises(ValueError, match="Execution external already exists"):
        executor.create_execution(execution_id="external")


@pytest.mark.asyncio
async def test_executor_steps_through_nodes_and_rejects_work_after_completion() -> None:
    executor = FlowExecutor(_linear_flow())
    execution_id = executor.create_execution({"request_id": 42})

    assert await executor.execute_step(execution_id) == (True, None)
    assert await executor.execute_step(execution_id) == (True, None)
    assert await executor.execute_step(execution_id) == (True, None)
    assert await executor.execute_step(execution_id) == (False, "Execution already completed")

    state = executor.get_execution_state(execution_id)
    assert state == {
        "execution_id": "exec_1",
        "flow_id": "linear",
        "current_node": "node_3",
        "visited_nodes": ["node_1", "node_2", "node_3"],
        "completed": True,
        "variables": {"request_id": 42},
        "error": None,
    }


@pytest.mark.asyncio
async def test_executor_reports_unknown_execution_ids() -> None:
    executor = FlowExecutor(_linear_flow())

    assert await executor.execute_step("missing") == (False, "Execution missing not found")
    assert await executor.execute_full("missing") == (False, "Execution missing not found")
    assert executor.get_execution_state("missing") is None


@pytest.mark.asyncio
async def test_full_execution_can_finish_on_the_exact_step_limit() -> None:
    flow = _linear_flow(action_count=FlowExecutor.MAX_STEPS - 2)
    executor = FlowExecutor(flow)
    execution_id = executor.create_execution()

    assert await executor.execute_full(execution_id) == (True, None)
    state = executor.get_execution_state(execution_id)
    assert state is not None
    assert state["completed"] is True
    assert len(state["visited_nodes"]) == FlowExecutor.MAX_STEPS


@pytest.mark.asyncio
async def test_cycle_stops_at_the_step_limit_and_records_the_error() -> None:
    flow = Flow("cycle", "Cycle")
    start = flow.add_node(NodeType.START, "Start")
    loop = flow.add_node(NodeType.ACTION, "Loop")
    end = flow.add_node(NodeType.END, "End")
    flow.add_edge(start, loop)
    flow.add_edge(loop, start)
    flow.add_edge(loop, end)
    assert flow.validate() == (True, None)

    executor = FlowExecutor(flow)
    execution_id = executor.create_execution()

    assert await executor.execute_full(execution_id) == (False, "Max steps exceeded")
    state = executor.get_execution_state(execution_id)
    assert state is not None
    assert state["completed"] is False
    assert state["error"] == "Max steps exceeded"
    assert len(state["visited_nodes"]) == FlowExecutor.MAX_STEPS


def test_injected_design_and_execution_tools_share_the_exact_store() -> None:
    store: dict[str, Flow] = {}

    design = FlowDesignTool(store)
    execution = FlowExecutionTool(store)

    assert design.flows is store
    assert execution.flows is store


async def _design_registered_linear_flow(registry: ToolRegistry, flow_id: str) -> list[str]:
    created = await registry.execute(
        "flow_design",
        {"action": "create_flow", "flow_id": flow_id, "name": f"{flow_id} flow"},
    )
    assert created.ok is True

    node_ids: list[str] = []
    for node_type in ("start", "end"):
        result = await registry.execute(
            "flow_design",
            {"action": "add_node", "flow_id": flow_id, "node_type": node_type, "name": node_type.title()},
        )
        assert result.ok is True
        node_ids.append(result.data["node_id"])

    edge = await registry.execute(
        "flow_design",
        {"action": "add_edge", "flow_id": flow_id, "source": node_ids[0], "target": node_ids[1]},
    )
    assert edge.ok is True
    return node_ids


@pytest.mark.asyncio
async def test_optional_registry_runs_create_design_validate_start_and_execute_end_to_end(monkeypatch) -> None:
    registry = ToolRegistry()
    monkeypatch.setattr(
        tool_extensions,
        "_OPTIONAL_TOOL_MODULES",
        [("thomas.flows.tools", "register_flows_tools")],
    )
    monkeypatch.setattr(tool_extensions, "_register_self_extend", lambda _registry: None)
    monkeypatch.setattr(tool_extensions, "_register_email_calendar", lambda _registry: None)
    monkeypatch.setattr(tool_extensions, "_register_work_google_drive", lambda _registry: None)

    assert tool_extensions.register_all_optional_tools(registry) == 1

    assert [tool.name for tool in registry.list_tools("flows")] == ["flow_design", "flow_execute"]
    created = await registry.execute("flow_design", {"action": "create_flow", "flow_id": "audit", "name": "Audit flow"})
    assert created.ok is True

    node_ids: list[str] = []
    for node_type, name in [("start", "Start"), ("action", "Review"), ("end", "Done")]:
        result = await registry.execute(
            "flow_design",
            {"action": "add_node", "flow_id": "audit", "node_type": node_type, "name": name},
        )
        assert result.ok is True
        node_ids.append(result.data["node_id"])

    for source, target in zip(node_ids[:-1], node_ids[1:], strict=True):
        result = await registry.execute(
            "flow_design", {"action": "add_edge", "flow_id": "audit", "source": source, "target": target}
        )
        assert result.ok is True

    validation = await registry.execute("flow_design", {"action": "validate", "flow_id": "audit"})
    assert validation.ok is True
    assert validation.data == {"valid": True, "error": None}

    started = await registry.execute(
        "flow_execute", {"action": "start_execution", "flow_id": "audit", "variables": {"ticket": 134}}
    )
    assert started.ok is True
    execution_id = started.data["execution_id"]

    completed = await registry.execute("flow_execute", {"action": "execute_full", "execution_id": execution_id})
    assert completed.ok is True
    assert completed.error is None
    assert completed.data["visited_nodes"] == node_ids
    assert completed.data["variables"] == {"ticket": 134}
    assert completed.data["completed"] is True


@pytest.mark.asyncio
async def test_two_flows_in_one_registry_keep_distinct_executions() -> None:
    registry = ToolRegistry()
    register_flows_tools(registry)
    alpha_nodes = await _design_registered_linear_flow(registry, "alpha")
    beta_nodes = await _design_registered_linear_flow(registry, "beta")

    alpha = await registry.execute("flow_execute", {"action": "start_execution", "flow_id": "alpha"})
    beta = await registry.execute("flow_execute", {"action": "start_execution", "flow_id": "beta"})
    alpha_id = alpha.data["execution_id"]
    beta_id = beta.data["execution_id"]

    assert alpha.ok is True
    assert beta.ok is True
    assert alpha_id.startswith("flow_exec_")
    assert beta_id.startswith("flow_exec_")
    assert alpha_id != beta_id

    alpha_done = await registry.execute("flow_execute", {"action": "execute_full", "execution_id": alpha_id})
    beta_waiting = await registry.execute("flow_execute", {"action": "get_state", "execution_id": beta_id})

    assert alpha_done.data["flow_id"] == "alpha"
    assert alpha_done.data["visited_nodes"] == alpha_nodes
    assert beta_waiting.data["flow_id"] == "beta"
    assert beta_waiting.data["visited_nodes"] == []
    assert beta_waiting.data["current_node"] is None

    beta_done = await registry.execute("flow_execute", {"action": "execute_full", "execution_id": beta_id})
    assert beta_done.data["flow_id"] == "beta"
    assert beta_done.data["visited_nodes"] == beta_nodes


@pytest.mark.asyncio
async def test_execution_ids_are_isolated_across_registries() -> None:
    first_registry = ToolRegistry()
    second_registry = ToolRegistry()
    register_flows_tools(first_registry)
    register_flows_tools(second_registry)
    await _design_registered_linear_flow(first_registry, "first")
    await _design_registered_linear_flow(second_registry, "second")

    first = await first_registry.execute("flow_execute", {"action": "start_execution", "flow_id": "first"})
    second = await second_registry.execute("flow_execute", {"action": "start_execution", "flow_id": "second"})
    first_id = first.data["execution_id"]
    second_id = second.data["execution_id"]

    assert first_id != second_id
    foreign = await second_registry.execute("flow_execute", {"action": "get_state", "execution_id": first_id})
    missing = await first_registry.execute("flow_execute", {"action": "get_state", "execution_id": "missing"})
    assert foreign.ok is False
    assert foreign.error == f"Execution {first_id} not found"
    assert missing.ok is False
    assert missing.error == "Execution missing not found"


@pytest.mark.asyncio
async def test_execution_tool_rejects_an_invalid_shared_flow() -> None:
    registry = ToolRegistry()
    register_flows_tools(registry)
    await registry.execute("flow_design", {"action": "create_flow", "flow_id": "invalid", "name": "Invalid"})

    result = await registry.execute("flow_execute", {"action": "start_execution", "flow_id": "invalid"})

    assert result.ok is False
    assert result.error == "Flow invalid is invalid: No start node defined"


@pytest.mark.asyncio
async def test_registered_tools_report_bad_actions_and_missing_records() -> None:
    registry = ToolRegistry()
    register_flows_tools(registry)

    unknown_action = await registry.execute("flow_design", {"action": "erase_everything"})
    missing_flow = await registry.execute("flow_design", {"action": "validate", "flow_id": "missing"})
    missing_execution = await registry.execute("flow_execute", {"action": "execute_step", "execution_id": "missing"})

    assert unknown_action.error == "Unknown action: erase_everything"
    assert missing_flow.error == "Flow missing not found"
    assert missing_execution.error == "Execution missing not found"
