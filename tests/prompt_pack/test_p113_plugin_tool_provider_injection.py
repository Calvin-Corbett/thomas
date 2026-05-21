import json

import pytest

from thomas.cli.commands.plugins.p113_plugin_tool_provider_injection import run_cli
from thomas.plugins.p113_plugin_tool_provider_injection import (
    ExternalFailureError,
    InvalidInputError,
    MissingConfigError,
    ToolProviderInjectionRequest,
    UnsupportedRegistryError,
    inject_tool_provider,
)


class DummyRegistry:
    def __init__(self) -> None:
        self.providers = []

    def register_tool_provider(self, provider):
        self.providers.append(provider)


class DualArgRegistry:
    def __init__(self) -> None:
        self.providers = []

    def register_tool_provider(self, provider_id, provider):
        self.providers.append((provider_id, provider))


class ExplodingRegistry:
    def register_tool_provider(self, provider):
        raise RuntimeError("boom")


class NoProviderRegistry:
    pass


def test_inject_tool_provider_success():
    reg = DummyRegistry()
    req = ToolProviderInjectionRequest(provider_id="demo.provider", tool_name="demo_echo", enabled=True)
    result = inject_tool_provider(reg, req)

    assert result.ok is True
    assert result.provider_id == "demo.provider"
    assert list(result.injected_tool_names) == ["demo_echo"]
    assert len(reg.providers) == 1

    provider = reg.providers[0]
    tools = provider.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "demo_echo"

    out = provider.call_tool("demo_echo", {"text": "hello"})
    assert out["echo"] == "hello"
    assert out["tool"] == "demo_echo"
    assert out["provider"] == "demo.provider"


def test_inject_tool_provider_success_dual_arg_registry_signature():
    reg = DualArgRegistry()
    req = ToolProviderInjectionRequest(provider_id="demo.provider", tool_name="demo_echo", enabled=True)
    result = inject_tool_provider(reg, req)

    assert result.ok is True
    assert len(reg.providers) == 1
    provider_id, provider = reg.providers[0]
    assert provider_id == "demo.provider"

    out = provider.call_tool("demo_echo", {"text": "hello"})
    assert out["echo"] == "hello"


def test_inject_tool_provider_invalid_input():
    reg = DummyRegistry()
    with pytest.raises(InvalidInputError) as excinfo:
        inject_tool_provider(reg, ToolProviderInjectionRequest(provider_id="", tool_name="x", enabled=True))
    assert excinfo.value.code == "invalid_input"


def test_inject_tool_provider_missing_config_disabled():
    reg = DummyRegistry()
    with pytest.raises(MissingConfigError) as excinfo:
        inject_tool_provider(reg, ToolProviderInjectionRequest(provider_id="x", tool_name="y", enabled=False))
    assert excinfo.value.code == "missing_config"


def test_inject_tool_provider_failure_unsupported_registry():
    with pytest.raises(UnsupportedRegistryError) as excinfo:
        inject_tool_provider(
            NoProviderRegistry(), ToolProviderInjectionRequest(provider_id="x", tool_name="y", enabled=True)
        )
    assert excinfo.value.code == "unsupported_registry"


def test_inject_tool_provider_external_failure_wrapped():
    with pytest.raises(ExternalFailureError) as excinfo:
        inject_tool_provider(
            ExplodingRegistry(), ToolProviderInjectionRequest(provider_id="x", tool_name="y", enabled=True)
        )
    assert excinfo.value.code == "external_failure"


def test_cli_json_success():
    reg = DummyRegistry()
    code, out = run_cli(provider_id="demo.provider", tool_name="demo_echo", json_output=True, registry=reg)
    assert code == 0

    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["provider_id"] == "demo.provider"
    assert payload["result"]["injected_tool_names"] == ["demo_echo"]


def test_cli_json_failure():
    code, out = run_cli(
        provider_id="demo.provider", tool_name="demo_echo", json_output=True, registry=NoProviderRegistry()
    )
    assert code == 2

    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unsupported_registry"
