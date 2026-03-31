from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime
from thomas.server.app import create_app


def _parse_ndjson(blob: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _build_bot_root(tmp_path: Path) -> Path:
    bot_root = tmp_path / "discord-server-bot"
    (bot_root / "src").mkdir(parents=True, exist_ok=True)
    (bot_root / "data").mkdir(parents=True, exist_ok=True)
    (bot_root / "node_modules" / "discord.js").mkdir(parents=True, exist_ok=True)
    (bot_root / "scripts").mkdir(parents=True, exist_ok=True)
    (bot_root / "package.json").write_text(
        json.dumps(
            {
                "name": "thomas-discord-bridge-test",
                "private": True,
                "type": "module",
                "dependencies": {"discord.js": "^14.25.1"},
            }
        ),
        encoding="utf-8",
    )
    (bot_root / "node_modules" / "discord.js" / "package.json").write_text(
        json.dumps({"name": "discord.js", "version": "14.25.1"}),
        encoding="utf-8",
    )
    (bot_root / "src" / "index.js").write_text("console.log('discord bot test');\n", encoding="utf-8")
    (bot_root / "scripts" / "voice-probe.mjs").write_text(
        "console.log(JSON.stringify({ ok: true }));\n", encoding="utf-8"
    )
    (bot_root / ".env").write_text(
        "\n".join(
            [
                "DISCORD_BOT_TOKEN=test-token-1234",
                "DISCORD_OWNER_USER_IDS=111,222",
                "DISCORD_OWNER_ONLY_MODE=true",
                "DISCORD_REQUIRE_MENTION=true",
                "DISCORD_DEFAULT_VOICE_CHANNEL_NAME=Music",
                "DISCORD_VOICE_TTS_BACKEND=piper",
                "DISCORD_VOICE_TTS_MODEL=en_US-ryan-high",
                "DISCORD_VOICE_CLOUD_VOICE=alloy",
                "DISCORD_VOICE_SILENCE_MS=700",
                "DISCORD_VOICE_STT_BEAM_SIZE=6",
                "DISCORD_VOICE_STT_VAD_FILTER=true",
                "DISCORD_VOICE_STT_VAD_MIN_SILENCE_MS=500",
                "DISCORD_VOICE_STT_PROMPT=Prefer Discord voice commands.",
                "DISCORD_VOICE_STT_HINT_PHRASES=music,soundboard",
                "THOMAS_BASE_URL=http://127.0.0.1:8899",
                "SESSION_PREFIX=thomas-discord",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bot_root / "data" / "runtime-settings.json").write_text(
        json.dumps(
            {
                "requireMention": True,
                "voiceRequireWakeWord": True,
                "voiceWakeWords": ["thomas"],
                "voiceMediaVolume": 100,
                "voiceProfile": "en_US-ryan-high",
                "accessGrants": {},
            }
        ),
        encoding="utf-8",
    )
    (bot_root / "data" / "sessions.json").write_text(
        json.dumps({"versions": {"dm:111": 4}}),
        encoding="utf-8",
    )
    return bot_root


async def _start_client(app) -> TestClient:
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def _build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
        server=ServerConfig(access_mode="local"),
    )


def _set_test_bridge_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bot_root: Path) -> None:
    monkeypatch.setenv("THOMAS_DISCORD_BRIDGE_ROOT", str(bot_root))
    monkeypatch.setenv("THOMAS_SHARED_SECRET_STORE_DIR", str(tmp_path / "shared-secrets"))


def _discord_owner_metadata(*, owner: bool) -> dict[str, object]:
    return {
        "source": "discord-bridge",
        "scope_key": "dm:111",
        "discord": {
            "user_id": "111",
            "display_name": "Owner User",
            "guild_id": None,
            "channel_id": "dm-111",
            "owner": owner,
            "owner_only_mode": True,
            "granted_capabilities": ["talk", "media", "settings"] if owner else ["talk"],
            "surface": "discord",
            "client": "discord_bot",
            "slash_command": None,
            "request_kind": "message",
            "owner_authorized_for_settings_actions": owner,
        },
    }


@pytest.mark.asyncio
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
        assert discord["config"]["voice_silence_ms"] == 700
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
        }
    )

    env_text = (bot_root / ".env").read_text(encoding="utf-8")
    assert "new-secret-token-5678" not in env_text
    assert "thomas-api-token-9999" not in env_text
    assert 'DISCORD_OWNER_USER_IDS="111,222"' in env_text
    assert updated["DISCORD_BOT_TOKEN"] == "new-secret-token-5678"

    status = runtime.status()
    assert status["config"]["bot_token_stored"] is True
    assert status["config"]["thomas_api_token_stored"] is True
    assert status["config"]["bot_token_masked"].endswith("5678")


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


def test_discord_runtime_runs_voice_probe_with_secure_env_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
    runtime.save_state({"enabled": True, "pid": 1234, "last_started_at": "2026-03-29T12:00:00Z"})

    bridge_entry = str(bot_root / "src" / "index.js")

    def fake_probe_process(pid: int | None):
        if pid == 1234:
            return {"pid": 1234, "command_line": bridge_entry}
        if pid == 4321:
            return {"pid": 4321, "command_line": bridge_entry}
        return None

    calls: list[str] = []
    subprocess_calls: list[dict[str, object]] = []

    def fake_stop() -> dict[str, object]:
        calls.append("stop")
        runtime.save_state({"enabled": True, "pid": None})
        return {"ok": True}

    def fake_start() -> dict[str, object]:
        calls.append("start")
        runtime.save_state({"enabled": True, "pid": 4321})
        return {"ok": True}

    def fake_run(args, **kwargs):
        subprocess_calls.append({"args": list(args), "env": dict(kwargs.get("env") or {})})

        class Result:
            returncode = 0
            stdout = (
                'voice-probe-joined:General\n{"ok":true,"reply_text":"Voice check","transcribed_reply":"Voice check"}\n'
            )
            stderr = ""

        return Result()

    monkeypatch.setattr(runtime, "_probe_process", fake_probe_process)
    monkeypatch.setattr(runtime, "stop", fake_stop)
    monkeypatch.setattr(runtime, "start", fake_start)
    monkeypatch.setattr("thomas.integrations.discord_bridge_runtime.shutil.which", lambda name: "C:\\node.exe")
    monkeypatch.setattr("thomas.integrations.discord_bridge_runtime.subprocess.run", fake_run)

    payload = runtime.run_voice_probe(wake="Hey Thomas, how are you?", speaker_name="Owner User", speaker_id="111")

    assert payload["ok"] is True
    assert payload["bridge_was_running"] is True
    assert payload["probe"]["reply_text"] == "Voice check"
    assert payload["duration_ms"] >= 0
    assert calls == ["stop", "start"]
    assert subprocess_calls
    assert subprocess_calls[0]["env"]["DISCORD_BOT_TOKEN"] == "test-token-1234"
    assert "--wake" in subprocess_calls[0]["args"]


@pytest.mark.asyncio
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
