"""What the run history row's words promise about the store: off takes the routes, and the recording goes on.

The row ``thomas.server.rows.runs`` holds the ten routes of ``thomas.server.routes.runs`` and nothing else. The store they
read belongs to the server: it opens in ``thomas/server/app_core.py``, chat and Code write to it, the System page reads it,
and two sweeps in ``thomas/server/app_routes_init.py`` close runs left open. Every test here runs a real server on a real
store, because a sentence on the Plugins page is only worth what it does there.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.plugin_view_fixture import config_in, until
from tests.row_proof_fixture import ROWS, choose
from thomas.core.config import AppConfig
from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.observability import run_store
from thomas.server import app_core
from thomas.server.app_keys import APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE
from thomas.server.routes.evolve_agent_http_support import _record_code_run_start
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

OFF = "/api/plugins/thomas/runs/off"
ON = "/api/plugins/thomas/runs/on"
# Each route, about a run that was recorded. Written out, as in the off test.
ASKS = (
    ("GET", "/api/runs"),
    ("GET", "/api/runs/{id}"),
    ("GET", "/api/runs/{id}/replay"),
    ("GET", "/api/runs/{id}/events"),
    ("POST", "/api/runs/{id}/replay/seek"),
    ("POST", "/api/runs/{id}/replay/step"),
    ("GET", "/api/runs/{id}/replay_stream?speed=0"),
    ("GET", "/api/runs/{id}/export"),
    ("GET", "/api/runs/{id}/export.json"),
    ("POST", "/api/runs/{id}/cancel"),
)
# A stop must not wait for either of these. The limit is on this test, so a row that held its switch fails rather than hangs.
PATIENCE = 30


class _Model:
    """The only stand-in below. The route, the chat turn and the store are the real ones."""

    async def stream_chat(self, *, messages: Any, tools: Any = None) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="token", data={"text": "Noted."})
        yield StreamEvent(type="done")


def _the_row(app: Any) -> dict[str, Any]:
    """This row as the Plugins page is told it, words and all."""
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "runs")


def _record(run_id: str, *, ended: bool = True, gap_ms: int = 100, payload: str = "hello", replies: int = 1) -> str:
    run_store.create_run(
        {"run_id": run_id, "session_id": "s1", "mode": "chat", "started_at": "2026-01-15T12:00:00+00:00"}
    )
    run_store.append_event(run_id, "prompt", {"role": "user", "text": payload}, t_ms=0, seq=0)
    for seq in range(1, replies + 1):
        run_store.append_event(run_id, "assistant", {"role": "assistant", "text": payload}, t_ms=seq * gap_ms, seq=seq)
    if ended:
        run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)
    return run_id


async def _answers(client: TestClient, run_id: str) -> dict[str, int]:
    found = {}
    for method, path in ASKS:
        async with client.request(method, path.format(id=run_id), json={"index": 0}) as answer:
            await answer.read()
            found[f"{method} {path}"] = answer.status
    return found


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppConfig]:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    yield config_in(tmp_path)
    run_store.shutdown(reset_db_path=True)


def test_a_recorded_run_answers_on_every_route_and_is_there_after_off_and_on(config: AppConfig) -> None:
    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            _record("before")
            on = await _answers(client, "before")
            pressed_off = await client.post(OFF)
            off = await _answers(client, "before")
            _record("while-off")
            pressed_on = await client.post(ON)
            listed = await (await client.get("/api/runs")).json()
            seen_again = await (await client.get("/api/runs/while-off/events")).json()
            return {
                "on": on,
                "off": off,
                "pressed": (pressed_off.status, pressed_on.status),
                "listed": [run["run_id"] for run in listed["runs"]],
                "events": seen_again["total"],
                "store_kept_on": (app[APP_RUN_STORE_ENABLED], app[APP_RUN_STORE_MODULE] is run_store),
            }

    found = asyncio.run(scenario())

    assert found["on"] == dict.fromkeys(found["on"], 200)
    assert found["off"] == dict.fromkeys(found["off"], 404)
    assert len(found["on"]) == 10
    assert found["pressed"] == (200, 200)
    assert sorted(found["listed"]) == ["before", "while-off"]
    assert found["events"] == 2
    assert found["store_kept_on"] == (True, True)


def test_replies_and_code_runs_are_recorded_while_off_and_the_agents_page_goes_on_listing_them(
    config: AppConfig, tmp_path: Path
) -> None:
    """The row's words say both, and neither goes through a route of its own.

    Chat and Code read the two app keys the server set as it started, and the System page's list (``/api/mission/control``) reads the store directly. If this
    row ever owns either key, this fails and those words have to change.
    """

    async def answered_by_the_model(app: Any, **kwargs: Any) -> tuple[_Model, None, str]:
        return _Model(), None, "local"

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            await client.post(OFF)
            sid = (await (await client.post("/api/session/new")).json())["session_id"]
            with patch("thomas.server.routes.chat_v2.initialize_chat_v2_llm", answered_by_the_model):
                said = await client.post(
                    "/api/v2/chat", json={"session_id": sid, "profile": "local", "message": "Hello."}
                )
                await said.text()
            settings = SimpleNamespace(family="", recorded_model=lambda: "")
            _record_code_run_start(app, "a-code-run", "c1", tmp_path, settings)
            mission = await (await client.get("/api/mission/control?fresh=1")).json()
            kept = run_store.list_runs(limit=50, offset=0, filters={})
            await client.post(ON)
            listed = await (await client.get("/api/runs")).json()
            return {
                "row": _the_row(app),
                "chat": said.status,
                "kept": {run["mode"]: run["run_id"] for run in kept if run["mode"] != "ambient-capture"},
                "mission": [agent["id"] for agent in mission["agents"] if agent.get("source") == "chat_run"],
                "listed": [run["run_id"] for run in listed["runs"]],
            }

    found = asyncio.run(scenario())

    assert found["chat"] == 200
    assert found["kept"]["code"] == "a-code-run"
    assert len(found["kept"]) == 2, found["kept"]
    assert {f"run:{run_id}" for run_id in found["kept"].values()} <= set(found["mission"])
    assert set(found["kept"].values()) <= set(found["listed"])
    off_means = found["row"]["off_means"]
    assert "Thomas goes on recording replies in Chat and jobs in Build" in off_means
    assert "the System page goes on listing the recent ones" in off_means
    assert "runs recorded while it was off are on the list with the others" in off_means


def test_the_words_promise_no_number_of_runs_kept_because_large_runs_can_leave_none(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past its size cap the store deletes runs until none are left, so no count of kept runs is true.

    Deleting rows does not shrink a SQLite file, so once the file is over ``MAX_DB_BYTES`` the retention loop in
    ``run_store._enforce_retention`` empties the store. That is a bug in the store, left alone by this row; what this
    test holds is that the row's words do not promise a number the store does not keep. The cap is made small here
    so a few runs pass it; at the real 200 MB the same happens after about 200 runs of 1 MB each.
    """
    app_core.create_app(config)
    _record("small")
    # Room for a few of the large runs below beyond what the empty store's file already takes.
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", run_store._require_db().stat().st_size + 200_000)
    kept = []
    for n in range(12):
        _record(f"large-{n}", payload="x" * 40_000)
        kept.append(len(run_store.list_runs(limit=500, offset=0, filters={})))

    assert max(kept) > 1, kept
    assert kept[-1] < max(kept), kept
    off_means = next(row for row in ROWS if row.id == "runs").config["words"]["off_means"]
    assert "500" not in off_means
    assert "newest runs" not in off_means


@pytest.mark.parametrize(
    ("route", "shape"),
    [
        # An hour between its two events, so at its own speed this replay would sit open for an hour.
        ("replay_stream", {"gap_ms": 3_600_000}),
        # A reader that stops reading leaves this one waiting on the socket, so it needs more than the socket will hold.
        ("replay", {"payload": "x" * 200_000, "replies": 300}),
    ],
)
def test_a_program_part_way_through_a_run_is_cut_off_and_cannot_hold_the_switch(
    config: AppConfig, route: str, shape: dict[str, Any]
) -> None:
    async def scenario() -> tuple[str, int, str]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            run_id = _record("long", **shape)
            reading = await client.get(f"/api/runs/{run_id}/{route}")
            first = await reading.content.readline()
            pressed = await asyncio.wait_for(client.post(OFF), PATIENCE)
            await asyncio.wait_for(until(lambda: _the_row(app)["state"] == "off"), PATIENCE)
            reading.close()
            return first[:2].decode(), pressed.status, _the_row(app)["off_means"]

    opened, status, off_means = asyncio.run(scenario())

    assert opened == '{"', "the replay was never under way"
    assert status == 200
    assert "one part way through reading a run is cut off" in off_means


def test_a_request_to_cancel_says_cancelled_and_stops_nothing(config: AppConfig) -> None:
    """``about`` says so, and a reply you are waiting on must not be thought safe to stop this way."""

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], str]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            _record("still-going", ended=False)
            answer = await (await client.post("/api/runs/still-going/cancel")).json()
            return answer, run_store.get_run("still-going")["run"], _the_row(app)["about"]

    answer, run, about = asyncio.run(scenario())

    assert answer == {"ok": True, "run_id": "still-going", "cancelled": True}
    assert run["ended_at"] is None
    assert "A request to cancel a run is answered here too, but it stops nothing." in about


def test_a_store_that_did_not_open_leaves_the_row_failed_with_its_reason(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the shell this was one warning in a log. A row reading active with nothing behind it would be a false reading."""

    def cannot_open(path: Any) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(run_store, "init_db", cannot_open)

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            at_start = _the_row(app)
            asked = await client.get("/api/runs")
            pressed = await client.post(ON)
            return {"at_start": at_start, "asked": asked.status, "pressed": pressed.status, "after": _the_row(app)}

    found = asyncio.run(scenario())

    assert (found["at_start"]["state"], found["after"]["state"]) == ("failed", "failed")
    assert "the run store did not open" in found["at_start"]["error"]
    assert (found["asked"], found["pressed"]) == (404, 200)


def test_a_row_started_off_leaves_both_sweeps_closing_runs_left_open(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off stops the API only. A server started with the row off still closes what the last one left, and goes on sweeping."""
    choose(tmp_path / "data", on=[row.id for row in ROWS if row.id != "runs"])
    monkeypatch.setattr("thomas.server.app_routes_init._RUN_STORE_JANITOR_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr("thomas.server.app_routes_init._RUN_STORE_STALE_IDLE_SECONDS", 1)

    def ended(run_id: str) -> bool:
        return bool(run_store.get_run(run_id)["run"]["ended_at"])

    async def scenario() -> tuple[str, bool, bool]:
        app = app_core.create_app(config)
        _record("left-by-the-last-server", ended=False)
        async with TestClient(TestServer(app)):
            at_start = ended("left-by-the-last-server")
            _record("gone-quiet", ended=False)
            await asyncio.wait_for(until(lambda: ended("gone-quiet")), PATIENCE)
            return _the_row(app)["state"], at_start, ended("gone-quiet")

    assert asyncio.run(scenario()) == ("off", True, True)
