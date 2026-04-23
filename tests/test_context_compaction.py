from __future__ import annotations

from thomas.agent.context_compaction import ContextCompactor


def test_token_usage_info_defaults_to_unknown_budget() -> None:
    compactor = ContextCompactor()
    usage = compactor.token_usage_info([{"role": "user", "content": "hello world"}])

    assert usage["context_window"] == 0
    assert usage["usage_pct"] == 0
    assert usage["should_compact"] is False
    assert usage["display_budget"] == "0"


def test_token_usage_info_respects_context_window_when_provided() -> None:
    compactor = ContextCompactor()
    usage = compactor.token_usage_info([{"role": "user", "content": "hello world"}], context_window=4000)

    assert usage["context_window"] == 4000
    assert usage["display_budget"] == "4.0k"
    assert usage["usage_pct"] > 0
