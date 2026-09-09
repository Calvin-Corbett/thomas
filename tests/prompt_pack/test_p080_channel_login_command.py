from __future__ import annotations

import argparse
import types

import pytest

import thomas.cli.commands.channel_ops.p080_channel_login_command as cli
import thomas.marketplace.channels.p080_channel_login_command as core


def test_channel_login_success_calls_integration_login(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.SimpleNamespace()

    def login(channel: str) -> dict:
        assert channel == "telegram"
        return {"account": "bot-123", "message": "Logged in"}

    fake_module.login = login

    def fake_import(name: str):
        assert name == "thomas.integrations.telegram"
        return fake_module

    monkeypatch.setattr(core.importlib, "import_module", fake_import)

    result = core.channel_login(core.ChannelLoginRequest(channel="telegram"))
    assert result.ok is True
    assert result.channel == "telegram"
    assert result.details == {"account": "bot-123"}
    assert "Logged in" in result.message


def test_channel_login_unknown_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import(name: str):
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(core.importlib, "import_module", fake_import)

    result = core.channel_login(core.ChannelLoginRequest(channel="madeup"))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == core.ChannelLoginErrorCode.UNKNOWN_CHANNEL


def test_channel_login_missing_config_reports_missing_params(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.SimpleNamespace()

    # Requires a token we won't provide.
    def login(token: str) -> None:
        raise AssertionError("Should not be called because token is missing")

    fake_module.login = login

    def fake_import(name: str):
        assert name == "thomas.integrations.telegram"
        return fake_module

    monkeypatch.setattr(core.importlib, "import_module", fake_import)

    result = core.channel_login(core.ChannelLoginRequest(channel="telegram"))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == core.ChannelLoginErrorCode.MISSING_CONFIG
    assert result.error.details.get("missing") == ["token"]


def test_channel_login_external_failure_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.SimpleNamespace()

    def login() -> None:
        raise RuntimeError("boom")

    fake_module.login = login

    def fake_import(name: str):
        assert name == "thomas.integrations.telegram"
        return fake_module

    monkeypatch.setattr(core.importlib, "import_module", fake_import)

    result = core.channel_login(core.ChannelLoginRequest(channel="telegram"))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == core.ChannelLoginErrorCode.EXTERNAL_FAILURE
    assert result.error.details.get("exception") == "RuntimeError"


def test_cli_json_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # Make the core login succeed without importing any integrations.
    monkeypatch.setattr(
        cli,
        "channel_login",
        lambda request: core.ChannelLoginResult(ok=True, channel="telegram", message="ok"),
    )

    args = argparse.Namespace(channel="telegram", json=True)
    exit_code = cli.run(args)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert '"ok": true' in captured.out
    assert '"channel": "telegram"' in captured.out
