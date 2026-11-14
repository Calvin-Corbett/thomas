"""The attention row, off: its three routes answer 404, its two tools are taken back, and nothing else moves.

The row is the cards Thomas puts beside the conversation. You asked for them on 2026-11-09: "have a panel pop up on
the left side of where the chat's not". They are a row so that they can be turned off: with it off no page shows a
card, no run can show one, and a server started that way never loads the code.

Proofs of ``thomas.server.rows.attention``, ``thomas.server.routes.attention_routes``,
``thomas.server.attention_tools`` and ``thomas.core.attention_cards``. What a card may carry and how one is drawn are
in ``tests/test_attention_cards.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from tests.row_words_fixture import sentences, unnamed_tests
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "attention"
# Written out, because a list worked out from the row would agree with whatever the row did. Each is sent an empty
# body: a card with no title is refused (400), and a card that is not open is gone (410), so neither reads as a 404.
ROUTES = {
    "GET /api/attention/cards": 200,
    "POST /api/attention/cards": 400,
    "POST /api/attention/cards/none/act": 410,
    "GET /api/attention/widgets": 200,
    "POST /api/attention/widgets/none": 400,
}
# aiohttp lists a HEAD beside each GET.
LISTED = {
    "GET /api/attention/cards",
    "HEAD /api/attention/cards",
    "POST /api/attention/cards",
    "POST /api/attention/cards/{id}/act",
    "GET /api/attention/widgets",
    "HEAD /api/attention/widgets",
    "POST /api/attention/widgets/{name}",
}
TOOLS = ["attention_read", "attention_show", "attention_widget", "attention_widget_save"]
OWN_CODE = (
    "thomas.core.attention_blocks",
    "thomas.core.attention_cards",
    "thomas.server.attention_tools",
    "thomas.server.attention_widget_templates",
    "thomas.server.attention_widgets",
    "thomas.server.routes.attention_routes",
    "thomas.server.rows.attention",
)
HERE = Path(__file__)
CARD_TESTS = ROOT / "tests" / "test_attention_cards.py"
WIDGET_TESTS = ROOT / "tests" / "test_attention_widgets.py"
JS = ROOT / "thomas" / "server" / "web" / "js"
# Run in the fresh process at each of the three points. It imports nothing the row names.
READING = """\
def reading():
    from thomas.agent.kernel_wiring import contributed_tools

    return sorted(tool.name for tool in contributed_tools() if tool.name.startswith("attention_"))


"""
WORDS = {
    "Lets Thomas put a card in the empty space left of the conversation, on whichever Chat, Build or Work tab you are "
    "looking at.": ("test_the_page_draws_in_the_gutter_and_only_on_the_tab_on_screen",),
    "A card is a notice, a question with buttons, a reply box, a picture, a live preview of a page he built, or a "
    "layout he wrote himself.": (
        "test_every_kind_of_card_is_drawn_and_nothing_a_card_carries_reaches_the_page_as_markup",
        "test_a_picture_or_a_preview_from_anywhere_but_this_pc_is_refused",
    ),
    "A widget is a card that stays open and shows live readings, lists, progress and switches in the app's own style, "
    "such as this PC's load or which plugins are on.": (
        "test_a_summoned_widget_stays_open_and_is_filled_from_the_live_readings",
        "test_an_open_widget_is_refilled_in_place_when_it_is_due",
        "test_a_switch_is_labelled_from_the_row_and_turns_it",
        "test_every_kind_of_block_is_drawn_in_the_apps_own_style",
    ),
    "Chat and the workers Thomas starts are given four tools for it, to show a card, read what you answered, summon a "
    "widget and save a new one.": (
        "test_turning_it_on_brings_back_the_routes_and_lends_the_four_tools_without_a_restart",
        "test_the_tools_show_a_card_and_read_its_answer",
        "test_thomas_lists_what_there_is_summons_one_makes_one_and_saves_one",
    ),
    "A Build tab that is not on screen shows a card when its task ends.": (
        "test_a_build_tab_that_is_not_on_screen_shows_a_card_when_its_task_ends",
    ),
    "A card also appears while this PC is close to its load limit.": (
        "test_a_card_appears_while_the_pc_is_close_to_its_limit",
        "test_the_row_starts_the_load_watch_as_a_task_a_stop_can_end",
    ),
    "Other programs can use the same routes.": (
        "test_a_remote_caller_with_no_token_is_refused_on_every_route",
        "test_a_card_shown_through_the_route_is_listed_answered_and_gone",
    ),
    "While this is off, no card or widget appears, and a page that is open asks once a minute in case it is turned "
    "back on.": (
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
        "test_a_page_told_404_goes_quiet_and_asks_once_a_minute",
    ),
    "Chat and the workers Thomas starts are no longer given the four tools, and a tool call to show a card is "
    "refused.": ("test_turned_off_on_a_running_server_the_routes_and_tools_go_and_the_code_stays_loaded",),
    "Cards are kept in memory only, so a restart starts with none.": (
        "test_the_cards_are_kept_in_memory_and_nothing_is_written",
    ),
    "A widget Thomas saved stays in the data folder and can be summoned again.": (
        "test_thomas_lists_what_there_is_summons_one_makes_one_and_saves_one",
    ),
    "A request that is still running will fail, and may need sending again.": (
        "test_stop_now_cuts_off_a_request_that_is_still_running",
    ),
}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("attention-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES), folder, reading=READING)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES), tmp_path_factory.mktemp("attention-remote"))
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES, 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_nothing_is_lent_and_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert seen["read_off"] == []
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_the_routes_and_lends_the_four_tools_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == ROUTES
    assert seen["read_on"] == TOOLS


def test_turned_off_on_a_running_server_the_routes_and_tools_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes and loans go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES, 404)
    assert seen["read_off_again"] == [], (
        "a run built from now on is not given the tools, and one that kept them is refused"
    )
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES, 401)
    assert remote["with_token"] == ROUTES


def test_a_card_shown_through_the_route_is_listed_answered_and_gone(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            card = {
                "title": "Sam sent you a message",
                "kind": "reply",
                "body": "Are we still on for 3?",
                "key": "route-test",
            }
            shown = await (await client.post("/api/attention/cards", json=card)).json()
            card_id = shown["card"]["id"]
            listed = await (await client.get("/api/attention/cards")).json()
            assert [row["id"] for row in listed["cards"] if row["key"] == "route-test"] == [card_id]
            refused = await client.post(
                "/api/attention/cards", json={"title": "x", "kind": "image", "image_url": "https://example.com/a.png"}
            )
            assert refused.status == 400 and "this PC" in (await refused.json())["error"]
            answered = await client.post(
                f"/api/attention/cards/{card_id}/act", json={"action": "reply", "value": "Yes, 3 works"}
            )
            assert (await answered.json())["card"]["answer"]["text"] == "Yes, 3 works"
            again = await client.post(f"/api/attention/cards/{card_id}/act", json={"action": "dismiss"})
            assert again.status == 410, "closed twice is told so, and not with the 404 that means the row is off"
            listed = await (await client.get("/api/attention/cards")).json()
            assert [row for row in listed["cards"] if row["key"] == "route-test"] == []

    asyncio.run(scenario())


def test_the_page_draws_in_the_gutter_and_only_on_the_tab_on_screen() -> None:
    page = (JS / "attention_cards.js").read_text(encoding="utf-8")
    assert "edge('aside.tc-sidebar', 'right', 0)" in page, "the gutter starts where the sidebar ends"
    for column in ("#tc-composer-rail", "#tc-thread", ".tc-work-home"):
        assert f"'{column}'" in page, f"and ends at the conversation in every mode ({column})"
    assert "room.width < MIN_GUTTER" in page and "host.classList.toggle('is-compact', compact)" in page
    resting = page.split("function resting() {", 1)[1].split("\n  }", 1)[0]
    assert "activity.isPaused()" in resting and "iframe.bt-doc.is-active.is-ready" in resting
    assert "if (!resting()) {" in page.split("async function ask() {", 1)[1].split("\n  }", 1)[0]
    helpers = (ROOT / "thomas" / "server" / "app_middleware_helpers.py").read_text(encoding="utf-8")
    assert helpers.index('"attention_card_view"') < helpers.index('"attention_cards"'), (
        "the drawing loads before its user"
    )


def test_a_page_told_404_goes_quiet_and_asks_once_a_minute() -> None:
    page = (JS / "attention_cards.js").read_text(encoding="utf-8")
    assert "QUIET_MS = 60000" in page
    assert "if (response.status === 404) { cards = []; wait = QUIET_MS; draw(); }" in page


def test_a_build_tab_that_is_not_on_screen_shows_a_card_when_its_task_ends() -> None:
    stream = (JS / "unified_code_run_stream.js").read_text(encoding="utf-8")
    finish = stream.split("async function finishRun() {", 1)[1]
    assert "window.ThomasAttention.taskEnded({ id: deps.state.activeId" in finish
    page = (JS / "attention_cards.js").read_text(encoding="utf-8")
    ended = page.split("function taskEnded(task) {", 1)[1].split("\n  }", 1)[0]
    assert "!activity.isPaused()) return;" in ended, "the tab you are looking at says nothing: you saw it end"
    assert "open_task: String(task.id)" in ended and "key: `task-${task.id}`" in ended


def test_the_row_starts_the_load_watch_as_a_task_a_stop_can_end() -> None:
    row = (ROOT / "thomas" / "server" / "rows" / "attention.py").read_text(encoding="utf-8")
    assert 'ctx.on_ready(lambda: ctx.task(lambda: watch_load(STORE), name="attention load watch"))' in row
    assert "asyncio.create_task" not in row


def test_the_cards_are_kept_in_memory_and_nothing_is_written() -> None:
    tree = ast.parse((ROOT / "thomas" / "core" / "attention_cards.py").read_text(encoding="utf-8"))
    imported = {
        (node.module if isinstance(node, ast.ImportFrom) else alias.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    assert imported <= {
        "__future__",
        "asyncio",
        "re",
        "threading",
        "time",
        "typing",
        "urllib.parse",
        "uuid",
        "thomas.core",
        "thomas.core.attention_blocks",
    }, imported
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "open"]


def test_stop_now_cuts_off_a_request_that_is_still_running(tmp_path: Path, own_data_dir: Path) -> None:
    began = asyncio.Event()

    async def never_ends() -> Any:
        yield b'{"title":'
        began.set()
        await asyncio.sleep(120)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            await views.rows_once_started(runtime)
            asking = asyncio.create_task(client.post("/api/attention/cards", data=never_ends()))
            await asyncio.wait_for(began.wait(), timeout=30)
            stopping = asyncio.create_task(runtime.turn_off(ROW))
            await asyncio.sleep(0.3)
            assert not stopping.done()

            await runtime.turn_off(ROW, force=True)
            await asyncio.wait_for(stopping, timeout=30)

            assert runtime._report_row(runtime._row(ROW))["state"] == "off"
            answer = (await asyncio.gather(asking, return_exceptions=True))[0]
            assert isinstance(answer, BaseException) or answer.status != 200, answer
            assert (await client.get("/api/attention/cards")).status == 404

    asyncio.run(scenario())


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    written = sentences(ROW, "about", "off_means", "stop_now")
    assert written == list(WORDS)
    assert unnamed_tests(WORDS, HERE, CARD_TESTS, WIDGET_TESTS) == []


@pytest.mark.parametrize(
    "changed",
    ["thomas/server/rows/attention.py", "thomas/server/routes/attention_routes.py", "thomas/core/attention_cards.py"],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_attention_off_touches_only_its_routes.py" in chosen
    assert "tests/test_attention_cards.py" in chosen
    assert "tests/test_attention_widgets.py" in chosen
