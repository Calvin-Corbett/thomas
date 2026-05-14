import json

import pytest
from typer.testing import CliRunner

import thomas.cli.commands.messages.p068_message_permissions_view as cli_mod
from thomas.messages.p068_message_permissions_view import (
    HttpResponse,
    MessagePermissionsViewConfig,
    MessagePermissionsViewError,
    MessagePermissionsViewRequest,
    view_message_permissions,
)

runner = CliRunner()


def test_view_message_permissions_static_success() -> None:
    cfg = MessagePermissionsViewConfig(static_permissions={"view": True, "edit": False})
    result = view_message_permissions(
        MessagePermissionsViewRequest(message_id="msg_123", user_id="user_1"),
        config=cfg,
    )

    assert result.message_id == "msg_123"
    assert result.user_id == "user_1"
    assert result.permissions == {"view": True, "edit": False}
    assert result.source == "static"


def test_view_message_permissions_invalid_input() -> None:
    cfg = MessagePermissionsViewConfig(static_permissions={"view": True})

    with pytest.raises(MessagePermissionsViewError) as excinfo:
        view_message_permissions(MessagePermissionsViewRequest(message_id="  "), config=cfg)

    assert excinfo.value.code == "invalid_input"


def test_view_message_permissions_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_MESSAGE_PERMISSIONS_VIEW_STATIC", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGE_PERMISSIONS_VIEW_TOKEN", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGE_PERMISSIONS_VIEW_TIMEOUT_S", raising=False)

    with pytest.raises(MessagePermissionsViewError) as excinfo:
        view_message_permissions(MessagePermissionsViewRequest(message_id="msg_123"))

    assert excinfo.value.code == "missing_config"


def test_view_message_permissions_remote_success() -> None:
    cfg = MessagePermissionsViewConfig(endpoint="https://example.test/permissions")

    def fake_get(url, params, headers, timeout_s):
        assert "message_id" in params
        return HttpResponse(status_code=200, text=json.dumps({"permissions": {"view": True, "delete": False}}))

    result = view_message_permissions(
        MessagePermissionsViewRequest(message_id="msg_123", user_id="user_1"),
        config=cfg,
        http_get=fake_get,
    )

    assert result.source == "remote"
    assert result.permissions == {"view": True, "delete": False}


def test_view_message_permissions_remote_non_200() -> None:
    cfg = MessagePermissionsViewConfig(endpoint="https://example.test/permissions")

    def fake_get(url, params, headers, timeout_s):
        return HttpResponse(status_code=503, text="nope")

    with pytest.raises(MessagePermissionsViewError) as excinfo:
        view_message_permissions(
            MessagePermissionsViewRequest(message_id="msg_123"),
            config=cfg,
            http_get=fake_get,
        )

    assert excinfo.value.code == "external_failure"


def test_cli_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "THOMAS_MESSAGE_PERMISSIONS_VIEW_STATIC",
        json.dumps({"view": True, "delete": False}),
    )

    result = runner.invoke(
        cli_mod.typer_app,
        [
            "view",
            "--message-id",
            "msg_123",
            "--user-id",
            "user_1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["message_id"] == "msg_123"
    assert payload["result"]["permissions"] == {"delete": False, "view": True}


def test_cli_json_failure_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_MESSAGE_PERMISSIONS_VIEW_STATIC", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT", raising=False)

    result = runner.invoke(
        cli_mod.typer_app,
        [
            "view",
            "--message-id",
            "msg_123",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
