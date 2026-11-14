"""The plugin_sets row, off: the two routes for ready-made sets answer 404, and every switch carries on.

``GET /api/plugins/sets`` serves the sets and the headings the long list is filed under. ``POST /api/plugins/sets/{id}/apply``
presses the switches for a set. The words of the row live in ``thomas/server/rows/default.toml``, and each sentence of
them names the test that shows it, in this file or in ``tests/test_plugin_sets_apply_what_they_say.py``,
``tests/test_the_plugins_page_offers_ready_made_sets.py`` and ``tests/test_the_plugins_page_in_a_browser_with_sets.py``.

The row is ``thomas.server.rows.plugin_sets`` and its routes are ``thomas.server.ready_made_sets``, and those names are how a check finds this file when it changes. The
sets and headings are ``thomas/server/rows/sets.toml``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import re
from types import SimpleNamespace
from typing import Any

import pytest
import tomllib
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.row_off_fixture import ask_as_a_remote_caller, ask_from_another_machine, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "plugin_sets"
LIST = "GET /api/plugins/sets"
APPLY = "POST /api/plugins/sets/nothing/apply"
ASKS = [LIST, APPLY]
OWN_CODE = ("thomas.server.rows.plugin_sets", "thomas.server.ready_made_sets")
# aiohttp lists a HEAD beside each GET.
LISTED = {"GET /api/plugins/sets", "HEAD /api/plugins/sets", "POST /api/plugins/sets/{id}/apply"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("sets-off")
    started, found = start_with_one_row_off(ROW, ASKS, folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("sets-remote")
    started, found = ask_as_a_remote_caller(ROW, ASKS, folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def elsewhere(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("sets-elsewhere")
    started, found = ask_from_another_machine(ROW, ASKS, folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_the_routes_answer_404_and_are_not_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == {LIST: 404, APPLY: 404}
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_the_switches_are_there_with_the_row_off(seen: dict[str, Any]) -> None:
    """The page's own switches are in the server, so a person who turned this off can turn it back on."""
    assert {
        "GET /api/plugins/thomas",
        "POST /api/plugins/thomas/{id}/on",
        "POST /api/plugins/thomas/{id}/off",
    } <= set(seen["listed_off"])


def test_turning_it_on_brings_the_routes_back_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    # An unknown set is 404 from the handler, which is also what a missing route says, so the list above tells them apart.
    assert seen["on"] == {LIST: 200, APPLY: 404}


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == {LIST: 404, APPLY: 404}
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    """Both are guarded. The token lets a caller in, and an unknown set is then the handler's own 404."""
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {LIST: 401, APPLY: 401}
    assert remote["with_token"] == {LIST: 200, APPLY: 404}


def test_a_caller_on_another_machine_is_refused_even_with_the_token(elsewhere: dict[str, Any]) -> None:
    """The switches are for this machine only, and so is a set, which presses them."""
    assert elsewhere["row"]["state"] == "active", elsewhere["row"]
    assert elsewhere["elsewhere"] == {LIST: 403, APPLY: 403}
    assert elsewhere["here"] == {LIST: 200, APPLY: 404}


def _a_bare_app_with(access: Any, loopback: Any) -> web.Application:
    app = web.Application()

    async def nothing(_request: web.Request) -> dict[str, Any]:
        return {}

    service = SimpleNamespace(
        view=lambda _ctx: app, app=app, require_api_access=access, require_loopback=loopback, read_json=nothing
    )
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})
    return app


def _refuse(_request: web.Request) -> None:
    raise web.HTTPForbidden()


def _let_in(_request: web.Request) -> None:
    return None


@pytest.mark.parametrize("access, loopback", [(_refuse, _let_in), (_let_in, _refuse)])
def test_the_apply_route_asks_both_guards_the_server_hands_the_row(access: Any, loopback: Any) -> None:
    """The remote test cannot see a guard go from this route, because the server refuses a POST under /api/ itself."""
    app = _a_bare_app_with(access, loopback)

    async def asked() -> tuple[int, int]:
        async with TestClient(TestServer(app)) as client:
            return (
                (await client.post("/api/plugins/sets/everyday/apply", json={})).status,
                (await client.get("/api/plugins/sets")).status,
            )

    assert asyncio.run(asked()) == (403, 403)


def test_a_row_given_no_guard_fails_rather_than_serving_open_routes() -> None:
    with pytest.raises(RuntimeError):
        _a_bare_app_with(None, _let_in)


def test_the_row_starts_no_work_and_has_no_stop_step() -> None:
    """It answers requests and presses switches. A stop waits for a request that is running, and that is all it needs."""
    for name in ("rows/plugin_sets.py", "ready_made_sets.py"):
        source = (ROOT / "thomas" / "server" / name).read_text(encoding="utf-8")
        code = ast.unparse(ast.parse(source))
        for word in ("on_stopped", "on_ready", "Thread", "create_task", "ctx.task", "Popen", "subprocess"):
            assert word not in code, (name, word)


def test_a_change_to_the_row_or_its_sets_runs_their_proofs() -> None:
    own = "tests/test_turning_plugin_sets_off_touches_only_its_routes.py"
    feature = "tests/test_plugin_sets_apply_what_they_say.py"
    for changed in (
        "thomas/server/rows/plugin_sets.py",
        "thomas/server/ready_made_sets.py",
        "thomas/server/rows/sets.toml",
    ):
        chosen = select(ROOT, [changed]).files
        assert own in chosen, changed
        assert feature in chosen, changed


# The words, a sentence at a time. Each is shown by the test named beside it, in this file or in the next one. A new,
# changed or dropped sentence fails here until the list has it with a test that shows it.
APPLYING = "test_applying_the_smallest_set_turns_the_rest_off_and_then_everything_turns_them_back_on"
WORDS = {
    "about": {
        "Offers ready-made sets of plugins, such as Everyday and Just chat and build, and the plain headings the long list "
        "of plugins is filed under.": (
            "test_the_three_sets_are_there_and_every_one_keeps_what_cannot_be_turned_off",
            "test_every_plugin_is_in_exactly_one_group",
        ),
        "Applying a set turns on every plugin it names and turns off every other plugin that can be turned off.": (
            APPLYING,
        ),
        "Chat and Build, and this plugin itself, are never turned off.": (APPLYING,),
        "The answer to applying a set says what was turned on, what was turned off and what was left alone, and why.": (
            APPLYING,
        ),
        "The Plugins page shows the sets as cards and folds the long list of plugins away under a button, with the "
        "plugins filed under these headings.": (
            "test_the_default_view_is_three_cards_and_no_list_of_plugins",
            "test_advanced_opens_every_plugin_under_the_headings_and_is_remembered_for_the_session_only",
        ),
    },
    "off_means": {
        "While this is off, the sets and headings cannot be fetched and no set can be applied.": (
            "test_with_the_row_off_the_routes_answer_404_and_are_not_listed",
        ),
        "Each plugin's own switch on the Plugins page still works, and every plugin stays as it is.": (
            "test_the_switches_are_there_with_the_row_off",
            "test_with_the_row_off_the_server_starts_and_every_other_row_is_up",
        ),
        "Turning this on again brings the sets back with no restart.": (
            "test_turning_it_on_brings_the_routes_back_without_a_restart",
        ),
        "The Plugins page then shows the long list of plugins in place of the cards, as it did before there were sets, "
        "and brings the cards back by itself.": (
            "test_with_the_sets_plugin_off_the_plain_list_is_the_page_and_turning_it_on_brings_the_cards_back",
            "test_turning_the_sets_plugin_off_from_the_list_brings_the_plain_list_back",
        ),
    },
    "stop_now": {
        "A set that is being applied is cut off part way, and the plugins it had not reached stay as they were.": (
            "test_stop_now_cuts_a_set_off_part_way_and_leaves_the_rest_as_they_were",
        ),
    },
}
FILES = (
    "test_turning_plugin_sets_off_touches_only_its_routes.py",
    "test_plugin_sets_apply_what_they_say.py",
    "test_the_plugins_page_in_a_browser_with_sets.py",
    "test_the_plugins_page_offers_ready_made_sets.py",
)


def _row() -> dict[str, Any]:
    rows = tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text("utf-8"))["row"]
    return next(row for row in rows if row["id"] == ROW)


@pytest.mark.parametrize("field", ["about", "off_means", "stop_now"])
def test_every_sentence_of_the_words_names_the_test_that_shows_it(field: str) -> None:
    text = "".join((ROOT / "tests" / name).read_text("utf-8") for name in FILES)
    assert re.split(r"(?<=\.)\s+", _row()[field]) == list(WORDS[field])
    named = {name for names in WORDS[field].values() for name in names}
    assert {name for name in named if f"def {name}(" not in text} == set()
