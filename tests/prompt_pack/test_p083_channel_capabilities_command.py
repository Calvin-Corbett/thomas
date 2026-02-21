import json
import sys
import types

import pytest

from thomas.channels.p083_channel_capabilities_command import (
    ChannelCapabilitiesCommandError,
    ChannelCapabilitiesRequest,
    get_channel_capabilities,
    output_json_schema,
)


def _install_dummy_integration(monkeypatch, *, module_name: str, capabilities_fn=None):
    dummy = types.ModuleType(module_name)

    def send_message(*args, **kwargs):  # pragma: no cover
        return None

    def send_photo(*args, **kwargs):  # pragma: no cover
        return None

    def delete_message(*args, **kwargs):  # pragma: no cover
        return None

    dummy.send_message = send_message
    dummy.send_photo = send_photo
    dummy.delete_message = delete_message

    if capabilities_fn is not None:
        dummy.get_capabilities = capabilities_fn

    monkeypatch.setitem(sys.modules, module_name, dummy)
    return dummy


def test_capabilities_success_derives_from_integration(monkeypatch):
    _install_dummy_integration(monkeypatch, module_name="thomas.integrations.telegram")
    config = {"channels": {"alerts": {"integration": "telegram"}}}

    result = get_channel_capabilities(ChannelCapabilitiesRequest(channel="alerts"), config=config)

    assert result.channel == "alerts"
    assert result.integration == "telegram"
    assert result.capabilities["send_text"] is True
    assert result.capabilities["send_image"] is True
    assert result.capabilities["delete_message"] is True


def test_capabilities_unknown_channel_is_deterministic(monkeypatch):
    _install_dummy_integration(monkeypatch, module_name="thomas.integrations.telegram")
    config = {"channels": {"alerts": {"integration": "telegram"}}}

    with pytest.raises(ChannelCapabilitiesCommandError) as exc:
        get_channel_capabilities(ChannelCapabilitiesRequest(channel="missing"), config=config)

    assert exc.value.code == "unknown_channel"


def test_capabilities_missing_config_is_deterministic():
    with pytest.raises(ChannelCapabilitiesCommandError) as exc:
        get_channel_capabilities(ChannelCapabilitiesRequest(channel="alerts"), config=None)

    assert exc.value.code == "missing_config"


def test_capabilities_external_failure_is_deterministic(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("nope")

    _install_dummy_integration(monkeypatch, module_name="thomas.integrations.telegram", capabilities_fn=boom)
    config = {"channels": {"alerts": {"integration": "telegram"}}}

    with pytest.raises(ChannelCapabilitiesCommandError) as exc:
        get_channel_capabilities(ChannelCapabilitiesRequest(channel="alerts"), config=config)

    assert exc.value.code == "external_failure"


def test_output_json_schema_has_required_fields():
    schema = output_json_schema()
    assert schema["type"] == "object"
    for k in ["ok", "schema_version", "channel", "integration", "capabilities"]:
        assert k in schema["required"]


def test_cli_json_success_and_error(monkeypatch, capsys):
    from thomas.cli.commands.channel_ops import p083_channel_capabilities_command as cli

    _install_dummy_integration(monkeypatch, module_name="thomas.integrations.telegram")
    config = {"channels": {"alerts": {"integration": "telegram"}}}

    class Args:
        channel = "alerts"
        json = True
        thomas_config = config

    rc = cli.run(Args(), config=None)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["channel"] == "alerts"

    class BadArgs:
        channel = "missing"
        json = True
        thomas_config = config

    rc2 = cli.run(BadArgs(), config=None)
    assert rc2 == 2
    payload2 = json.loads(capsys.readouterr().out.strip())
    assert payload2["ok"] is False
    assert payload2["error"]["code"] == "unknown_channel"
