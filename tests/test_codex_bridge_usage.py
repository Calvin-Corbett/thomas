from __future__ import annotations

from thomas.marketplace.codex.bridge import _command_display_name, _extract_usage_payload, _file_change_path


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


def test_command_display_name_accepts_string_or_argv_shapes() -> None:
    assert _command_display_name("python -m pytest -q") == "python -m pytest -q"
    assert _command_display_name(["python", "-m", "pytest", "-q"]) == "python -m pytest -q"
    assert _command_display_name("") == "?"


def test_file_change_path_accepts_known_codex_item_shapes() -> None:
    assert _file_change_path({"filePath": "a.py"}) == "a.py"
    assert _file_change_path({"path": "b.py"}) == "b.py"
    assert _file_change_path({"changes": [{"relativePath": "c.py"}]}) == "c.py"
    assert _file_change_path({}) == "?"
