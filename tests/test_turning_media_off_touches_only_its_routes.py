"""The media row, off: its four routes answer 404, a server started that way never loads them, and Chat carries on.

Only the page's Create image, Create video and Create music reach these routes. What runs is a job, which is two tasks and
a worker thread, so a 404 proves little: ``tests/test_media_jobs_through_off_and_on.py`` holds what happens to a job.

The word media names other things. ``thomas/marketplace/autonomy/media_agents.py`` and the Discord bridge's
``media-service.js`` have nothing to do with these routes. Files in a chat and pictures in Library are served by
``/deliverable``, so they stay with the row off.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did. The medium and the id are
# safe to ask for with an empty body: nothing here chooses a model, and no job has that id.
ROUTES = {
    "GET /api/media/lanes": "GET /api/media/lanes",
    "PUT /api/media/lanes/{medium}": "PUT /api/media/lanes/image",
    "POST /api/media/generate": "POST /api/media/generate",
    "GET /api/media/jobs/{job_id}": "GET /api/media/jobs/no-such-job",
}
OWN_CODE = ("thomas.server.rows.media", "thomas.server.routes.media_generation_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/media/lanes", "HEAD /api/media/jobs/{job_id}"}
# What each route answers on the real store with the row on: the lanes, two refusals of an empty body, and the handler's
# own 404 for a job it does not know.
ANSWERS_ON = {
    "GET /api/media/lanes": 200,
    "PUT /api/media/lanes/image": 400,
    "POST /api/media/generate": 400,
    "GET /api/media/jobs/no-such-job": 404,
}

ROW = "media"
WEB = ROOT / "thomas" / "server" / "web"


class _Scope(dict):
    """As much of a row's scope as ``apply`` touches. A refused caller must never get as far as starting a job."""

    def task(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a caller the guard refused started a job")


def _fresh(found: Any, started: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("media-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert _fresh(found, started)["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("media-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    return _fresh(found, started)


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_four_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """The job route answers 404 itself for an id it does not know, so only ``live_on`` tells it from a route that left."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == ANSWERS_ON


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so ``_LOCAL_LOCK`` and a worker holding it outlive off, and the words may not say so."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert remote["with_token"] == ANSWERS_ON


def test_every_route_asks_the_guard_the_server_hands_the_row(tmp_path: Path) -> None:
    """The test above cannot see the PUT or the POST lose this guard: the server refuses both under ``/api/`` first.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the routes.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    service = SimpleNamespace(view=lambda _ctx: app, require_api_access=refuse, config=views.config_in(tmp_path))
    importlib.import_module(OWN_CODE[0]).plugin.apply(_Scope(web=service), {})

    async def asked() -> dict[str, int]:
        async with TestClient(TestServer(app)) as client:
            found = {}
            for ask in ROUTES.values():
                method, path = ask.split()
                found[ask] = (await client.request(method, path, json=None if method == "GET" else {})).status
            return found

    assert asyncio.run(asked()) == dict.fromkeys(ROUTES.values(), 403)


@pytest.mark.parametrize("changed", ["thomas/server/rows/media.py", "thomas/server/routes/media_generation_routes.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_media_off_touches_only_its_routes.py" in chosen
    assert "tests/test_media_jobs_through_off_and_on.py" in chosen
    assert "tests/test_what_the_media_row_says_is_true.py" in chosen
    assert "tests/test_media_generation_routes.py" in chosen
    assert "tests/test_media_generation_job_state.py" in chosen
