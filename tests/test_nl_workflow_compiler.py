from __future__ import annotations

from thomas.autonomy.nl_workflow_compiler import compile_nl_workflow_payload


def test_compile_infers_parallel_workers_from_nl_text() -> None:
    payload, meta = compile_nl_workflow_payload(
        {
            "text": "Run this in parallel: gather logs; summarize incidents; draft action plan.",
        }
    )
    assert payload["workflow"] == "parallel"
    assert payload.get("goal")
    workers = payload.get("workers") or []
    assert len(workers) >= 2
    assert isinstance(meta, dict)
    assert "workflow" in (meta.get("changes") or [])


def test_compile_adds_chain_steps_when_missing() -> None:
    payload, meta = compile_nl_workflow_payload(
        {
            "workflow": "chain",
            "goal": "collect requirements then design solution then review tradeoffs",
        }
    )
    assert payload["workflow"] == "chain"
    steps = payload.get("steps") or []
    assert len(steps) >= 2
    assert isinstance(meta, dict)
    assert "steps" in (meta.get("changes") or [])


def test_compile_routing_without_routes_falls_back_to_chain() -> None:
    payload, meta = compile_nl_workflow_payload(
        {
            "workflow": "routing",
            "text": "choose the best approach and write a recommendation",
        }
    )
    assert payload["workflow"] == "chain"
    assert payload.get("steps")
    assert isinstance(meta, dict)
    assert "workflow(chain_fallback)" in (meta.get("changes") or [])

