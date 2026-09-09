"""A receipt says when the model server reported no usage (2026-09-07).

Driving the chat on :8977 with a local model (qwen2.5-coder:7b through the
OpenAI-compatible path), every reply's receipt read ``This reply 0 in · 0 out ·
~$0.0000``. Nothing about the reply was free: the client never asked the
server for usage (OpenAI-compatible streams only carry it when
``stream_options.include_usage`` is set), no usage event arrived, and the
terminal contract normalized the absence to zeros, which the readout then
priced.

Two changes, tested from both ends here:

* the streaming request asks for usage on every OpenAI-compatible provider
  that honours the field (Azure's older API versions reject it and are left
  alone);
* the terminal usage contract carries ``usage_reported``, false when no count
  reached the server, so the readout can say so instead of showing zeros.
"""

from __future__ import annotations

from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.server.routes.chat_v2_usage import terminal_usage_fields

MESSAGES = [{"role": "user", "content": "hi"}]


def _client(provider: str) -> LLMClient:
    return LLMClient(ModelConfig(name="test", provider=provider, base_url="http://127.0.0.1:1", model="fixture"))


def test_a_streaming_request_asks_the_compatible_server_for_usage() -> None:
    for provider in ("ollama", "openai", "openai_compat", "vllm", "lm_studio"):
        body = _client(provider)._build_openai_request(MESSAGES, stream=True)
        assert body["stream_options"] == {"include_usage": True}, provider


def test_azure_and_non_streaming_requests_are_left_alone() -> None:
    assert "stream_options" not in _client("azure")._build_openai_request(MESSAGES, stream=True)
    assert "stream_options" not in _client("ollama")._build_openai_request(MESSAGES, stream=False)


def test_the_terminal_contract_says_whether_usage_was_reported() -> None:
    silent = terminal_usage_fields(run_usage=None, session_usage=None)
    assert silent["usage_reported"] is False
    assert silent["usage"]["total_tokens"] == 0

    counted = terminal_usage_fields(
        run_usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}, session_usage=None
    )
    assert counted["usage_reported"] is True
    assert counted["usage"]["total_tokens"] == 15
