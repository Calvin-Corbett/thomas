from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_discord_channels_support import (
    DiscordBridgeRuntime,
    _build_bot_root,
    _build_config,
    _set_test_bridge_env,
    _start_client,
    create_app,
)


async def test_discord_channels_routes_return_status_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
    runtime.save_state({"enabled": True, "last_started_at": "2026-03-29T12:00:00Z"})
    runtime.append_history_turn(
        session_id="thomas-discord:dm:111:v4",
        user_text="Can you summarize the invoice thread?",
        assistant_text="The invoice thread is waiting on approval.",
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
        status_resp = await client.get("/api/channels/discord")
        assert status_resp.status == 200
        status_payload = await status_resp.json()
        discord = status_payload["discord"]
        assert discord["config"]["owner_only_mode"] is True
        assert discord["config"]["default_voice_channel_name"] == "Music"
        assert discord["config"]["voice_tts_backend"] == "piper"
        assert discord["config"]["voice_tts_model"] == "en_US-ryan-high"
        assert discord["config"]["voice_tts_use_cuda"] is True
        assert discord["config"]["voice_silence_ms"] == 700
        assert discord["config"]["voice_max_reply_chars"] == 140
        assert discord["config"]["voice_tts_sentence_pause_ms"] == 50
        assert discord["config"]["voice_tts_length_scale"] == "0.85"
        assert discord["config"]["voice_stt_beam_size"] == 6
        assert discord["config"]["voice_stt_vad_filter"] is True
        assert discord["config"]["voice_stt_hint_phrases"] == ["music", "soundboard"]
        assert discord["conversations"]["indexed_turns"] == 1

        history_resp = await client.get("/api/channels/discord/history?q=invoice")
        assert history_resp.status == 200
        history_payload = await history_resp.json()
        assert history_payload["hits"]
        assert history_payload["sessions"][0]["session_id"] == "thomas-discord:dm:111:v4"

        session_resp = await client.get("/api/channels/discord/history/thomas-discord:dm:111:v4")
        assert session_resp.status == 200
        session_payload = await session_resp.json()
        assert session_payload["turns"][0]["assistant_text"] == "The invoice thread is waiting on approval."
    finally:
        await client.close()


def test_discord_runtime_moves_secret_fields_out_of_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)

    updated = runtime.update_env(
        {
            "bot_token": "new-secret-token-5678",
            "thomas_api_token": "thomas-api-token-9999",
            "owner_user_ids": "111,222",
            "thomas_base_url": "http://127.0.0.1:8899",
            "voice_max_reply_chars": 140,
            "voice_tts_length_scale": 0.85,
        }
    )

    env_text = (bot_root / ".env").read_text(encoding="utf-8")
    assert "new-secret-token-5678" not in env_text
    assert "thomas-api-token-9999" not in env_text
    assert 'DISCORD_OWNER_USER_IDS="111,222"' in env_text
    assert "DISCORD_VOICE_MAX_REPLY_CHARS=140" in env_text
    assert "DISCORD_VOICE_TTS_LENGTH_SCALE=0.85" in env_text
    assert updated["DISCORD_BOT_TOKEN"] == "new-secret-token-5678"

    status = runtime.status()
    assert status["config"]["bot_token_stored"] is True
    assert status["config"]["thomas_api_token_stored"] is True
    assert status["config"]["bot_token_masked"].endswith("5678")


def test_discord_runtime_persists_false_and_zero_env_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)

    runtime.update_env(
        {
            "owner_only_mode": False,
            "require_mention": False,
            "voice_tts_use_cuda": False,
            "voice_tts_sentence_pause_ms": 0,
        }
    )

    env_text = (bot_root / ".env").read_text(encoding="utf-8")
    assert "DISCORD_OWNER_ONLY_MODE=false" in env_text
    assert "DISCORD_REQUIRE_MENTION=false" in env_text
    assert "DISCORD_VOICE_TTS_USE_CUDA=false" in env_text
    assert "DISCORD_VOICE_TTS_SENTENCE_PAUSE_MS=0" in env_text

    status = runtime.status()
    assert status["config"]["owner_only_mode"] is False
    assert status["config"]["require_mention"] is False
    assert status["config"]["voice_tts_use_cuda"] is False
    assert status["config"]["voice_tts_sentence_pause_ms"] == 0


def test_discord_runtime_defaults_to_embedded_bridge_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_DISCORD_BRIDGE_ROOT", raising=False)
    monkeypatch.setenv("THOMAS_SHARED_SECRET_STORE_DIR", str(tmp_path / "shared-secrets"))
    cfg = _build_config(tmp_path)

    runtime = DiscordBridgeRuntime(cfg)

    assert runtime.uses_embedded_bridge is True
    assert runtime.bridge_root.name == "discord_bridge_service"
    assert runtime.env_path == cfg.memory.root_path / ".thomas" / "discord_bridge" / "bridge.env"
    assert (
        runtime.runtime_settings_path
        == cfg.memory.root_path / ".thomas" / "discord_bridge" / "service_data" / "runtime-settings.json"
    )
    assert (
        runtime.sessions_path == cfg.memory.root_path / ".thomas" / "discord_bridge" / "service_data" / "sessions.json"
    )


def test_discord_runtime_updates_voice_settings_and_restarts_running_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
    runtime.save_state({"enabled": True, "pid": 9876, "last_started_at": "2026-03-29T12:00:00Z"})

    monkeypatch.setattr(
        runtime,
        "_probe_process",
        lambda pid: {"pid": 9876, "command_line": str(bot_root / "src" / "index.js")} if pid == 9876 else None,
    )
    restarted: list[str] = []

    def fake_restart() -> dict[str, object]:
        restarted.append("restart")
        runtime.save_state({"enabled": True, "pid": 9876, "last_started_at": "2026-03-29T12:05:00Z"})
        return {"ok": True}

    monkeypatch.setattr(runtime, "restart", fake_restart)

    result = runtime.update_runtime_settings(
        {
            "voice_profile": "en_GB-alan-medium",
            "voice_wake_words": "thomas, okay thomas",
            "voice_require_wake_word": False,
            "voice_media_volume": 85,
        }
    )

    assert result["restarted"] is True
    assert restarted == ["restart"]
    status = runtime.status()
    assert status["runtime"]["voice_profile"] == "en_GB-alan-medium"
    assert status["runtime"]["voice_wake_words"] == ["thomas", "okay thomas"]
    assert status["runtime"]["voice_require_wake_word"] is False
    assert status["runtime"]["voice_media_volume"] == 85


def test_discord_runtime_accepts_camel_case_runtime_updates_and_false_strings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)

    result = runtime.update_runtime_settings(
        {
            "voiceRequireWakeWord": "false",
            "voiceWakeWords": ["thomas", "yo thomas"],
            "requireMention": "false",
        },
        restart_if_running=False,
    )

    assert result["restarted"] is False
    assert result["settings"]["voiceRequireWakeWord"] is False
    assert result["settings"]["voiceWakeWords"] == ["thomas", "yo thomas"]
    assert result["settings"]["requireMention"] is False
    status = runtime.status()
    assert status["runtime"]["voice_require_wake_word"] is False
    assert status["runtime"]["voice_wake_words"] == ["thomas", "yo thomas"]
