import json

import pytest
from click.testing import CliRunner

from thomas.cli.commands.messages.p060_message_pin_command import pin_command
from thomas.messages.p060_message_pin_command import (
    MessagePinConfig,
    MessagePinConfigError,
    MessagePinExternalError,
    MessagePinInput,
    InvalidMessagePinInput,
    load_message_pin_config,
    pin_message,
    reset_memory_pins,
)


def test_pin_message_memory_success_and_idempotent(monkeypatch):
    reset_memory_pins()

    monkeypatch.setenv("THOMAS_MESSAGES_BACKEND", "memory")
    monkeypatch.delenv("THOMAS_MESSAGES_API_URL", raising=False)

    cfg = load_message_pin_config()
    assert cfg.backend == "memory"

    result1 = pin_message(MessagePinInput(channel_id="C-P060-1", message_id="M-P060-1"), config=cfg)
    assert result1.pinned is True
    assert result1.already_pinned is False
    assert result1.backend == "memory"
    assert result1.pin_id.startswith("mempin_")

    result2 = pin_message(MessagePinInput(channel_id="C-P060-1", message_id="M-P060-1"), config=cfg)
    assert result2.pinned is True
    assert result2.already_pinned is True
    assert result2.pin_id == result1.pin_id


def test_pin_message_invalid_input_is_deterministic(monkeypatch):
    monkeypatch.setenv("THOMAS_MESSAGES_BACKEND", "memory")

    cfg = load_message_pin_config()
    with pytest.raises(InvalidMessagePinInput) as excinfo:
        pin_message(MessagePinInput(channel_id="   ", message_id="M-P060-2"), config=cfg)

    err = excinfo.value.to_dict()
    assert err["type"] == "invalid_input"
    assert err["code"] == "invalid_input"
    assert err["details"]["field"] == "channel_id"


def test_pin_message_missing_config(monkeypatch):
    # Default backend is http; without an API URL we should fail deterministically.
    monkeypatch.delenv("THOMAS_MESSAGES_BACKEND", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGES_API_URL", raising=False)

    with pytest.raises(MessagePinConfigError) as excinfo:
        pin_message(MessagePinInput(channel_id="C-P060-3", message_id="M-P060-3"))

    err = excinfo.value.to_dict()
    assert err["type"] == "config_error"
    assert err["code"] == "missing_config"
    assert "THOMAS_MESSAGES_API_URL" in err["details"].get("missing", [])


def test_pin_message_http_external_failure():
    cfg = MessagePinConfig(backend="http", api_base_url="https://example.invalid", timeout_seconds=0.1)

    def boom(*args, **kwargs):
        import requests

        raise requests.ConnectionError("nope")

    with pytest.raises(MessagePinExternalError) as excinfo:
        pin_message(MessagePinInput(channel_id="C-P060-4", message_id="M-P060-4"), config=cfg, http_post=boom)

    err = excinfo.value.to_dict()
    assert err["type"] == "external_error"
    assert err["code"] == "external_failure"
    assert err["details"]["exception"] == "ConnectionError"


def test_pin_message_http_409_conflict_is_idempotent_success():
    cfg = MessagePinConfig(backend="http", api_base_url="https://example.invalid")

    class DummyResp:
        status_code = 409
        text = "conflict"

        def json(self):
            raise ValueError("no json")

    def fake_post(*args, **kwargs):
        return DummyResp()

    result = pin_message(MessagePinInput(channel_id="C-P060-5", message_id="M-P060-5"), config=cfg, http_post=fake_post)
    assert result.pinned is True
    assert result.already_pinned is True
    assert result.backend == "http"
    assert result.pin_id.startswith("mempin_")


def test_pin_message_http_success_parses_json_fields():
    cfg = MessagePinConfig(backend="http", api_base_url="https://example.invalid")

    class DummyResp:
        status_code = 200
        text = "ok"

        def json(self):
            return {"pinned": True, "already_pinned": False, "pin_id": "PIN-XYZ"}

    def fake_post(*args, **kwargs):
        return DummyResp()

    result = pin_message(MessagePinInput(channel_id="C-P060-6", message_id="M-P060-6"), config=cfg, http_post=fake_post)
    assert result.pinned is True
    assert result.already_pinned is False
    assert result.pin_id == "PIN-XYZ"


def test_cli_messages_pin_json_success():
    runner = CliRunner()
    result = runner.invoke(
        pin_command,
        [
            "--channel-id",
            "C-P060-CLI",
            "--message-id",
            "M-P060-CLI",
            "--backend",
            "memory",
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["channel_id"] == "C-P060-CLI"
    assert payload["result"]["message_id"] == "M-P060-CLI"
    assert payload["result"]["backend"] == "memory"


def test_cli_messages_pin_json_missing_config(monkeypatch):
    # Force http backend without URL to trigger deterministic config error.
    monkeypatch.delenv("THOMAS_MESSAGES_BACKEND", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGES_API_URL", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        pin_command,
        [
            "--channel-id",
            "C-P060-CLI2",
            "--message-id",
            "M-P060-CLI2",
            "--backend",
            "http",
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "config_error"
    assert payload["error"]["code"] == "missing_config"
