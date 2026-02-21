import json
import sys
import types

import pytest

from thomas.channels.p075_channel_provider_interface_contract import (
    ERROR_INVALID_INPUT,
    ERROR_MISSING_CONFIG,
    ERROR_PROVIDER_EXTERNAL_FAILURE,
    ERROR_PROVIDER_NOT_FOUND,
    ProviderContractRequest,
    run_provider_contract,
)


def _install_module(name: str, module: types.ModuleType) -> None:
    """Install module into sys.modules, ensuring parent packages exist."""

    parts = name.split(".")
    for i in range(1, len(parts)):
        pkg_name = ".".join(parts[:i])
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg
    sys.modules[name] = module


def test_unknown_provider_returns_deterministic_error():
    resp = run_provider_contract(ProviderContractRequest(provider="definitely-not-a-real-provider", action="describe"))
    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.code == ERROR_PROVIDER_NOT_FOUND


@pytest.mark.parametrize(
    "req, expected_code",
    [
        (ProviderContractRequest(provider="dummy", action="send", config=None, recipient="x", message="hi"), ERROR_MISSING_CONFIG),
        (ProviderContractRequest(provider="dummy", action="send", config={}, recipient=None, message="hi"), ERROR_INVALID_INPUT),
        (ProviderContractRequest(provider="dummy", action="send", config={}, recipient="x", message=""), ERROR_INVALID_INPUT),
        (ProviderContractRequest(provider="dummy", action="nope"), ERROR_INVALID_INPUT),
    ],
)
def test_validation_errors(req, expected_code):
    resp = run_provider_contract(req)
    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.code == expected_code


def test_success_describe_and_send_with_module_function_provider():
    mod = types.ModuleType("thomas.integrations.dummy")

    def describe(config=None, **kwargs):
        return {"name": "Dummy Provider", "capabilities": ["send"], "required_config_keys": ["api_key"]}

    def send_message(config=None, recipient=None, message=None, **kwargs):
        assert config["api_key"] == "secret"
        assert recipient == "dest"
        assert message == "hello"
        return {"delivered": True, "message_id": "m-123"}

    mod.describe = describe
    mod.send_message = send_message
    _install_module("thomas.integrations.dummy", mod)

    resp = run_provider_contract(ProviderContractRequest(provider="dummy", action="describe"))
    assert resp.ok is True
    assert resp.result is not None
    assert resp.result["name"] == "Dummy Provider"

    resp2 = run_provider_contract(
        ProviderContractRequest(provider="dummy", action="send", config={"api_key": "secret"}, recipient="dest", message="hello")
    )
    assert resp2.ok is True
    assert resp2.result is not None
    assert resp2.result["message_id"] == "m-123"


def test_missing_required_config_keys_are_detected():
    mod = types.ModuleType("thomas.integrations.needcfg")

    def describe(config=None, **kwargs):
        return {"name": "NeedCfg", "capabilities": ["send"], "required_config_keys": ["token"]}

    def send_message(config=None, recipient=None, message=None, **kwargs):
        return {"delivered": True}

    mod.describe = describe
    mod.send_message = send_message
    _install_module("thomas.integrations.needcfg", mod)

    resp = run_provider_contract(ProviderContractRequest(provider="needcfg", action="send", config={}, recipient="x", message="hi"))
    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.code == ERROR_MISSING_CONFIG
    assert resp.error.details.get("missing_keys") == ["token"]


def test_provider_external_failure_wrapped():
    mod = types.ModuleType("thomas.integrations.flaky")

    def send_message(config=None, recipient=None, message=None, **kwargs):
        raise RuntimeError("boom")

    mod.send_message = send_message
    _install_module("thomas.integrations.flaky", mod)

    resp = run_provider_contract(
        ProviderContractRequest(provider="flaky", action="send", config={"x": 1}, recipient="dest", message="hello")
    )

    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.code == ERROR_PROVIDER_EXTERNAL_FAILURE
    assert resp.error.details.get("exception") == "RuntimeError"
    assert resp.error.details.get("message") == "boom"


def test_cli_json_output(capsys):
    from thomas.cli.commands.channel_ops.p075_channel_provider_interface_contract import run_cli

    mod = types.ModuleType("thomas.integrations.dummycli")

    def send_message(config=None, recipient=None, message=None, **kwargs):
        return {"delivered": True, "message_id": "xyz"}

    mod.send_message = send_message
    _install_module("thomas.integrations.dummycli", mod)

    exit_code = run_cli(
        [
            "dummycli",
            "--action",
            "send",
            "--recipient",
            "dest",
            "--message",
            "hello",
            "--config",
            json.dumps({"token": "t"}),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["provider"] == "dummycli"
    assert payload["action"] == "send"
    assert payload["result"]["message_id"] == "xyz"
