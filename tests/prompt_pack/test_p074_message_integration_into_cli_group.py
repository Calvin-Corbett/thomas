from __future__ import annotations

import json
import uuid

import httpx
from typer.testing import CliRunner

import thomas.messages.p074_message_integration_into_cli_group as msg_mod
from thomas.cli.parity_compat import app


def test_messages_send_json_success(monkeypatch: object) -> None:
    seen: dict = {}

    def fake_default_post(url: str, payload: dict, *, timeout_seconds: float) -> httpx.Response:
        seen["url"] = url
        seen["payload"] = payload
        seen["timeout"] = timeout_seconds
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(msg_mod, "_default_post_json", fake_default_post)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["messages", "send", "hello", "--channel", "general", "--meta", "a=1", "--json"],
        env={"THOMAS_MESSAGE_WEBHOOK_URL": "https://example.test/webhook"},
    )
    assert result.exit_code == 0

    # ensure the outbound request is correct
    assert seen["url"] == "https://example.test/webhook"
    assert seen["timeout"] == 5.0
    assert seen["payload"]["channel"] == "general"
    assert seen["payload"]["text"] == "hello"
    assert seen["payload"]["metadata"] == {"a": "1"}
    uuid.UUID(seen["payload"]["id"])

    payload = json.loads(result.stdout)
    assert payload["ok"] is True

    out = payload["result"]
    uuid.UUID(out["message_id"])  # raises if invalid
    assert out["channel"] == "general"
    assert out["text"] == "hello"
    assert out["provider"] == "webhook"
    assert out["response_status"] == 200
    assert isinstance(out["delivered_at"], str) and out["delivered_at"]


def test_messages_send_json_missing_config() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["messages", "send", "hi", "--channel", "general", "--json"], env={})

    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"


def test_messages_send_json_invalid_input_empty_text() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["messages", "send", "", "--channel", "general", "--json"],
        env={"THOMAS_MESSAGE_WEBHOOK_URL": "https://example.test/webhook"},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"


def test_messages_send_json_invalid_meta() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["messages", "send", "hi", "--channel", "general", "--meta", "nope", "--json"],
        env={"THOMAS_MESSAGE_WEBHOOK_URL": "https://example.test/webhook"},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"


def test_messages_send_json_external_failure(monkeypatch: object) -> None:
    def fake_default_post(url: str, payload: dict, *, timeout_seconds: float) -> httpx.Response:
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(msg_mod, "_default_post_json", fake_default_post)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["messages", "send", "hello", "--channel", "general", "--json"],
        env={"THOMAS_MESSAGE_WEBHOOK_URL": "https://example.test/webhook"},
    )

    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "delivery_failed"
    assert payload["error"]["details"]["status_code"] == 500
