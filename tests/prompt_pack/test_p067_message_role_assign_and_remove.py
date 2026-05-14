import json
from typing import Any

import pytest
from typer.testing import CliRunner

from thomas.cli.commands.messages.p067_message_role_assign_and_remove import app as cli_app
from thomas.messages.p067_message_role_assign_and_remove import (
    ExternalMessageRoleFailure,
    HttpResult,
    InvalidMessageRoleInput,
    MessageRoleChangeRequest,
    MissingMessageRoleConfig,
    change_member_role,
)


def test_change_member_role_assign_success(monkeypatch):
    monkeypatch.setenv("THOMAS_DISCORD_BOT_TOKEN", "tkn")

    def fake_request(method: str, url: str, headers: dict[str, str], timeout_s: float) -> HttpResult:
        assert method == "PUT"
        assert "authorization" in headers
        return HttpResult(status_code=204, headers={}, body=b"")

    req = MessageRoleChangeRequest(
        guild_id="123456789012345678",
        user_id="234567890123456789",
        role_id="345678901234567890",
        action="assign",
    )
    res = change_member_role(req, http_request=fake_request)
    assert res.ok is True
    assert res.action == "assign"
    assert res.status_code == 204


def test_change_member_role_remove_success(monkeypatch):
    monkeypatch.setenv("THOMAS_DISCORD_BOT_TOKEN", "tkn")

    def fake_request(method: str, url: str, headers: dict[str, str], timeout_s: float) -> HttpResult:
        assert method == "DELETE"
        return HttpResult(status_code=204, headers={}, body=b"")

    req = MessageRoleChangeRequest(
        guild_id="123456789012345678",
        user_id="234567890123456789",
        role_id="345678901234567890",
        action="remove",
    )
    res = change_member_role(req, http_request=fake_request)
    assert res.ok is True
    assert res.action == "remove"


def test_invalid_input(monkeypatch):
    monkeypatch.setenv("THOMAS_DISCORD_BOT_TOKEN", "tkn")

    req = MessageRoleChangeRequest(
        guild_id="not-a-snowflake",
        user_id="234567890123456789",
        role_id="345678901234567890",
        action="assign",
    )
    with pytest.raises(InvalidMessageRoleInput) as ei:
        change_member_role(req, http_request=lambda *a, **k: HttpResult(204, {}, b""))
    assert ei.value.code == "invalid_input"


def test_missing_config(monkeypatch):
    for k in ("THOMAS_DISCORD_BOT_TOKEN", "THOMAS_DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "DISCORD_TOKEN"):
        monkeypatch.delenv(k, raising=False)

    req = MessageRoleChangeRequest(
        guild_id="123456789012345678",
        user_id="234567890123456789",
        role_id="345678901234567890",
        action="assign",
    )
    with pytest.raises(MissingMessageRoleConfig) as ei:
        change_member_role(req, http_request=lambda *a, **k: HttpResult(204, {}, b""))
    assert ei.value.code == "missing_config"


def test_external_failure_json_body(monkeypatch):
    monkeypatch.setenv("THOMAS_DISCORD_BOT_TOKEN", "tkn")

    def fake_request(method: str, url: str, headers: dict[str, str], timeout_s: float) -> HttpResult:
        body = json.dumps({"message": "Missing Permissions", "code": 50013}).encode("utf-8")
        return HttpResult(status_code=403, headers={"content-type": "application/json"}, body=body)

    req = MessageRoleChangeRequest(
        guild_id="123456789012345678",
        user_id="234567890123456789",
        role_id="345678901234567890",
        action="assign",
    )
    with pytest.raises(ExternalMessageRoleFailure) as ei:
        change_member_role(req, http_request=fake_request)
    assert ei.value.code == "external_failure"
    assert ei.value.details["status_code"] == 403
    assert ei.value.details["response_json"]["code"] == 50013


def test_cli_json_success(monkeypatch):
    monkeypatch.setenv("THOMAS_DISCORD_BOT_TOKEN", "tkn")

    import thomas.messages.p067_message_role_assign_and_remove as mod

    def fake_default(method: str, url: str, headers: dict[str, str], timeout_s: float) -> HttpResult:
        return HttpResult(status_code=204, headers={}, body=b"")

    monkeypatch.setattr(mod, "_default_http_request", fake_default)

    runner = CliRunner()
    res = runner.invoke(
        cli_app,
        [
            "assign",
            "--guild-id",
            "123456789012345678",
            "--user-id",
            "234567890123456789",
            "--role-id",
            "345678901234567890",
            "--json",
        ],
    )
    assert res.exit_code == 0
    payload = json.loads(res.stdout.strip())
    assert payload["ok"] is True
    assert payload["action"] == "assign"


def test_cli_json_failure(monkeypatch):
    for k in ("THOMAS_DISCORD_BOT_TOKEN", "THOMAS_DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "DISCORD_TOKEN"):
        monkeypatch.delenv(k, raising=False)

    runner = CliRunner()
    res = runner.invoke(
        cli_app,
        [
            "assign",
            "--guild-id",
            "123456789012345678",
            "--user-id",
            "234567890123456789",
            "--role-id",
            "345678901234567890",
            "--json",
        ],
    )
    assert res.exit_code == 1
    payload = json.loads(res.stdout.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
