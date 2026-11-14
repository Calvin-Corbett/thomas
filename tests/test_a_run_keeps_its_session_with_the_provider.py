"""A run's requests to the ChatGPT backend carry its cache key as ``session_id``, so they stay where they are cached.

On 2026-11-06 requests that only grew at the end of the one before them were served 37% from cache: the key was in
the body, but the header the backend keeps a session's calls together by was never sent. Regression for
thomas.core.llm_streaming.stream_openai_codex.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from thomas.core import capture_context, codex_auth
from thomas.core.llm_streaming import stream_openai_codex
from thomas.core.llm_streaming_codex import _run_cache_key

OK = 'event: response.output_text.delta\ndata: {"delta":"hi"}\n\nevent: response.completed\ndata: {"response":{}}\n\n'


class _Lease:
    output_cap = 4096


class _Owner:
    _max_retries = 1
    _base_retry_delay = 0

    def __init__(self, client):
        self.client = client
        self.config = SimpleNamespace(
            name="openai_codex",
            model="gpt-test",
            api_key="fixture-token",
            base_url="https://chatgpt.com/backend-api/codex",
            max_tokens=4096,
        )

    async def _get_client(self):
        return self.client

    async def begin_budget_attempt(self, *_):
        return _Lease()

    async def abort_budget_attempt(self, *_):
        pass

    async def finish_budget_attempt(self, *_):
        pass


async def _headers_of_one_call(monkeypatch) -> httpx.Headers:
    monkeypatch.setattr(codex_auth, "_recovered_tokens", {})
    seen: list[httpx.Headers] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, text=OK)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        [event async for event in stream_openai_codex(_Owner(client), [{"role": "user", "content": "hello"}])]
    assert len(seen) == 1
    return seen[0]


@pytest.mark.asyncio
async def test_a_runs_request_carries_its_key_as_the_session(monkeypatch) -> None:
    token = capture_context.set_capture_run("run-session")
    try:
        headers = await _headers_of_one_call(monkeypatch)
        assert headers["session_id"] == _run_cache_key() and headers["session_id"].startswith("thomas-run-")
    finally:
        capture_context.reset(token)


@pytest.mark.asyncio
async def test_a_request_outside_a_run_names_no_session(monkeypatch) -> None:
    assert capture_context.current() is None
    assert "session_id" not in await _headers_of_one_call(monkeypatch)
