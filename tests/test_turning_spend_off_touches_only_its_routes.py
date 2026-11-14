"""The spend row, off: its nine routes answer 404, a server started that way never loads them, and an open page cannot
hold the switch.

The page calls this Token Economy, and the word spend names several things in Thomas. This row serves one: the ledger
in ``thomas_spend.jsonl``, read through ``thomas/core/cost_tracker.py``, plus the prices and the runtime settings shown
beside it. The token budget for a chat and the guardrails spend cap keep figures of their own and read no route here, and
the limit on self-upgrade spending reads the ledger file itself. The cost line in Chat counts tokens from each reply's
own receipt and asks this row only for its prices, which is why off costs it the dollars and leaves the tokens. These
tests hold the row's words to that.

Each sentence of those words was also checked once in a browser against a real server, with this row pressed off and on.
A test here cannot hold what a page paints, so the tests below hold what that painting rests on.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from evolve_supervisor import record_evolve_child_spend
from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS, stop_ends_by_itself
from thomas.core.cost_tracker import CostTracker
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = (
    "GET /api/spend/today",
    "GET /api/spend/session",
    "POST /api/spend/session/reset",
    "GET /api/spend/history",
    "GET /api/spend/pricing",
    "GET /api/spend/export.csv",
    "GET /api/spend/stream",
    "GET /api/runtime/profile",
    "GET /api/runtime/matrix",
)
OWN_CODE = ("thomas.server.rows.spend", "thomas.server.routes.spend")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(route.replace("GET", "HEAD") for route in ROUTES if route.startswith("GET"))}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("spend-off")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("THOMAS_SPEND_PATH", str(folder / "ledger.jsonl"))  # its default is beside the checkout
        started, found = start_with_one_row_off("spend", list(ROUTES), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("spend-remote")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("THOMAS_SPEND_PATH", str(folder / "ledger.jsonl"))
        started, found = ask_as_a_remote_caller("spend", list(ROUTES), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "spend"}
    assert seen["rows"]["spend"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES, 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_nine_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys(ROUTES, 200)


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does.

    The ledger's running totals live in ``thomas/core/cost_tracker.py``, so they survive off and on the same way.
    """
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES, 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES, 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_an_open_token_economy_page_cannot_hold_the_off_switch(tmp_path: Path, own_data_dir: Path) -> None:
    """The stream sends a keepalive every 15 seconds for as long as the page is open, so a stop that waited for it would
    never end. The page sees the stream end, and the row reads off with no second press."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            opened = await client.get("/api/spend/stream")
            assert opened.status == 200
            assert await opened.content.readline() == b"event: hello\n"

            assert await stop_ends_by_itself(runtime, "spend")

            assert runtime._report_row(runtime._row("spend"))["state"] == "off"
            assert await opened.content.read() == b"data: {}\n\n"  # the rest of hello, then the end of the stream
            assert (await client.get("/api/spend/stream")).status == 404

    asyncio.run(scenario())


def test_the_ledger_counts_a_self_upgrade_run_as_a_call_with_no_tokens(tmp_path: Path) -> None:
    """The row's words tell you replies in chat are not counted. Only the self-upgrade loop adds to this ledger.

    If anything else starts reading the ledger through the tracker, or a reply starts adding to it, this fails and those
    words have to change.
    """
    (tmp_path / "evolve_governor.toml").write_text(
        "[spend_governor]\n"
        "enabled = true\n"
        'ledger_path = "thomas_spend.jsonl"\n'
        "daily_usd_cap = 10.0\n"
        "total_usd_cap = 250.0\n"
        "per_iteration_usd_reserve = 0.25\n",
        encoding="utf-8",
    )
    today = date.today().isoformat()
    written = record_evolve_child_spend(tmp_path, {"returncode": 0}, session_id="s", phase="green", today=today)
    tracker = CostTracker(spend_path=tmp_path / "thomas_spend.jsonl", toml_path=tmp_path / "none.toml")

    assert written.ok, written.message
    assert tracker.today_call_count() == 1
    assert tracker.today_tokens()["total"] == 0

    package = ROOT / "thomas"
    using = {path: path.read_text(encoding="utf-8") for path in package.rglob("*.py")}
    tracked = {path: text for path, text in using.items() if "cost_tracker import" in text or "CostTracker(" in text}
    assert sorted(path.relative_to(package).as_posix() for path in tracked) == [
        "cli/repl_runtime.py",
        "core/cost_tracker.py",
        "server/routes/spend.py",
    ]
    outside = [text for path, text in tracked.items() if path.name != "cost_tracker.py"]
    assert not any(call in text for text in outside for call in ("tracker.record", "ct.record", "record_from_any"))


def test_the_limit_on_self_upgrade_spending_reads_the_ledger_and_not_these_routes() -> None:
    """The row's words tell you that limit still works with this off."""
    governor = (ROOT / "evolve_supervisor" / "spend_governor.py").read_text(encoding="utf-8")
    assert "_read_spend_ledger(ledger_path" in governor
    assert "api/spend" not in governor


def test_two_places_a_person_can_reach_ask_these_routes() -> None:
    """Token Economy and the cost line, which are all the row's words name.

    The third script fetches for a view called finance. If it gets a way in from the sidebar, or a fourth script starts
    asking, this fails and those words have to change. A landing runs this only for a change to those scripts, this row
    or its routes. A caller added anywhere else is found by the full suite.
    """
    web = ROOT / "thomas" / "server" / "web"
    scripts = {path: path.read_text(encoding="utf-8") for path in web.rglob("*.js")}
    routes = ("/api/spend", "/api/runtime/profile", "/api/runtime/matrix")
    pages = [path for path in web.rglob("*.html") if any(route in path.read_text(encoding="utf-8") for route in routes)]
    asking = sorted(path.name for path, text in scripts.items() if any(route in text for route in routes))
    sidebar = scripts[web / "js" / "browser_shell.js"].partition("const BUILTIN_WS")[2].partition("};")[0]

    # system_page.js is the System page's Spend page (684cf65e2), reached from System in the sidebar.
    assert (pages, asking) == (
        [],
        ["024_mission_control_02.js", "cost_readout.js", "system_page.js", "token_economy.js"],
    )
    assert "Token Economy" in sidebar  # an empty read would pass the line below
    assert "finance" not in sidebar


def test_the_cost_line_asks_for_its_prices_once_as_chat_loads() -> None:
    """The row's words tell you an open Chat keeps its dollars, and one reloaded with this off needs reloading once it
    is back on. If the line starts asking again later, this fails and those words have to change."""
    script = (ROOT / "thomas" / "server" / "web" / "js" / "cost_readout.js").read_text(encoding="utf-8")
    assert script.count("loadPricing()") == 2  # where it is written, and the one line that calls it
    assert "function start() { wrap(); loadPricing(); }" in script


def test_the_window_is_the_one_control_that_costs_an_open_page_what_it_shows() -> None:
    """The row's words in ``default.toml`` tell you an open Token Economy page keeps its counts, except when you change
    its Window. That control throws the history away before it asks, and only a good answer fills it again, so with this
    off there is nothing left to draw. The bar under today's count and the percent under the average are worked out from
    the same history. Nothing asks again when this comes back on, which is why the words send you to Refresh. If any of
    that changes, this fails and those words have to change.
    """
    script = (ROOT / "thomas" / "server" / "web" / "js" / "token_economy.js").read_text(encoding="utf-8")
    window = script.partition("sel.addEventListener('change'")[2].partition("const rb")[0]
    hero = script.partition("function paintHero()")[2].partition("function paintDataStrip()")[0]
    strip = script.partition("function paintDataStrip()")[2].partition("function paintModes()")[0]
    stream = script.partition("function sseOn()")[2].partition("function sseOff()")[0]
    words = next(row.config["words"]["off_means"] for row in ROWS if row.id == "spend")

    assert -1 < window.find("_s.history = null;") < window.find("refresh({ force")
    assert "if (h.ok) _s.history = " in script
    assert "_s.history" in hero and "_s.history" in strip
    assert "EventSource" in stream  # an empty read would pass the line below
    assert "refresh(" not in stream
    for said in (
        "Changing its Window",
        "awaiting first API call",
        "the bar under today's count",
        "the percent under the average",
        "press Refresh",
    ):
        assert said in words
    assert (
        "tests/test_turning_spend_off_touches_only_its_routes.py"
        in select(ROOT, ["thomas/server/rows/default.toml"]).files
    )


@pytest.mark.parametrize("changed", ["thomas/server/rows/spend.py", "thomas/server/routes/spend.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these two only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_spend_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_spend_routes.py" in chosen
