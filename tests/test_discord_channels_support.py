from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from thomas.chat.conversation import ConversationManager
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime
from thomas.server.app import create_app

__all__ = [
    "ConversationManager",
    "DiscordBridgeRuntime",
    "create_app",
    "_build_bot_root",
    "_build_config",
    "_discord_owner_metadata",
    "_parse_ndjson",
    "_set_test_bridge_env",
    "_start_client",
]


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
                "DISCORD_VOICE_TTS_USE_CUDA=true",
                "DISCORD_VOICE_SILENCE_MS=700",
                "DISCORD_VOICE_MAX_REPLY_CHARS=140",
                "DISCORD_VOICE_STT_BEAM_SIZE=6",
                "DISCORD_VOICE_STT_VAD_FILTER=true",
                "DISCORD_VOICE_STT_VAD_MIN_SILENCE_MS=500",
                "DISCORD_VOICE_STT_PROMPT=Prefer Discord voice commands.",
                "DISCORD_VOICE_STT_HINT_PHRASES=music,soundboard",
                "DISCORD_VOICE_TTS_SENTENCE_PAUSE_MS=50",
                "DISCORD_VOICE_TTS_LENGTH_SCALE=0.85",
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
