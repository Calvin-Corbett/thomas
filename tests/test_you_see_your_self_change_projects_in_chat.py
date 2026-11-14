"""Every Chat V2 turn tells the model which of Thomas's own self-change projects are going.

You asked Chat "What are you working on on yourself right now? List each of your own projects that is running" and
it answered "No self-development projects are currently running", without a tool call, while three ran
(2026-09-29). Now every Chat V2 turn carries one line counting those projects by state, where the model already
learns of this chat's running tasks, read at most every 30 s, never holding a turn more than 2 s, and saying so when
the list cannot be read. No word list decides which turns get it.

The tests drive the real ``/api/v2/chat`` handler in this process (``make_mocked_request``, no socket). The brain is a
stand-in that records what it is told about work going on, except in one test where only the model is, under the
real brain. The project list is a stand-in too, counted.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.routes import chat_v2_turn_inputs as turn_inputs
from thomas.server.routes import self_project_routes as routes

RUNNING = {"conversation_id": "thomas-aaa", "title": "Fix the voice button", "state": "running", "detail": "going"}
STOPPED = {"conversation_id": "thomas-bbb", "title": "Tidy the logs", "state": "stopped", "detail": "it ended"}


@pytest.fixture(autouse=True)
def isolated_persistence(tmp_path, monkeypatch):
    from thomas.core import persistence

    state, reports = tmp_path / "thomas_state.json", tmp_path / "reports"
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", state)
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", reports)
    monkeypatch.setattr(persistence, "_engine", persistence.PersistenceEngine(state, report_dir=reports))


# --- one line on every Chat V2 turn ------------------------------------------------------------------------


class _Body:
    """The request body, for ``make_mocked_request``: one chunk, then the end."""

    def __init__(self, data: bytes) -> None:
        self._chunks = [data]

    def set_read_chunk_size(self, size: int) -> None:
        self._read_chunk_size = size

    async def readany(self) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _Brain:
    """The brain is a stand-in: it records what it was told about work going on (``active_task_digest``)."""

    digests: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = session_id
        _Brain.digests.append(str(kwargs.get("active_task_digest") or ""))
        await dispatcher.emit_text("Sure.")
        return conversation.append_message("user", prompt).append_message("assistant", "Sure.")


class _Model:
    """Only the model is a stand-in, under the real brain: it records every message it is given."""

    seen: list[str] = []

    def stream_chat(self, *, messages, tools=None):  # noqa: ANN001
        from thomas.core.llm_shared import StreamEvent

        _ = tools
        _Model.seen.append("\n".join(str(message.get("content") or "") for message in messages))

        async def reply():
            yield StreamEvent(type="token", data={"text": "Sure."})
            yield StreamEvent(type="done", data={})

        return reply()


class _Listing:
    """A counted stand-in for ``self_project_routes.read_projects``."""

    def __init__(self, answer: Any = None, *, delay_s: float = 0.0) -> None:
        self.calls = 0
        self.lock = threading.Lock()
        self.answer = answer if answer is not None else {"ok": True, "projects": [RUNNING, STOPPED], "unreadable": []}
        self.delay_s = delay_s

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        with self.lock:
            self.calls += 1
        time.sleep(self.delay_s)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _send(tmp_path: Path, messages: list[str], *, temporary: bool = False) -> None:
    """Send each message to the real /api/v2/chat handler of one app, in this process."""
    from thomas.server.app import create_app
    from thomas.server.routes import chat_v2

    model = ModelConfig(name="local", provider="openai_compat", base_url="http://127.0.0.1:11434/v1", model="dummy")
    config = AppConfig(
        models={"local": model},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
        server=ServerConfig(access_mode="local"),
    )
    transport = mock.Mock()
    transport.is_closing.return_value = False  # the client stays connected
    transport.get_extra_info.return_value = ("127.0.0.1", 50000)

    async def scenario() -> None:
        app = create_app(config)
        for message in messages:
            body = {"session_id": "sess-self-projects", "profile": "local", "message": message, "temporary": temporary}
            request = make_mocked_request(
                "POST",
                "/api/v2/chat",
                headers={"Content-Type": "application/json"},
                app=app,
                transport=transport,
                payload=_Body(json.dumps(body).encode()),
            )
            response = await chat_v2.handle_chat_v2(request)
            assert response.status == 200

    asyncio.run(scenario())


def _told(tmp_path: Path, messages: list[str]) -> list[str]:
    """What the brain was told about work going on, one entry per turn."""
    _Brain.digests = []
    with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _Brain):
        _send(tmp_path, messages)
    assert len(_Brain.digests) == len(messages)
    return list(_Brain.digests)


@pytest.fixture
def chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    return tmp_path


def test_a_turn_about_something_else_still_carries_the_line(chat: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listing = _Listing()
    monkeypatch.setattr(routes, "read_projects", listing, raising=False)

    [told] = _told(chat, ["Can you build me a landing page?"])

    assert "Your self-change projects right now: 1 running, 1 stopped." in told
    assert "self.projects" in told
    assert listing.calls == 1


def test_the_model_itself_is_given_the_line(chat: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "read_projects", _Listing(), raising=False)

    async def model(app, **kwargs):  # noqa: ANN001, ANN003
        _ = app, kwargs
        return _Model(), None, "local"

    _Model.seen = []
    with patch("thomas.server.routes.chat_v2.initialize_chat_v2_llm", model):
        _send(chat, ["Can you build me a landing page?"], temporary=True)

    assert _Model.seen and "Your self-change projects right now: 1 running, 1 stopped." in _Model.seen[0]


def test_a_second_turn_inside_the_window_reads_nothing_again(chat: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listing = _Listing()
    monkeypatch.setattr(routes, "read_projects", listing, raising=False)

    first, second = _told(chat, ["Hello there", "What is the weather like?"])

    assert "1 running, 1 stopped" in first and "1 running, 1 stopped" in second
    assert listing.calls == 1


def test_the_line_says_the_list_is_unavailable_when_the_read_fails(chat: Path, monkeypatch) -> None:
    monkeypatch.setattr(routes, "read_projects", _Listing(PermissionError(13, "Access is denied")), raising=False)

    [told] = _told(chat, ["What are you working on on yourself right now?"])

    assert "Your own project list is unavailable right now; do not say none are running." in told


def test_the_line_says_some_could_not_be_read(chat: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    partial = {"ok": True, "projects": [RUNNING], "unreadable": ["green/work/thomas-bbb could not be read"]}
    monkeypatch.setattr(routes, "read_projects", _Listing(partial), raising=False)

    [told] = _told(chat, ["Hi"])

    assert "1 running" in told and "do not say none are running" in told


def test_a_slow_read_never_holds_a_turn_and_only_one_read_is_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = _Listing(delay_s=0.6)
    monkeypatch.setattr(routes, "read_projects", listing, raising=False)
    monkeypatch.setattr(turn_inputs, "SELF_PROJECTS_WAIT_S", 0.05)

    async def scenario() -> tuple[list[str], float, str]:
        app = web.Application()
        started = time.monotonic()
        first = await asyncio.gather(*(turn_inputs.self_projects_status(app) for _ in range(3)))
        waited = time.monotonic() - started
        await asyncio.sleep(1.0)  # the read carries on after the turns stopped waiting, and keeps its line
        return first, waited, await turn_inputs.self_projects_status(app)

    first, waited, later = asyncio.run(scenario())

    assert first == [turn_inputs.SELF_PROJECTS_UNAVAILABLE] * 3
    assert waited < 0.5, f"three turns waited {waited:.2f} s for a read that takes 0.6 s"
    assert "1 running, 1 stopped" in later
    assert listing.calls == 1


def test_the_turn_reads_states_only_never_every_green_s_changed_files(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def listing(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return {"ok": True, "projects": [], "unreadable": []}

    monkeypatch.setattr(routes, "read_projects", listing, raising=False)

    line = asyncio.run(turn_inputs.self_projects_status(web.Application()))

    assert [call.get("changed_files") for call in seen] == [False]
    assert "Your self-change projects right now: none." in line
