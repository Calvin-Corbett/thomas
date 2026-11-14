"""Every model call lands in the token log, with what the provider served from its cache and wrote into it.

You asked for a token log on 2026-11-06. The step log (thomas.core.step_log) already had a row for each model call
with its prompt and completion tokens, in every process that makes one, summed at /api/metrics/steps; but the cache
reads and writes were dropped on the way, so whether prompt caching worked could not be read. Regression for
thomas.core.capture_context (the one place every model call passes), the Claude CLI's usage, and
thomas.core.step_report (tokens and the cached share per model).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.core import capture_context, step_log, step_report
from thomas.core.llm_shared import StreamEvent, TokenUsage
from thomas.core.llm_streaming_claude_cli import _usage_event


class _Owner:
    def __init__(self) -> None:
        self.session_usage = TokenUsage()


def _call(usage: TokenUsage, model: str = "gpt-6.1-sol") -> None:
    state = capture_context.CaptureState(run_id=None, correlation="ambient")
    capture_context.record_stream_event(state, StreamEvent(type="usage", data={"usage": usage}))
    capture_context.end_model_capture(
        state,
        interrupted=False,
        served_by_model=model,
        served_by_provider="openai_codex",
        provider_attempts=1,
        merged_partial_output=False,
    )


def _rows(folder: Path) -> list[dict]:
    return [json.loads(line) for day in folder.glob("steps-*.jsonl") for line in day.read_text("utf-8").splitlines()]


def test_a_model_call_writes_its_cache_use_to_the_step_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(step_log.DIR_ENV, str(tmp_path))
    _call(TokenUsage(prompt_tokens=1000, completion_tokens=50, total_tokens=1050, cached_prompt_tokens=800))
    _call(TokenUsage(prompt_tokens=10, completion_tokens=1, total_tokens=11))

    first, second = _rows(tmp_path)
    assert (first["step"], first["model"], first["prompt_tokens"], first["completion_tokens"]) == (
        "model",
        "gpt-6.1-sol",
        1000,
        50,
    )
    assert first["cached_prompt_tokens"] == 800 and first["cache_write_prompt_tokens"] == 0
    assert second["cached_prompt_tokens"] == 0, "a call that cached nothing says 0, so it is told from an old row"


def test_the_captured_reply_payload_is_unchanged() -> None:
    state = capture_context.CaptureState(run_id=None, correlation="ambient", active=True)
    usage = TokenUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7, cached_prompt_tokens=4)
    capture_context.record_stream_event(state, StreamEvent(type="usage", data={"usage": usage}))
    assert state.usage == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    assert state.cached_prompt_tokens == 4


def test_the_claude_cli_reports_its_cache_writes() -> None:
    event = _usage_event(
        _Owner(),
        {"input_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 40, "output_tokens": 9},
    )
    assert event is not None
    usage = event.data["usage"]
    assert (usage.prompt_tokens, usage.cached_prompt_tokens, usage.cache_write_prompt_tokens) == (145, 100, 40)


def test_session_totals_add_cache_writes() -> None:
    total = TokenUsage()
    total.add(TokenUsage(prompt_tokens=10, cache_write_prompt_tokens=3))
    total.add(TokenUsage(prompt_tokens=10, cache_write_prompt_tokens=4))
    assert total.cache_write_prompt_tokens == 7


def test_the_step_summary_shows_tokens_and_the_cached_share_per_model() -> None:
    rows = [
        {"step": "model", "model": "a", "seconds": 1.0, "prompt_tokens": 1000, "completion_tokens": 10},
        {
            "step": "model",
            "model": "a",
            "seconds": 1.0,
            "prompt_tokens": 400,
            "completion_tokens": 5,
            "cached_prompt_tokens": 300,
            "cache_write_prompt_tokens": 0,
        },
        {"step": "model", "model": "b", "seconds": 2.0, "prompt_tokens": 50, "completion_tokens": 1},
    ]
    model = step_report.summarize(rows)["model"]
    assert model["prompt_tokens"] == 1450 and model["completion_tokens"] == 16
    assert model["cached_prompt_tokens"] == 300 and model["cache_reported_calls"] == 1
    assert model["cached_share"] == 0.75, "only calls that reported their cache use count toward the share"
    assert model["by_model"]["a"]["prompt_tokens"] == 1400 and model["by_model"]["a"]["count"] == 2
    assert model["by_model"]["b"]["cached_share"] is None, "no report is not the same as nothing cached"
