from __future__ import annotations

from thomas.marketplace.autonomy.nl_workflow_compiler import compile_nl_workflow_payload


def test_prose_does_not_select_parallel_or_create_workers() -> None:
    payload, meta = compile_nl_workflow_payload(
        {"text": "Run this in parallel: gather logs; summarize incidents; draft action plan."}
    )
    assert payload["workflow"] == "chain"
    assert payload["steps"] == [payload["text"]]
    assert "workers" not in payload
    assert isinstance(meta, dict)
    assert "workflow(neutral_default)" in (meta.get("changes") or [])


def test_prose_connectors_do_not_split_a_chain_into_multiple_tasks() -> None:
    goal = "collect requirements then design solution then review tradeoffs"
    payload, meta = compile_nl_workflow_payload({"workflow": "chain", "goal": goal})
    assert payload["workflow"] == "chain"
    assert payload["steps"] == [goal]
    assert isinstance(meta, dict)
    assert "steps(single_task_default)" in (meta.get("changes") or [])


def test_explicit_parallel_workers_are_preserved_exactly() -> None:
    workers = [{"name": "facts", "prompt": "Gather facts", "capability": "research"}]
    payload, meta = compile_nl_workflow_payload({"workflow": "parallel", "goal": "Prepare a brief", "workers": workers})
    assert payload["workflow"] == "parallel"
    assert payload["workers"] == workers
    assert meta is None


def test_incomplete_structured_routing_is_not_inferred_from_text() -> None:
    payload, _meta = compile_nl_workflow_payload(
        {"workflow": "routing", "text": "if urgent then page someone else archive it"}
    )
    assert payload["workflow"] == "routing"
    assert "routes" not in payload
