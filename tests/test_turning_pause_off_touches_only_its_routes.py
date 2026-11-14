"""Pause is a required row: its three routes answer, it cannot be turned off, and a caller with no token is refused.

The row is ``thomas.server.rows.pause`` and its routes are ``thomas.server.routes.pause_routes``, which read and change
the saved switch in ``thomas.core.pause``. Being required, there is no off case to prove: every way of turning it off is
refused and the routes stay. No page calls these routes yet, so there is no page to open with the row off. The words the
Plugins page shows for it are held, a sentence at a time, by ``test_the_pause_words_name_the_tests_that_show_them.py``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from tests.row_off_fixture import ask_as_a_remote_caller
from tests.row_proof_fixture import ROOT, ROWS, module_of, named
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.routes import evolve_agent_run_state as run_state
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "pause"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = ["GET /api/thomas/pause", "POST /api/thomas/pause", "POST /api/thomas/resume"]
OWN_CODE = ("thomas.server.rows.pause", "thomas.server.routes.pause_routes")
SENTENCE = "Pause and Resume is part of how Thomas works, so it cannot be turned off."
KEYS = {"paused", "since", "reason", "still_running"}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices and the Pause switch both live in the data dir, so a server started here must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    return tmp_path / "data"


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    started, found = ask_as_a_remote_caller(ROW, ROUTES, tmp_path_factory.mktemp("pause-remote"))
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def _serve(tmp_path: Path) -> tuple[Any, TestClient]:
    app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
    return app, TestClient(TestServer(app))


def _names(routes: Any) -> set[str]:
    return {f"{route.method} {route.resource.canonical}" for route in routes if route.resource is not None}


def _row(app: Any) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == ROW)


def test_every_route_is_on_the_live_table_and_the_shell_registers_none(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> tuple[set[str], set[str]]:
        app, client = _serve(tmp_path)
        async with client:
            return _names(app.router._live.routes()), _names(app.router.server_routes())

    live, shell = asyncio.run(scenario())

    assert live >= {*ROUTES, "HEAD /api/thomas/pause"}
    assert shell.isdisjoint(ROUTES)


def test_the_row_is_required_and_on(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> dict[str, Any]:
        app, client = _serve(tmp_path)
        async with client:
            return _row(app)

    row = asyncio.run(scenario())

    assert (row["required"], row["enabled"], row["state"]) == (True, True, "active")
    assert row["title"].casefold() != ROW


def test_turning_it_off_is_refused_with_a_sentence_even_when_forced_and_a_saved_off_is_ignored(
    tmp_path: Path, own_data_dir: Path
) -> None:
    choices = own_data_dir / "plugins" / "choices.json"
    choices.parent.mkdir(parents=True)
    choices.write_text(json.dumps({ROW: {"enabled": False}}), encoding="utf-8")

    async def scenario() -> tuple[list[tuple[int, str]], str, list[int]]:
        app, client = _serve(tmp_path)
        async with client:
            answers = []
            for query in ("", "?force=1"):
                answer = await client.post(f"/api/plugins/thomas/{ROW}/off{query}")
                answers.append((answer.status, await answer.text()))
            still = [(await client.get("/api/thomas/pause")).status]
            return answers, _row(app)["state"], still

    answers, state, still = asyncio.run(scenario())

    assert answers == [(409, SENTENCE)] * 2
    assert state == "active"
    assert still == [200]  # the routes stay
    assert json.loads(choices.read_text(encoding="utf-8")) == {ROW: {"enabled": False}}  # a refused press saved nothing


def test_the_three_routes_read_pause_and_resume_the_saved_switch(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> list[tuple[int, dict[str, Any]]]:
        _, client = _serve(tmp_path)
        async with client:
            seen = []
            for method, path, body in (
                ("get", "/api/thomas/pause", None),
                ("post", "/api/thomas/pause", {"reason": "going out"}),
                ("get", "/api/thomas/pause", None),
                ("post", "/api/thomas/pause", {"reason": "second try"}),
                ("post", "/api/thomas/resume", None),
                ("get", "/api/thomas/pause", None),
            ):
                answer = await getattr(client, method)(path, **({"json": body} if body else {}))
                seen.append((answer.status, await answer.json()))
            return seen

    first, paused, again, twice, resumed, last = asyncio.run(scenario())

    assert all(status == 200 and set(body) == KEYS for status, body in (first, paused, again, twice, resumed, last))
    assert first[1] == {"paused": False, "since": None, "reason": "", "still_running": 0}
    assert (paused[1]["paused"], paused[1]["reason"]) == (True, "going out") and paused[1]["since"]
    assert again[1] == paused[1]
    assert twice[1]["reason"] == "going out"  # pausing twice keeps the first time and reason
    assert resumed[1] == last[1] == first[1]


def test_a_pause_with_no_body_or_a_body_that_is_not_an_object_still_pauses(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> list[tuple[int, bool, str]]:
        _, client = _serve(tmp_path)
        async with client:
            seen = []
            for kwargs in ({}, {"data": "not json"}, {"json": [1, 2]}):
                await client.post("/api/thomas/resume")
                answer = await client.post("/api/thomas/pause", **kwargs)
                body = await answer.json()
                seen.append((answer.status, body["paused"], body["reason"]))
            return seen

    assert asyncio.run(scenario()) == [(200, True, "")] * 3


def test_pausing_does_not_end_a_run_and_still_running_counts_it(tmp_path: Path, own_data_dir: Path) -> None:
    going = {"session": {"run_id": "r1", "proc": SimpleNamespace(returncode=None)}}

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        app, client = _serve(tmp_path)
        async with client:
            run_state.runs(app)["c1"] = going
            paused = await (await client.post("/api/thomas/pause")).json()
            resumed = await (await client.post("/api/thomas/resume")).json()
            going["session"]["proc"].returncode = 0  # the run ends by itself
            ended = await (await client.get("/api/thomas/pause")).json()
            return paused, resumed, ended

    paused, resumed, ended = asyncio.run(scenario())

    assert (paused["paused"], paused["still_running"]) == (True, 1)
    assert (resumed["paused"], resumed["still_running"]) == (False, 1)
    assert ended["still_running"] == 0
    assert going["session"]["proc"].returncode == 0  # nothing here touched the run


def test_the_pause_flag_is_kept_in_the_data_folder_so_a_new_server_starts_paused(
    tmp_path: Path, own_data_dir: Path
) -> None:
    async def scenario(first: bool) -> dict[str, Any]:
        _, client = _serve(tmp_path / ("one" if first else "two"))
        async with client:
            answer = await client.post("/api/thomas/pause") if first else await client.get("/api/thomas/pause")
            return await answer.json()

    asyncio.run(scenario(True))

    assert (own_data_dir / "paused.json").is_file()
    assert asyncio.run(scenario(False))["paused"] is True


class _SaysHello:
    """A brain that says one sentence, so no model is asked."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001, ANN003
        _ = session_id, kwargs
        await dispatcher.emit_text("Hello from a fake model.")
        return conversation.append_message("user", prompt).append_message("assistant", "Hello from a fake model.")


def test_chat_still_answers_while_paused(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> tuple[int, str]:
        _, client = _serve(tmp_path)
        async with client:
            await client.post("/api/thomas/pause")
            with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _SaysHello):
                sent = await client.post("/api/v2/chat", json={"session_id": "s1", "profile": "local", "message": "hi"})
                return sent.status, await sent.text()

    status, streamed = asyncio.run(scenario())

    assert status == 200 and "Hello from a fake model." in streamed


def test_the_row_names_its_route_modules() -> None:
    entry = next(row for row in ROWS if row.id == ROW)
    assert sorted(named(entry)) == sorted(set(OWN_CODE) - {module_of(entry)})


def test_a_remote_caller_with_no_token_gets_401_on_all_three_routes(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES, 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_change_to_the_row_runs_its_proofs() -> None:
    chosen = select(ROOT, ["thomas/server/rows/pause.py"]).files
    assert "tests/test_turning_pause_off_touches_only_its_routes.py" in chosen
    chosen = select(ROOT, ["thomas/server/routes/pause_routes.py"]).files
    assert "tests/test_turning_pause_off_touches_only_its_routes.py" in chosen
