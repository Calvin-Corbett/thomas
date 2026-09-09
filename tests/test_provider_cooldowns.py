"""A provider cooldown is visible to the page (frontier parity: Codex rate-limit banner, 2026-09-05).

The LLM client parks a profile for a while after a 429 or a server failure and
the chat turn fails with a generic error; nothing told the person the model
was resting or for how long. A reader over the client's cooldown registry and
a route expose it.
"""

from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import llm_client
from thomas.core.provider_cooldowns import active_cooldowns
from thomas.server.routes.cooldown_routes import setup_cooldown_routes


def _reset() -> None:
    llm_client._PROVIDER_COOLDOWNS.clear()


def test_active_cooldowns_list_the_resting_profiles_with_seconds_left() -> None:
    _reset()
    llm_client._get_cooldown("gpt-5.6-sol").mark("rate_limit", base_s=20.0)
    llm_client._get_cooldown("claude-x").mark("server", base_s=5.0)
    llm_client._get_cooldown("idle")  # registered but never marked

    rows = active_cooldowns()
    by_key = {r["profile"]: r for r in rows}
    assert set(by_key) == {"gpt-5.6-sol", "claude-x"}
    assert by_key["gpt-5.6-sol"]["failure_type"] == "rate_limit"
    assert 18 <= by_key["gpt-5.6-sol"]["remaining_s"] <= 20
    assert by_key["claude-x"]["failure_type"] == "server"
    # longest wait first, so the page can show the one that matters
    assert rows[0]["profile"] == "gpt-5.6-sol"

    llm_client._get_cooldown("gpt-5.6-sol").clear()
    assert [r["profile"] for r in active_cooldowns()] == ["claude-x"]
    _reset()


def test_the_route_reports_them_and_an_empty_list_when_nothing_rests() -> None:
    _reset()
    app = web.Application()
    setup_cooldown_routes(app, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            quiet = await (await client.get("/api/chat/cooldowns")).json()
            llm_client._get_cooldown("gpt-5.6-sol").mark("rate_limit", base_s=30.0)
            resting = await (await client.get("/api/chat/cooldowns")).json()
            return quiet, resting

    quiet, resting = asyncio.run(scenario())
    assert quiet == {"cooldowns": []}
    assert resting["cooldowns"][0]["profile"] == "gpt-5.6-sol"
    assert resting["cooldowns"][0]["failure_type"] == "rate_limit"
    assert resting["cooldowns"][0]["remaining_s"] >= 28
    _reset()
