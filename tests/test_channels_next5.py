from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from click.testing import CliRunner

from thomas.channels.p080_channel_login_command import ChannelLoginRequest, channel_login
from thomas.cli.commands.channels import app as channels_app
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


def test_channels_cli_test_validates_matrix_local_shape(tmp_path: Path) -> None:
    runner = CliRunner()
    fake_config = _fake_config(tmp_path)

    configure = runner.invoke(
        channels_app,
        [
            "configure",
            "--name",
            "matrix",
            "--token",
            "matrix-token",
            "--webhook",
            "https://matrix.example.test",
            "--target",
            "!room:example.test",
            "--json",
        ],
        obj={"config": fake_config},
    )
    assert configure.exit_code == 0, configure.output

    result = runner.invoke(channels_app, ["test", "--name", "matrix", "--json"], obj={"config": fake_config})
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert any(check["check"] == "matrix_homeserver" and check["ok"] for check in payload["checks"])


def test_provider_contract_send_supports_next_five(monkeypatch) -> None:
    def fake_urlopen(req, timeout):
        url = getattr(req, "full_url", "")
        method = getattr(req, "method", "GET")
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host == "chat.googleapis.com":
            return _FakeHTTPResponse({"name": "spaces/AAAA/messages/1"})
        if host == "outlook.office.com":
            return _FakeHTTPResponse({"id": "teams-1"})
        if method == "PUT" and parsed.path.startswith("/_matrix/client/v3/rooms/"):
            return _FakeHTTPResponse({"event_id": "$event-1"})
        if host == "signal.example.test":
            return _FakeHTTPResponse({"message_id": "signal-1"})
        if host == "imessage.example.test":
            return _FakeHTTPResponse({"message_id": "imsg-1"})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cases = [
        (
            "googlechat",
            {"webhook": "https://chat.googleapis.com/v1/spaces/AAAA/messages?key=x&token=y"},
            "thread-1",
            "spaces/AAAA/messages/1",
        ),
        (
            "msteams",
            {"webhook": "https://outlook.office.com/webhook/T/B/C"},
            "conversation-1",
            "teams-1",
        ),
        (
            "matrix",
            {"homeserver": "https://matrix.example.test", "token": "matrix-token"},
            "!room:example.test",
            "$event-1",
        ),
        (
            "signal",
            {"http_url": "https://signal.example.test/send", "target": "+15551234567"},
            "+15551234567",
            "signal-1",
        ),
        (
            "imessage",
            {"relay_url": "https://imessage.example.test/send", "target": "chat:+15557654321"},
            "chat:+15557654321",
            "imsg-1",
        ),
    ]

    for provider, config, recipient, expected_message_id in cases:
        response = run_provider_contract(
            ProviderContractRequest(
                provider=provider,
                action="send",
                config=config,
                recipient=recipient,
                message=f"hello from {provider}",
            )
        )
        assert response.ok is True, provider
        assert response.result is not None
        assert response.result["message_id"] == expected_message_id


def test_channel_login_supports_next_five_modules() -> None:
    for channel_name in ("googlechat", "msteams", "matrix", "signal", "imessage"):
        result = channel_login(ChannelLoginRequest(channel=channel_name))
        assert result.ok is True, channel_name
