"""What the Browser tools row tells the Plugins page, one sentence at a time, each with the test that shows it.

The words are what you are told, so none of them lands on the strength of having been true once. A new, changed or dropped
sentence fails ``test_every_sentence_of_the_words_names_the_test_that_shows_it`` until WORDS has it with a test. The tests
are in this file and in ``tests/test_turning_browser_off_stops_the_browser.py``. ``thomas.server.rows.browser`` is the row,
``thomas.tools.browser`` and ``thomas.tools.browser_parity`` are the tools, and ``thomas.server.chat_tool_policy`` is where
the switch under Autonomy in Settings is read, so a change to any of them runs this file. ``thomas/server/rows/default.toml``
holds the words themselves.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient

from tests import browser_row_fixture as fake
from tests import plugin_view_fixture as views
from thomas.server.app_helpers import add_tools_rows_lent_the_server
from thomas.server.app_keys import APP_TOOLS
from thomas.server.chat_tool_policy import PolicyToolRegistryView
from thomas.server.chat_tool_policy_model import ToolRuntimePolicy
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS
from thomas.tools import browser
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
ELSEWHERE = "tests/test_turning_browser_off_stops_the_browser.py"
HERE = "tests/test_the_browser_row_says_what_stops.py"
ALLOWED = ToolRuntimePolicy(
    allow_shell=True,
    allow_file_write=True,
    allow_network=True,
    allow_browser=True,
    allow_channels=True,
    allow_git=True,
    require_command_approval=False,
    tool_timeout_s=120,
    max_parallel_tools=6,
    allowed_paths=(),
    blocked_commands=(),
)
# A sentence of the words, and the tests that show it. A test name is looked up in the file it is listed under.
WORDS: dict[str, tuple[tuple[str, str], ...]] = {
    "Gives Thomas a web browser it can drive while it works.": ((ELSEWHERE, "test_on_it_lends_all_eight_tools"),),
    "In Chat and Build, a run can open a page, click, type, take a screenshot, read the text of a page, and read what a "
    "page wrote to its console and which requests it made.": ((ELSEWHERE, "test_on_it_lends_all_eight_tools"),),
    "The first time a run opens a page, Thomas starts a Chromium browser of its own on this computer, out of sight "
    "unless the run asks to see it.": ((HERE, "test_chromium_starts_with_the_first_page_and_out_of_sight"),),
    "It is closed when this is turned off and when Thomas closes.": (
        (ELSEWHERE, "test_off_closes_what_a_session_started"),
        (ELSEWHERE, "test_closing_the_server_closes_the_browser"),
    ),
    "The switch under Autonomy in Settings that allows Thomas to open pages, click, type, and take screenshots in a "
    "browser is your permission, and this is whether Thomas has a browser at all, so Thomas browses only while both "
    "are on.": (
        (HERE, "test_the_permission_hides_and_refuses_the_tools_a_run_has"),
        (ELSEWHERE, "test_a_run_that_holds_a_tool_is_refused_at_once"),
    ),
    "While this is off, Thomas has no browser tools, so a chat message or Build run started now cannot open a page, "
    "click, type or take a screenshot of one.": ((ELSEWHERE, "test_a_run_that_holds_a_tool_is_refused_at_once"),),
    "Web search and fetching the text of an address are other tools and carry on.": (
        (HERE, "test_other_tools_carry_on_with_the_row_off"),
    ),
    "A run that was already going and asks for a browser tool is refused at once, and goes on with its other tools.": (
        (ELSEWHERE, "test_a_run_that_holds_a_tool_is_refused_at_once"),
        (HERE, "test_a_call_while_the_browser_is_closing_is_refused_and_starts_nothing"),
        (HERE, "test_other_tools_carry_on_with_the_row_off"),
    ),
    "Chat is told the tool is unknown, and a Build run is told the browser is turned off.": (
        (HERE, "test_chat_calls_by_name_and_is_told_the_tool_is_unknown"),
    ),
    "The browser Thomas started is closed with every page and sign-in in it, and what Thomas had recorded of the console "
    "and requests of its pages is forgotten, so turning this on again starts with a blank browser.": (
        (ELSEWHERE, "test_off_closes_what_a_session_started"),
        (ELSEWHERE, "test_on_again_starts_clean"),
    ),
    "The switch under Autonomy in Settings stays where you left it and still saves, and turning this on does not "
    "override it: if that is off, Thomas still does not browse.": (
        (HERE, "test_the_permission_stays_where_you_left_it_and_still_saves"),
        (HERE, "test_the_permission_hides_and_refuses_the_tools_a_run_has"),
    ),
    "No page asks again and again, because no page calls these tools.": ((HERE, "test_no_page_calls_a_browser_tool"),),
    "A page that a run is loading, clicking or reading when this is turned off is cut off, and that step ends in an "
    "error.": ((HERE, "test_a_page_being_loaded_is_cut_off_with_an_error"),),
    "If closing the browser is still going when you press Stop now, it is cut short and the browser may stay open until "
    "Thomas closes.": ((HERE, "test_stop_now_on_a_close_that_is_stuck_ends_the_wait"),),
}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Your choices and your settings are saved in the data folder, so a test that changes them needs its own."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    for name in ("THOMAS_DB_PATH", "THOMAS_SQLITE_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "data"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> fake.World:
    return fake.install(monkeypatch)


class _Plain(Tool):
    name = "plain.echo"
    description = "A tool that is not the browser's"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data="still here")


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    import tomllib

    row = next(
        row
        for row in tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text("utf-8"))["row"]
        if row["id"] == "browser"
    )
    written = [sentence for key in ("about", "off_means", "stop_now") for sentence in re.split(r"(?<=\.)\s+", row[key])]
    assert written == list(WORDS)
    texts = {name: (ROOT / name).read_text(encoding="utf-8") for name in (ELSEWHERE, HERE)}
    missing = [(name, test) for shows in WORDS.values() for name, test in shows if f"def {test}" not in texts[name]]
    assert missing == []


def test_chromium_starts_with_the_first_page_and_out_of_sight(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    async def scenario(client: TestClient, app: Any) -> None:
        assert world.starts == []
        await browser._ensure_session_page("default")
        assert len(world.starts) == 1 and world.headless == [True]

    fake.on_a_server(tmp_path, scenario)


def test_the_permission_hides_and_refuses_the_tools_a_run_has(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    """The row on does not override it, in chat or in a run built for Build, which both read it through this view."""

    async def scenario(client: TestClient, app: Any) -> None:
        run = ToolRegistry()
        add_tools_rows_lent_the_server(run, app[APP_TOOLS], tmp_path)
        for tools in (app[APP_TOOLS], run):
            open_to_all = PolicyToolRegistryView(tools, ALLOWED, base_root=tmp_path)
            assert {t.name for t in open_to_all.list_tools()} >= fake.NAMES
            forbidden = PolicyToolRegistryView(tools, replace(ALLOWED, allow_browser=False), base_root=tmp_path)
            assert not any(t.name.startswith("browser.") for t in forbidden.list_tools())
            refused = await forbidden.execute("browser.open", {"url": "https://example.com"})
            assert not refused.ok and "allow_browser policy denied" in str(refused.error)
        assert world.starts == []

    fake.on_a_server(tmp_path, scenario)


def test_other_tools_carry_on_with_the_row_off(tmp_path: Path, own_data_dir: Path, world: fake.World) -> None:
    async def scenario(client: TestClient, app: Any) -> None:
        held = ToolRegistry()
        held.register(_Plain())
        add_tools_rows_lent_the_server(held, app[APP_TOOLS], tmp_path)
        await fake.press(client, app, "off")
        assert not (await held.execute("browser.open", {})).ok
        assert (await held.execute("plain.echo", {})).data == "still here"
        names = {t.name for t in app[APP_TOOLS].list_tools()}
        assert {"web.search", "web.fetch"} <= names

    fake.on_a_server(tmp_path, scenario)


def test_the_permission_stays_where_you_left_it_and_still_saves(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    async def allowed(client: TestClient) -> Any:
        found = (await (await client.get("/api/preferences")).json())["advanced"]["tools"]
        return found["allow_browser"]

    async def scenario(client: TestClient, app: Any) -> None:
        assert await allowed(client) is True
        await fake.press(client, app, "off")
        assert await allowed(client) is True
        saved = await client.patch("/api/preferences", json={"advanced": {"tools": {"allow_browser": False}}})
        assert saved.status == 200 and await allowed(client) is False
        await fake.press(client, app, "on")
        assert await allowed(client) is False

    fake.on_a_server(tmp_path, scenario)


def test_no_page_calls_a_browser_tool() -> None:
    """The one file that names them lists what to say while a run uses one. Nothing in a page runs a tool by name."""
    call = re.compile(r"""['"`]browser\.(open|click|type|screenshot|extract|close|console|network)['"`]\s*[,)]""")
    named = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas" / "server" / "web").rglob("*")
        if path.suffix in {".js", ".html"} and call.search(path.read_text(encoding="utf-8", errors="replace"))
    }
    assert named <= {"thomas/server/web/js/runtime/002_virtual_office_data.js"}, named
    labels = (ROOT / "thomas/server/web/js/runtime/002_virtual_office_data.js").read_text(encoding="utf-8")
    assert re.search(r"'browser\.open':\s+'Opening a page", labels)
    assert not re.search(r"fetch\([^)]*browser\.", labels)


def test_a_page_being_loaded_is_cut_off_with_an_error(tmp_path: Path, own_data_dir: Path, world: fake.World) -> None:
    run_folder = tmp_path / "run"
    run_folder.mkdir()
    page = run_folder / "index.html"
    page.write_text("<title>x</title>", encoding="utf-8")
    world.hang_on_goto = True

    async def scenario(client: TestClient, app: Any) -> None:
        loading = asyncio.ensure_future(browser.BrowserOpenTool(run_folder).execute({"url": page.as_uri()}))
        while not world.pages:
            await asyncio.sleep(0.01)
        await fake.press(client, app, "off")
        # The bound only turns a hang into an answer.
        result = await asyncio.wait_for(loading, 10)
        assert not result.ok and result.error
        assert fake.state(app) == "off" and world.starts[0].stopped

    fake.on_a_server(tmp_path, scenario)


def test_stop_now_on_a_close_that_is_stuck_ends_the_wait(tmp_path: Path, own_data_dir: Path, world: fake.World) -> None:
    async def scenario(client: TestClient, app: Any) -> None:
        await browser._ensure_session_page("default")
        world.hang_on_close = True
        stopping = asyncio.ensure_future(client.post("/api/plugins/thomas/browser/off"))
        while not world.close_began:
            await asyncio.sleep(0.01)
        assert not stopping.done()  # the plain press waits for the close, which does not end
        pressed = await client.post("/api/plugins/thomas/browser/off?force=1")
        assert pressed.status == 200
        assert (await asyncio.wait_for(stopping, 10)).status == 200
        await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
        assert fake.state(app) == "off"
        # What was cut short is left: the page and context closed, the browser did not, and Playwright was not stopped.
        assert not world.browsers[0].closed and not world.starts[0].stopped
        world.hang_on_close = False

    fake.on_a_server(tmp_path, scenario)


def test_a_call_while_the_browser_is_closing_is_refused_and_starts_nothing(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    """The refusal comes as the stop begins, not once it has finished, or a call in between would be let through."""

    async def scenario(client: TestClient, app: Any) -> None:
        held = app[APP_TOOLS].get("browser.open")
        await browser._ensure_session_page("default")
        world.hang_on_close = True
        stopping = asyncio.ensure_future(client.post("/api/plugins/thomas/browser/off"))
        while not world.close_began:
            await asyncio.sleep(0.01)
        refused = await asyncio.wait_for(held.safe_execute({"url": "https://example.com"}), 5)
        assert refused.error == "browser.open is not available: browser is turned off"
        assert len(world.starts) == 1
        assert not app[APP_TOOLS].get("browser.open")  # and a run built now no longer gets it
        world.hang_on_close = False
        assert (await asyncio.wait_for(stopping, 10)).status == 200

    fake.on_a_server(tmp_path, scenario)


def test_chat_calls_by_name_and_is_told_the_tool_is_unknown_while_a_build_run_is_told_the_browser_is_off(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    """Chat reads the server's one tool set and calls a tool by name, so it never holds the tool that was lent."""

    async def scenario(client: TestClient, app: Any) -> None:
        run_copy = ToolRegistry()
        add_tools_rows_lent_the_server(run_copy, app[APP_TOOLS], tmp_path)
        await fake.press(client, app, "off")

        in_chat = await asyncio.wait_for(app[APP_TOOLS].execute("browser.open", {"url": "https://example.com"}), 5)
        assert not in_chat.ok and in_chat.error.startswith("Unknown tool: browser.open")
        in_build = await asyncio.wait_for(run_copy.execute("browser.open", {"url": "https://example.com"}), 5)
        assert in_build.error == "browser.open is not available: browser is turned off"
        assert world.starts == []

    fake.on_a_server(tmp_path, scenario)
