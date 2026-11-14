"""The search row, off: its thirteen routes answer 404, a server started that way never loads them, and chat still searches.

The word search names many things in Thomas, and this row serves two of them. ``GET /api/search/web`` fills the results
page you reach from either Search or type a URL box, through the ``web.search`` tool. That tool is on the server's own
list, not this row's, so off leaves chat searching the web. The other twelve routes serve one store,
``thomas/core/search_history.py``: an index of conversations, with bookmarks and saved searches beside it. No page calls
those twelve, and the index reads a list nothing writes, so on a new install it is empty. Other things with the name are
further away still: the bookmarks bar keeps its list in the browser, and the Discord history, the code search and the
chat list filter have nothing to do with these routes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server import app_core
from thomas.server.app_helpers import _build_tools
from thomas.server.app_keys import APP_TOOLS
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS
from thomas.tools.base import ToolResult

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/search": "GET /api/search?q=hello",
    # Asked with no question, because a real one goes out to the web. The test below asks it through a stand-in tool.
    "GET /api/search/web": "GET /api/search/web",
    "GET /api/search/suggest": "GET /api/search/suggest?q=he",
    "GET /api/search/context": "GET /api/search/context?turn_id=t1",
    "GET /api/search/channels": "GET /api/search/channels",
    "GET /api/search/status": "GET /api/search/status",
    "POST /api/search/reindex": "POST /api/search/reindex",
    "GET /api/search/bookmarks": "GET /api/search/bookmarks",
    "POST /api/search/bookmarks": "POST /api/search/bookmarks",
    "DELETE /api/search/bookmarks/{turn_id}": "DELETE /api/search/bookmarks/t1",
    "GET /api/search/saved": "GET /api/search/saved",
    "POST /api/search/saved": "POST /api/search/saved",
    "DELETE /api/search/saved/{sid}": "DELETE /api/search/saved/1",
}
# The store is here too: nothing else imports it, so a server started off never opens its file.
OWN_CODE = ("thomas.server.rows.search", "thomas.server.routes.search", "thomas.core.search_history")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(name.replace("GET", "HEAD") for name in ROUTES if name.startswith("GET "))}

WEB = ROOT / "thomas" / "server" / "web"
SEARCH_JS = WEB / "js" / "browser_shell_search.js"
PLAYTEST = ROOT / "tests" / "web_node" / "browser_search_playtest.html"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("search-off")
    started, found = start_with_one_row_off("search", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("search-remote")
    started, found = ask_as_a_remote_caller("search", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "search"}
    assert seen["rows"]["search"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_thomas_can_still_search_the_web_in_chat(seen: dict[str, Any], tmp_path: Path) -> None:
    """The row's words promise this. Chat asks the tool directly, so a tool off this row's list would break that promise."""
    assert "thomas.tools.resilient_web_search" in seen["loaded"]
    assert "web.search" in _build_tools(views.config_in(tmp_path))


def test_turning_it_on_brings_back_all_thirteen_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """Each answer is the handler's, on the real store. The fixture sends an empty body, so the two POSTs that need one
    refuse it, and ``/api/search/web`` refuses a missing question. No handler here answers 404 for what it lacks.
    """
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {
        **dict.fromkeys(ROUTES.values(), 200),
        "GET /api/search/web": 400,
        "POST /api/search/bookmarks": 400,
        "POST /api/search/saved": 400,
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does.

    The store stays open too, because it is held at the top level of its module, and that is why what it holds is there
    when the row comes back.
    """
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_web_search_reaches_the_tool_through_the_row(tmp_path: Path, own_data_dir: Path) -> None:
    """The one route a page uses, on a real server. The handler finds the tool on ``request.app``, which a row must not lose."""

    async def scenario() -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
        app = app_core.create_app(views.config_in(tmp_path))
        asked: list[dict[str, Any]] = []

        async def answer(args: dict[str, Any]) -> ToolResult:
            asked.append(args)
            row = {"title": "A page", "url": "https://example.com/a", "description": "It says so."}
            return ToolResult(ok=True, data={"provider": "stand-in", "results": [row]})

        app[APP_TOOLS].get("web.search").execute = answer
        async with TestClient(TestServer(app)) as client:
            answered = await client.get("/api/search/web", params={"q": "tallest tree", "count": "3"})
            return answered.status, await answered.json(), asked

    status, body, asked = asyncio.run(scenario())

    assert (status, asked) == (200, [{"query": "tallest tree", "count": 3}])
    assert body["results"] == [
        {"title": "A page", "url": "https://example.com/a", "snippet": "It says so.", "published": None}
    ]


def test_a_row_that_cannot_register_reads_failed_and_not_active_with_no_routes(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``tests/test_server_app_routes_init.py`` pins the log line, and would pass with the raise after it gone."""

    def fails(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("a reason you can read")

    monkeypatch.setitem(sys.modules, "thomas.server.routes.search", SimpleNamespace(register_search_routes=fails))
    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.search"):
        app = app_core.create_app(views.config_in(tmp_path))
    row = next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "search")

    assert row["state"] == "failed", row
    assert "a reason you can read" in row["error"]
    assert "Search routes unavailable: a reason you can read" in caplog.text


def test_a_server_with_no_access_guard_gets_no_search_routes(caplog: pytest.LogCaptureFixture) -> None:
    from thomas.server.rows.search import plugin

    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.search"):
        with pytest.raises(RuntimeError, match="no access guard"):
            plugin.apply({"web": SimpleNamespace(require_api_access=None)}, {})

    assert "Search route registration skipped: missing runtime dependencies" in caplog.text


def test_one_page_calls_these_routes_and_it_calls_one_of_them() -> None:
    """The row's words name that page and say no page shows the rest. If a caller appears, those words have to change.

    A landing runs this only for a change to the row, its routes or this file. A caller added anywhere else is found by the
    full suite.
    """
    files = {path: path.read_text(encoding="utf-8") for path in [*WEB.rglob("*.js"), *WEB.rglob("*.html")]}

    assert [path.name for path, text in files.items() if "/api/search" in text] == [SEARCH_JS.name]
    assert re.findall(r'"(/api/search[^"?]*)', files[SEARCH_JS]) == ["/api/search/web"]


def test_both_boxes_the_words_name_lead_to_the_results_page() -> None:
    bar = (WEB / "js" / "browser_shell.js").read_text(encoding="utf-8")
    new_tab = (WEB / "js" / "browser_shell_web.js").read_text(encoding="utf-8")

    assert "openUrl(websearch.toUrl(raw))" in bar
    assert "convertNtpToWeb(tab, websearch().toUrl(inp.value))" in new_tab
    assert 'placeholder="Search or type a URL' in bar
    assert 'placeholder="Search or type a URL' in new_tab


def test_the_bookmarks_bar_keeps_its_own_list_in_the_browser() -> None:
    """The row's words say it is separate from the bookmarks these routes hold. The test above shows it never calls them."""
    assert 'localStorage.setItem("thomas_browser_bookmarks"' in (WEB / "js" / "browser_shell.js").read_text(
        encoding="utf-8"
    )


def test_nothing_in_thomas_adds_to_the_conversation_index() -> None:
    """The row's words say so. The index reads one list and ``record_turn`` is the only way onto it, with no caller.

    If something starts recording turns, this fails and those words have to change.
    """
    adding = re.compile(r"\.(record_turn|index_turn)\(")
    found = [path for path in (ROOT / "thomas").rglob("*.py") if adding.search(path.read_text(encoding="utf-8"))]

    assert sorted(path.relative_to(ROOT).as_posix() for path in found) == [
        "thomas/core/persistence.py",  # a line of its docstring, not a call
        "thomas/core/search_history.py",  # what the index does with the list it read
    ]


def test_a_search_that_gets_a_404_says_so_on_the_page_as_the_words_describe() -> None:
    """The shipped page, handed what a server with this row off really answers: a 404 with a text body."""
    from tests.web_fixtures.thomas_chat_fixture import browser_ok

    if not browser_ok():
        pytest.skip("Chromium unavailable")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(PLAYTEST.as_uri())
            page.locator(".bt-sr-title").first.wait_for()
            page.evaluate(
                """() => {
                  const before = window.fetch;
                  window.fetch = async (url, options = {}) => String(url).startsWith('/api/search/web')
                    ? new Response('404: Not Found', { status: 404, headers: { 'Content-Type': 'text/plain' } })
                    : before(url, options);
                }"""
            )
            assert page.locator(".bt-sr-title").count() == 2  # off does not reach a page already open

            page.locator(".bt-sr-form input").fill("tallest tree")
            page.locator(".bt-sr-form input").press("Enter")
            page.get_by_text("Couldn’t load results").wait_for()

            assert page.locator(".bt-sr-summary").inner_text() == "Search unavailable"
            assert "HTTP 404" in page.locator(".bt-sr-empty").inner_text()
            assert page.get_by_role("button", name="Try again").count() == 1
            assert page.locator(".bt-ai").count() == 0  # no overview either
        finally:
            browser.close()


@pytest.mark.parametrize("changed", ["thomas/server/rows/search.py", "thomas/server/routes/search.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these two only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_search_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_search_routes.py" in chosen
