"""The smart title: named from the exact first prompt, named again from the whole chat after the fifth, kept beside the sessions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server import app_chat_store
from thomas.server.chat_app_keys import APP_SESSION_STORE
from thomas.server.routes import chat_titles_runtime as titles


class FakeLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def chat(self, messages):
        self.prompts.append(messages[0]["content"])
        return {"text": self.answer}


def save_session(folder: Path, sid: str, prompts: int) -> None:
    messages = []
    for n in range(1, prompts + 1):
        messages.append({"role": "user", "content": f"prompt number {n} about the habit tracker"})
        messages.append({"role": "assistant", "content": f"reply number {n}"})
    (folder / f"chat_{sid}.json").write_text(
        json.dumps(
            {
                "session_id": sid,
                "saved_at": 1794000000,
                "meta": {"surface_mode": "chat"},
                "conversation": {"messages": messages},
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def client_and_state(tmp_path, monkeypatch):
    folder = tmp_path / "sessions_v2"
    folder.mkdir()
    llm = FakeLLM("Habit tracker dark mode")
    monkeypatch.setattr(titles, "_open_title_llm", lambda *a, **k: llm)
    app = web.Application()
    app[APP_SESSION_STORE] = SimpleNamespace(path_of=lambda sid: folder / f"chat_{sid}.json")
    titles.register_chat_title_routes(app, guard=lambda request: None, root=tmp_path)
    return app, folder, llm


async def ask(app, **body):
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/chats/auto-title", json=body)
        return response.status, await response.json()


async def test_the_first_prompt_names_the_chat_and_the_name_is_kept_beside_the_sessions(client_and_state):
    app, folder, llm = client_and_state
    save_session(folder, "s1", 1)
    status, body = await ask(app, session_id="s1")
    assert status == 200 and body["title"] == "Habit tracker dark mode" and body["stage"] == 1
    assert "prompt number 1" in llm.prompts[0] and "reply number" not in llm.prompts[0]  # the exact first prompt only
    assert json.loads((folder.parent / "chat_titles.json").read_text())["s1"]["title"] == "Habit tracker dark mode"
    listed = app_chat_store._v2_sessions_as_chats(folder)
    assert listed[0]["title"] == "Habit tracker dark mode"  # the sidebar list shows it


async def test_a_second_ask_at_the_same_point_does_nothing(client_and_state):
    app, folder, llm = client_and_state
    save_session(folder, "s1", 2)
    await ask(app, session_id="s1")
    status, body = await ask(app, session_id="s1")
    assert body["skipped"] == "already named" and len(llm.prompts) == 1


async def test_after_the_fifth_prompt_it_renames_from_the_whole_chat_once(client_and_state):
    app, folder, llm = client_and_state
    save_session(folder, "s1", 1)
    await ask(app, session_id="s1")
    save_session(folder, "s1", 5)
    llm.answer = "Habit tracker themes"
    status, body = await ask(app, session_id="s1")
    assert body["stage"] == 5 and body["title"] == "Habit tracker themes"
    last = llm.prompts[-1]
    assert "prompt number 1" in last and "prompt number 5" in last and "reply number 3" in last  # the full context
    status, again = await ask(app, session_id="s1")
    assert again["skipped"] == "already named"  # five is a one-time rename
    assert app_chat_store._v2_sessions_as_chats(folder)[0]["title"] == "Habit tracker themes"


async def test_a_greeting_stays_unnamed_and_a_timing_call_never_renames(client_and_state):
    app, folder, llm = client_and_state
    save_session(folder, "s1", 1)
    llm.answer = "New chat"
    _, body = await ask(app, session_id="s1")
    assert body["title"] == "" and not (folder.parent / "chat_titles.json").exists()
    llm.answer = "Timing title"
    _, timed = await ask(app, session_id="s1", model="gpt-6-luna", effort="low")
    assert timed["title"] == "Timing title" and not (folder.parent / "chat_titles.json").exists()


async def test_a_bad_session_id_is_refused(client_and_state):
    app, _, _ = client_and_state
    status, _ = await ask(app, session_id="../secrets")
    assert status == 400


def test_the_conversation_for_the_model_keeps_the_first_message_and_the_latest_within_the_limit():
    many = [{"role": "user" if n % 2 == 0 else "assistant", "content": f"message {n} " + "x" * 450} for n in range(60)]
    text = titles.conversation_text(many)
    assert text.startswith("User: message 0") and "message 59" in text and len(text) <= 7600
    assert "message 30" not in text


def test_the_title_model_defaults_are_a_fast_low_effort_model():
    assert titles.DEFAULT_TITLE_EFFORT == "low" and titles.DEFAULT_TITLE_MODEL in {"gpt-6-luna", "gpt-6.1-terra"}
