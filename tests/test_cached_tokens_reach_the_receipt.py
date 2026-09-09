"""Cache reads reach the reply receipt (frontier parity: Claude Code /cost shows prompt-cache hits).

Every transport receives a cached-token count from its provider and, until
2026-09-05, dropped it at TokenUsage. The chat page can only show what the
receipt carries.
"""

from __future__ import annotations

from thomas.core.llm_shared import TokenUsage
from thomas.core.llm_streaming_codex import _extract_responses_usage
from thomas.server.routes.chat_v2_usage import terminal_usage_fields


def test_token_usage_carries_and_sums_cache_reads() -> None:
    first = TokenUsage(prompt_tokens=1200, completion_tokens=30, total_tokens=1230, cached_prompt_tokens=1000)
    second = TokenUsage(prompt_tokens=800, completion_tokens=10, total_tokens=810, cached_prompt_tokens=700)
    first.add(second)
    assert first.cached_prompt_tokens == 1700
    assert TokenUsage().cached_prompt_tokens == 0


def test_the_responses_api_cached_count_is_read() -> None:
    usage = _extract_responses_usage(
        {
            "response": {
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 30,
                    "total_tokens": 1230,
                    "input_tokens_details": {"cached_tokens": 1000},
                }
            }
        }
    )
    assert usage is not None
    assert usage.cached_prompt_tokens == 1000
    # chat-completions shape, and a malformed detail block, both stay safe
    assert (
        _extract_responses_usage(
            {"usage": {"prompt_tokens": 5, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 4}}}
        ).cached_prompt_tokens
        == 4
    )
    assert (
        _extract_responses_usage(
            {"usage": {"input_tokens": 5, "output_tokens": 1, "input_tokens_details": "nope"}}
        ).cached_prompt_tokens
        == 0
    )


def test_the_terminal_receipt_carries_cache_reads_from_objects_and_dicts() -> None:
    fields = terminal_usage_fields(
        run_usage=TokenUsage(prompt_tokens=1200, completion_tokens=30, total_tokens=1230, cached_prompt_tokens=1000),
        session_usage={
            "prompt_tokens": 2000,
            "completion_tokens": 40,
            "total_tokens": 2040,
            "cached_prompt_tokens": 1500,
        },
    )
    assert fields["usage"]["cached_prompt_tokens"] == 1000
    assert fields["run_usage"]["cached_prompt_tokens"] == 1000
    assert fields["session_usage"]["cached_prompt_tokens"] == 1500
    # a receipt without the field reads as zero, never as missing
    assert terminal_usage_fields(run_usage={"prompt_tokens": 1})["usage"]["cached_prompt_tokens"] == 0
