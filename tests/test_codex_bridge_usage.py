from __future__ import annotations

from thomas.marketplace.codex.bridge import _extract_usage_payload


def test_extract_usage_payload_supports_thread_token_usage_updated_shape() -> None:
    payload = {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "tokenUsage": {
            "total": {
                "totalTokens": 27835,
                "inputTokens": 27819,
                "cachedInputTokens": 3456,
                "outputTokens": 16,
                "reasoningOutputTokens": 9,
            },
            "last": {
                "totalTokens": 27835,
                "inputTokens": 27819,
                "cachedInputTokens": 3456,
                "outputTokens": 16,
                "reasoningOutputTokens": 9,
            },
            "modelContextWindow": 258400,
        },
    }

    assert _extract_usage_payload(payload) == {
        "prompt_tokens": 27819,
        "completion_tokens": 16,
        "total_tokens": 27835,
    }


def test_extract_usage_payload_prefers_last_usage_when_available() -> None:
    payload = {
        "tokenUsage": {
            "total": {
                "totalTokens": 300,
                "inputTokens": 250,
                "outputTokens": 50,
            },
            "last": {
                "totalTokens": 120,
                "inputTokens": 100,
                "outputTokens": 20,
            },
        }
    }

    assert _extract_usage_payload(payload) == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
