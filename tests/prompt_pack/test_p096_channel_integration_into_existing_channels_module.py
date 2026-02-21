from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.channels.p096_channel_integration_into_existing_channels_module import (
    ChannelIntegrationRequest,
    ExternalFailureError,
    InvalidInputError,
    MissingConfigError,
    integrate_channel,
)


class _FailingTelegramSender:
    def send_message(self, *, token: str, chat_id: str, text: str):
        raise RuntimeError("boom")


def test_integrate_channel_success_persists_enablement(tmp_path: Path) -> None:
    config_path = tmp_path / "thomas.json"
    config_path.write_text(
        json.dumps(
            {
                "channels": {"telegram": {"token": "token_123", "chat_id": "42"}},
            }
        )
        + "\n"
    )

    result = integrate_channel(
        ChannelIntegrationRequest(provider="telegram", config_path=config_path, persist_enablement=True)
    )

    assert result.integrated is True
    assert result.validated is True
    assert result.wrote_config is True
    assert result.enabled_channels == ["telegram"]

    updated = json.loads(config_path.read_text())
    assert updated["channels_enabled"] == ["telegram"]


def test_integrate_channel_dry_run_does_not_write(tmp_path: Path) -> None:
    config_path = tmp_path / "thomas.json"
    original = {"channels": {"telegram": {"token": "token_123", "chat_id": "42"}}}
    config_path.write_text(json.dumps(original) + "\n")

    result = integrate_channel(
        ChannelIntegrationRequest(
            provider="telegram",
            config_path=config_path,
            persist_enablement=True,
            dry_run=True,
        )
    )

    assert result.integrated is True
    assert result.validated is True
    assert result.wrote_config is False
    assert json.loads(config_path.read_text()) == original


def test_integrate_channel_invalid_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "thomas.json"
    config_path.write_text(json.dumps({}) + "\n")

    with pytest.raises(InvalidInputError):
        integrate_channel(ChannelIntegrationRequest(provider="sms", config_path=config_path))


def test_integrate_channel_missing_token(tmp_path: Path) -> None:
    config_path = tmp_path / "thomas.json"
    config_path.write_text(json.dumps({"channels": {"telegram": {"chat_id": "42"}}}) + "\n")

    with pytest.raises(MissingConfigError):
        integrate_channel(ChannelIntegrationRequest(provider="telegram", config_path=config_path))


def test_integrate_channel_external_failure_wrapped(tmp_path: Path) -> None:
    config_path = tmp_path / "thomas.json"
    config_path.write_text(
        json.dumps({"channels": {"telegram": {"token": "token_123", "chat_id": "42"}}}) + "\n"
    )

    with pytest.raises(ExternalFailureError) as exc:
        integrate_channel(
            ChannelIntegrationRequest(
                provider="telegram",
                config_path=config_path,
                persist_enablement=False,
                dry_run=False,
                test_message="hi",
            ),
            telegram_sender=_FailingTelegramSender(),
        )

    assert exc.value.code == "external_failure"


def test_cli_integrate_channel_json_success(tmp_path: Path) -> None:
    from thomas.cli.commands.channels import app as channels_app

    # Ensure the P096 command is registered even if channels.py doesn't auto-load ops.
    try:
        from thomas.cli.commands.channel_ops.p096_channel_integration_into_existing_channels_module import (
            register as register_p096,
        )
        register_p096(channels_app)
    except Exception:
        # If already registered, Typer may raise. Proceed.
        pass

    config_path = tmp_path / "thomas.json"
    config_path.write_text(
        json.dumps({"channels": {"telegram": {"token": "token_123", "chat_id": "42"}}}) + "\n"
    )

    runner = CliRunner()
    res = runner.invoke(
        channels_app,
        ["integrate", "telegram", "--config", str(config_path), "--persist", "--json"],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["integrated"] is True
    assert payload["result"]["provider"] == "telegram"
