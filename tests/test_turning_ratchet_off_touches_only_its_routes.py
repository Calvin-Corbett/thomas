"""The ratchet row, off: its two routes answer 404, no daily run starts, and Chat can still read what it recorded.

This row starts work that keeps running, so a 404 proves little here. The daily loop is named below, and only that test
can see it. Only the caged Thomas starts that loop, so one server here stands in for it by naming this account. That
server asks ``GET`` alone: with this account named, ``POST /api/ratchet/run`` would start a real run of the real backlog.
Every other server here names an account that is not this one, so that the same test run under the caged account stays
safe too.

The word ratchet names other things. ``plugins/ratchet.toml`` is a list of files for the check selection, and
``tests/test_marketplace_commerce_engine_is_gone.py`` calls itself one. Neither is this.

``tests/test_a_ratchet_run_through_off_and_on.py`` holds what happens to a run through off and on, and
``tests/test_the_ratchet_in_a_release.py`` what a release shows.

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

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.core.kernel import Kernel
from thomas.server.proof.selection import select
from thomas.server.ratchet.ledger import Ledger

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/ratchet": "GET /api/ratchet",
    "POST /api/ratchet/run": "POST /api/ratchet/run",
}
OWN_CODE = (
    "thomas.server.rows.ratchet",
    "thomas.server.routes.ratchet_routes",
    "thomas.server.ratchet.service",
)
LISTED = {*ROUTES, "HEAD /api/ratchet"}

ROW = "ratchet"
DAILY = "plugin:ratchet:daily run"

# Goes ahead of the server's script, so these are in place before Thomas is imported. Reads what Chat reads, the way Chat
# reads it, after the list of loaded modules is taken.
_THE_REST = """\
import asyncio
import getpass
import os

os.environ["THOMAS_RATCHET_AUTORUN"] = "1"
os.environ["THOMAS_RATCHET_ACCOUNT"] = {account}


def reading():
    from thomas.server.app_helpers import _read_unlanded

    return {{
        "tasks": sorted(task.get_name() for task in asyncio.all_tasks()),
        "chat_counts": _read_unlanded()["counts"],
    }}


"""
NOT_THIS_ACCOUNT = _THE_REST.format(account='"somebody-else"')
THIS_ACCOUNT = _THE_REST.format(account="getpass.getuser()")


def _one_reported_candidate(folder: Path) -> None:
    ledger = Ledger(folder / "data" / "ratchet" / "ledger.jsonl")
    ledger.record(sha="a" * 40, refs=["refs/heads/fix/a"], dev_sha="d" * 40, state="reported", reason="a test failed")


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("ratchet-off")
    _one_reported_candidate(folder)
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder, reading=NOT_THIS_ACCOUNT)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def caged(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """As the caged Thomas, whose loop sleeps for its first 15 minutes, which is far longer than this server lives."""
    folder = tmp_path_factory.mktemp("ratchet-caged")
    started, found = start_with_one_row_off(ROW, ["GET /api/ratchet"], folder, reading=THIS_ACCOUNT)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("ratchet-remote")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("THOMAS_RATCHET_ACCOUNT", "somebody-else")
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


def test_with_the_row_off_nothing_of_the_ratchet_has_loaded(seen: dict[str, Any]) -> None:
    """The whole package, because Chat's report was imported at every boot and took the package with it."""
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []
    assert [module for module in seen["loaded"] if module.startswith("thomas.server.ratchet")] == []


def test_turning_it_on_brings_back_both_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {"GET /api/ratchet": 200, "POST /api/ratchet/run": 409}  # not the caged Thomas, so it refuses


def test_its_daily_run_is_there_only_while_the_row_is_on_in_the_caged_thomas(caged: dict[str, Any]) -> None:
    assert caged["on"] == {"GET /api/ratchet": 200}
    assert DAILY not in caged["read_off"]["tasks"]
    assert DAILY in caged["read_on"]["tasks"]
    assert DAILY not in caged["read_off_again"]["tasks"]


def test_every_other_server_never_starts_the_daily_run(seen: dict[str, Any]) -> None:
    assert DAILY not in seen["read_on"]["tasks"]


def test_chat_reads_the_same_records_whether_the_row_is_off_or_on(seen: dict[str, Any]) -> None:
    assert seen["read_off"]["chat_counts"] == {"reported": 1}
    assert seen["read_on"]["chat_counts"] == {"reported": 1}
    assert seen["read_off_again"]["chat_counts"] == {"reported": 1}


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert remote["with_token"] == {"GET /api/ratchet": 200, "POST /api/ratchet/run": 409}


def test_both_routes_ask_the_guard_the_server_hands_the_row() -> None:
    """The server refuses a POST under ``/api/`` before a row is reached, so only a bare app shows this guard go."""
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    scope = Kernel().root
    scope.set("web", SimpleNamespace(app=app, view=lambda _ctx: app, require_api_access=refuse))
    importlib.import_module(OWN_CODE[0]).plugin.apply(scope, {})

    async def asked() -> list[int]:
        async with TestClient(TestServer(app)) as client:
            return [(await client.get("/api/ratchet")).status, (await client.post("/api/ratchet/run", json={})).status]

    assert asyncio.run(asked()) == [403, 403]


def test_no_page_of_ours_calls_these_routes() -> None:
    """The row's words tell you nothing you normally use changes. If a page or a script starts calling these, they must.

    The routes' own file is in the answer, so a search that found nothing at all cannot pass.
    """
    places = ("thomas", "web", "extensions", "apps", "desktop", "scripts")
    found = subprocess.run(
        ["git", "grep", "-l", "api/ratchet", "--", *places], cwd=ROOT, capture_output=True, text=True
    )

    named = found.stdout.split()
    assert "thomas/server/routes/ratchet_routes.py" in named
    assert [name for name in named if name.startswith(("thomas/server/web/", "web/", "extensions/", "apps/"))] == []
    assert [name for name in named if name.startswith(("desktop/", "scripts/"))] == []


@pytest.mark.parametrize("changed", ["thomas/server/rows/ratchet.py", "thomas/server/routes/ratchet_routes.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_ratchet_off_touches_only_its_routes.py" in chosen
    assert "tests/test_a_ratchet_run_through_off_and_on.py" in chosen
    assert "tests/test_ratchet_routes.py" in chosen
