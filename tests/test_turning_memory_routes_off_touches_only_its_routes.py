"""The memory routes, off: their nine routes answer 404, a server started that way never loads them, and Thomas remembers.

The word memory names several things in Thomas, and this row is one way into one of them. The routes look into the memory
engine the server builds as it starts, under ``thomas/memory``. Chat reads and writes that engine directly, never through
a route, so off cannot make Thomas forget. A job's memory in Work is a different store again, reached through
``/api/work``, and no route here reads it. These tests hold the row's words to that.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.plugin_view_fixture import config_in
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS, choose
from thomas.core.config import ServerConfig
from thomas.core.llm_shared import StreamEvent
from thomas.server import app_core
from thomas.server.app_keys import APP_MEMORY
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, WORDS

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/memory": "GET /api/memory",
    "POST /api/memory/pins": "POST /api/memory/pins",
    "DELETE /api/memory/pins/{key}": "DELETE /api/memory/pins/k1",
    "GET /api/memory/contradictions": "GET /api/memory/contradictions",
    "POST /api/memory/contradictions/{cid}/resolve": "POST /api/memory/contradictions/1/resolve",
    "GET /api/memory/contradictions/review": "GET /api/memory/contradictions/review",
    "POST /api/memory/contradictions/{cid}/review": "POST /api/memory/contradictions/1/review",
    "GET /api/memory/curator/approvals": "GET /api/memory/curator/approvals",
    "POST /api/memory/curator/approvals/{aid}/decision": "POST /api/memory/curator/approvals/1/decision",
}
OWN_CODE = ("thomas.server.rows.memory_routes", "thomas.server.routes.memory_aiohttp")
# aiohttp lists a HEAD beside each GET.
LISTED = {
    *ROUTES,
    "HEAD /api/memory",
    "HEAD /api/memory/contradictions",
    "HEAD /api/memory/contradictions/review",
    "HEAD /api/memory/curator/approvals",
}
READS = (
    "/api/memory",
    "/api/memory/contradictions?only_open=0&limit=500",
    "/api/memory/contradictions/review?limit=500",
    "/api/memory/curator/approvals?status=&limit=1000",
)
TOKEN = "a-token-for-this-test"
WITH_TOKEN = {"Authorization": f"Bearer {TOKEN}"}


class _Model:
    """The only stand-in below. The route, the chat turn, the remember tool and the memory engine are the real ones.

    Told to save something, its first answer does what a model does and calls the tool it was offered. What it was sent
    is kept, so a test can see what reached it.
    """

    def __init__(self, *, saves: str = "", says: str = "Noted.") -> None:
        self.saves = saves
        self.says = says
        self.sent: list[str] = []

    async def stream_chat(self, *, messages: Any, tools: Any = None) -> AsyncIterator[StreamEvent]:
        self.sent.append(json.dumps(messages, default=str))
        if self.saves and len(self.sent) == 1:
            arguments = json.dumps({"text": self.saves})
            yield StreamEvent(type="tool_call_end", data={"id": "saved-1", "name": "remember", "arguments": arguments})
        else:
            yield StreamEvent(type="token", data={"text": self.says})
        yield StreamEvent(type="done")


async def _chat(client: TestClient, model: _Model, session_id: str, message: str, **options: Any) -> int:
    """One real turn through the chat route. Reading the answer to its end is what lets the turn finish."""

    async def answered_by_the_model(app: Any, **kwargs: Any) -> tuple[_Model, None, str]:
        return model, None, "local"

    body = {"session_id": session_id, "profile": "local", "message": message}
    with patch("thomas.server.routes.chat_v2.initialize_chat_v2_llm", answered_by_the_model):
        said = await client.post("/api/v2/chat", json=body, **options)
        await said.text()
    return said.status


def _the_row(app: Any) -> dict[str, Any]:
    """This row as the Plugins page is told it, words and all."""
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "memory_routes")


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("memory-routes-off")
    started, found = start_with_one_row_off("memory_routes", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("memory-routes-remote")
    started, found = ask_as_a_remote_caller("memory_routes", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "memory_routes"}
    assert seen["rows"]["memory_routes"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_memory_engine_is_still_loaded(seen: dict[str, Any]) -> None:
    assert "thomas.memory.autonomy" in seen["loaded"]


def test_turning_it_on_brings_back_all_nine_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {
        "GET /api/memory": 200,
        "POST /api/memory/pins": 400,  # asked with an empty body, so it has no key
        "DELETE /api/memory/pins/k1": 200,
        "GET /api/memory/contradictions": 200,
        "POST /api/memory/contradictions/1/resolve": 500,  # the handler's own answer for an id that does not exist
        "GET /api/memory/contradictions/review": 200,
        "POST /api/memory/contradictions/1/review": 400,  # no decision in an empty body
        "GET /api/memory/curator/approvals": 200,
        "POST /api/memory/curator/approvals/1/decision": 400,  # no approve flag in an empty body
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does.

    The route file holds nothing at the top level but two type aliases, so nothing of its own survives off and on.
    """
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_off_leaves_what_thomas_remembers_and_on_shows_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words tell you Thomas goes on remembering and goes on using what it remembers in chat.

    Chat reaches the engine through ``app[APP_MEMORY]``, which the server builds before any row loads. If that engine is
    ever built by this row, or off ever clears it, this fails and those words have to change.
    """
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            engine = app[APP_MEMORY]
            pinned = await client.post("/api/memory/pins", json={"key": "pet.name", "text": "Bramble the collie"})
            before = await (await client.get("/api/memory")).json()
            pressed_off = await client.post("/api/plugins/thomas/memory_routes/off")
            asked_off = await client.get("/api/memory")
            engine_stayed = app[APP_MEMORY] is engine
            remembered = engine.retrieve("Bramble the collie").text
            engine.pin("pet.toy", "a chewed tennis ball")
            pressed_on = await client.post("/api/plugins/thomas/memory_routes/on")
            after = await (await client.get("/api/memory")).json()
            return {
                "statuses": (pinned.status, pressed_off.status, asked_off.status, pressed_on.status),
                "pins_before": sorted(pin["key"] for pin in before["pins"]),
                "engine_stayed": engine_stayed,
                "remembered": remembered,
                "pins_after": sorted(pin["key"] for pin in after["pins"]),
            }

    found = asyncio.run(scenario())

    assert found["statuses"] == (200, 200, 404, 200)
    assert found["engine_stayed"] is True
    assert "Bramble the collie" in found["remembered"]
    assert found["pins_before"] == ["pet.name"]
    assert found["pins_after"] == ["pet.name", "pet.toy"]


def test_off_takes_these_controls_and_a_program_keeps_chat_and_deleting_a_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words say what a program holding the token keeps, so this asks as one, in remote mode with the row off.

    Chat and deleting a chat are the server's own routes, so both go on reaching memory. Deleting a chat forgets what was
    said in it. A fact Thomas saved with its remember tool belongs to no chat, so that a later chat can find it, and it
    stays. The words have to carry that exception or they promise a deletion that never happens.
    """
    data = tmp_path / "data"
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    choose(data, on=[row.id for row in ROWS if row.id != "memory_routes"])
    config = replace(config_in(tmp_path), server=ServerConfig(access_mode="remote", api_token=TOKEN))
    model = _Model(saves="The gate code for the south yard is 5582.")

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            engine = app[APP_MEMORY]
            engine.pin("gate.west", "The west gate is painted bright orange.")
            asked = await client.get("/api/memory", headers=WITH_TOKEN)
            made = await client.post("/api/session/new", headers=WITH_TOKEN)
            sid = (await made.json())["session_id"]
            message = "What colour is the west gate? The north yard code is 4471."
            chatted = await _chat(client, model, sid, message, headers=WITH_TOKEN)
            said_before = engine.retrieve("north yard code", thread=sid).text
            saved_before = engine.retrieve("south yard gate code").text
            deleted = await client.delete(f"/api/v2/chat/session/{sid}", headers=WITH_TOKEN)
            return {
                "row": _the_row(app),
                "statuses": (asked.status, made.status, chatted, deleted.status),
                "said_before": said_before,
                "saved_before": saved_before,
                "purge": (await deleted.json())["memory_purge"],
                "said_after": engine.retrieve("north yard code", thread=sid).text,
                "said_after_anywhere": engine.retrieve("north yard code").text,
                "saved_after": engine.retrieve("south yard gate code").text,
            }

    found = asyncio.run(scenario())

    assert found["row"]["state"] == "off"
    assert found["statuses"] == (404, 200, 200, 200)
    assert any("bright orange" in sent for sent in model.sent), "chat did not use what Thomas remembers"
    assert "4471" in found["said_before"]
    assert "5582" in found["saved_before"]
    assert found["purge"]["forgotten"] is True
    assert "4471" not in found["said_after"]
    assert "4471" not in found["said_after_anywhere"]
    assert "5582" in found["saved_after"]
    off_means = found["row"]["off_means"]
    assert "Other programs lose these controls." in off_means
    assert "They can still chat with Thomas, which uses what it remembers" in off_means
    assert "deleting a chat still forgets what came from it, apart from any fact Thomas saved to keep." in off_means


def test_the_read_routes_show_pins_counts_and_a_named_chats_searches_and_never_a_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``about`` may claim only what these routes show, read here after a real chat turn.

    The engine can retrieve what the chat left, and no route lists it. What comes back is the pins, the counts and, for a
    chat named in the request, what was searched for. A turn searches with your whole message, so your words show there.
    The reply was never searched for, so what it said shows nowhere.

    A landing runs this for a change to the row or its routes. An edit to the words alone is found by the full suite,
    because naming the list here would run this file for every row that lands.
    """
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    model = _Model(says="Noted. The south yard code is 5582.")
    message = "The north yard code is 4471, and what was the other one?"

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            engine = app[APP_MEMORY]
            sid = (await (await client.post("/api/session/new")).json())["session_id"]
            await client.post("/api/memory/pins", json={"key": "pet.name", "text": "Bramble the collie"})
            await client.post("/api/memory/pins", json={"key": "pet.toy", "text": "a chewed tennis ball"})
            forgot = await client.delete("/api/memory/pins/pet.toy")
            status = await _chat(client, model, sid, message)
            recalled = engine.retrieve("south yard code", thread=sid).text
            named = f"/api/memory?session_id={sid}&trace_limit=50"
            answers = {read: await (await client.get(read)).text() for read in (*READS, named)}
            return {
                "row": _the_row(app),
                "statuses": (forgot.status, status),
                "recalled": recalled,
                "still_held": engine.retrieve("chewed tennis ball").text,
                "named": named,
                "answers": answers,
            }

    found = asyncio.run(scenario())
    answers, named = found["answers"], found["named"]
    nothing_named = json.loads(answers["/api/memory"])
    a_chat_named = json.loads(answers[named])

    assert found["statuses"] == (200, 200)
    assert "5582" in found["recalled"]
    assert "tennis ball" not in found["still_held"]
    assert [read for read, text in answers.items() if "5582" in text] == []
    assert [read for read, text in answers.items() if "4471" in text] == [named]
    assert [read for read, text in answers.items() if "Bramble" in text] == ["/api/memory", named]
    assert [read for read, text in answers.items() if "tennis ball" in text] == []
    assert nothing_named["traces"] == []
    assert message in [trace["query"] for trace in a_chat_named["traces"]]
    assert nothing_named["stats"]["v2_episodes"] >= 2
    row = found["row"]
    assert re.search(r"(see|change) what Thomas remembers", " ".join(row[word] for word in WORDS)) is None
    assert "see what Thomas has pinned, how much it holds and, for a chat they name, what it searched" in row["about"]
    assert "which can be your own words from that chat" in row["about"]


def test_no_page_in_the_sidebar_or_settings_reads_these_routes() -> None:
    """The row's words tell you nothing you normally use changes. One script fetches two of these routes, for one panel.

    That panel opens from a button on the older full page, and everything that opens the older page asks for it embedded,
    which hides both the button and the panel. If the script gets a new caller, anything opens the older page plain, or
    the panel stops reading a failed fetch as memory being disabled, this fails and those words have to change. A landing
    runs this only for a change to that script, the older page, this row or its routes. A caller added anywhere else is
    found by the full suite.
    """
    web = ROOT / "thomas" / "server" / "web"
    scripts = {path: path.read_text(encoding="utf-8") for path in web.rglob("*.js")}
    pages = {path: path.read_text(encoding="utf-8") for path in web.rglob("*.html")}
    code = [
        line
        for text in (*scripts.values(), *pages.values())
        for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    ]
    dock = scripts[web / "js" / "runtime" / "015_debug_dock.js"]
    older_page = pages[web / "index.html"]
    opening_the_panel = [
        line.strip() for line in code if "setDebugDockOpen(" in line and "false" not in line and "function" not in line
    ]

    assert [path.name for path, text in pages.items() if "/api/memory" in text] == []
    assert [path.name for path, text in scripts.items() if "/api/memory" in text] == ["015_debug_dock.js"]
    assert re.findall(r"/api/memory[^?'`]*", dock) == ["/api/memory", "/api/memory", "/api/memory/contradictions"]
    assert "memory: memoryRes.ok ? memoryRes.data : null" in dock
    assert "const enabled = Boolean(memoryData?.enabled);" in dock
    assert {found for line in code for found in re.findall(r"""["'`]/classic[^"'`]*""", line)} == {
        '"/classic?embed=1',
        "'/classic?embed=1",
    }
    assert opening_the_panel == ["setDebugDockOpen(!open);"]  # only the button, which sits in the top bar
    assert older_page.index('class="top-nav"') < older_page.index('id="debugDockToggleBtn"')
    assert "html.tcw-embed body .top-nav" in older_page
    assert "html.tcw-embed body .debug-dock" in older_page


@pytest.mark.parametrize("changed", ["thomas/server/rows/memory_routes.py", "thomas/server/routes/memory_aiohttp.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these two only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_memory_routes_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_memory_contradictions_api.py" in chosen
