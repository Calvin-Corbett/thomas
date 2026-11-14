"""A ChatGPT answer that says it is overloaded, before any output, is asked again instead of ending the run (2026-10-26).

On 2026-10-26 eight Build runs ended on "Our servers are currently overloaded. Please try again later.": the codex stream
raised it as a plain failure, nothing above retried it, and each team started its next run from scratch. Now the
request is sent again after 15 s, then 30 s. A failure after part of the answer reached the caller, a rate limit, or
anything that is not an overload or a server error still goes up at once.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.test_codex_revoked_recovery import _Owner
from thomas.core import llm_streaming
from thomas.core.llm_shared import LLMError
from thomas.core.llm_streaming import stream_openai_codex

OVERLOADED = 'event: response.failed\ndata: {"error":{"message":"Our servers are currently overloaded. Please try again later."}}\n\n'
REFUSED = 'event: response.failed\ndata: {"error":{"message":"Invalid prompt: the request was refused."}}\n\n'
ANSWER = (
    'event: response.output_text.delta\ndata: {"delta":"ok"}\n\nevent: response.completed\ndata: {"response":{}}\n\n'
)
PARTIAL_THEN_OVERLOADED = 'event: response.output_text.delta\ndata: {"delta":"half"}\n\n' + OVERLOADED


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(llm_streaming.asyncio, "sleep", sleep)
    return waits


async def _ask(bodies: list[str]) -> tuple[list[Any], int]:
    sent: list[int] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        sent.append(1)
        return httpx.Response(200, text=bodies[min(len(sent), len(bodies)) - 1])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        owner = _Owner(client)
        owner.config.api_key, owner._max_retries = "token", 3
        events = [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hi"}])]
    return events, len(sent)


@pytest.mark.asyncio
async def test_an_overloaded_answer_before_any_output_is_asked_again(slept: list[float]) -> None:
    events, sent = await _ask([OVERLOADED, ANSWER])
    assert any(event.type == "token" for event in events) and sent == 2
    assert slept == [15.0], "it waits before asking again"


@pytest.mark.asyncio
async def test_an_overload_that_lasts_still_ends_the_run_after_two_waits(slept: list[float]) -> None:
    with pytest.raises(LLMError, match="overloaded"):
        await _ask([OVERLOADED])
    assert slept == [15.0, 30.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [REFUSED, PARTIAL_THEN_OVERLOADED], ids=["not an overload", "after part of the answer"]
)
async def test_anything_else_goes_up_at_once(slept: list[float], body: str) -> None:
    sent: list[int] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        sent.append(1)
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        owner = _Owner(client)
        owner.config.api_key, owner._max_retries = "token", 3
        with pytest.raises(LLMError):
            [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hi"}])]
    assert sent == [1] and slept == [], "asked once: never repeated after output, never for a refusal"
