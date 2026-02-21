from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest


def _ensure_pkg(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path)]
    sys.modules[name] = pkg


def _import_module(module_name: str, file_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_message_module():
    try:
        from thomas.messages import p065_message_member_timeout as mod  # type: ignore

        return mod
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[2]
        _ensure_pkg("thomas", repo_root / "thomas")
        _ensure_pkg("thomas.messages", repo_root / "thomas" / "messages")
        return _import_module(
            "thomas.messages.p065_message_member_timeout",
            repo_root / "thomas" / "messages" / "p065_message_member_timeout.py",
        )


def _load_cli_module():
    try:
        from thomas.cli.commands.messages import p065_message_member_timeout as mod  # type: ignore

        return mod
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[2]
        _ensure_pkg("thomas", repo_root / "thomas")
        _ensure_pkg("thomas.messages", repo_root / "thomas" / "messages")
        _ensure_pkg("thomas.cli", repo_root / "thomas" / "cli")
        _ensure_pkg("thomas.cli.commands", repo_root / "thomas" / "cli" / "commands")
        _ensure_pkg("thomas.cli.commands.messages", repo_root / "thomas" / "cli" / "commands" / "messages")
        _load_message_module()
        return _import_module(
            "thomas.cli.commands.messages.p065_message_member_timeout",
            repo_root / "thomas" / "cli" / "commands" / "messages" / "p065_message_member_timeout.py",
        )


class _StubResponse:
    def __init__(self, status_code: int, text: str = "", json_data: Any = None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


def test_timeout_member_success_builds_expected_request():
    mod = _load_message_module()

    calls: list[Mapping[str, Any]] = []

    def http_stub(method: str, url: str, *, json: Mapping[str, Any] | None = None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "json": json, "headers": headers, "timeout": timeout})
        return _StubResponse(204, "")

    req = mod.MemberTimeoutRequest(
        guild_id="123",
        user_id="456",
        duration_seconds=60,
        reason="cool off",
    )
    cfg = mod.MemberTimeoutConfig(bot_token="TOKEN", api_base_url="https://discord.com/api/v10", timeout_seconds=5.0)

    fixed_now = datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc)
    result = mod.timeout_member(req, cfg, http=http_stub, now=fixed_now)

    assert result.guild_id == "123"
    assert result.user_id == "456"
    assert result.duration_seconds == 60
    assert result.timed_out_until == "2026-02-20T00:01:00.000Z"

    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "PATCH"
    assert call["url"] == "https://discord.com/api/v10/guilds/123/members/456"
    assert call["json"] == {"communication_disabled_until": "2026-02-20T00:01:00.000Z"}
    assert call["timeout"] == 5.0
    assert call["headers"]["Authorization"] == "Bot TOKEN"


def test_timeout_member_invalid_input_duration_raises_deterministic_error():
    mod = _load_message_module()

    req = mod.MemberTimeoutRequest(guild_id="123", user_id="456", duration_seconds=0)
    cfg = mod.MemberTimeoutConfig(bot_token="TOKEN")

    with pytest.raises(mod.InvalidInputError) as exc:
        mod.timeout_member(req, cfg, http=lambda *a, **k: _StubResponse(204))

    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details.get("field") == "duration_seconds"


def test_timeout_member_missing_config_token_raises_deterministic_error():
    mod = _load_message_module()

    req = mod.MemberTimeoutRequest(guild_id="123", user_id="456", duration_seconds=60)
    cfg = mod.MemberTimeoutConfig(bot_token="")

    with pytest.raises(mod.MissingConfigError) as exc:
        mod.timeout_member(req, cfg, http=lambda *a, **k: _StubResponse(204))

    assert exc.value.code == "MISSING_CONFIG"
    assert exc.value.details.get("missing") == "bot_token"


def test_timeout_member_external_failure_non_2xx_is_wrapped_and_includes_details():
    mod = _load_message_module()

    def http_stub(*args, **kwargs):
        return _StubResponse(401, "nope", json_data={"message": "Unauthorized", "code": 0})

    req = mod.MemberTimeoutRequest(guild_id="123", user_id="456", duration_seconds=60)
    cfg = mod.MemberTimeoutConfig(bot_token="TOKEN")

    with pytest.raises(mod.ExternalServiceError) as exc:
        mod.timeout_member(req, cfg, http=http_stub)

    assert exc.value.code == "EXTERNAL_FAILURE"
    assert exc.value.details.get("status_code") == 401
    assert "discord_message" in exc.value.details


def test_run_envelope_success_and_failure():
    mod = _load_message_module()

    fixed_now = datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc)

    def http_ok(*args, **kwargs):
        return _StubResponse(204, "")

    ok = mod.run(
        {"guild_id": "123", "user_id": "456", "duration_seconds": "60"},
        config={"bot_token": "TOKEN"},
        http=http_ok,
        now=fixed_now,
    )
    assert ok["ok"] is True
    assert ok["result"]["timed_out_until"] == "2026-02-20T00:01:00.000Z"

    bad = mod.run({"guild_id": "123", "user_id": "456", "duration_seconds": 0}, config={"bot_token": "TOKEN"})
    assert bad["ok"] is False
    assert bad["error"]["code"] == "INVALID_INPUT"


def test_cli_json_success(monkeypatch):
    cli_mod = _load_cli_module()

    import requests

    def fake_request(method, url, json=None, headers=None, timeout=None):
        return _StubResponse(204, "")

    monkeypatch.setattr(requests, "request", fake_request)

    from click.testing import CliRunner

    runner = CliRunner()
    res = runner.invoke(
        cli_mod.command,
        [
            "--guild-id",
            "123",
            "--user-id",
            "456",
            "--duration-seconds",
            "60",
            "--token",
            "TOKEN",
            "--json",
        ],
    )

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["result"]["guild_id"] == "123"
    assert payload["result"]["user_id"] == "456"
    assert payload["result"]["duration_seconds"] == 60
    assert isinstance(payload["result"]["timed_out_until"], str)
    assert payload["result"]["timed_out_until"].endswith("Z")


def test_cli_json_failure_missing_token_is_machine_readable():
    cli_mod = _load_cli_module()

    from click.testing import CliRunner

    runner = CliRunner()
    res = runner.invoke(
        cli_mod.command,
        [
            "--guild-id",
            "123",
            "--user-id",
            "456",
            "--duration-seconds",
            "60",
            "--json",
        ],
    )

    assert res.exit_code != 0
    payload = json.loads(res.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MISSING_CONFIG"
