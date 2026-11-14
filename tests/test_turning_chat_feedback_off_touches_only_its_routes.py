"""The thumbs under a reply, off: two routes answer 404, a server started that way never loads them, the file stays.

``POST /api/chat/feedback`` appends one line to ``.thomas/feedback.jsonl`` and ``GET`` lists the lines. Neither changes
what Thomas answers, so off takes away only the saving and the listing. These tests hold the row's words to that.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS, module_of, named
from thomas.server import app_core
from thomas.server.proof.selection import select

ROW = "chat_feedback"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "POST /api/chat/feedback": "POST /api/chat/feedback",
    "GET /api/chat/feedback": "GET /api/chat/feedback",
}
OWN_CODE = ("thomas.server.rows.chat_feedback", "thomas.server.routes.chat_feedback_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/chat/feedback"}
WEB = ROOT / "thomas" / "server" / "web"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("chat-feedback-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("chat-feedback-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a server started here must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_the_row_names_its_route_module() -> None:
    """A press on imports what a row names in a thread, and the proof of every row watches only what it names."""
    entry = next(row for row in ROWS if row.id == ROW)
    assert sorted(named(entry)) == sorted(set(OWN_CODE) - {module_of(entry)})


def test_turning_it_on_brings_back_both_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /api/chat/feedback"] == 200
    assert seen["on"]["POST /api/chat/feedback"] == 400  # the handler, asking for a message and a rating


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_saved_thumb_lands_in_the_data_folder_and_is_listed_through_the_live_table(
    tmp_path: Path, own_data_dir: Path
) -> None:
    """The words say the saved thumbs stay in a file under the data folder. This asks for one on the real store."""

    async def scenario() -> tuple[int, int, list[str]]:
        app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            posted = await client.post(
                "/api/chat/feedback",
                json={"session_id": "chat_a", "message_id": "1-abc", "rating": "down", "note": "x"},
            )
            listed = await client.get("/api/chat/feedback")
            body = await listed.json()
            return posted.status, listed.status, [r["message_id"] for r in body["feedback"]]

    posted, listed, ids = asyncio.run(scenario())
    store = tmp_path / "memory" / ".thomas" / "feedback.jsonl"

    assert (posted, listed, ids) == (200, 200, ["1-abc"])
    assert [json.loads(line)["rating"] for line in store.read_text(encoding="utf-8").splitlines()] == ["down"]


def test_only_the_thumbs_call_these_routes_and_they_only_post() -> None:
    """The row's words describe the thumbs under a reply. If a page gets a second caller, they have to change."""
    pages = [*WEB.rglob("*.js"), *WEB.rglob("*.html")]
    texts = {path: path.read_text(encoding="utf-8", errors="replace") for path in pages}
    thumbs = texts[WEB / "js" / "message_feedback.js"]

    assert [path.name for path, text in texts.items() if "api/chat/feedback" in text] == ["message_feedback.js"]
    assert "method: 'POST'" in thumbs
    assert "return res.ok;" in thumbs
    assert "catch (_err) { /* stays clickable */ }" in thumbs
    assert "window.prompt('What was wrong? (optional)', '')" in thumbs


@pytest.mark.parametrize(
    "changed",
    ["thomas/server/rows/chat_feedback.py", "thomas/server/routes/chat_feedback_routes.py"],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_chat_feedback_off_touches_only_its_routes.py" in chosen
    assert "tests/test_chat_feedback.py" in chosen
