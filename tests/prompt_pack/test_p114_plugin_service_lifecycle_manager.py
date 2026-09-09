from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from typer.testing import CliRunner

from thomas.cli.commands.plugins.p114_plugin_service_lifecycle_manager import app as cli_app
from thomas.plugins.p114_plugin_service_lifecycle_manager import (
    SERVICE_LIFECYCLE_TOOL_NAME,
    ExternalFailureError,
    InvalidInputError,
    LifecycleAction,
    MissingConfigError,
    PluginServiceLifecycleManager,
    PluginServiceLifecycleManagerPlugin,
    ServiceDefinition,
    ServiceLifecycleRequest,
    ServiceState,
    apply_lifecycle_request,
    parse_lifecycle_request,
)


@pytest.mark.asyncio
async def test_manager_start_stop_success_and_ordering() -> None:
    events: list[str] = []

    async def start_a() -> None:
        events.append("start:a")

    async def stop_a() -> None:
        events.append("stop:a")

    async def start_b() -> None:
        events.append("start:b")

    async def stop_b() -> None:
        events.append("stop:b")

    mgr = PluginServiceLifecycleManager(
        services=[
            ServiceDefinition(service_id="b", start=lambda: start_b(), stop=lambda: stop_b()),
            ServiceDefinition(service_id="a", start=lambda: start_a(), stop=lambda: stop_a()),
        ]
    )

    # start_all should be deterministic: sorted service_ids
    await mgr.start_all()
    assert events == ["start:a", "start:b"]
    assert mgr.status("a").state == ServiceState.RUNNING
    assert mgr.status("b").state == ServiceState.RUNNING

    events.clear()
    await mgr.stop_all()
    # stop_all should be deterministic: reverse sorted order
    assert events == ["stop:b", "stop:a"]
    assert mgr.status("a").state == ServiceState.STOPPED
    assert mgr.status("b").state == ServiceState.STOPPED


@pytest.mark.asyncio
async def test_manager_invalid_input_unknown_service() -> None:
    mgr = PluginServiceLifecycleManager(
        services=[ServiceDefinition(service_id="a", start=lambda: None, stop=lambda: None)]
    )
    with pytest.raises(InvalidInputError) as ei:
        await mgr.start("nope")
    assert ei.value.code == "invalid_input"
    assert "Unknown service id" in str(ei.value)


@pytest.mark.asyncio
async def test_manager_missing_config_no_services_registered() -> None:
    mgr = PluginServiceLifecycleManager()
    with pytest.raises(MissingConfigError) as ei:
        await mgr.start_all()
    assert ei.value.code == "missing_config"


@pytest.mark.asyncio
async def test_manager_external_failure_start_raises_deterministic_error() -> None:
    def boom() -> None:
        raise RuntimeError("nope")

    mgr = PluginServiceLifecycleManager(services=[ServiceDefinition(service_id="a", start=boom, stop=lambda: None)])

    with pytest.raises(ExternalFailureError) as ei:
        await mgr.start("a")

    assert ei.value.code == "external_failure"
    assert ei.value.details["service_id"] == "a"
    # The stored last_error is deterministic (exception type only)
    assert mgr.status("a").state == ServiceState.FAILED
    assert mgr.status("a").last_error == "RuntimeError"


@pytest.mark.asyncio
async def test_apply_lifecycle_request_json_contract() -> None:
    events: list[str] = []

    async def start_a() -> None:
        events.append("start")

    mgr = PluginServiceLifecycleManager(
        services=[ServiceDefinition(service_id="a", start=lambda: start_a(), stop=lambda: None)]
    )

    resp = await apply_lifecycle_request(mgr, ServiceLifecycleRequest(action=LifecycleAction.START, service_id="a"))
    payload = resp.to_dict()
    assert payload["ok"] is True
    assert payload["services"][0]["service_id"] == "a"
    assert payload["services"][0]["state"] == "running"


def test_parse_request_rejects_invalid_payloads() -> None:
    with pytest.raises(InvalidInputError):
        parse_lifecycle_request({})
    with pytest.raises(InvalidInputError):
        parse_lifecycle_request({"action": "nope"})
    with pytest.raises(InvalidInputError):
        parse_lifecycle_request({"action": "start", "timeout_s": -1})


@pytest.mark.asyncio
async def test_status_requires_service_id_in_apply() -> None:
    mgr = PluginServiceLifecycleManager(
        services=[ServiceDefinition(service_id="a", start=lambda: None, stop=lambda: None)]
    )
    resp = await apply_lifecycle_request(mgr, ServiceLifecycleRequest(action=LifecycleAction.STATUS))
    payload = resp.to_dict()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"


def test_plugin_register_tools_duck_typing() -> None:
    plugin = PluginServiceLifecycleManagerPlugin()

    class FakeRegistry:
        def __init__(self) -> None:
            self.registered: dict[str, Any] = {}

        def register_tool(self, name: str, tool: Any) -> None:
            self.registered[name] = tool

    reg = FakeRegistry()
    plugin.register_tools(reg)

    assert SERVICE_LIFECYCLE_TOOL_NAME in reg.registered
    tool = reg.registered[SERVICE_LIFECYCLE_TOOL_NAME]
    assert "input_schema" in tool and "output_schema" in tool


def test_cli_json_success_and_failure_and_apply() -> None:
    runner = CliRunner()

    async def start_a() -> None:
        return None

    mgr = PluginServiceLifecycleManager(
        services=[ServiceDefinition(service_id="a", start=lambda: start_a(), stop=lambda: None)]
    )

    @dataclass
    class CtxObj:
        plugin_service_manager: Any

    # status should list all
    result = runner.invoke(cli_app, ["status", "--json"], obj=CtxObj(plugin_service_manager=mgr))
    assert result.exit_code == 0
    out = json.loads(result.stdout.strip())
    assert out["ok"] is True
    assert any(s["service_id"] == "a" for s in out["services"])

    # apply should accept a JSON request
    req = json.dumps({"action": "start", "service_id": "a"})
    result_apply = runner.invoke(cli_app, ["apply", "--request", req, "--json"], obj=CtxObj(plugin_service_manager=mgr))
    assert result_apply.exit_code == 0
    out_apply = json.loads(result_apply.stdout.strip())
    assert out_apply["ok"] is True
    assert out_apply["services"][0]["state"] == "running"

    # Failure path: missing ctx.obj manager
    result2 = runner.invoke(cli_app, ["status", "--json"])
    assert result2.exit_code != 0
    out2 = json.loads(result2.stdout.strip())
    assert out2["ok"] is False
    assert out2["error"]["code"] == "missing_config"
