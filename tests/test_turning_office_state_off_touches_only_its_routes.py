"""The office state row, off: its two routes answer 404, a server started that way never loads them, and the map changes.

The routes read and save one thing, the agent the Virtual Office follows. That small a row still changes what you see.
The page paints its older tile map only once a read of these routes succeeds, so with them gone it stays on its newer
floor plan, and following an agent moves only the tile map. Each of these was seen on the real page, in a real browser,
pressing the row off and on. These tests hold the row's words to what that showed.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from tests import plugin_view_fixture
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from tests.workspace_specialist_test_support import Dispatcher, GuardedRunner, operator
from thomas.server import app_core
from thomas.server.office_state import OfficeStateStore
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import PROFILE_PATH

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/office/state": "GET /api/office/state",
    "PATCH /api/office/state": "PATCH /api/office/state",
}
OWN_CODE = ("thomas.server.rows.office_state", "thomas.server.routes.office_state_aiohttp")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/office/state"}
WEB = ROOT / "thomas" / "server" / "web"


def _script(name: str) -> str:
    return (WEB / "js" / "runtime" / name).read_text(encoding="utf-8")


def _words() -> dict[str, str]:
    """What the Plugins page shows for this row."""
    with PROFILE_PATH.open("rb") as handle:
        return next(row for row in tomllib.load(handle)["row"] if row["id"] == "office_state")


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("office-state-off")
    started, found = start_with_one_row_off("office_state", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("office-state-remote")
    started, found = ask_as_a_remote_caller("office_state", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "office_state"}
    assert seen["rows"]["office_state"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_both_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /api/office/state"] == 200
    # The ask sends an empty body, and the handler is the one that refuses it. A 404 here would be the route missing.
    assert seen["on"]["PATCH /api/office/state"] == 400


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_the_virtual_office_is_the_only_page_that_asks_for_this() -> None:
    """The row's words are all about one page in the sidebar. If a second page starts asking, they have to change."""
    asking = [
        path.name
        for path in WEB.rglob("*")
        if path.suffix in {".js", ".html"} and "/api/office/state" in path.read_text(encoding="utf-8")
    ]
    sidebar = (WEB / "js" / "browser_shell.js").read_text(encoding="utf-8").partition("const BUILTIN_WS")[2]

    assert asking == ["office_server_state.js"]
    assert '"Virtual Office": { mode: "office"' in sidebar.partition("};")[0]


def test_the_office_says_nothing_when_these_routes_are_gone() -> None:
    """The row's words say nothing tells you it is off, and a choice made in an open page is not saved while it is.

    If the page learns to say so, this fails and those words have to change.
    """
    bridge = _script("office_server_state.js")

    assert bridge.count("if (!response.ok) return null;") == 2  # the read, and the save
    assert "if (!officeServerStateHydrated || officeServerStateApplying) return null;" in bridge


def test_the_tile_map_is_painted_only_after_a_read_of_these_routes_succeeds() -> None:
    """Why the floor plan shows while this is off, which the row's words tell you.

    It looks like a fault in the page: a read that succeeds paints the tile map over the floor plan just drawn, and a
    click in the Office's toolbar draws the floor plan again. If that is ever fixed, this fails and the words change.
    """
    reading = _script("office_server_state.js").partition("async function officeHydrateServerState")[2]
    reading = reading.partition("async function officePersistServerFollowAgent")[0]
    painting = _script("018_virtual_office_02.js").partition("function officeRenderScene()")[2].partition("\n}")[0]

    assert reading.index("if (!response.ok) return null;") < reading.index("officeRenderScene();")
    assert "officeDrawTilemap(" in painting


def test_following_an_agent_moves_only_the_tile_map() -> None:
    """The row's words say no agent is followed on the floor plan. If the floor plan learns to, they have to change."""
    ticking = _script("020_virtual_office_04.js").partition("const draftMapActive =")[2]
    on_the_floor_plan, _, on_the_tile_map = ticking.partition("} else {")

    assert "officeTickFollowCamera();" not in on_the_floor_plan
    assert "officeTickFollowCamera();" in on_the_tile_map.partition("officeRenderAgents(now)")[0]


def test_the_office_chat_saves_an_agent_without_these_routes(tmp_path: Path, seen: dict[str, Any]) -> None:
    """The row's words say the chat goes on saving while this is off, so it has to need nothing from these routes.

    Its receipt is what lets it tell you it worked. It reads back the file, which is not what the page on your screen reads.
    """
    config = SimpleNamespace(
        memory=SimpleNamespace(root_path=tmp_path), tools=SimpleNamespace(sandbox_path=str(tmp_path))
    )
    resident = operator("office", Dispatcher(), guarded_runner=GuardedRunner(), config=config)

    receipt = asyncio.run(resident.execute({"action": "office.view.set_follow_agent", "target_id": "agent-4"}))

    assert receipt["ok"] is True
    assert OfficeStateStore(tmp_path).get(user_id="owner-test")["follow_agent_id"] == "agent-4"
    assert "thomas.server.workspace_specialist_actions" in seen["loaded"]


def test_the_words_promise_neither_agent_once_this_is_back_on() -> None:
    """Off is what lets your browser and the file disagree, and then how the page loads decides which one wins.

    The Office keeps the agent it follows in your browser too, and starting up it follows that agent. Its save is held back
    only until the first read of these routes returns. So a choice made while this was off can overwrite the saved agent
    when you turn it back on, or not, and the row's words can promise neither. If the page stops this, these lines go, this
    fails and the words have to change. The next test shows both outcomes in a real browser.
    """
    assert "officeSetFollowMode(true, storedCamera.followAgentId);" in _script("office_workspace_state.js")
    assert "if (!officeServerStateHydrated || officeServerStateApplying) return null;" in _script(
        "office_server_state.js"
    )

    off_means = _words()["off_means"]
    assert "goes back to it" not in off_means
    assert "is not saved while this is off, but your browser remembers it" in off_means
    assert "can replace the saved agent the next time the Office opens, or it may not" in off_means


@pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="playwright not installed")
@pytest.mark.parametrize(("read_first", "saves"), [(True, ['{"follow_agent_id":"agent-1"}']), (False, [])])
def test_how_the_page_loads_decides_whether_a_remembered_agent_is_saved(read_first: bool, saves: list[str]) -> None:
    """The page's real save and its real follow, started in each order. Nothing but the order differs.

    agent-3 is saved and your browser remembers agent-1, as it does after a choice made while this was off.
    """
    from playwright.sync_api import sync_playwright

    following = _script("017_virtual_office_01.js").partition("function officeSetFollowMode")[2]
    following = following.partition("function officeTickFollowCamera")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(
            "http://thomas.test/",
            lambda route: route.fulfill(status=200, content_type="text/html", body="<main>Office</main>"),
        )
        page.goto("http://thomas.test/")
        page.evaluate(
            """() => {
              window.__saves = [];
              const held = new Promise(resolve => { window.__answerTheRead = resolve; });
              window.officeState = null;
              window.safeString = value => String(value || '').trim();
              window.officeGetAgentById = () => null;
              window.officeUpdateFollowUi = () => {};
              window.officePersistCameraState = () => {};
              window.officeRenderScene = () => {};
              window.fetch = async (_url, options) => {
                if (options && options.method === 'PATCH') {
                  window.__saves.push(options.body);
                  return { ok: true, json: async () => ({ state: {} }) };
                }
                await held;
                return { ok: true, json: async () => ({ state: { follow_agent_id: 'agent-3' } }) };
              };
            }"""
        )
        page.add_script_tag(content="function officeSetFollowMode" + following)
        page.add_script_tag(path=str(WEB / "js" / "runtime" / "office_server_state.js"))
        start_up = "() => { window.officeState = { followAgentId: '' }; officeSetFollowMode(true, 'agent-1'); }"
        if read_first:
            page.evaluate("() => window.__answerTheRead()")
            page.wait_for_function("officeServerStateHydrated === true")
            page.evaluate(start_up)
            page.wait_for_function("window.__saves.length > 0")
        else:
            page.evaluate(start_up)
            page.evaluate("() => window.__answerTheRead()")
            page.wait_for_function("officeState.followAgentId === 'agent-3'")
        assert page.evaluate("() => window.__saves") == saves
        browser.close()


def test_the_chat_that_can_follow_an_agent_opens_only_in_the_classic_layout() -> None:
    """The row's words place this chat in the Classic layout, because the tab layout has no way to it.

    Only the resident of the Office can follow an agent, and only a message carrying the Office's context reaches it. Only
    the drawer sends that, and the button for it asks whether the page opened a workspace itself. The tab layout gives each
    workspace its own tab and stops both clicks that would open one the old way, so there the button still reads Chat and
    opens nothing, and Ask Thomas and the toolbar's Chat send no context. If the tab layout gets a way to this chat, this
    fails and the words have to change.

    The words say "if you use" and give no way there on purpose. Nothing on that layout brings the tabs back afterwards.
    """
    scripts = {path.name: path.read_text(encoding="utf-8") for path in (WEB / "js").rglob("*.js")}
    button = scripts["chat_shell_bindings.js"].partition("getElementById('tc-canvas-btn')")[2].partition("});")[0]

    assert "context_id: scoped.context" in scripts["workspace_chat_drawer.js"]
    assert [name for name, text in scripts.items() if "workspace:office" in text] == ["workspace_chat_transport.js"]
    assert "deps.state.workspaceOpen && window.ThomasWorkspaceChat" in button
    assert [name for name, text in scripts.items() if "workspaceOpen = true" in text] == [
        "chat_workspace_navigation.js"
    ]
    assert "e.stopPropagation();                 // capture phase" in scripts["browser_shell.js"]
    assert 'stop(e, doc); openWorkspaceTab("settings");' in scripts["browser_shell_docs.js"]

    words = _words()
    assert "Office chat" not in words["about"] + words["off_means"]
    assert "In the Classic layout" in words["about"]
    assert "If you use the Classic layout, the Chat button at the top right of the Office" in words["off_means"]


def test_the_routes_serve_the_file_the_office_chat_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The row has to hand the routes the server's memory folder, which is where the chat keeps its choice.

    With any other folder the page and the chat each keep an agent of their own, and every other test here still passes,
    because none of them sends a real body. A real store, and a real body, so the read and the save are both of the file.
    """
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    config = plugin_view_fixture.config_in(tmp_path)
    store = OfficeStateStore(config.memory.root_path)

    async def scenario() -> tuple[int, Any, int]:
        async with TestClient(TestServer(app_core.create_app(config))) as client:
            store.set_follow_agent("agent-4")
            read = await client.get("/api/office/state")
            body = await read.json()
            saved = await client.patch("/api/office/state", json={"follow_agent_id": "agent-7"})
            return read.status, body, saved.status

    read_status, body, saved_status = asyncio.run(scenario())

    assert read_status == 200
    assert body["state"]["follow_agent_id"] == "agent-4"
    assert saved_status == 200
    assert store.get()["follow_agent_id"] == "agent-7"


@pytest.mark.parametrize(
    "changed", ["thomas/server/rows/office_state.py", "thomas/server/routes/office_state_aiohttp.py"]
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these two only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_office_state_off_touches_only_its_routes.py" in chosen
    assert "tests/test_office_state_bridge.py" in chosen
