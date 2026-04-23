from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_discord_channels_support import (
    ConversationManager,
    _build_bot_root,
    _build_config,
    _discord_owner_metadata,
    _parse_ndjson,
    _set_test_bridge_env,
    _start_client,
    create_app,
)


async def test_discord_origin_chat_route_indexes_task_manager_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    app = create_app(cfg)
    client = await _start_client(app)

    async def fake_ack(_llm, *, user_text: str, emit_text):
        assert user_text == "build me a game"
        await emit_text("Working on it.")
        return "Working on it."

    async def fake_dispatch_async(text: str, session_id: str, *, emit_event):
        assert text == "build me a game"
        assert session_id == "thomas-discord:dm:111:v4"
        await emit_event({"type": "task_status", "text": "queued"})
        return SimpleNamespace(ok=True, task_id="task-123", execution_id="exec-123", error="")

    async def fake_watch_task(task_id: str, *, emit_event):
        assert task_id == "task-123"
        await emit_event({"type": "task_completed", "text": "done"})

    monkeypatch.setattr("thomas.agent.dispatch.should_dispatch", lambda text: SimpleNamespace(action="dispatch"))
    monkeypatch.setattr("thomas.agent.chat_dispatcher.is_task_manager_dispatch_ready", lambda: True)
    monkeypatch.setattr("thomas.agent.chat_dispatcher.dispatch_async", fake_dispatch_async)
    monkeypatch.setattr("thomas.server.routes.chat_aiohttp_streaming.stream_task_start_acknowledgment", fake_ack)
    monkeypatch.setattr("thomas.server.routes.task_events.watch_task", fake_watch_task)

    try:
        resp = await client.post(
            "/api/chat",
            json={
                "session_id": "thomas-discord:dm:111:v4",
                "profile": "local",
                "mode": "fast",
                "text": "build me a game",
                "channel": "discord",
                "source": "discord_bridge",
                "client": "discord_bot",
                "surface": "discord",
                "metadata": _discord_owner_metadata(owner=True),
            },
        )
        assert resp.status == 200
        events = _parse_ndjson(await resp.text())
        assert any(event.get("type") == "task_dispatched" for event in events)

        history_resp = await client.get("/api/channels/discord/history")
        assert history_resp.status == 200
        history_payload = await history_resp.json()
        assert history_payload["sessions"][0]["session_id"] == "thomas-discord:dm:111:v4"

        session_resp = await client.get("/api/channels/discord/history/thomas-discord:dm:111:v4")
        assert session_resp.status == 200
        session_payload = await session_resp.json()
        assert session_payload["turns"][-1]["user_text"] == "build me a game"
        assert session_payload["turns"][-1]["assistant_text"] == "Working on it."
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_discord_origin_chat_v2_indexes_inline_reply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    app = create_app(cfg)
    client = await _start_client(app)

    class _FakeBrain:
        def __init__(self, **_kwargs):
            pass

        async def process_message(
            self,
            *,
            session_id: str,
            conversation: ConversationManager,
            prompt: str,
            dispatcher,
            **_kwargs,
        ) -> ConversationManager:
            assert session_id == "thomas-discord:dm:111:v5"
            await dispatcher.emit_text("Discord voice bridge is ready.")
            await dispatcher.emit_done(
                session_id=session_id,
                conversation_version=1,
                thinking_summary="fake_brain",
                iterations=1,
                tool_calls=0,
                tokens_used=0,
                specialists_used=["reasoning"],
            )
            return conversation.append_message("user", prompt).append_message("assistant", "Discord voice bridge is ready.")

    async def fake_get_or_create_session_llm(*_args, **_kwargs):
        return None, None

    monkeypatch.setattr("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain)
    monkeypatch.setattr("thomas.server.routes.chat_v2._get_or_create_session_llm", fake_get_or_create_session_llm)

    try:
        resp = await client.post(
            "/api/v2/chat",
            json={
                "session_id": "thomas-discord:dm:111:v5",
                "profile": "local",
                "mode": "auto",
                "message": "say hello in discord",
                "channel": "discord",
                "source": "discord_bridge",
                "client": "discord_bot",
                "surface": "discord",
                "metadata": _discord_owner_metadata(owner=True),
            },
        )
        assert resp.status == 200
        events = _parse_ndjson(await resp.text())
        done = next(event for event in events if event.get("type") == "done")
        assert done["thinking_summary"] == "fake_brain"

        session_resp = await client.get("/api/channels/discord/history/thomas-discord:dm:111:v5")
        assert session_resp.status == 200
        session_payload = await session_resp.json()
        assert session_payload["turns"][-1]["user_text"] == "say hello in discord"
        assert session_payload["turns"][-1]["assistant_text"] == "Discord voice bridge is ready."
    finally:
        await client.close()
