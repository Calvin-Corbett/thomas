from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_discord_channels_support import (
    DiscordBridgeRuntime,
    _build_bot_root,
    _build_config,
    _discord_owner_metadata,
    _parse_ndjson,
    _set_test_bridge_env,
    _start_client,
    create_app,
)


async def test_discord_voice_probe_route_returns_probe_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    seen: dict[str, object] = {}

    def fake_run_voice_probe(self, **kwargs):
        seen.update(kwargs)
        return {
            "ok": True,
            "probe": {
                "ok": True,
                "mode": "wake",
                "raw_transcript": "Hey Thomas, how are you?",
                "reply_text": "Voice probe is healthy.",
                "transcribed_reply": "Voice probe is healthy.",
            },
            "bridge_was_running": False,
            "bridge_restart_error": "",
            "stderr": "",
        }

    monkeypatch.setattr(
        DiscordBridgeRuntime,
        "run_voice_probe",
        fake_run_voice_probe,
    )
    cfg = _build_config(tmp_path)
    app = create_app(cfg)
    client = await _start_client(app)
    try:
        resp = await client.post(
            "/api/channels/discord/voice-probe",
            json={"wake": "Hey Thomas, how are you?"},
        )
        assert resp.status == 200
        payload = await resp.json()
        assert seen["wake"] == "Hey Thomas, how are you?"
        assert payload["probe"]["reply_text"] == "Voice probe is healthy."
        assert payload["discord"]["bridge"]["status"] in {"unconfigured", "stopped"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_discord_runtime_route_updates_voice_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    seen: dict[str, object] = {}

    def fake_update_runtime_settings(self, payload, restart_if_running=True):
        seen["payload"] = dict(payload)
        seen["restart_if_running"] = restart_if_running
        return {
            "settings": {
                "voiceProfile": "en_US-ryan-high",
                "voiceRequireWakeWord": True,
            },
            "restarted": True,
        }

    monkeypatch.setattr(DiscordBridgeRuntime, "update_runtime_settings", fake_update_runtime_settings)
    cfg = _build_config(tmp_path)
    app = create_app(cfg)
    client = await _start_client(app)
    try:
        resp = await client.post(
            "/api/channels/discord/runtime",
            json={
                "voice_profile": "en_US-ryan-high",
                "voice_require_wake_word": True,
                "voice_wake_words": "thomas, hey thomas",
                "restart_if_running": False,
            },
        )
        assert resp.status == 200
        payload = await resp.json()
        assert seen["payload"]["voice_profile"] == "en_US-ryan-high"
        assert seen["payload"]["voice_wake_words"] == "thomas, hey thomas"
        assert seen["restart_if_running"] is False
        assert payload["restarted"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_discord_runtime_settings_alias_updates_voice_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    seen: dict[str, object] = {}

    def fake_update_runtime_settings(self, payload, restart_if_running=True):
        seen["payload"] = dict(payload)
        seen["restart_if_running"] = restart_if_running
        return {
            "settings": {
                "voiceProfile": "en_US-ryan-high",
                "voiceRequireWakeWord": False,
            },
            "restarted": False,
        }

    monkeypatch.setattr(DiscordBridgeRuntime, "update_runtime_settings", fake_update_runtime_settings)
    cfg = _build_config(tmp_path)
    app = create_app(cfg)
    client = await _start_client(app)
    try:
        resp = await client.post(
            "/api/channels/discord/runtime-settings",
            json={
                "voice_require_wake_word": False,
                "restart_if_running": True,
            },
        )
        assert resp.status == 200
        payload = await resp.json()
        assert seen["payload"]["voice_require_wake_word"] is False
        assert seen["restart_if_running"] is True
        assert payload["settings"]["voiceRequireWakeWord"] is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_local_chat_can_report_discord_status_without_agent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    app = create_app(cfg)
    client = await _start_client(app)
    try:
        sess_resp = await client.post("/api/session/new")
        assert sess_resp.status == 200
        sid = str((await sess_resp.json()).get("session_id") or "")
        resp = await client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "show discord status",
            },
        )
        assert resp.status == 200
        events = _parse_ndjson(await resp.text())
        done = next(event for event in events if event.get("type") == "done")
        assert done["tool_calls"] == 0
        assert "Discord bridge status:" in str(done["text"])
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_non_owner_discord_request_cannot_start_bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    app = create_app(cfg)
    client = await _start_client(app)
    try:
        resp = await client.post(
            "/api/chat",
            json={
                "session_id": "thomas-discord:dm:111:v4",
                "profile": "local",
                "mode": "fast",
                "text": "start the discord bot",
                "channel": "discord",
                "source": "discord_bridge",
                "client": "discord_bot",
                "surface": "discord",
                "metadata": _discord_owner_metadata(owner=False),
            },
        )
        assert resp.status == 200
        events = _parse_ndjson(await resp.text())
        done = next(event for event in events if event.get("type") == "done")
        assert "owner-only" in str(done["text"]).lower()
        runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
        assert runtime.load_state()["pid"] is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_owner_discord_request_can_reference_recent_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
    runtime.append_history_turn(
        session_id="thomas-discord:dm:111:v4",
        user_text="Remember the podcast guest follow-up.",
        assistant_text="We said to send the guest the calendar link tomorrow morning.",
        context={
            "scope_key": "dm:111",
            "user_id": "111",
            "display_name": "Owner User",
            "surface": "discord",
            "request_kind": "message",
            "owner": True,
            "granted_capabilities": ["talk", "media", "settings"],
        },
        tool_calls=0,
    )
    app = create_app(cfg)
    client = await _start_client(app)
    try:
        resp = await client.post(
            "/api/chat",
            json={
                "session_id": "thomas-discord:dm:111:v4",
                "profile": "local",
                "mode": "fast",
                "text": "show recent discord conversations",
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
        assert "Recent Discord conversations:" in str(done["text"])
        assert "thomas-discord:dm:111:v4" in str(done["text"])
    finally:
        await client.close()
