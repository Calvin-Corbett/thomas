import json

import pytest
from click.testing import CliRunner

from thomas.marketplace.channels.p087_channel_auth_validation_helper import (
    ChannelAuthValidationRequest,
    ChannelAuthValidationResult,
    ChannelIdentity,
    ExternalChannelAuthValidationError,
    InvalidChannelAuthInputError,
    MissingChannelAuthConfigError,
    validate_channel_auth,
)


def test_success_telegram_http(monkeypatch):
    # Patch HTTP call to keep test offline/deterministic.
    from thomas.marketplace.channels import p087_channel_auth_validation_helper as mod

    def fake_http_get_json(*, url: str, timeout_s: float):
        assert "api.telegram.org" in url
        assert timeout_s == 5.0
        return {"ok": True, "result": {"id": 42, "username": "thomas_bot", "first_name": "Thomas"}}

    monkeypatch.setattr(mod, "_http_get_json", fake_http_get_json)

    res = validate_channel_auth(ChannelAuthValidationRequest(channel="telegram", token="123:ABC", timeout_s=5.0))
    assert res.channel == "telegram"
    assert res.valid is True
    assert res.identity is not None
    assert res.identity.id == "42"
    assert res.identity.username == "thomas_bot"
    assert res.identity.display_name == "Thomas"


def test_alias_tg(monkeypatch):
    from thomas.marketplace.channels import p087_channel_auth_validation_helper as mod

    monkeypatch.setattr(mod, "_http_get_json", lambda **kwargs: {"ok": True, "result": {"id": 1}})
    res = validate_channel_auth(ChannelAuthValidationRequest(channel="tg", token="x"))
    assert res.channel == "telegram"
    assert res.valid is True


def test_missing_config(monkeypatch):
    from thomas.marketplace.channels import p087_channel_auth_validation_helper as mod

    for k in mod._expected_env_vars("telegram"):
        monkeypatch.delenv(k, raising=False)

    with pytest.raises(MissingChannelAuthConfigError) as ei:
        validate_channel_auth(ChannelAuthValidationRequest(channel="telegram"))

    assert ei.value.code == "MISSING_CONFIG"
    assert ei.value.channel == "telegram"
    assert "missing authentication credentials" in str(ei.value)


def test_env_token_resolution(monkeypatch):
    from thomas.marketplace.channels import p087_channel_auth_validation_helper as mod

    monkeypatch.setenv("THOMAS_TELEGRAM_BOT_TOKEN", "ENV_TOKEN")
    monkeypatch.setattr(mod, "_http_get_json", lambda **kwargs: {"ok": True, "result": {"id": 7}})

    res = validate_channel_auth(ChannelAuthValidationRequest(channel="telegram"))
    assert res.details is not None
    assert res.details.get("source") == "env"
    assert res.identity is not None and res.identity.id == "7"


def test_invalid_channel():
    with pytest.raises(InvalidChannelAuthInputError) as ei:
        validate_channel_auth(ChannelAuthValidationRequest(channel="nope", token="x"))
    assert ei.value.code == "INVALID_INPUT"


def test_invalid_timeout():
    with pytest.raises(InvalidChannelAuthInputError) as ei:
        validate_channel_auth(ChannelAuthValidationRequest(channel="telegram", token="x", timeout_s=0))
    assert ei.value.code == "INVALID_INPUT"
    assert ei.value.channel == "telegram"


def test_external_failure(monkeypatch):
    from thomas.marketplace.channels import p087_channel_auth_validation_helper as mod

    def boom(*, url: str, timeout_s: float):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mod, "_http_get_json", boom)

    with pytest.raises(ExternalChannelAuthValidationError) as ei:
        validate_channel_auth(ChannelAuthValidationRequest(channel="telegram", token="x"))

    assert ei.value.code == "EXTERNAL_FAILURE"
    assert ei.value.channel == "telegram"


def test_cli_json_success(monkeypatch):
    from thomas.cli.commands.channel_ops import p087_channel_auth_validation_helper as cli_mod

    def fake_validate(req):
        assert req.channel == "telegram"
        return ChannelAuthValidationResult(
            channel="telegram",
            valid=True,
            identity=ChannelIdentity(id="99", username="bot", display_name="Bot"),
            details={"source": "override"},
        )

    monkeypatch.setattr(cli_mod, "validate_channel_auth", fake_validate)

    runner = CliRunner()
    out = runner.invoke(cli_mod.command, ["telegram", "--token", "x", "--json"])
    assert out.exit_code == 0, out.output
    payload = json.loads(out.output.strip())
    assert payload["ok"] is True
    assert payload["channel"] == "telegram"
    assert payload["identity"]["id"] == "99"


def test_cli_json_failure(monkeypatch):
    from thomas.cli.commands.channel_ops import p087_channel_auth_validation_helper as cli_mod
    from thomas.marketplace.channels.p087_channel_auth_validation_helper import MissingChannelAuthConfigError

    def fake_validate(req):
        raise MissingChannelAuthConfigError("no token", channel="telegram")

    monkeypatch.setattr(cli_mod, "validate_channel_auth", fake_validate)

    runner = CliRunner()
    out = runner.invoke(cli_mod.command, ["telegram", "--json"])
    assert out.exit_code != 0
    payload = json.loads(out.output.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MISSING_CONFIG"
    assert payload["error"]["channel"] == "telegram"
