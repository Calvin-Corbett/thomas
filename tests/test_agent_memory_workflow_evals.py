from __future__ import annotations

from pathlib import Path

import pytest

from agent_memory.app import AgentMemoryApp
from agent_memory.eval.suite import (
    handoff_continuity_test,
    mode_stability_test,
    needle_test,
    no_memory_guardrail_test,
    run_all,
    temporal_contradiction_test,
)


@pytest.fixture
def memory_root(tmp_path: Path) -> Path:
    return tmp_path / "agent-memory-eval"


def test_query_surfaces_handoff_context_and_trace(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        app.log_event(
            thread="handoff",
            etype="note",
            text="Handoff preference: use green accents and preserve retry budget of 3",
        )
        app.log_event(
            thread="handoff",
            etype="note",
            text="Workflow state: waiting on deployment evidence pack",
        )

        out = app.query(thread="handoff", mode="deep", text="what handoff preference did i set")
        packed = str(out.get("packed") or "").lower()

        assert "green" in packed
        assert isinstance(out.get("selected"), list)
        assert (out.get("trace") or {}).get("thread") == "handoff"
    finally:
        app.close()


def test_handoff_continuity_persists_across_restart(memory_root: Path) -> None:
    app1 = AgentMemoryApp(memory_root)
    try:
        app1.log_event(thread="continuity", etype="note", text="I like blue for UI accents")
        app1.log_event(thread="continuity", etype="note", text="Update: use green instead")
    finally:
        app1.close()

    app2 = AgentMemoryApp(memory_root)
    try:
        out = app2.query(thread="continuity", mode="deep", text="what color should i use for ui accents")
        packed = str(out.get("packed") or "").lower()
        assert "green" in packed
    finally:
        app2.close()


def test_temporal_contradiction_eval_prefers_latest_preference(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        result = temporal_contradiction_test(app, thread="temporal")
        assert result.name == "temporal_contradiction"
        assert result.passed
    finally:
        app.close()


def test_mode_stability_eval_surfaces_core_preference_in_fast_and_deep(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        result = mode_stability_test(app, thread="modes")
        assert result.name == "mode_stability"
        assert result.passed
    finally:
        app.close()


def test_run_all_reports_expected_eval_set(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        results = run_all(app)
        by_name = {item.name: item for item in results}

        assert set(by_name) == {
            "needle",
            "temporal_contradiction",
            "mode_stability",
            "handoff_continuity",
            "no_memory_guardrail",
            "latency_smoke",
        }
        assert by_name["needle"].passed
        assert by_name["temporal_contradiction"].passed
        assert by_name["mode_stability"].passed
        assert by_name["handoff_continuity"].passed
        assert by_name["no_memory_guardrail"].passed
    finally:
        app.close()


def test_needle_eval_recovers_fact_after_long_context(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        result = needle_test(app, thread="needle-long-context")
        assert result.name == "needle"
        assert result.passed
    finally:
        app.close()


def test_handoff_continuity_eval_surfaces_latest_owner(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        result = handoff_continuity_test(app, thread="handoff-eval")
        assert result.name == "handoff_continuity"
        assert result.passed
    finally:
        app.close()


def test_no_memory_guardrail_eval_blocks_secret_recall(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        result = no_memory_guardrail_test(app, thread="no-memory-eval")
        assert result.name == "no_memory_guardrail"
        assert result.passed
    finally:
        app.close()


def test_pinned_handoff_instruction_persists_across_restart(memory_root: Path) -> None:
    app1 = AgentMemoryApp(memory_root)
    try:
        app1.rt.meta.pin_set("handoff", "Always continue execution after user says ok")
    finally:
        app1.close()

    app2 = AgentMemoryApp(memory_root)
    try:
        out = app2.query(thread="pin-thread", mode="fast", text="what are pinned handoff instructions")
        packed = str(out.get("packed") or "").lower()
        assert "always continue execution after user says ok" in packed
    finally:
        app2.close()


def test_lexicon_translation_supports_workflow_memory_recall(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        app.log_event(
            thread="lexicon",
            etype="note",
            text="site reliability excellence runbook is stored in vault-7",
        )
        app.rt.meta.lex_add("SREX", "site reliability excellence")

        out = app.query(
            thread="lexicon",
            mode="deep",
            text="where is the SREX runbook stored",
        )
        packed = str(out.get("packed") or "").lower()
        assert "vault-7" in packed
    finally:
        app.close()


def test_nightly_rebuild_preserves_handoff_memory(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        app.log_event(
            thread="nightly",
            etype="note",
            text="Deployment handoff owner is alex and rollback budget is 2",
        )
        build_name = app.nightly()
        out = app.query(thread="nightly", mode="deep", text="who owns deployment handoff")
        packed = str(out.get("packed") or "").lower()

        assert build_name.startswith("build_")
        assert "alex" in packed
    finally:
        app.close()


def test_post_nightly_delta_event_remains_retrievable(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        app.log_event(thread="delta", etype="note", text="Use blue for tabs")
        app.nightly()
        app.log_event(thread="delta", etype="note", text="Correction: use green for tabs")

        out = app.query(thread="delta", mode="deep", text="what color should tabs use")
        packed = str(out.get("packed") or "").lower()
        assert "green" in packed
    finally:
        app.close()


def test_trace_history_records_query_modes_and_selected_ids(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        app.log_event(thread="trace", etype="note", text="trace baseline entry")
        app.query(thread="trace", mode="fast", text="trace ping")
        app.query(thread="trace", mode="deep", text="trace detailed question")

        traces = list(app.rt.meta.trace_iter(limit=10))
        assert len(traces) >= 2

        modes = [row[2] for row in traces]
        assert "fast" in modes
        assert "deep" in modes
        assert all(isinstance((row[4] or {}).get("selected"), list) for row in traces[:2])
    finally:
        app.close()


def test_no_memory_mode_omits_retrieval_context(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        app.log_event(thread="privacy", etype="note", text="secret token is ORANGE-DELTA")
        out = app.query(thread="privacy", mode="no_memory", text="what is my secret token")
        packed = str(out.get("packed") or "").lower()

        assert "orange-delta" not in packed
        assert "mode: no_memory" in packed
        assert out.get("selected") == []
        assert ((out.get("trace") or {}).get("mode") or "") == "no_memory"
    finally:
        app.close()


def test_deep_query_does_not_leak_other_thread_graph_receipts(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        app.log_event(
            thread="thread_a",
            etype="note",
            text="project SECRETX has credential ORANGE-DELTA",
        )
        app.log_event(thread="thread_b", etype="note", text="This thread should stay isolated.")

        out = app.query(thread="thread_b", mode="deep", text="secretx")
        packed = str(out.get("packed") or "").lower()

        assert "orange-delta" not in packed
        assert "credential" not in packed
    finally:
        app.close()


def test_trace_payload_respects_selected_and_candidate_bounds(memory_root: Path) -> None:
    app = AgentMemoryApp(memory_root)
    try:
        for idx in range(260):
            app.log_event(
                thread="bounds",
                etype="note",
                text=f"event {idx} with project alpha and preference signal",
            )

        out = app.query(thread="bounds", mode="deep", text="alpha preference signal")
        trace = out.get("trace") or {}

        assert len(trace.get("selected") or []) <= 10
        assert len(trace.get("candidates") or []) <= 80
    finally:
        app.close()
