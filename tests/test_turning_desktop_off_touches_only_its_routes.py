"""The desktop row, off: its six routes answer 404, the helper's code never loads, and a helper this Thomas started stops.

Two things in this test are not the routes. The isolated desktop's code used to load for every server, because Mission
Control and Easy Setup imported it at the top of their files, so these tests ask both pages and then look at what loaded.
And the helper is a program of its own, which only a test that names it can see stop: the row reads off and every route
answers 404 whether or not it is still running.

Two routes launch real programs, ``install`` through a PowerShell call that asks Windows for administrator rights and
``open-viewer`` through another. Every server this file starts is given a ``Popen`` that refuses those two and records that
it was asked, so the routes are asked with the real store and nothing on this computer is installed or opened.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.desktop_gate import desktop_row_is_on
from thomas.server.proof.selection import select

ROW = "desktop"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/onboarding/desktop/status": "GET /api/onboarding/desktop/status",
    "POST /api/onboarding/desktop/opt-in": "POST /api/onboarding/desktop/opt-in",
    "POST /api/onboarding/desktop/trust": "POST /api/onboarding/desktop/trust",
    "POST /api/onboarding/desktop/vm-source": "POST /api/onboarding/desktop/vm-source",
    "POST /api/onboarding/desktop/install": "POST /api/onboarding/desktop/install",
    "POST /api/onboarding/desktop/open-viewer": "POST /api/onboarding/desktop/open-viewer",
}
# The two pages that used to load the helper's code for every server. They stay on whatever this row does.
PAGES = {"GET /api/setup/bootstrap": "GET /api/setup/bootstrap", "GET /api/mission/control": "GET /api/mission/control"}
OWN_CODE = (
    "thomas.server.rows.desktop",
    "thomas.server.routes.desktop_aiohttp",
    "thomas.desktop_operator",
    "thomas.desktop_operator.host_service",
    "thomas.desktop_operator.manager",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/onboarding/desktop/status"}

# Run ahead of every server below. A launch of PowerShell or of a viewer is refused and counted, and ``reading`` is asked
# at each press. Once the helper's code has loaded it gives the shared manager a helper of its own to stop, a program that
# only sleeps, and says whether that program is still alive. The last call ends it if the row did not.
THE_LAUNCHES = """\
import subprocess
import sys

_REAL = subprocess.Popen
_REFUSED = []
_HELPER = []
_ASKED = []


class _Refusing(_REAL):
    def __init__(self, args, *more, **options):
        text = " ".join(map(str, args)) if isinstance(args, (list, tuple)) else str(args)
        if "powershell" in text.lower() or "vmconnect" in text.lower():
            _REFUSED.append(text[:60])
            raise OSError("a test does not launch this")
        super().__init__(args, *more, **options)


subprocess.Popen = _Refusing


"""
THE_HELPER = """\
def reading():
    _ASKED.append(1)
    module = sys.modules.get("thomas.desktop_operator.manager")
    if module is None:
        return {"refused": len(_REFUSED), "helper_alive": None}
    if not _HELPER:
        helper = _REAL([sys.executable, "-c", "import time; time.sleep(120)"])
        module.get_global_desktop_operator_manager().process = helper
        _HELPER.append(helper)
    alive = _HELPER[0].poll() is None
    if len(_ASKED) == 3 and alive:
        _HELPER[0].kill()
    return {"refused": len(_REFUSED), "helper_alive": alive}


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("desktop-off")
    asks = [*ROUTES.values(), *PAGES.values()]
    started, found = start_with_one_row_off(ROW, asks, folder, reading=THE_LAUNCHES + THE_HELPER)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("desktop-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder, ahead=THE_LAUNCHES)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def _only_the_routes(answers: dict[str, int]) -> dict[str, int]:
    return {ask: answers[ask] for ask in ROUTES.values()}


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert _only_the_routes(seen["off"]) == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_mission_control_and_easy_setup_still_answer(seen: dict[str, Any]) -> None:
    """The next test looks at what loaded after these two were asked, so they must really have been answered."""
    assert {ask: seen["off"][ask] for ask in PAGES.values()} == dict.fromkeys(PAGES.values(), 200)


def test_with_the_row_off_none_of_the_helpers_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_six_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert _only_the_routes(seen["on"]) == dict.fromkeys(ROUTES.values(), 200)


def test_install_and_the_viewer_reached_the_launcher_and_were_refused_by_this_test(seen: dict[str, Any]) -> None:
    """If this fails the routes answered without launching, and the test is no longer asking what it thinks it asks."""
    assert seen["read_off"]["refused"] == 0
    assert seen["read_on"]["refused"] >= 1


def test_the_helper_this_thomas_started_runs_only_while_the_row_is_on(seen: dict[str, Any]) -> None:
    assert seen["read_off"]["helper_alive"] is None
    assert seen["read_on"]["helper_alive"] is True
    assert seen["read_off_again"]["helper_alive"] is False


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert _only_the_routes(seen["off_again"]) == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


class _Context:
    """Enough of what a row is handed for ``apply``: the web service by name, and a place to put a stop step."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self.stops: list[Any] = []

    def __getitem__(self, name: str) -> Any:
        return self.service

    def on_stopped(self, step: Any) -> None:
        self.stops.append(step)


def test_every_route_asks_the_guard_the_server_hands_the_row() -> None:
    """The test above cannot see a guard go on a POST, because the server refuses any POST under ``/api/`` first.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the routes.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    class Service:
        require_api_access = staticmethod(refuse)

        @staticmethod
        def view(_ctx: Any) -> web.Application:
            return app

    context = _Context(Service())
    importlib.import_module(OWN_CODE[0]).plugin.apply(context, {})

    async def asked() -> dict[str, int]:
        async with TestClient(TestServer(app)) as client:
            found = {}
            for ask in ROUTES:
                method, path = ask.split()
                found[ask] = (await client.request(method, path, json=None if method == "GET" else {})).status
            return found

    assert asyncio.run(asked()) == dict.fromkeys(ROUTES, 403)


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/desktop.py",
        "thomas/server/routes/desktop_aiohttp.py",
        "thomas/server/desktop_gate.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_desktop_off_touches_only_its_routes.py" in chosen
    if changed != "thomas/server/desktop_gate.py":
        assert "tests/test_server_onboarding_desktop_routes.py" in chosen


class _Rows:
    """What ``app[APP_RUNTIME_PLUGINS]`` answers to ``report``: this row in the state given, and one other."""

    def __init__(self, state: str | None) -> None:
        self.state = state

    def report(self) -> dict[str, Any]:
        rows = [{"id": "setup", "state": "active"}]
        if self.state is not None:
            rows.append({"id": ROW, "state": self.state})
        return {"rows": rows}


@pytest.mark.parametrize(
    ("state", "wanted"), [("active", True), ("off", False), ("loading", False), ("failed", False), (None, False)]
)
def test_mission_control_and_easy_setup_read_the_helper_only_while_the_row_is_on(
    state: str | None, wanted: bool
) -> None:
    from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

    assert desktop_row_is_on({APP_RUNTIME_PLUGINS: _Rows(state)}) is wanted


def test_an_app_with_no_rows_at_all_is_read_as_it_always_was() -> None:
    """A bare app in a test, or a restart harness, loads no rows, and asking it would hide what those tests read."""
    assert desktop_row_is_on({}) is True
