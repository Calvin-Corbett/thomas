from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_discord_channels_support import (
    DiscordBridgeRuntime,
    _build_bot_root,
    _build_config,
    _set_test_bridge_env,
)


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


def test_discord_runtime_disconnects_voice_sessions_via_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(*, method: str, path: str, token: str, payload=None, timeout: float = 10.0):
        calls.append((method, path, payload))
        assert token == "test-token-1234"
        if method == "GET":
            return 200, {"id": "bot-user-1"}
        return 200, {"channel_id": None}

    monkeypatch.setattr(runtime, "_discord_api_request", fake_request)
    result = runtime._disconnect_bot_voice_sessions(
        {
            "DISCORD_BOT_TOKEN": "test-token-1234",
            "DISCORD_GUILD_ID": "guild-a",
            "DISCORD_ALLOWED_GUILD_IDS": "guild-b,guild-a",
        }
    )

    assert result["attempted"] is True
    assert result["bot_user_id"] == "bot-user-1"
    assert result["disconnected_guild_ids"] == ["guild-a", "guild-b"]
    assert result["errors"] == []
    assert calls == [
        ("GET", "/users/@me", None),
        ("PATCH", "/guilds/guild-a/members/bot-user-1", {"channel_id": None}),
        ("PATCH", "/guilds/guild-b/members/bot-user-1", {"channel_id": None}),
    ]


def test_discord_runtime_stop_cleans_orphaned_voice_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
    runtime.save_state({"enabled": True, "pid": 9876, "last_started_at": "2026-03-29T12:00:00Z"})
    cleanup_calls: list[str] = []

    monkeypatch.setattr(runtime, "_probe_process", lambda pid: None)
    monkeypatch.setattr(
        runtime,
        "_disconnect_bot_voice_sessions",
        lambda env: cleanup_calls.append(env.get("DISCORD_BOT_TOKEN", "")) or {"errors": [], "disconnected_guild_ids": ["guild-a"]},
    )

    payload = runtime.stop()

    assert cleanup_calls == ["test-token-1234"]
    assert payload["bridge"]["running"] is False
    assert runtime.load_state()["pid"] is None
    assert runtime.load_state()["last_error"] == ""


def test_discord_runtime_start_cleans_stale_voice_sessions_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_root = _build_bot_root(tmp_path)
    _set_test_bridge_env(monkeypatch, tmp_path, bot_root)
    cfg = _build_config(tmp_path)
    runtime = DiscordBridgeRuntime(cfg, bridge_root=bot_root)
    cleanup_calls: list[str] = []
    bridge_entry = str(bot_root / "src" / "index.js")

    class DummyProcess:
        pid = 4321

        @staticmethod
        def poll():
            return None

    def fake_probe_process(pid: int | None):
        if pid == 4321:
            return {"pid": 4321, "command_line": bridge_entry}
        return None

    monkeypatch.setattr(runtime, "_probe_process", fake_probe_process)
    monkeypatch.setattr(runtime, "_find_node", lambda: "C:\\node.exe")
    monkeypatch.setattr(runtime, "_find_npm", lambda: "C:\\npm.cmd")
    monkeypatch.setattr(runtime, "ensure_node_dependencies", lambda: {"ready": True, "installed": False, "node": "C:\\node.exe"})
    monkeypatch.setattr(
        runtime,
        "_disconnect_bot_voice_sessions",
        lambda env: cleanup_calls.append(env.get("DISCORD_BOT_TOKEN", "")) or {"errors": [], "disconnected_guild_ids": ["guild-a"]},
    )
    monkeypatch.setattr("thomas.integrations.discord_bridge_runtime.subprocess.Popen", lambda *args, **kwargs: DummyProcess())

    payload = runtime.start()

    assert cleanup_calls == ["test-token-1234"]
    assert payload["bridge"]["running"] is True
    assert runtime.load_state()["pid"] == 4321
