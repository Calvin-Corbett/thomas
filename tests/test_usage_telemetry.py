"""Tests for CAP-014 context/token usage telemetry.

Acceptance line: "Expose prompt, completion, tool, compaction, and retrieval
usage with totals that reconcile within 5%."
"""

from __future__ import annotations

import threading

import pytest

from thomas.core.usage_telemetry import (
    CATEGORIES,
    ReconciliationResult,
    UsageTelemetry,
)


def test_records_all_five_categories_and_reports_totals():
    tel = UsageTelemetry()
    tel.record_prompt(1000, {"note": "system+user"})
    tel.record_completion(250)
    tel.record_tool(120)
    tel.record_compaction(30)
    tel.record_retrieval(100)

    report = tel.report()
    subtotals = report["subtotals"]

    assert set(subtotals) == set(CATEGORIES)
    assert subtotals["prompt"] == 1000
    assert subtotals["completion"] == 250
    assert subtotals["tool"] == 120
    assert subtotals["compaction"] == 30
    assert subtotals["retrieval"] == 100

    # Grand total is the sum of every category.
    assert report["grand_total"] == 1000 + 250 + 120 + 30 + 100 == 1500
    assert report["categories"]["prompt"]["events"] == 1
    assert report["categories"]["prompt"]["metadata"] == [{"note": "system+user"}]


def test_repeated_records_accumulate():
    tel = UsageTelemetry()
    tel.record_prompt(400)
    tel.record_prompt(600)
    assert tel.subtotals()["prompt"] == 1000
    assert tel.report()["categories"]["prompt"]["events"] == 2


def test_unknown_category_rejected():
    tel = UsageTelemetry()
    with pytest.raises(ValueError):
        tel.record("hallucinated", 10)


def test_negative_and_garbage_token_counts_floored_to_zero():
    tel = UsageTelemetry()
    tel.record_prompt(-50)
    tel.record_completion("not-a-number")
    tel.record_tool(None)
    assert tel.grand_total() == 0


def test_reconcile_passes_at_exact_equality():
    tel = UsageTelemetry()
    tel.record_prompt(1000)
    tel.record_completion(500)
    result = tel.reconcile(1500)
    assert isinstance(result, ReconciliationResult)
    assert result.ok is True
    assert bool(result) is True
    assert result.grand_total == 1500
    assert result.delta == 0
    assert result.delta_pct == 0.0


def test_reconcile_passes_within_five_percent():
    tel = UsageTelemetry()
    tel.record_prompt(1000)
    # Grand total 1000; independent measure 1040 -> ~3.85% off, inside 5%.
    result = tel.reconcile(1040)
    assert result.ok is True
    assert result.delta == -40
    assert result.delta_pct == pytest.approx(3.8462, abs=1e-3)


def test_reconcile_passes_at_exactly_five_percent_boundary():
    tel = UsageTelemetry()
    tel.record_prompt(1050)
    # 1050 vs 1000 -> exactly 5.0% high; boundary is inclusive.
    result = tel.reconcile(1000)
    assert result.delta_pct == 5.0
    assert result.ok is True


def test_reconcile_fails_beyond_five_percent():
    tel = UsageTelemetry()
    tel.record_prompt(1000)
    tel.record_completion(200)
    # Grand total 1200 vs independent 1000 -> 20% off.
    result = tel.reconcile(1000)
    assert result.ok is False
    assert result.delta == 200
    assert result.delta_pct == pytest.approx(20.0)


def test_reconcile_custom_tolerance_override():
    tel = UsageTelemetry()
    tel.record_prompt(1100)
    # 10% off: fails at default 5%, passes when tolerance widened to 15%.
    assert tel.reconcile(1000).ok is False
    assert tel.reconcile(1000, tolerance_pct=15.0).ok is True


def test_from_token_report_maps_realistic_report_and_reconciles():
    # A realistic token_report as produced by
    # thomas.agent.loop_streaming.build_token_report.
    report = {
        "mode": "deep",
        "iterations": 2,
        "prompt_tokens": 1200,
        "completion_tokens": 300,
        "total_tokens": 1500,
        "peak_context_tokens": 1500,
        "avg_context_tokens": 1200,
        "memory_context_tokens": 400,
        "tool_output_chars_total": 8000,
        "tool_output_chars_kept": 2000,
        "tool_output_chars_dropped": 6000,
        "prompt_chars": 4800,
    }

    tel = UsageTelemetry.from_token_report(report)
    subtotals = tel.subtotals()

    # retrieval = memory_context_tokens
    assert subtotals["retrieval"] == 400
    # tool = tool_output_chars_kept / 4
    assert subtotals["tool"] == 500
    # prompt = prompt_tokens - retrieval - tool (residual base prompt)
    assert subtotals["prompt"] == 1200 - 400 - 500 == 300
    assert subtotals["completion"] == 300
    # plain turn report -> no compaction
    assert subtotals["compaction"] == 0

    # Categories partition the billed total, so they reconcile exactly.
    assert tel.grand_total() == report["total_tokens"]
    assert tel.reconcile(report["total_tokens"]).ok is True
    assert tel.reconcile(report["total_tokens"]).delta_pct == 0.0


def test_from_token_report_maps_the_real_build_token_report_shape():
    # Exercise the genuine producer to prove the mapping is not invented.
    from types import SimpleNamespace

    from thomas.agent.loop_streaming import build_token_report

    agent = SimpleNamespace(_context_window=200_000)
    report = build_token_report(
        agent,
        prompt_text="hello world " * 40,
        usage_obj={"prompt_tokens": 2000, "completion_tokens": 500, "total_tokens": 2500},
        mode="deep",
        iterations=3,
        peak_context_tokens=2500,
        avg_context_tokens=2000,
        memory_tokens=600,
        tool_chars_total=12_000,
        tool_chars_kept=4_000,
    )

    tel = UsageTelemetry.from_token_report(report)
    result = tel.reconcile(report["total_tokens"])
    assert result.ok is True
    assert result.delta_pct <= 5.0
    # The five categories must all be present in the report surface.
    assert set(tel.report()["subtotals"]) == set(CATEGORIES)


def test_from_token_report_bounds_retrieval_and_tool_to_prompt():
    # Retrieval + estimated tool tokens must never exceed prompt_tokens.
    report = {
        "prompt_tokens": 500,
        "completion_tokens": 100,
        "total_tokens": 600,
        "memory_context_tokens": 400,
        "tool_output_chars_kept": 8000,  # ~2000 tokens, way over the prompt
    }
    tel = UsageTelemetry.from_token_report(report)
    sub = tel.subtotals()
    assert sub["retrieval"] == 400
    assert sub["retrieval"] + sub["tool"] <= report["prompt_tokens"]
    assert sub["prompt"] >= 0
    # Still a clean partition of the billed total.
    assert tel.grand_total() == report["total_tokens"]


def test_from_token_report_with_compaction_section():
    report = {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "total_tokens": 1200,
        "memory_context_tokens": 0,
        "tool_output_chars_kept": 0,
        "compaction": {"tokens": 40},
    }
    tel = UsageTelemetry.from_token_report(report)
    assert tel.subtotals()["compaction"] == 40
    # Compaction is genuinely extra spend on top of the billed turn total,
    # but it stays within 5% of that total here.
    assert tel.reconcile(report["total_tokens"]).ok is True
    assert tel.grand_total() == 1240


def test_from_token_report_handles_empty_report():
    tel = UsageTelemetry.from_token_report(None)
    assert tel.grand_total() == 0
    assert tel.reconcile(0).ok is True


def test_thread_safety_concurrent_records_sum_correctly():
    tel = UsageTelemetry()
    per_thread = 1000
    threads_per_category = 4

    def worker(category: str) -> None:
        for _ in range(per_thread):
            tel.record(category, 1)

    threads = []
    for category in CATEGORIES:
        for _ in range(threads_per_category):
            threads.append(threading.Thread(target=worker, args=(category,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    sub = tel.subtotals()
    expected_per_category = per_thread * threads_per_category
    for category in CATEGORIES:
        assert sub[category] == expected_per_category
        assert tel.report()["categories"][category]["events"] == expected_per_category

    total = expected_per_category * len(CATEGORIES)
    assert tel.grand_total() == total
    assert tel.reconcile(total).ok is True
