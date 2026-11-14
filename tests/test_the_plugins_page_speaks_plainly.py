"""What the Plugins page is told: words a person can read, and why a row failed.

The words of every row are in ``thomas/server/rows/default.toml``. That name is also how a check finds this file when the
list changes: a check follows imports and dotted names, and for a file that is not Python it looks for the file's name.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

from tests import plugin_view_fixture as views
from tests import runtime_plugin_fixture as fixture
from tests.plugin_page_fixture import FAILS_STARTING, HOOK_FAILS, ROUTES, report_of
from tests.plugin_view_fixture import runtime_with, state_of, until
from tests.row_proof_fixture import ROOT, ROWS, stop_ends_by_itself, what_holds_a_stop
from thomas.core.kernel import Entry
from thomas.server import app_core
from thomas.server.live_routes import WebService
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, PROFILE_PATH, RuntimePlugins

# What must never reach the page. The list is the one the page's wording was written against.
FOR_THE_CODE = re.compile(
    r"\b(row|fork|kernel|mount|seam|hook|profile|entry|unloading|pending|disposed|loopback)\b|[/\\_]", re.IGNORECASE
)
# The Marketplace row's words, a sentence at a time, each with the tests that show it on a real server and in a real
# browser. The routes and the apps you installed are in tests/test_turning_catalog_off_touches_only_its_routes.py, and
# the page in the window is in tests/test_the_marketplace_page_when_its_row_is_off.py. This is the one file a check runs
# when the words change, and those are the ones it runs when the page changes, so either change has to go through what
# the other says.
CATALOG_PROOFS = (
    "tests/test_turning_catalog_off_touches_only_its_routes.py",
    "tests/test_the_marketplace_page_when_its_row_is_off.py",
)
CATALOG_WORDS = {
    "While this is off, the Marketplace page says it is unavailable and where to turn it back on, and nothing from the "
    "store is listed.": (
        "test_with_the_row_off_the_page_says_so_and_lists_nothing",
        "test_a_normal_window_shows_the_words_without_scrolling",
    ),
    "You cannot install, remove, turn on or turn off anything from it, except in its Plugged in section, which still "
    "answers.": ("test_only_the_plugged_in_section_still_answers",),
    "The page tries again about every minute and a half, even in a tab you have left, and you can scroll it, type in its "
    "search box and click on it as usual.": (
        "test_after_a_failed_ask_the_page_waits_even_in_a_tab_you_have_left",
        "test_turned_back_on_the_page_fills_in_by_itself",
        "test_the_wheel_your_typing_and_a_normal_click_all_work",
    ),
    "Turned back on, it fills in by itself the next time it tries, or at once if you press Sync Catalog.": (
        "test_turned_back_on_the_page_fills_in_by_itself",
        "test_a_press_of_sync_catalog_does_not_wait",
    ),
    "Apps you installed stay installed and keep what they saved, but their pages will not open: after a reload they leave "
    "the sidebar and Library and nothing says why, and a desktop shortcut to one shows 404: Not Found.": (
        "test_an_installed_app_loses_only_its_pages_through_off_and_on",
        "test_after_a_reload_an_app_leaves_the_sidebar_and_library_and_nothing_says_why",
        "test_a_desktop_shortcut_to_an_app_shows_a_bare_404",
    ),
    "An app page already open goes on working until you reload it.": (
        "test_an_open_app_page_goes_on_working_until_you_reload_it",
    ),
    "A Marketplace page already open keeps its list until you reload it, but installing or removing anything from it "
    "fails.": (
        "test_an_open_marketplace_page_keeps_its_list_through_a_failed_refresh",
        "test_only_the_plugged_in_section_still_answers",
    ),
    "Other computers cannot reach the plugin store on this Thomas.": (
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
}
# The same for the agent panels row, in tests/test_turning_agent_panels_off_touches_only_its_routes.py. Its about is held
# too, because that claims the most.
AGENT_PANELS_WORDS = {
    "Keeps routes for steering a running agent, live run telemetry and worktree progress.": (
        "test_the_routes_are_steering_run_telemetry_and_worktree_progress",
    ),
    "No page in Thomas shows these any more, so only other programs can call them.": (
        "test_no_page_in_thomas_calls_these_routes",
    ),
    "Nothing in Thomas reports to them, so your agents, Build runs and chats never appear there.": (
        "test_nothing_in_thomas_feeds_these_panels",
    ),
    "They hold only what another program sends them.": ("test_nothing_in_thomas_feeds_these_panels",),
    "A steer sent to them is kept, but no agent reads it.": (
        "test_a_steer_is_kept_where_nothing_can_read_it",
        "test_nothing_in_thomas_feeds_these_panels",
    ),
    "While this is off, your agents, Build runs and chats carry on as before, because none of them report to these "
    "routes.": ("test_nothing_in_thomas_feeds_these_panels",),
    "Nothing you see in Thomas changes, because no page shows them.": ("test_no_page_in_thomas_calls_these_routes",),
    "Every one of these routes answers 404 and none is listed.": (
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "Turning this off forgets everything they held, including any target set and any steer sent, and other programs "
    "cannot report here.": (
        "test_off_forgets_what_the_panels_held_and_on_starts_empty",
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "When you turn this back on the routes work with no restart, and start empty.": (
        "test_turning_it_on_brings_back_all_14_routes_without_a_restart",
        "test_off_forgets_what_the_panels_held_and_on_starts_empty",
    ),
}


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    views.reset()
    fixture.failures_left = 0
    fixture.cleaned_up.clear()


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _shipped_rows() -> list[dict[str, Any]]:
    with PROFILE_PATH.open("rb") as handle:
        return tomllib.load(handle)["row"]


@pytest.mark.parametrize("row", _shipped_rows(), ids=lambda row: row["id"])
def test_every_shipped_row_says_what_it_is_in_plain_words(row: dict[str, Any]) -> None:
    for word in ("title", "about", "off_means"):
        assert row[word].strip(), word
    assert "stop_now" in row  # left empty only by a row a stop never waits for, which the test below holds it to
    assert row["title"].casefold() != row["id"].casefold()
    written = " ".join(row[word] for word in ("title", "about", "off_means", "stop_now"))
    assert FOR_THE_CODE.search(written) is None, written
    if row.get("required"):  # it has no off switch, so its words say what the page shows in place of one
        assert "cannot be turned off" in row["off_means"]


def test_every_sentence_of_the_marketplace_words_names_the_test_that_shows_it() -> None:
    """The words are what you are told, so none of them lands on the strength of having been true once.

    A new sentence, a changed one or a dropped one fails here until CATALOG_WORDS has it with a test that shows it.
    """
    row = next(row for row in _shipped_rows() if row["id"] == "catalog")
    proofs = {name: (ROOT / name).read_text(encoding="utf-8") for name in CATALOG_PROOFS}

    assert re.split(r"(?<=\.)\s+", row["off_means"]) == list(CATALOG_WORDS)
    named = {name for names in CATALOG_WORDS.values() for name in names}
    assert {name for name in named if not any(f"def {name}(" in text for text in proofs.values())} == set()


def test_every_sentence_of_the_agent_panels_words_names_the_test_that_shows_it() -> None:
    """As for the Marketplace above. A new, changed or dropped sentence fails here until the list has it with a test."""
    row = next(row for row in _shipped_rows() if row["id"] == "agent_panels")
    proofs = (ROOT / "tests" / "test_turning_agent_panels_off_touches_only_its_routes.py").read_text(encoding="utf-8")

    written = [*re.split(r"(?<=\.)\s+", row["about"]), *re.split(r"(?<=\.)\s+", row["off_means"])]
    assert written == list(AGENT_PANELS_WORDS)
    named = {name for names in AGENT_PANELS_WORDS.values() for name in names}
    assert {name for name in named if f"def {name}(" not in proofs} == set()


def test_a_change_to_the_list_runs_this_file() -> None:
    """Each row's words reach the list by hand at its landing, so words broken there must not land green."""
    assert "tests/test_the_plugins_page_speaks_plainly.py" in select(ROOT, ["thomas/server/rows/default.toml"]).files


def test_a_row_with_no_stop_now_words_gives_a_stop_nothing_to_wait_for(tmp_path: Path, own_data_dir: Path) -> None:
    """Stop now always shows its cost beside it, so a row that could ever show the button needs that sentence."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = app[APP_RUNTIME_PLUGINS]
            rows = {row["id"]: row for row in runtime.report()["rows"]}
            assert rows  # an empty compare would pass
            for entry in ROWS:
                assert rows[entry.id]["title"], entry.id
                if rows[entry.id]["required"]:  # a stop is refused, so it never waits
                    continue
                if not rows[entry.id]["stop_now"]:
                    assert what_holds_a_stop(runtime, entry) == [], entry.id
                    assert await stop_ends_by_itself(runtime, entry.id), entry.id

    asyncio.run(scenario())


class _Holds:
    """A row with no routes whose work a stop would wait for, and no words to warn of it."""

    name = "holds-a-stop"
    inject = ()

    def __init__(self, build: Any) -> None:
        self._build = build

    def apply(self, ctx: Any, config: Any) -> None:
        self._build(ctx)


def _busy_in_a_task(ctx: Any) -> None:
    async def work() -> None:
        async with ctx.busy():
            await asyncio.Event().wait()

    ctx.on_ready(lambda: ctx.task(work, name="work"))


async def _nothing() -> None:
    return None


def _slow_to_end(ctx: Any) -> None:
    async def work() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await fixture.gate.wait()

    ctx.on_ready(lambda: ctx.task(work, name="work"))


busy_in_a_task = _Holds(_busy_in_a_task)
stop_step = _Holds(lambda ctx: ctx.on_stopped(_nothing))
drain_step = _Holds(lambda ctx: ctx.on_drain(_nothing))
slow_to_end = _Holds(_slow_to_end)


def _entry(attribute: str) -> Entry:
    return Entry(id="row", plugin=f"{__name__}:{attribute}")


def test_a_row_with_no_routes_whose_work_holds_a_stop_is_refused_those_words(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("row", f"{__name__}:busy_in_a_task", True)])
        runtime.load()
        runtime.mark_ready()
        await until(lambda: report_of(runtime, "row")["waiting_for"] == 1)

        held = what_holds_a_stop(runtime, _entry("busy_in_a_task"))

        assert held[0] == "work running now"
        assert not await stop_ends_by_itself(runtime, "row", within=0.05)
        await runtime.turn_off("row", force=True)

    asyncio.run(scenario())


def test_a_row_whose_work_has_not_begun_is_refused_those_words_too(tmp_path: Path) -> None:
    """Its work may start every few hours, so what is running when anyone looks is not enough to go on."""
    runtime = runtime_with(tmp_path, [("row", f"{__name__}:busy_in_a_task", True)])
    runtime.load()

    assert what_holds_a_stop(runtime, _entry("busy_in_a_task")) == [f"{__name__} marks work as busy"]


@pytest.mark.parametrize(("attribute", "reason"), [("stop_step", "stop steps"), ("drain_step", "drain steps")])
def test_a_row_with_steps_a_stop_must_run_is_refused_those_words(attribute: str, reason: str, tmp_path: Path) -> None:
    runtime = runtime_with(tmp_path, [("row", f"{__name__}:{attribute}", True)])
    runtime.load()

    assert reason in what_holds_a_stop(runtime, _entry(attribute))


def test_a_row_with_routes_is_refused_those_words(tmp_path: Path) -> None:
    runtime = runtime_with(tmp_path, [("row", ROUTES, True)])
    runtime.load()

    assert "routes" in what_holds_a_stop(runtime, Entry(id="row", plugin=ROUTES))


def test_a_task_slow_to_end_is_seen_by_a_real_stop_alone(tmp_path: Path) -> None:
    """Nothing about it can be read beforehand, so the guard turns the row off and watches."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("row", f"{__name__}:slow_to_end", True)])
        runtime.load()
        runtime.mark_ready()
        await asyncio.sleep(0)

        try:
            assert report_of(runtime, "row")["waiting_for"] == 0
            assert not await stop_ends_by_itself(runtime, "row", within=0.05)
        finally:
            fixture.gate.set()
        await until(lambda: state_of(runtime, "row") == "off")

    asyncio.run(scenario())


def test_your_saved_choice_leaves_a_rows_words_alone(tmp_path: Path) -> None:
    """A choice replaces the row's settings, so words kept beside them must survive it."""
    runtime = runtime_with(tmp_path, [("a", ROUTES, True)])
    profile = tmp_path / "profile.toml"
    words = 'title = "Apps"\nabout = "Runs them."\noff_means = "They stop."\nstop_now = "They fail."\n'
    profile.write_text(profile.read_text(encoding="utf-8") + words, encoding="utf-8")
    choices = tmp_path / "plugins" / "choices.json"
    choices.parent.mkdir()
    choices.write_text('{"a": {"enabled": false}}', encoding="utf-8")

    runtime.load()

    row = report_of(runtime, "a")
    assert row["state"] == "off"
    assert (row["title"], row["about"], row["off_means"], row["stop_now"]) == (
        "Apps",
        "Runs them.",
        "They stop.",
        "They fail.",
    )


def test_a_row_with_no_words_sends_none_and_never_its_id(tmp_path: Path) -> None:
    """The page falls back to its own wording on an empty field, so the id must not be put there to fill it."""
    runtime = runtime_with(tmp_path, [("a", ROUTES, False)])

    runtime.load()

    row = report_of(runtime, "a")
    assert (row["title"], row["about"], row["off_means"], row["stop_now"]) == ("", "", "", "")


def test_notes_carry_a_fixed_code_beside_their_text(tmp_path: Path) -> None:
    service = WebService(web.Application(), None, require_api_access=None, read_json=None)
    unreadable_list = RuntimePlugins(service, profile_path=tmp_path / "nope.toml", choices_path=tmp_path / "c.json")
    unreadable_list.load()

    damaged = runtime_with(tmp_path, [("a", ROUTES, False)])
    choices = tmp_path / "plugins" / "choices.json"
    choices.parent.mkdir()
    choices.write_text("{not json", encoding="utf-8")
    damaged.load()

    assert unreadable_list.report()["note_codes"] == ["list_unreadable"]
    assert damaged.report()["note_codes"] == ["choices_unreadable"]
    assert "could not be read" in damaged.report()["notes"][0]


def test_a_row_that_fails_starting_says_why(tmp_path: Path) -> None:
    fixture.failures_left = 1
    runtime = runtime_with(tmp_path, [("bad", FAILS_STARTING, True)])
    runtime.load()

    runtime.mark_ready()

    row = report_of(runtime, "bad")
    assert row["state"] == "failed"
    assert row["error"] == "RuntimeError: the port is taken"


def test_a_row_whose_startup_hook_fails_says_why(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.failures_left = 1
        runtime = runtime_with(tmp_path, [("bad", HOOK_FAILS, True)])
        runtime.load()

        runtime.mark_ready()
        await until(lambda: state_of(runtime, "bad") == "failed")

        assert report_of(runtime, "bad")["error"] == "RuntimeError: the port is taken"

    asyncio.run(scenario())


def test_a_row_clearing_away_its_failure_stops_showing_it(tmp_path: Path) -> None:
    """A reason belongs to a row that reads failed. While one clears away, the page has nothing to explain."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        fixture.failures_left = 1
        runtime = runtime_with(tmp_path, [("a", HOOK_FAILS, True)])
        runtime.load()
        runtime.mark_ready()
        async with TestClient(TestServer(runtime.web.app)) as client:
            await until(lambda: state_of(runtime, "a") == "failed")
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)

            trying = asyncio.create_task(runtime.turn_on("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")

            assert report_of(runtime, "a")["error"] == ""

            fixture.gate.set()
            await asyncio.gather(trying, running)

    asyncio.run(scenario())
