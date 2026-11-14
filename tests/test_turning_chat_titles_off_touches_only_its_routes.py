"""The sidebar names row, off: its one route is refused, a server started that way never loads it, and the list carries on.

The sidebar asks this route to give long, prompt-like thread names a short readable title. It builds a model client for
each request, from the models slot, and keeps nothing running between requests. A title it wrote is saved by the sidebar
in your browser, not by this route, so off cannot take a title away. Off takes only the asking: the sidebar keeps the
names it had.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "chat_titles"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "POST /api/chats/title": "POST /api/chats/title",
    "POST /api/chats/auto-title": "POST /api/chats/auto-title",
}
OWN_CODE = ("thomas.server.rows.chat_titles", "thomas.server.routes.chat_titles_runtime")
LISTED = set(ROUTES)
# The shell has PUT and DELETE on ``/api/chats/{chat_id}``, which a POST to ``/api/chats/title`` also matches by path. So
# with the row off the server says that method is not allowed, which is 405, and not that nothing is there.
OFF_ANSWER = 405


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("chat-titles-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("chat-titles-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_the_route_is_refused_and_none_is_listed(seen: dict[str, Any]) -> None:
    """A 405 and not a 404, from the chat route beside it, which the sidebar treats the same: it reads no title either way."""
    assert seen["off"] == dict.fromkeys(ROUTES.values(), OFF_ANSWER)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_the_route_without_a_restart(seen: dict[str, Any]) -> None:
    """Asked with an empty body, so no model is called. The handler answers 200 with nothing to title."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys(ROUTES.values(), 200)


def test_turned_off_on_a_running_server_the_route_goes_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its route goes and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), OFF_ANSWER)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert remote["with_token"] == dict.fromkeys(ROUTES.values(), 200)


def test_the_route_asks_the_guard_the_server_hands_the_row() -> None:
    """The test above cannot see this guard go, because the server refuses any POST under ``/api/`` before a row is reached.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the route.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    service = SimpleNamespace(view=lambda _ctx: app, require_api_access=refuse)
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})

    async def asked() -> int:
        async with TestClient(TestServer(app)) as client:
            return (await client.post("/api/chats/title", json={"items": [{"id": "a", "text": "x"}]})).status

    assert asyncio.run(asked()) == 403


def test_a_row_whose_route_file_will_not_load_reads_failed_and_does_not_log_and_carry_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shell used to swallow an import error and boot. A row that does so reads active with no route."""
    monkeypatch.setitem(__import__("sys").modules, OWN_CODE[1], None)
    service = SimpleNamespace(view=lambda _ctx: web.Application(), require_api_access=lambda _request: None)

    with pytest.raises(ImportError):
        importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})


@pytest.mark.parametrize(
    "changed", ["thomas/server/rows/chat_titles.py", "thomas/server/routes/chat_titles_runtime.py"]
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_chat_titles_off_touches_only_its_routes.py" in chosen
    assert "tests/test_sidebar_history_contract.py" in chosen
