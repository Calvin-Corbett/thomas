"""The chat row also serves ``/api/chat/questions``, its answer route and ``/api/chat/todos``, and still cannot be turned off.

These three used to be registered by the shell in ``parity_routes.py``. They are part of Chat now, because a password or
protected file card is answered through the questions route, so the row that carries them is required and has no off
switch. A part that cannot load is logged and left out, as the other side routes of the row are.

Proofs of ``thomas.server.rows.chat``, ``thomas.server.routes.user_questions_routes`` and
``thomas.server.routes.todo_routes``. The routes themselves are in ``tests/test_ask_user.py``, ``tests/test_todo_list.py``
and ``tests/test_session_scope.py``, and that no required row has an off switch is in
``tests/test_a_required_row_has_no_off_switch.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller
from tests.row_proof_fixture import ROOT
from tests.row_words_fixture import sentences, unnamed_tests
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/chat/questions": "GET /api/chat/questions",
    "POST /api/chat/questions/{question_id}/answer": "POST /api/chat/questions/q1/answer",
    "GET /api/chat/todos": "GET /api/chat/todos",
}
HERE = Path(__file__)
NEW_SENTENCE = (
    "It also lists the questions Thomas is waiting for you to answer, such as a choice or a password, takes your "
    "answer, and lists the checklist Thomas is working through."
)


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that presses a switch must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("chat-questions-remote")
    started, found = ask_as_a_remote_caller("chat", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_the_chat_row_holds_the_three_routes_and_the_shell_none(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            live = {f"{r.method} {r.resource.canonical}" for r in app.router._live.routes() if r.resource}
            shell = {f"{r.method} {r.resource.canonical}" for r in app.router.server_routes() if r.resource}
            assert set(ROUTES) <= live
            assert set(ROUTES).isdisjoint(shell)
            chat = next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "chat")
            assert chat["state"] == "active"

    asyncio.run(scenario())


def test_the_shell_no_longer_has_a_file_for_them() -> None:
    assert not (ROOT / "thomas" / "server" / "parity_routes.py").exists()
    left = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if "parity_routes" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert left == []


def test_the_health_report_no_longer_lists_them_as_features(tmp_path: Path, own_data_dir: Path) -> None:
    """Reported: the two keys went with the shell block, and a failure to register them now shows only in the log."""

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            return await (await client.get("/api/health")).json()

    features = asyncio.run(scenario())["features"]
    assert "user_questions" not in features
    assert "todos" not in features
    assert features["chat"] is True


def test_the_chat_row_cannot_be_turned_off_so_the_routes_stay(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            refused = await client.post("/api/plugins/thomas/chat/off")
            assert 400 <= refused.status < 500
            assert (await client.get("/api/chat/questions")).status == 200
            assert (await client.get("/api/chat/todos")).status == 200

    asyncio.run(scenario())


def test_a_part_that_fails_to_load_is_logged_and_the_rest_of_chat_carries_on(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("no checklist today")

    monkeypatch.setattr("thomas.server.routes.todo_routes.setup_todo_routes", broken)

    async def scenario() -> None:
        with caplog.at_level(logging.WARNING):
            app = app_core.create_app(views.config_in(tmp_path))
            async with TestClient(TestServer(app)) as client:
                chat = next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "chat")
                assert chat["state"] == "active"
                assert (await client.get("/api/chat/questions")).status == 200
                assert (await client.get("/api/chat/todos")).status == 404

    asyncio.run(scenario())
    assert "Todo routes unavailable: no checklist today" in caplog.text


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]
    assert remote["with_token"]["GET /api/chat/questions"] == 200
    assert remote["with_token"]["GET /api/chat/todos"] == 200


def test_the_new_sentence_of_the_chat_words_names_the_tests_that_show_it() -> None:
    written = sentences("chat", "about")
    assert written[-1] == NEW_SENTENCE
    shown = {
        NEW_SENTENCE: (
            "test_the_chat_row_holds_the_three_routes_and_the_shell_none",
            "test_a_remote_caller_with_no_token_is_refused_on_every_route",
        )
    }
    assert unnamed_tests(shown, HERE) == []


@pytest.mark.parametrize(
    "changed", ["thomas/server/routes/user_questions_routes.py", "thomas/server/routes/todo_routes.py"]
)
def test_a_change_to_the_routes_runs_this_file(changed: str) -> None:
    assert "tests/test_the_chat_row_serves_the_questions_and_checklist.py" in select(ROOT, [changed]).files
