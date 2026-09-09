"""CAP-041: cheap-model periodic status summaries with change-only cadence.

Acceptance line: "Add low-cost periodic status summaries with change-only
cadence and per-summary cost."

Every test uses an injected fake adapter -- no live model calls.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from thomas.core.status_summaries import (
    SkippedSummary,
    StatusSummarizer,
    StatusSummary,
)


class ScriptedAdapter:
    """Fake cheap-model adapter returning scripted JSON, recording each call."""

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls: list[list[dict[str, Any]]] = []

    async def __call__(self, messages: list[dict[str, Any]]) -> str:
        self.calls.append(messages)
        if not self.outputs:
            raise AssertionError("adapter called more times than scripted")
        return self.outputs.pop(0)


def _status(summary: str, status: str = "running") -> str:
    return json.dumps({"status": status, "summary": summary})


# ---------------------------------------------------------------------------
# 1. Summaries emit on cadence (steps mode).
# ---------------------------------------------------------------------------


def test_summaries_emit_on_step_cadence():
    adapter = ScriptedAdapter([_status("step 1"), _status("step 4")])
    summ = StatusSummarizer(adapter, model_profile="cheapo-mini", interval_steps=3)

    # The first call always fires cadence (initial summary) -> a summary.
    first = asyncio.run(summ.maybe_summarize("d1", "ctx", step=1))
    assert isinstance(first, StatusSummary)
    assert first.text == "step 1"
    assert first.step == 1
    # Steps 2 and 3 are before the next interval boundary (anchor 1 + 3) -> not due.
    assert asyncio.run(summ.maybe_summarize("d2", "ctx", step=2)) is None
    assert asyncio.run(summ.maybe_summarize("d3", "ctx", step=3)) is None
    # Step 4 fires cadence again and state changed -> a summary.
    second = asyncio.run(summ.maybe_summarize("d4", "ctx", step=4))
    assert isinstance(second, StatusSummary)
    assert second.text == "step 4"
    assert len(summ.summaries) == 2
    assert len(adapter.calls) == 2


def test_summaries_emit_on_seconds_cadence():
    adapter = ScriptedAdapter([_status("t0"), _status("t10")])
    summ = StatusSummarizer(adapter, model_profile="cheapo-mini", interval_seconds=10)

    a = asyncio.run(summ.maybe_summarize("d0", "ctx", now=100.0))
    assert isinstance(a, StatusSummary)  # first call always due
    assert asyncio.run(summ.maybe_summarize("d1", "ctx", now=105.0)) is None  # < 10s
    b = asyncio.run(summ.maybe_summarize("d2", "ctx", now=111.0))
    assert isinstance(b, StatusSummary)  # >= 10s later
    assert len(adapter.calls) == 2


# ---------------------------------------------------------------------------
# 2. Change-only: an unchanged digest is SKIPPED with no model call.
# ---------------------------------------------------------------------------


def test_unchanged_digest_is_skipped_no_model_call():
    adapter = ScriptedAdapter([_status("only once")])
    summ = StatusSummarizer(adapter, model_profile="cheapo-mini", interval_steps=1)

    first = asyncio.run(summ.maybe_summarize("SAME", "ctx", step=1))
    assert isinstance(first, StatusSummary)

    # Cadence fires again (interval 1) but the digest is identical -> skipped.
    skip = asyncio.run(summ.maybe_summarize("SAME", "ctx", step=2))
    assert isinstance(skip, SkippedSummary)
    assert skip.changed is False
    assert skip.reason == "unchanged"
    assert skip.cost == 0.0
    # Crucially, the cheap model was NOT called for the skip.
    assert len(adapter.calls) == 1
    assert len(summ.summaries) == 1
    assert len(summ.skipped) == 1


# ---------------------------------------------------------------------------
# 3. Each emitted summary reports its own token + cost.
# ---------------------------------------------------------------------------


def test_each_summary_reports_its_own_token_and_cost():
    # Deterministic estimator: 1 token per character, so token math is exact.
    def one_per_char(text: str) -> int:
        return len(text)

    completion = _status("done")  # counted as completion tokens
    adapter = ScriptedAdapter([completion])
    summ = StatusSummarizer(
        adapter,
        model_profile="cheapo-mini",
        interval_steps=1,
        cost_per_1k=2.0,
        token_estimator=one_per_char,
    )

    out = asyncio.run(summ.maybe_summarize("d", "PROMPT_CTX", step=1))
    assert isinstance(out, StatusSummary)
    assert out.prompt_tokens == len("PROMPT_CTX")
    assert out.completion_tokens == len(completion)
    assert out.total_tokens == out.prompt_tokens + out.completion_tokens
    expected_cost = round(out.total_tokens / 1000.0 * 2.0, 6)
    assert out.cost == expected_cost
    assert out.cost > 0.0
    assert out.model_profile == "cheapo-mini"


def test_skipped_summary_has_zero_cost():
    adapter = ScriptedAdapter([_status("first")])
    summ = StatusSummarizer(adapter, model_profile="cheapo-mini", interval_steps=1, cost_per_1k=5.0)
    asyncio.run(summ.maybe_summarize("x", "ctx", step=1))
    before = summ.total_cost
    skip = asyncio.run(summ.maybe_summarize("x", "ctx", step=2))
    assert isinstance(skip, SkippedSummary)
    assert skip.cost == 0.0
    # A skip adds no cost to the running session total.
    assert summ.total_cost == before


# ---------------------------------------------------------------------------
# 4. Total cost sums across a session (and skips do not inflate it).
# ---------------------------------------------------------------------------


def test_total_cost_sums_across_session():
    def one_per_char(text: str) -> int:
        return len(text)

    outs = [_status("a"), _status("b"), _status("c")]
    adapter = ScriptedAdapter(list(outs))
    summ = StatusSummarizer(
        adapter,
        model_profile="cheapo-mini",
        interval_steps=1,
        cost_per_1k=1.0,
        token_estimator=one_per_char,
    )

    emitted = []
    # changed, changed, unchanged(skip), changed -> 3 emits + 1 skip
    emitted.append(asyncio.run(summ.maybe_summarize("d1", "ctx", step=1)))
    emitted.append(asyncio.run(summ.maybe_summarize("d2", "ctx", step=2)))
    skip = asyncio.run(summ.maybe_summarize("d2", "ctx", step=3))
    emitted.append(asyncio.run(summ.maybe_summarize("d3", "ctx", step=4)))

    assert isinstance(skip, SkippedSummary)
    summaries = [e for e in emitted if isinstance(e, StatusSummary)]
    assert len(summaries) == 3
    expected_total = round(sum(s.cost for s in summaries), 6)
    assert summ.total_cost == expected_total
    # usage_telemetry grand total reconciles with the summed per-summary tokens.
    assert summ.total_tokens == sum(s.total_tokens for s in summaries)


def test_telemetry_categorizes_prompt_and_completion():
    def one_per_char(text: str) -> int:
        return len(text)

    adapter = ScriptedAdapter([_status("x")])
    summ = StatusSummarizer(
        adapter,
        model_profile="cheapo-mini",
        interval_steps=1,
        cost_per_1k=1.0,
        token_estimator=one_per_char,
    )
    out = asyncio.run(summ.maybe_summarize("d", "CTX", step=1))
    report = summ.telemetry.report()
    assert report["subtotals"]["prompt"] == out.prompt_tokens
    assert report["subtotals"]["completion"] == out.completion_tokens
    assert report["grand_total"] == out.total_tokens


# ---------------------------------------------------------------------------
# 5. The cheap-model adapter is injectable (no live model).
# ---------------------------------------------------------------------------


def test_adapter_is_injectable():
    sentinel = _status("from injected adapter", status="green")
    adapter = ScriptedAdapter([sentinel])
    summ = StatusSummarizer(adapter, model_profile="whatever", interval_steps=1)
    out = asyncio.run(summ.maybe_summarize("d", "ctx", step=1))
    assert isinstance(out, StatusSummary)
    assert out.fields["status"] == "green"
    assert out.text == "from injected adapter"
    # Proof the injected adapter (and only it) produced the content.
    assert len(adapter.calls) == 1


# ---------------------------------------------------------------------------
# 6. Change-only cadence proven across a same-then-different sequence.
# ---------------------------------------------------------------------------


def test_change_only_cadence_across_same_then_different_states():
    # Sequence of digests: A (new), A (same), A (same), B (new), B (same), C (new)
    # Only the *changed* states should trigger a cheap-model call.
    adapter = ScriptedAdapter([_status("A"), _status("B"), _status("C")])
    summ = StatusSummarizer(adapter, model_profile="cheapo-mini", interval_steps=1)

    digests = ["A", "A", "A", "B", "B", "C"]
    feed = []
    for i, d in enumerate(digests, start=1):
        feed.append(asyncio.run(summ.maybe_summarize(d, "ctx", step=i)))

    kinds = ["emit" if isinstance(x, StatusSummary) else "skip" for x in feed]
    assert kinds == ["emit", "skip", "skip", "emit", "skip", "emit"]
    # Exactly one model call per changed state.
    assert len(adapter.calls) == 3
    assert [s.text for s in summ.summaries] == ["A", "B", "C"]
    assert len(summ.skipped) == 3
    # The history feed preserves emit/skip order for a UI to render.
    assert len(summ.history) == 6


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_requires_exactly_one_cadence():
    with pytest.raises(ValueError):
        StatusSummarizer(ScriptedAdapter([]), model_profile="m")
    with pytest.raises(ValueError):
        StatusSummarizer(ScriptedAdapter([]), model_profile="m", interval_steps=1, interval_seconds=1)


def test_rejects_nonpositive_interval():
    with pytest.raises(ValueError):
        StatusSummarizer(ScriptedAdapter([]), model_profile="m", interval_steps=0)
    with pytest.raises(ValueError):
        StatusSummarizer(ScriptedAdapter([]), model_profile="m", interval_seconds=-1)
