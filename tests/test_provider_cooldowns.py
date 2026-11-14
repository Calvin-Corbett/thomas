"""A provider cooldown is visible to the page (frontier parity: Codex rate-limit banner, 2026-09-05).

The LLM client parks a profile for a while after a 429 or a server failure and
the chat turn fails with a generic error; nothing told the person the model
was resting or for how long. A reader over the client's cooldown registry and
a route expose it.

``thomas.server.rows.cooldown_and_logs`` is what puts that route on a real
server. This names it because a check finds a test by what it imports or spells
out, so a change to the row runs this file only through this line.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import llm_client
from thomas.core.provider_cooldowns import active_cooldowns, limit_rows, spent_allowances
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


def test_a_park_set_by_a_spent_allowance_carries_the_limit_and_its_reset() -> None:
    """The park is capped at ten minutes; the allowance behind it can be out for a day
    and a half. ``remaining_s`` alone is "please wait a moment" as a countdown, so the
    row also carries whose limit it is and when it resets -- read from the refusal the
    park remembers, by the one reader, and worded there.
    """
    _reset()
    resets_at = int(time.time()) + 36 * 3600
    error = {"type": "usage_limit_reached", "message": "The usage limit has been reached", "plan_type": "pro",
             "resets_at": resets_at, "resets_in_seconds": 36 * 3600}  # fmt: skip
    body = json.dumps({"error": error}, separators=(",", ":"))
    llm_client._get_cooldown("gpt-5.6-sol").mark(
        "rate_limit", base_s=600.0, refusal=f"ChatGPT/Codex HTTP 429 rate limited. {body[:240]}"
    )
    # a genuine burst, and a park with no words kept, must claim nothing
    burst = 'Anthropic HTTP 429 rate limited. Retry after about 20s. {"error":{"type":"rate_limit_error"}}'
    llm_client._get_cooldown("claude-x").mark("rate_limit", base_s=20.0, refusal=burst)
    llm_client._get_cooldown("silent").mark("server", base_s=30.0)

    rows = {r["profile"]: r for r in active_cooldowns()}

    spent = rows["gpt-5.6-sol"]
    assert spent["spent"] is True and spent["account"] == "ChatGPT Pro"
    assert int(spent["resets_at"]) == resets_at
    when = datetime.fromtimestamp(resets_at)
    assert spent["resets_words"] == f"{when:%A} {when.day} {when:%B} at {when:%H:%M}"
    assert spent["resets_estimated"] is False
    assert spent["remaining_s"] <= 600, "the park is still only the park"
    for quiet in ("claude-x", "silent"):
        assert "spent" not in rows[quiet] and "resets_at" not in rows[quiet]
    _reset()


def _spent_refusal(resets_at: int) -> str:
    body = json.dumps(
        {"error": {"type": "usage_limit_reached", "plan_type": "pro", "resets_at": resets_at}},
        separators=(",", ":"),
    )
    return f"ChatGPT/Codex HTTP 429 rate limited. {body}"


def test_the_page_is_still_told_about_a_limit_after_its_park_has_lifted() -> None:
    """The park is the wrong clock for the line under the message box.

    A rate-limit park is capped at ten minutes and the limit you met ran 41 hours, so
    read on the park alone the line went quiet eleven minutes in -- and a chat page
    opened over the rest of that day said nothing about the limit until a message was
    sent and refused again. ``limit_rows`` is what the route serves: the parks, plus
    an allowance that is still out, with no park left to count. A burst that has
    cleared is not resting and stays out of it.
    """
    _reset()
    resets_at = int(time.time()) + 36 * 3600
    burst = 'Anthropic HTTP 429 rate limited. Retry after about 20s. {"error":{"type":"rate_limit_error"}}'
    llm_client._get_cooldown("gpt-5.6-sol").mark("rate_limit", base_s=600.0, refusal=_spent_refusal(resets_at))
    llm_client._get_cooldown("claude-x").mark("rate_limit", base_s=20.0, refusal=burst)
    for profile in ("gpt-5.6-sol", "claude-x"):  # eleven minutes later: both parks are over
        llm_client._PROVIDER_COOLDOWNS[profile].until = time.monotonic() - 1

    assert active_cooldowns() == [], "the park itself is capped at ten minutes, which is what it is for"
    rows = {r["profile"]: r for r in limit_rows()}
    assert set(rows) == {"gpt-5.6-sol"}, "a burst that has cleared is not still resting"
    spent = rows["gpt-5.6-sol"]
    assert spent["spent"] is True and spent["account"] == "ChatGPT Pro"
    assert spent["remaining_s"] == 0, "there is no park left to count down; the reset is what the page ends on"
    assert int(spent["resets_at"]) == resets_at
    when = datetime.fromtimestamp(resets_at)
    assert spent["resets_words"] == f"{when:%A} {when.day} {when:%B} at {when:%H:%M}"
    _reset()


def test_a_wait_given_only_as_a_duration_is_not_kept_past_its_park() -> None:
    """A duration runs from the refusal, and this is read long after it.

    "Retry after 3600s" counted from whenever the question is asked moves an hour
    further off every time, and so never arrives: the model would be announced as out
    and kept off the list of what you can use instead until this process restarted.
    Inside the park it is reported, because the park is the wait it describes.
    """
    _reset()
    hour = 'ChatGPT/Codex HTTP 429 rate limited. Retry after about 3600s. {"error":{"type":"rate_limit_error"}}'
    llm_client._get_cooldown("gpt-5.6-sol").mark("rate_limit", base_s=600.0, refusal=hour)

    assert [r["profile"] for r in limit_rows()] == ["gpt-5.6-sol"], "the park is the wait it describes"
    llm_client._PROVIDER_COOLDOWNS["gpt-5.6-sol"].until = time.monotonic() - 1
    assert spent_allowances() == {}, "a duration read later is not a reset the provider named"
    assert limit_rows() == []
    _reset()


def test_the_route_serves_a_limit_a_page_opened_mid_limit_asks_about() -> None:
    """The page asks this route when it opens (``rate_limit_banner.js``)."""
    _reset()
    app = web.Application()
    setup_cooldown_routes(app, require_api_access=lambda _r: None)
    resets_at = int(time.time()) + 36 * 3600
    llm_client._get_cooldown("gpt-5.6-sol").mark("rate_limit", base_s=600.0, refusal=_spent_refusal(resets_at))
    llm_client._PROVIDER_COOLDOWNS["gpt-5.6-sol"].until = time.monotonic() - 1

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            return await (await client.get("/api/chat/cooldowns")).json()

    body = asyncio.run(scenario())
    assert [r["profile"] for r in body["cooldowns"]] == ["gpt-5.6-sol"]
    assert body["cooldowns"][0]["spent"] is True
    assert int(body["cooldowns"][0]["resets_at"]) == resets_at
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
