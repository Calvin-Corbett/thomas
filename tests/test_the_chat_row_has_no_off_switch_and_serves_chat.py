"""Chat is a required row: it serves its routes from the live table, answers a message, and cannot be turned off.

The row is ``thomas.server.rows.chat``. It brings up the Chat V2 turn routes, the session routes, the plan and slash
command routes and the deliverable routes, in the order the server always did, and the shell no longer registers any of
them. A real model is never used: the brain a turn runs is replaced by one that says a fixed sentence.

The Chat V2 route set is ``thomas.server.routes.chat_v2_registration``, the sessions are ``sessions_aiohttp``, the side
routes are ``chat_auxiliary`` and the pages workers built are ``deliverable_aiohttp``. What happens when the row fails to
start is in tests/test_when_chat_fails_to_start_the_server_says_so.py.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from tests.row_off_fixture import ask_as_a_remote_caller
from tests.row_proof_fixture import ROOT, ROWS, module_of, named
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "chat"
SESSION = "/api/v2/chat/session/s1"
# Written out, because a list worked out from the row would agree with whatever the row did. What is asked, then the
# route it reaches.
ROUTES = {
    "POST /api/chat": "POST /api/chat",
    "POST /api/v2/chat": "POST /api/v2/chat",
    "POST /api/v2/chat/documents/extract": "POST /api/v2/chat/documents/extract",
    "POST /api/v2/chat/transcribe": "POST /api/v2/chat/transcribe",
    "POST /api/v2/chat/speak": "POST /api/v2/chat/speak",
    "GET /api/v2/chat/voice/status": "GET /api/v2/chat/voice/status",
    "GET /api/v2/chat/specialists": "GET /api/v2/chat/specialists",
    f"GET {SESSION}": "GET /api/v2/chat/session/{session_id}",
    f"DELETE {SESSION}": "DELETE /api/v2/chat/session/{session_id}",
    f"GET {SESSION}/export": "GET /api/v2/chat/session/{session_id}/export",
    f"POST {SESSION}/truncate": "POST /api/v2/chat/session/{session_id}/truncate",
    f"GET {SESSION}/delegations": "GET /api/v2/chat/session/{session_id}/delegations",
    f"GET {SESSION}/delegations/e1/detail": ("GET /api/v2/chat/session/{session_id}/delegations/{execution_id}/detail"),
    f"POST {SESSION}/delegations/e1/steer": ("POST /api/v2/chat/session/{session_id}/delegations/{execution_id}/steer"),
    f"POST {SESSION}/delegations/e1/cancel": (
        "POST /api/v2/chat/session/{session_id}/delegations/{execution_id}/cancel"
    ),
    f"POST {SESSION}/delegations/e1/reported": (
        "POST /api/v2/chat/session/{session_id}/delegations/{execution_id}/reported"
    ),
    f"POST {SESSION}/delegations/e1/announce": (
        "POST /api/v2/chat/session/{session_id}/delegations/{execution_id}/announce"
    ),
    "POST /api/session/new": "POST /api/session/new",
    "POST /api/session/fork": "POST /api/session/fork",
    "POST /api/session/import": "POST /api/session/import",
    "GET /api/chat/plan/s1": "GET /api/chat/plan/{session_id}",
    "GET /api/chat/slash-commands": "GET /api/chat/slash-commands",
    "GET /deliverable/e1": "GET /deliverable/{execution_id}",
    "GET /deliverable/e1/index.html": "GET /deliverable/{execution_id}/{tail}",
}
OWN_CODE = (
    "thomas.server.rows.chat",
    "thomas.server.routes.chat_v2",
    "thomas.server.routes.sessions_aiohttp",
    "thomas.server.routes.chat_auxiliary",
    "thomas.server.routes.deliverable_aiohttp",
    "thomas.server.routes.user_questions_routes",
    "thomas.server.routes.todo_routes",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES.values(), *(f"HEAD {route[4:]}" for route in ROUTES.values() if route.startswith("GET "))}
SENTENCE = "Chat and your saved sessions is part of how Thomas works, so it cannot be turned off."
REPLY = "Hello from a fake model."


class _SaysHello:
    """A brain that says one sentence and keeps the turn, so no model is asked."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001, ANN003
        _ = session_id, kwargs
        await dispatcher.emit_text(REPLY)
        return conversation.append_message("user", prompt).append_message("assistant", REPLY)


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a server started here must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES), tmp_path_factory.mktemp("chat-remote"))
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def _serve(tmp_path: Path) -> tuple[Any, TestClient]:
    app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
    return app, TestClient(TestServer(app))


def _names(routes: Any) -> set[str]:
    return {f"{route.method} {route.resource.canonical}" for route in routes if route.resource is not None}


def _row(app: Any) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == ROW)


def test_every_route_is_on_the_live_table_and_the_shell_registers_none(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> tuple[set[str], set[str]]:
        app, client = _serve(tmp_path)
        async with client:
            return _names(app.router._live.routes()), _names(app.router.server_routes())

    live, shell = asyncio.run(scenario())

    assert live >= LISTED
    assert shell.isdisjoint(LISTED)


def test_the_row_is_required_and_on(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> dict[str, Any]:
        app, client = _serve(tmp_path)
        async with client:
            return _row(app)

    row = asyncio.run(scenario())

    assert (row["required"], row["enabled"], row["state"]) == (True, True, "active")
    assert row["title"].casefold() != ROW


def test_turning_it_off_is_refused_with_a_sentence_even_when_forced_and_a_saved_off_is_ignored(
    tmp_path: Path, own_data_dir: Path
) -> None:
    choices = own_data_dir / "plugins" / "choices.json"
    choices.parent.mkdir(parents=True)
    choices.write_text(json.dumps({ROW: {"enabled": False}}), encoding="utf-8")

    async def scenario() -> tuple[list[tuple[int, str]], str]:
        app, client = _serve(tmp_path)
        async with client:
            answers = []
            for query in ("", "?force=1"):
                answer = await client.post(f"/api/plugins/thomas/{ROW}/off{query}")
                answers.append((answer.status, await answer.text()))
            return answers, _row(app)["state"]

    answers, state = asyncio.run(scenario())

    assert answers == [(409, SENTENCE)] * 2
    assert state == "active"
    assert json.loads(choices.read_text(encoding="utf-8")) == {
        ROW: {"enabled": False}
    }  # the refused press saved nothing


def test_a_message_is_answered_while_the_reply_is_written_and_kept_as_a_session(
    tmp_path: Path, own_data_dir: Path
) -> None:
    async def scenario() -> tuple[int, str, int, list[Any]]:
        _, client = _serve(tmp_path)
        async with client:
            with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _SaysHello):
                sent = await client.post("/api/v2/chat", json={"session_id": "s1", "profile": "local", "message": "hi"})
                streamed = await sent.text()
            kept = await client.get(SESSION)
            body = await kept.json()
            return sent.status, streamed, kept.status, [m.get("content") for m in body["conversation"]["messages"]]

    status, streamed, kept, contents = asyncio.run(scenario())

    assert status == 200
    assert REPLY in streamed
    assert kept == 200
    assert contents[-1] == REPLY


def test_the_row_names_its_route_modules() -> None:
    """A press on imports what a row names in a thread, and the proof of every row watches only what it names."""
    entry = next(row for row in ROWS if row.id == ROW)
    assert sorted(named(entry)) == sorted(set(OWN_CODE) - {module_of(entry)})


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES, 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_change_to_the_row_runs_its_proofs() -> None:
    chosen = select(ROOT, ["thomas/server/rows/chat.py"]).files
    assert "tests/test_the_chat_row_has_no_off_switch_and_serves_chat.py" in chosen
    assert "tests/test_when_chat_fails_to_start_the_server_says_so.py" in chosen
