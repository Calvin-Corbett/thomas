"""What the words of the ratchet row promise about a run, through a real server's off and on.

``tests/test_turning_ratchet_off_touches_only_its_routes.py`` holds the row's routes and its daily loop. This file holds
the rest of what ``thomas.server.rows.ratchet`` says: a run going holds off until it ends, Stop now cuts it short and
leaves nothing in the way of the next one, a card stays for the next run, and turning on finds nothing of the last. That
dotted name, here, is how a check of the row finds this file.

Every test names this account, as the caged Thomas does, so none of them may reach a real run, which would prove the real
backlog. ``run_once`` is a stand-in here, and the one test that keeps the real one hands it a repository and a cage of
its own.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import getpass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import until
from tests.ratchet_support import FakeCage, make_repo
from thomas.core.kernel import ContextDisposed, Kernel, stop
from thomas.server import app_core
from thomas.server.ratchet.attempt import Hooks
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.service import ACCOUNT_ENV, AUTORUN_ENV, RatchetService
from thomas.server.routes import ratchet_routes
from thomas.server.routes.ratchet_routes import APP_RATCHET
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "ratchet"
TURN_ON = f"/api/plugins/thomas/{ROW}/on"
TURN_OFF = f"/api/plugins/thomas/{ROW}/off"
DAILY = "plugin:ratchet:daily run"


class _ARun:
    """Stands in for ``RatchetService.run_once``: holds until told to go, and says how it ended."""

    def __init__(self) -> None:
        self.began = asyncio.Event()
        self.let_go = asyncio.Event()
        self.ended: list[str] = []

    async def run_once(self, *, limit: int, chat: str) -> dict[str, Any]:
        self.began.set()
        try:
            await self.let_go.wait()
        except asyncio.CancelledError:
            self.ended.append("cut short")
            raise
        self.ended.append("by itself")
        return {"status": "ran", "proven": []}


@pytest.fixture(autouse=True)
def as_the_caged_thomas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())


@pytest.fixture
def a_run(monkeypatch: pytest.MonkeyPatch) -> _ARun:
    stand_in = _ARun()

    async def run_once(_self: RatchetService, *, limit: int, chat: str) -> dict[str, Any]:
        return await stand_in.run_once(limit=limit, chat=chat)

    monkeypatch.setattr(RatchetService, "run_once", run_once)
    return stand_in


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == ROW)


def _tasks() -> set[str]:
    return {task.get_name() for task in asyncio.all_tasks()}


async def _gone(client: TestClient) -> None:
    """A row reads unloading a moment before its routes leave, so a test waits for the 404 rather than assume it."""
    while (await client.get("/api/ratchet")).status != 404:
        await asyncio.sleep(0.01)


def test_off_waits_for_a_run_going_and_the_run_ends_as_it_would_have(tmp_path: Path, a_run: _ARun) -> None:
    async def scene() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            assert (await client.post("/api/ratchet/run", json={})).status == 202
            await until(a_run.began.is_set)

            pressing = asyncio.create_task(client.post(TURN_OFF))
            await until(lambda: _row(app)["state"] == "unloading")
            await _gone(client)
            assert _row(app)["waiting_for"] == 1
            assert not pressing.done() and a_run.ended == []

            a_run.let_go.set()
            assert (await pressing).status == 200
            assert a_run.ended == ["by itself"]
            assert (_row(app)["state"], _row(app)["stopped_partway"]) == ("off", False)

    asyncio.run(scene())


def test_stop_now_cuts_a_run_short_and_a_new_run_can_start_after_it(tmp_path: Path, a_run: _ARun) -> None:
    async def scene() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            assert (await client.post("/api/ratchet/run", json={})).status == 202
            await until(a_run.began.is_set)
            pressing = asyncio.create_task(client.post(TURN_OFF))
            await until(lambda: _row(app)["state"] == "unloading")
            await _gone(client)

            assert (await client.post(f"{TURN_OFF}?force=1")).status == 200
            assert (await pressing).status == 200
            assert a_run.ended == ["cut short"]
            assert (_row(app)["state"], _row(app)["stopped_partway"]) == ("off", True)

            assert (await client.post(TURN_ON)).status == 200
            a_run.began.clear()
            assert (await client.post("/api/ratchet/run", json={})).status == 202
            await until(a_run.began.is_set)
            a_run.let_go.set()

    asyncio.run(scene())


def _scope_of_a_row() -> Any:
    return Kernel().mount(SimpleNamespace(name="ratchet", apply=lambda _ctx, _config: None))


def test_a_daily_run_holds_a_stop_like_any_other_and_the_wait_between_runs_does_not(a_run: _ARun) -> None:
    async def scene() -> None:
        fork = _scope_of_a_row()
        ratchet = RatchetService(work=fork.ctx, first_delay_s=0.0, interval_s=3600.0)
        ratchet.start()
        await until(a_run.began.is_set)
        assert fork.ctx.working == 1

        stopping = asyncio.create_task(stop(fork))
        await asyncio.sleep(0.05)
        assert not stopping.done()

        a_run.let_go.set()
        await stopping
        assert a_run.ended == ["by itself"]
        assert ratchet._daily.cancelled()

        between = _scope_of_a_row()
        ratchet = RatchetService(work=between.ctx, first_delay_s=0.0, interval_s=3600.0)
        ratchet.start()
        await until(lambda: len(a_run.ended) == 2)
        await asyncio.sleep(0)
        assert between.ctx.working == 0
        await asyncio.wait_for(stop(between), 5)
        assert ratchet._daily.cancelled()

    asyncio.run(scene())


def test_a_row_that_has_gone_refuses_a_run_rather_than_answer_that_it_started(a_run: _ARun) -> None:
    """A run started as a plain task would be counted the same, so this is what owning it adds: no 202 for a dead run."""

    async def scene() -> None:
        fork = _scope_of_a_row()
        ratchet = RatchetService(work=fork.ctx)
        await stop(fork)
        with pytest.raises(ContextDisposed):
            ratchet.launch()

    asyncio.run(scene())
    assert a_run.ended == []


def test_in_the_caged_thomas_the_loop_starts_with_the_server_and_ends_with_it(
    tmp_path: Path, a_run: _ARun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUTORUN_ENV, "1")

    async def scene() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        assert DAILY not in _tasks()
        async with TestClient(TestServer(app)):
            assert DAILY in _tasks()
        await asyncio.sleep(0)
        assert DAILY not in _tasks()

    asyncio.run(scene())
    assert a_run.ended == []  # the loop waits 15 minutes before its first run


def test_a_row_that_cannot_register_reads_failed_with_its_reason_and_starts_nothing(
    tmp_path: Path, a_run: _ARun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The family in the shell logged this and the server carried on. A row that did that would read active with no routes."""
    monkeypatch.setenv(AUTORUN_ENV, "1")

    def refused(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("no routes today")

    monkeypatch.setattr(ratchet_routes, "register_ratchet_routes", refused)

    async def scene() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            assert (_row(app)["state"], _row(app)["error"]) == ("failed", "RuntimeError: no routes today")
            assert (await client.get("/api/ratchet")).status == 404
            assert DAILY not in _tasks()

    asyncio.run(scene())


def test_each_turn_on_builds_a_new_service_and_its_key_leaves_with_the_row(tmp_path: Path, a_run: _ARun) -> None:
    async def scene() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            first = app[APP_RATCHET]
            assert first.app is app

            assert (await client.post(TURN_OFF)).status == 200
            assert APP_RATCHET not in app

            assert (await client.post(TURN_ON)).status == 200
            assert app[APP_RATCHET] is not first and app[APP_RATCHET].app is app

    asyncio.run(scene())


def test_a_run_stopped_at_your_card_leaves_the_card_for_the_next_run(tmp_path: Path) -> None:
    """The real run, on a repository and a cage of its own, waiting where a run spends most of its time."""
    repo = make_repo(tmp_path)
    root = tmp_path / "ratchet"
    Ledger(root / "ledger.jsonl").record(
        sha="e" * 40,
        refs=["refs/heads/earlier"],
        dev_sha="d" * 40,
        state="awaiting_card",
        reason="waiting for your card",
        submission="self-ratchet-cand-eeeeeee-ddddddd",
        files=[],
    )
    at_your_card = asyncio.Event()

    async def wait_for_ever(_seconds: float) -> None:
        at_your_card.set()
        await asyncio.Event().wait()

    async def stopped_at_the_card() -> bool:
        fork = _scope_of_a_row()
        hooks = Hooks(run_caged=FakeCage(), runner_alive=lambda: True, sleep=wait_for_ever)
        ratchet = RatchetService(work=fork.ctx, repo=repo, root=root, hooks=hooks)
        assert ratchet.launch()
        await until(at_your_card.is_set)
        await stop(fork, force=True)
        return ratchet.busy()

    assert asyncio.run(stopped_at_the_card()) is False

    assert [event["candidate_ref"] for event in Ledger(root / "ledger.jsonl").awaiting()] == ["refs/heads/earlier"]
    hooks = Hooks(run_caged=FakeCage(), runner_alive=lambda: True, verdict_timeout_s=0.0)
    next_run = RatchetService(repo=repo, root=root, hooks=hooks)
    assert asyncio.run(next_run.run_once()) == {"status": "awaiting_card", "candidate": "refs/heads/earlier"}
