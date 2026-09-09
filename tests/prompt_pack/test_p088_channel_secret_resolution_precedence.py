from pathlib import Path

import pytest

from thomas.marketplace.channels.p088_channel_secret_resolution_precedence import (
    ChannelSecretRequest,
    InvalidSecretRequestError,
    SecretNotFoundError,
    SecretSource,
    SecretSourceError,
    resolve_channel_secret,
)


def test_precedence_cli_over_env_and_config(monkeypatch):
    monkeypatch.setenv("THOMAS_TELEGRAM_BOT_TOKEN", "env-token")
    req = ChannelSecretRequest(
        provider="telegram",
        secret_key="token",
        cli_spec="cli-token",
        config_spec="config-token",
    )
    res = resolve_channel_secret(req)
    assert res.value == "cli-token"
    assert res.source is SecretSource.CLI


def test_precedence_channel_over_env(monkeypatch):
    monkeypatch.setenv("THOMAS_TELEGRAM_BOT_TOKEN", "env-token")
    req = ChannelSecretRequest(
        provider="telegram",
        secret_key="token",
        channel_spec="channel-token",
    )
    res = resolve_channel_secret(req)
    assert res.value == "channel-token"
    assert res.source is SecretSource.CHANNEL


def test_precedence_env_over_config(monkeypatch):
    monkeypatch.setenv("THOMAS_TELEGRAM_BOT_TOKEN", "env-token")
    req = ChannelSecretRequest(
        provider="telegram",
        secret_key="token",
        config_spec="config-token",
    )
    res = resolve_channel_secret(req)
    assert res.value == "env-token"
    assert res.source is SecretSource.ENV


def test_precedence_config_when_env_missing(monkeypatch):
    monkeypatch.delenv("THOMAS_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    req = ChannelSecretRequest(
        provider="telegram",
        secret_key="token",
        config_spec="config-token",
        env_var_names=("NO_SUCH_ENV_VAR",),
    )
    res = resolve_channel_secret(req)
    assert res.value == "config-token"
    assert res.source is SecretSource.CONFIG


def test_explicit_env_spec(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "env-token")
    req = ChannelSecretRequest(provider="telegram", secret_key="token", cli_spec="env:MY_TOKEN")
    res = resolve_channel_secret(req)
    assert res.value == "env-token"
    assert res.source is SecretSource.CLI


def test_missing_env_var_in_explicit_spec_is_error(monkeypatch):
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    req = ChannelSecretRequest(provider="telegram", secret_key="token", cli_spec="env:MISSING_TOKEN")
    with pytest.raises(SecretSourceError) as excinfo:
        resolve_channel_secret(req)
    assert excinfo.value.code == "secret_source_error"
    assert excinfo.value.details.get("env_var") == "MISSING_TOKEN"


def test_file_spec(monkeypatch, tmp_path: Path):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("file-token\n", encoding="utf-8")
    req = ChannelSecretRequest(provider="telegram", secret_key="token", channel_spec=f"file:{secret_file}")
    res = resolve_channel_secret(req)
    assert res.value == "file-token"
    assert res.source is SecretSource.CHANNEL


def test_missing_file_in_spec_is_error(tmp_path: Path):
    missing_file = tmp_path / "missing.txt"
    req = ChannelSecretRequest(provider="telegram", secret_key="token", channel_spec=f"file:{missing_file}")
    with pytest.raises(SecretSourceError) as excinfo:
        resolve_channel_secret(req)
    assert excinfo.value.code == "secret_source_error"
    assert str(missing_file) in (excinfo.value.details.get("path") or "")


def test_not_found_error_when_everything_missing(monkeypatch):
    monkeypatch.delenv("THOMAS_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    req = ChannelSecretRequest(provider="telegram", secret_key="token", env_var_names=("NOPE",))
    with pytest.raises(SecretNotFoundError) as excinfo:
        resolve_channel_secret(req)
    assert excinfo.value.code == "secret_not_found"


def test_invalid_request_errors():
    with pytest.raises(InvalidSecretRequestError):
        resolve_channel_secret(ChannelSecretRequest(provider="", secret_key="token"))
    with pytest.raises(InvalidSecretRequestError):
        resolve_channel_secret(ChannelSecretRequest(provider="telegram", secret_key=""))
