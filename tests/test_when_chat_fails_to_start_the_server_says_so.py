"""The Chat row fails softly: the server runs, answers 503 where Chat should be, shows it in health, and tries again.

``thomas.server.rows.chat`` is required, so it cannot be turned off, but it can fail to start. Then ``app_routes_init``
puts the 503 answer in the place of ``POST /api/chat`` and marks chat degraded, as it did before Chat was a row. Try again
runs the row a second time, and its routes come before the 503 answer. The other parts of the row, the session routes, the
side routes and the deliverable routes, are logged and left out when they cannot load, and Chat carries on without them.

The words the Plugins page shows for the row are held here sentence by sentence. The routes, the message and the refusal
to turn it off are in tests/test_the_chat_row_has_no_off_switch_and_serves_chat.py.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from thomas.server import app_core
from thomas.server.chat_app_keys import APP_SESSION_LLM_CACHE, APP_SESSION_STORE
from thomas.server.live_routes import WebService
from thomas.server.rows.chat import _ledger_update_for
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, PROFILE_PATH, RuntimePlugins, read_profile

HERE = "tests/test_when_chat_fails_to_start_the_server_says_so.py"
FIRST = "tests/test_the_chat_row_has_no_off_switch_and_serves_chat.py"
# Each sentence of what the Plugins page says, and the tests that show it.
WORDS = {
    "Lets you talk to Thomas in Chat: your message goes to the model and the reply comes back as it is written.": (
        f"{FIRST}::test_a_message_is_answered_while_the_reply_is_written_and_kept_as_a_session",
    ),
    "It keeps each conversation so it can be reopened, exported, cut back to resend an edited message, copied into a "
    "new one or started from a conversation brought in from elsewhere.": (
        f"{FIRST}::test_every_route_is_on_the_live_table_and_the_shell_registers_none",
    ),
    "It follows, steers and cancels the tasks Thomas handed to workers from Chat, shows the plan Thomas is following, "
    "lists the commands you can type after a slash, takes documents you attach, listens to your voice and reads replies "
    "aloud, and serves the pages and games those workers built so you can open and play them.": (
        f"{FIRST}::test_every_route_is_on_the_live_table_and_the_shell_registers_none",
    ),
    "It also lists the questions Thomas is waiting for you to answer, such as a choice or a password, takes your "
    "answer, and lists the checklist Thomas is working through.": (
        "tests/test_the_chat_row_serves_the_questions_and_checklist.py"
        "::test_the_chat_row_holds_the_three_routes_and_the_shell_none",
        "tests/test_the_chat_row_serves_the_questions_and_checklist.py"
        "::test_a_remote_caller_with_no_token_is_refused_on_every_route",
    ),
    "Chat is part of how Thomas works, so it cannot be turned off.": (
        f"{FIRST}::test_turning_it_off_is_refused_with_a_sentence_even_when_forced_and_a_saved_off_is_ignored",
    ),
    "The Plugins page shows it as on, with no switch, and anything that tries to turn it off is refused with a message "
    "saying so.": (
        f"{FIRST}::test_the_row_is_required_and_on",
        f"{FIRST}::test_turning_it_off_is_refused_with_a_sentence_even_when_forced_and_a_saved_off_is_ignored",
    ),
    "If Chat fails to start, Thomas goes on running without it, sending a message is answered with a message that Chat "
    "is unavailable, and Try again on this page starts it once the cause is fixed.": (
        f"{HERE}::test_a_chat_that_fails_to_start_is_answered_with_503_and_tries_again",
    ),
}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a server started here must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "chat")


def _words() -> dict[str, str]:
    return next(row for row in read_profile(PROFILE_PATH).entries if row.id == "chat").config["words"]


async def _post_empty(client: TestClient) -> web.StreamResponse:
    return await client.post("/api/chat", json={"text": ""})


def test_a_chat_that_fails_to_start_is_answered_with_503_and_tries_again(
    tmp_path: Path, own_data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> dict[str, Any]:
        with patch("thomas.server.routes.chat_v2.register_chat_v2_routes", side_effect=RuntimeError("chat-v2-boom")):
            app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        seen: dict[str, Any] = {"row_failed": _row(app)}
        async with TestClient(TestServer(app)) as client:
            down = await _post_empty(client)
            seen["down"] = (down.status, (await down.json()).get("code"))
            seen["health_down"] = await (await client.get("/api/health")).json()
            pressed = await client.post("/api/plugins/thomas/chat/on")
            seen["pressed"] = (pressed.status, (await pressed.json())["state"])
            up = await _post_empty(client)
            seen["up"] = up.status
            seen["health_up"] = await (await client.get("/api/health")).json()
        return seen

    with caplog.at_level(logging.ERROR):
        seen = asyncio.run(scenario())

    assert (seen["row_failed"]["state"], seen["row_failed"]["error"]) == ("failed", "RuntimeError: chat-v2-boom")
    assert seen["down"] == (503, "chat_v2_registration_failed")
    assert (seen["health_down"]["status"], "chat" in seen["health_down"]["degraded"]) == ("degraded", True)
    assert seen["health_down"]["features"]["chat"] is False
    assert seen["pressed"] == (200, "active")
    assert seen["up"] == 400  # the real handler, asking for a message, and no longer the 503 answer
    assert seen["health_up"]["features"]["chat"] is True
    assert "chat" not in seen["health_up"]["degraded"]
    assert "Chat V2 route registration FAILED (RuntimeError: chat-v2-boom)." in caplog.text


def test_a_start_that_fails_part_way_leaves_nothing_half_made_and_a_second_try_makes_it_once(
    tmp_path: Path, own_data_dir: Path
) -> None:
    async def scenario() -> tuple[bool, bool, int, bool]:
        late = patch(
            "thomas.server.routes.chat_v2_registration.get_chat_budget_ledger", side_effect=RuntimeError("late")
        )
        with late:
            app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        left_by_failure = APP_SESSION_STORE in app
        async with TestClient(TestServer(app)) as client:
            failed = _row(app)["state"] == "failed"
            await client.post("/api/plugins/thomas/chat/on")
            live = [r for r in app.router._live.routes() if r.resource.canonical == "/api/v2/chat/specialists"]
            return left_by_failure, failed, (len(live), (await _post_empty(client)).status), APP_SESSION_STORE in app

    left_by_failure, failed, second, made = asyncio.run(scenario())

    assert (left_by_failure, failed, made) == (False, True, True)
    # The second try added Chat's routes once, to a table that had none of them, and the 503 answer passes the turn on.
    assert second == (2, 400)  # a GET and the HEAD aiohttp lists beside it


@pytest.mark.parametrize(
    ("module", "attribute", "logged"),
    [
        ("sessions_aiohttp", "register_sessions_routes", "Session routes unavailable: part-boom"),
        ("chat_auxiliary", "register_chat_auxiliary_routes", "Chat auxiliary routes unavailable: part-boom"),
        ("deliverable_aiohttp", "register_deliverable_routes", "Deliverable routes unavailable: part-boom"),
    ],
)
def test_a_part_that_cannot_load_is_logged_and_left_out_and_chat_carries_on(
    module: str, attribute: str, logged: str, tmp_path: Path, own_data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> tuple[str, int]:
        with patch(f"thomas.server.routes.{module}.{attribute}", side_effect=RuntimeError("part-boom")):
            app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            return _row(app)["state"], (await _post_empty(client)).status

    with caplog.at_level(logging.WARNING):
        state, answered = asyncio.run(scenario())

    assert (state, answered) == ("active", 400)
    assert logged in caplog.text


def test_with_no_access_guard_it_says_so_and_the_row_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    service = WebService(
        web.Application(), plugin_view_fixture.config_in(tmp_path), require_api_access=None, read_json=None
    )
    profile = tmp_path / "profile.toml"
    profile.write_text(
        'name = "t"\n[[row]]\nid = "chat"\nentry = "thomas.server.rows.chat:plugin"\nrequired = true\ntitle = "Chat"\n',
        encoding="utf-8",
    )
    runtime = RuntimePlugins(service, profile_path=profile, choices_path=tmp_path / "plugins" / "choices.json")

    with caplog.at_level(logging.WARNING):
        runtime.load()

    row = next(row for row in runtime.report()["rows"] if row["id"] == "chat")
    assert (row["state"], row["error"]) == ("failed", "RuntimeError: missing API access guard")
    assert "Chat/session route registration skipped: missing runtime dependencies" in caplog.text
    assert "Deliverable routes unavailable: missing API access guard" in caplog.text


def test_a_stop_at_shutdown_closes_the_clients_chat_kept_and_takes_back_its_state(
    tmp_path: Path, own_data_dir: Path
) -> None:
    closed: list[str] = []

    class _Client:
        async def close(self) -> None:
            closed.append("closed")

    async def scenario() -> bool:
        app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            app[APP_SESSION_LLM_CACHE]["s1"] = SimpleNamespace(llm=_Client())
        return APP_SESSION_LLM_CACHE in app

    still_there = asyncio.run(scenario())

    assert closed == ["closed"]
    assert still_there is False


def test_the_session_routes_record_a_goal_in_the_ledger_the_way_they_always_did() -> None:
    from thomas.server.app_keys import APP_TASK_LEDGER

    calls: list[Any] = []

    class _Ledger:
        def update(self, session_id: str, **kwargs: Any) -> None:
            calls.append((session_id, kwargs))

    class _OlderLedger:
        def update_session_goal(self, session_id: str, goal: str, status: str) -> None:
            calls.append((session_id, goal, status))

    app = web.Application()
    app[APP_TASK_LEDGER] = _Ledger()
    record = _ledger_update_for(app)
    record("s1", active_goal="build it", status="in_progress", source="session_new")
    assert calls == [
        (
            "s1",
            {
                "active_goal": "build it",
                "status": "in_progress",
                "missing_inputs": None,
                "last_progress": None,
                "source": "session_new",
                "force_event": False,
            },
        )
    ]

    calls.clear()
    older = web.Application()
    older[APP_TASK_LEDGER] = _OlderLedger()
    _ledger_update_for(older)("s2", active_goal="plan", status=None)
    assert calls == [("s2", "plan", "in_progress")]

    none = web.Application()
    none[APP_TASK_LEDGER] = None
    _ledger_update_for(none)("s3", active_goal="x", status="done")  # nothing to record in, and nothing raised


def test_every_sentence_the_plugins_page_says_names_the_test_that_shows_it() -> None:
    words = _words()
    said = [
        sentence for key in ("about", "off_means") for sentence in re.split(r"(?<=\.) ", words[key].strip()) if sentence
    ]
    assert said, "no words, so this proves nothing"
    assert sorted(said) == sorted(WORDS), "a sentence was added, changed or left out without its test"
    for tests in WORDS.values():
        for name in tests:
            path, _, function = name.partition("::")
            assert f"def {function}(" in Path(path).read_text(encoding="utf-8"), name
