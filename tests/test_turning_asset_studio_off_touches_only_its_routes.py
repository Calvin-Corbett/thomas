"""The Asset Studio row, off: its 39 routes answer 404, a server started that way never loads them, and its work ends.

The row writes three keys to the app and adds a cleanup, so this is a row that writes to the app: the keys hold a job
runner and a ComfyUI service, and the cleanup is the only thing that ends what those two started. A press of off that
took the routes and skipped it would read off and leave a job's process running, which no test of a route can see.
``tests/test_asset_studio_jobs_through_off_and_on.py`` holds that, ``tests/test_asset_studio_page_through_off_and_on.py``
holds the page, and this file holds the routes.

The routes read and change a store of their own, ``thomas.asset_studio.db`` beside ``thomas.db`` in the data folder, and
nothing else in Thomas opens it. The word asset also names the Virtual Office's furniture and ``/static`` files, and the
word studio names Canvas, Dev Studio and Game Studio, and this row has nothing to do with any of those. Chat has two
tools named for Asset Studio, in ``thomas/marketplace/asset_studio/tools.py``, loaded with or without the row, which is
why the row may not name those modules in ``imports``. Neither reaches this store, on or off, so the words say nothing of
chat.

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
from thomas.marketplace.asset_studio.tools import ConnectorManagementTool, RuntimeTool
from thomas.server.proof.selection import select

BASE = "/api/asset-studio/v1"
# Written out, because a list worked out from the row would agree with whatever the row did. ``detect=0`` because
# detecting runs every connector's version command, on the event loop, and a test is not asking about those.
ROUTES = {
    f"GET {BASE}/connectors": f"GET {BASE}/connectors?detect=0",
    f"GET {BASE}/health": f"GET {BASE}/health?detect=0",
    f"GET {BASE}/comfy/status": f"GET {BASE}/comfy/status?timeout_s=0.5",
    f"POST {BASE}/comfy/boot": f"POST {BASE}/comfy/boot",
    f"POST {BASE}/comfy/shutdown": f"POST {BASE}/comfy/shutdown",
    f"POST {BASE}/comfy/queue": f"POST {BASE}/comfy/queue",
    f"GET {BASE}/comfy/history/{{prompt_id}}": f"GET {BASE}/comfy/history/p1?timeout_s=1",
    f"GET {BASE}/comfy/outputs/{{prompt_id}}": f"GET {BASE}/comfy/outputs/p1?timeout_s=1",
    f"GET {BASE}/webhooks/completion": f"GET {BASE}/webhooks/completion",
    f"POST {BASE}/webhooks/completion": f"POST {BASE}/webhooks/completion",
    f"DELETE {BASE}/webhooks/completion": f"DELETE {BASE}/webhooks/completion",
    f"POST {BASE}/connectors/{{connector_id}}/detect": f"POST {BASE}/connectors/c1/detect",
    f"GET {BASE}/connectors/{{connector_id}}/actions": f"GET {BASE}/connectors/c1/actions",
    f"POST {BASE}/jobs/preview": f"POST {BASE}/jobs/preview",
    f"POST {BASE}/jobs/validate": f"POST {BASE}/jobs/validate",
    f"POST {BASE}/jobs/batch": f"POST {BASE}/jobs/batch",
    f"POST {BASE}/jobs/recommend": f"POST {BASE}/jobs/recommend",
    f"POST {BASE}/jobs/recommendations": f"POST {BASE}/jobs/recommendations",
    f"POST {BASE}/jobs/auto": f"POST {BASE}/jobs/auto",
    f"POST {BASE}/templates": f"POST {BASE}/templates",
    f"POST {BASE}/templates/import": f"POST {BASE}/templates/import",
    f"GET {BASE}/templates": f"GET {BASE}/templates",
    f"PATCH {BASE}/templates/{{template_id}}": f"PATCH {BASE}/templates/t1",
    f"DELETE {BASE}/templates/{{template_id}}": f"DELETE {BASE}/templates/t1",
    f"POST {BASE}/templates/{{template_id}}/clone": f"POST {BASE}/templates/t1/clone",
    f"GET {BASE}/templates/{{template_id}}/export": f"GET {BASE}/templates/t1/export",
    f"GET {BASE}/templates/{{template_id}}/webhook": f"GET {BASE}/templates/t1/webhook",
    f"POST {BASE}/templates/{{template_id}}/webhook": f"POST {BASE}/templates/t1/webhook",
    f"DELETE {BASE}/templates/{{template_id}}/webhook": f"DELETE {BASE}/templates/t1/webhook",
    f"POST {BASE}/templates/{{template_id}}/run": f"POST {BASE}/templates/t1/run",
    f"POST {BASE}/templates/by-name/{{template_name}}/run": f"POST {BASE}/templates/by-name/n1/run",
    f"POST {BASE}/templates/run-favorite": f"POST {BASE}/templates/run-favorite",
    f"POST {BASE}/jobs": f"POST {BASE}/jobs",
    f"GET {BASE}/jobs": f"GET {BASE}/jobs",
    f"GET {BASE}/jobs/{{job_id}}": f"GET {BASE}/jobs/j1",
    f"GET {BASE}/jobs/{{job_id}}/events": f"GET {BASE}/jobs/j1/events",
    f"GET {BASE}/jobs/{{job_id}}/events/stream": f"GET {BASE}/jobs/j1/events/stream",
    f"POST {BASE}/jobs/{{job_id}}/cancel": f"POST {BASE}/jobs/j1/cancel",
    f"POST {BASE}/jobs/{{job_id}}/retry": f"POST {BASE}/jobs/j1/retry",
}
OWN_CODE = (
    "thomas.server.rows.asset_studio",
    "thomas.server.routes.asset_studio_aiohttp",
)
DEFINED_HERE = {
    "thomas/marketplace/asset_studio/comfy_service.py",
    "thomas/marketplace/asset_studio/job_store.py",
    "thomas/marketplace/asset_studio/runtime_engine.py",
}
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(f"HEAD {route.removeprefix('GET ')}" for route in ROUTES if route.startswith("GET "))}
# What each route answers on a real store with an empty body, read to its reason. With no ComfyUI listening, the two that
# fetch from one answer 502, and a boot with no command says so in a 200. The rest of the 404s are the handler's own, for
# an id that does not exist, so only ``live_on`` tells those from a lost route.
ANSWERS = {
    **dict.fromkeys(ROUTES.values(), 404),
    **dict.fromkeys(
        (
            f"GET {BASE}/connectors?detect=0",
            f"GET {BASE}/health?detect=0",
            f"GET {BASE}/comfy/status?timeout_s=0.5",
            f"POST {BASE}/comfy/boot",
            f"POST {BASE}/comfy/shutdown",
            f"GET {BASE}/webhooks/completion",
            f"DELETE {BASE}/webhooks/completion",
            f"GET {BASE}/templates",
            f"GET {BASE}/jobs",
        ),
        200,
    ),
    **dict.fromkeys(
        (
            f"POST {BASE}/comfy/queue",
            f"POST {BASE}/webhooks/completion",
            f"POST {BASE}/jobs/preview",
            f"POST {BASE}/jobs/validate",
            f"POST {BASE}/jobs/batch",
            f"POST {BASE}/jobs/recommend",
            f"POST {BASE}/jobs/recommendations",
            f"POST {BASE}/jobs/auto",
            f"POST {BASE}/templates",
            f"POST {BASE}/templates/import",
            f"PATCH {BASE}/templates/t1",
            f"POST {BASE}/templates/t1/webhook",
            f"POST {BASE}/jobs",
        ),
        400,
    ),
    f"GET {BASE}/comfy/history/p1?timeout_s=1": 502,
    f"GET {BASE}/comfy/outputs/p1?timeout_s=1": 502,
}

ROW = "asset_studio"


def _without_a_way_to_start_comfy(env: pytest.MonkeyPatch) -> None:
    """With this set, an empty boot request would start whatever it names on the machine running the test."""
    env.delenv("THOMAS_COMFYUI_BOOT_CMD", raising=False)
    env.delenv("THOMAS_DB_PATH", raising=False)
    env.delenv("THOMAS_SQLITE_PATH", raising=False)


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("asset-studio-off")
    with pytest.MonkeyPatch.context() as env:
        _without_a_way_to_start_comfy(env)
        started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("asset-studio-remote")
    with pytest.MonkeyPatch.context() as env:
        _without_a_way_to_start_comfy(env)
        started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


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


def test_turning_it_on_brings_back_all_39_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == ANSWERS


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_the_only_page_that_uses_these_routes_is_the_asset_studio_panel_and_only_five_of_them() -> None:
    """The row's words describe that panel, and say that no sidebar button opens it. A second caller changes both."""
    web = ROOT / "thomas" / "server" / "web"
    calling: dict[str, set[str]] = {}
    for path in [*web.rglob("*.js"), *web.rglob("*.html")]:
        text = path.read_text(encoding="utf-8")
        for piece in text.split("/api/asset-studio/v1/")[1:]:
            calling.setdefault(path.name, set()).add(piece.split("'")[0].split("?")[0].rstrip("/"))

    assert set(calling) == {"041_model_setup_settings_02.js", "042_model_setup_settings_03.js"}
    assert calling["042_model_setup_settings_03.js"] == {
        "comfy/status",
        "comfy/boot",
        "comfy/shutdown",
        "comfy/queue",
        "comfy/outputs",
    }


def test_the_routes_are_the_only_way_to_this_store_and_chat_has_none() -> None:
    """Who else opens the store decides whether off stops the jobs, so the words hold only while the answer is nobody.

    ``asset_runtime_control`` builds a runner with no store, which raises, and its status is a fixed ``ready``.
    ``asset_connector_manage`` reads an attribute the catalog does not have, so all it does is report the error.
    """
    reaching = ("AssetStudioRuntime(", "AssetStudioJobStore(", "ComfyStudioService(")
    found = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if any(word in path.read_text(encoding="utf-8") for word in reaching)
    }

    assert found - DEFINED_HERE == {
        "thomas/server/routes/asset_studio_aiohttp.py",
        "thomas/marketplace/asset_studio/tools.py",
    }
    assert asyncio.run(RuntimeTool().execute({"action": "create_runtime"})).ok is False
    assert asyncio.run(RuntimeTool().execute({"action": "get_status"})).data == {"status": "ready"}
    assert asyncio.run(ConnectorManagementTool().execute({"action": "list_connectors"})).ok is False


def test_every_route_asks_the_guard_the_server_hands_the_row() -> None:
    """The remote test cannot see most of these go, because the server refuses a POST under ``/api/`` before a row.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the routes.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    async def nothing(_request: web.Request) -> dict[str, Any]:
        return {}

    service = SimpleNamespace(view=lambda _ctx, **_options: app, require_api_access=refuse, read_json=nothing)
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})

    async def asked() -> dict[str, int]:
        async with TestClient(TestServer(app)) as client:
            answers = {}
            for ask in ROUTES.values():
                method, path = ask.split()
                answers[ask] = (await client.request(method, path, json={})).status
            return answers

    assert asyncio.run(asked()) == dict.fromkeys(ROUTES.values(), 403)


@pytest.mark.parametrize(
    "changed", ["thomas/server/rows/asset_studio.py", "thomas/server/routes/asset_studio_aiohttp.py"]
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_asset_studio_off_touches_only_its_routes.py" in chosen
    assert "tests/test_asset_studio_jobs_through_off_and_on.py" in chosen
    assert "tests/test_asset_studio_page_through_off_and_on.py" in chosen
    # tests/test_asset_studio_routes.py is over the size limit, so it cannot name the row and a check does not choose it.
