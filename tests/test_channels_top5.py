from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from thomas.channels.p080_channel_login_command import ChannelLoginRequest, channel_login
from thomas.cli.commands.channels import app as channels_app
from thomas.marketplace.channels._registry import get_registry
from thomas.marketplace.channels.p075_channel_provider_interface_contract import (
    ProviderContractRequest,
    run_provider_contract,
)


class _FakeHTTPResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _fake_config(root: Path) -> SimpleNamespace:
    return SimpleNamespace(memory=SimpleNamespace(root_path=root))


def test_marketplace_registry_lists_top_five_channels() -> None:
    channels = get_registry().list_channels()
    for name in (
        "discord",
        "googlechat",
        "imessage",
        "matrix",
        "msteams",
        "signal",
        "slack",
        "telegram",
        "webchat",
        "whatsapp",
    ):
        assert name in channels


def test_channels_cli_list_and_configure_surfaces_top_five(tmp_path: Path) -> None:
    runner = CliRunner()
    fake_config = _fake_config(tmp_path)

    result = runner.invoke(channels_app, ["list", "--json"], obj={"config": fake_config})
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [row["name"] for row in payload["channels"]] == [
        "discord",
        "telegram",
        "webchat",
        "whatsapp",
        "slack",
        "googlechat",
        "msteams",
        "matrix",
        "signal",
        "imessage",
    ]

    result = runner.invoke(
        channels_app,
        ["configure", "--name", "telegram", "--token", "123:ABC", "--target", "42", "--json"],
        obj={"config": fake_config},
    )
    assert result.exit_code == 0, result.output
    configured = json.loads(result.output)
    assert configured["configured"] is True
    assert configured["target_set"] is True

    result = runner.invoke(channels_app, ["status", "--json"], obj={"config": fake_config})
    status_payload = json.loads(result.output)
    telegram_row = next(row for row in status_payload["details"] if row["name"] == "telegram")
    assert telegram_row["configured"] is True


def test_channels_cli_test_validates_whatsapp_local_shape(tmp_path: Path) -> None:
    runner = CliRunner()
    fake_config = _fake_config(tmp_path)

    configure = runner.invoke(
        channels_app,
        ["configure", "--name", "whatsapp", "--token", "wa-token", "--target", "123456789", "--json"],
        obj={"config": fake_config},
    )
    assert configure.exit_code == 0, configure.output

    result = runner.invoke(channels_app, ["test", "--name", "whatsapp", "--json"], obj={"config": fake_config})
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert any(check["check"] == "whatsapp_phone_number_id" and check["ok"] for check in payload["checks"])


def test_provider_contract_send_supports_top_five(monkeypatch) -> None:
    def fake_urlopen(req, timeout):
        url = getattr(req, "full_url", "")
        if "api.telegram.org" in url:
            return _FakeHTTPResponse({"ok": True, "result": {"message_id": 101, "id": 7}})
        if "discord.com" in url:
            return _FakeHTTPResponse({"id": "discord-1"})
        if "graph.facebook.com" in url:
            return _FakeHTTPResponse({"messages": [{"id": "wamid-1"}]})
        if "webchat.example.test" in url:
            return _FakeHTTPResponse({"message_id": "webchat-1"})
        if "hooks.slack.com" in url:
            return _FakeHTTPResponse("ok")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cases = [
        ("discord", {"webhook": "https://discord.com/api/webhooks/1/abc"}, "discord-1"),
        ("telegram", {"token": "123:ABC", "chat_id": "42"}, "101"),
        ("webchat", {"webhook_url": "https://webchat.example.test/hook"}, "webchat-1"),
        ("whatsapp", {"token": "wa-token", "target": "123456789"}, "wamid-1"),
        ("slack", {"webhook": "https://hooks.slack.com/services/T/B/C"}, "webhook-delivered"),
    ]

    for provider, config, expected_message_id in cases:
        response = run_provider_contract(
            ProviderContractRequest(
                provider=provider,
                action="send",
                config=config,
                recipient="dest-1",
                message=f"hello from {provider}",
            )
        )
        assert response.ok is True, provider
        assert response.result is not None
        assert response.result["message_id"] == expected_message_id


def test_channel_login_supports_new_top_five_modules() -> None:
    for channel_name in ("discord", "telegram", "webchat", "whatsapp", "slack"):
        result = channel_login(ChannelLoginRequest(channel=channel_name))
        assert result.ok is True, channel_name
