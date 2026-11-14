from __future__ import annotations

import importlib
import logging

import pytest

from thomas.server import tool_extensions
from thomas.tools.registry import ToolRegistry


def _registered_tool(_registry) -> None:
    return None


# Each removed module used to be offered through the same boot table on server and CLI.
_RETIRED_MODULES = (
    "channels",
    "codex",
    "intake",
    "messages",
    "nodes",
    "notify",
    "orchestrator",
    "realtime",
    "reference_cli_compat",
    "tray_agent",
    "vision",
    "webhooks",
)
_RETAINED_MODULES = ("asset_studio", "policy", "security", "paper_trading")


@pytest.mark.parametrize("module", _RETIRED_MODULES)
def test_broken_or_misleading_module_is_not_offered_at_boot(module: str) -> None:
    assert not any(path == f"thomas.{module}.tools" for path, _ in tool_extensions._OPTIONAL_TOOL_MODULES)


@pytest.mark.parametrize("module", _RETAINED_MODULES)
def test_engine_backed_module_remains_offered(module: str) -> None:
    assert any(path.endswith(f".{module}.tools") for path, _ in tool_extensions._OPTIONAL_TOOL_MODULES)


def test_every_optional_boot_module_can_import_and_register_its_tools() -> None:
    for module_path, function_name in tool_extensions._OPTIONAL_TOOL_MODULES:
        # Do not use the forgiving _try_import here: a missing module or broken
        # registration must fail this test, not silently disappear from boot.
        candidates = [module_path]
        if module_path.startswith("thomas.") and not module_path.startswith(
            ("thomas.marketplace.", "thomas.tools.", "thomas.forge.")
        ):
            candidates.append(f"thomas.marketplace.{module_path.removeprefix('thomas.')}")
        registration = None
        for candidate in candidates:
            try:
                registration = getattr(importlib.import_module(candidate), function_name)
                break
            except ModuleNotFoundError as exc:
                if exc.name != candidate:
                    raise
        assert registration is not None, module_path
        registry = ToolRegistry()
        registration(registry)
        assert registry.list_tools(), module_path
        assert all(callable(tool.execute) for tool in registry.list_tools()), module_path


def test_retired_tools_are_absent_from_boot_registry() -> None:
    registry = ToolRegistry()
    tool_extensions.register_all_optional_tools(registry)
    retired = {
        "channel_auth",
        "transaction_coordination",
        "vision_ocr",
        "vision_image_analysis",
        "nodes_create_node",
        "realtime_subscribe",
        "webhooks_list",
        "notify_send",
        "messages_list",
        "intake_get_clipboard",
        "tray_agent_get_status",
    }
    offered = {tool.name for tool in registry.list_tools()}
    assert retired.isdisjoint(offered)
    for module in _RETIRED_MODULES:
        registration = tool_extensions._try_import(f"thomas.{module}.tools", f"register_{module}_tools")
        if registration is not None:
            previously_offered = ToolRegistry()
            registration(previously_offered)
            assert {tool.name for tool in previously_offered.list_tools()}.isdisjoint(offered), module
    assert all(registry.list_tools(category) for category in _RETAINED_MODULES)


def test_retired_api_gateway_stays_out_of_optional_tools() -> None:
    fn = tool_extensions._try_import("thomas.api_gateway.tools", "register_api_gateway_tools")

    assert fn is None
    assert ("thomas.api_gateway.tools", "register_api_gateway_tools") not in tool_extensions._OPTIONAL_TOOL_MODULES


def test_register_all_optional_tools_warns_when_loaded_count_is_below_threshold(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        tool_extensions,
        "_OPTIONAL_TOOL_MODULES",
        [
            ("fake.present", "register_present_tools"),
            ("fake.missing_one", "register_missing_one_tools"),
            ("fake.missing_two", "register_missing_two_tools"),
        ],
    )
    monkeypatch.setattr(tool_extensions, "_OPTIONAL_TOOL_LOW_LOAD_WARNING_THRESHOLD", 2)
    monkeypatch.setattr(tool_extensions, "_register_self_extend", lambda _registry: None)
    monkeypatch.setattr(tool_extensions, "_register_email_calendar", lambda _registry: None)
    monkeypatch.setattr(
        tool_extensions,
        "_try_import",
        lambda _module_path, func_name: _registered_tool if func_name == "register_present_tools" else None,
    )

    with caplog.at_level(logging.WARNING, logger="thomas.server.tool_extensions"):
        count = tool_extensions.register_all_optional_tools(object())

    assert count == 1
    assert "Loaded only 1/3 optional tool modules; expected at least 2" in caplog.text


def test_register_all_optional_tools_skips_low_load_warning_at_threshold(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        tool_extensions,
        "_OPTIONAL_TOOL_MODULES",
        [
            ("fake.present_one", "register_present_one_tools"),
            ("fake.present_two", "register_present_two_tools"),
            ("fake.missing", "register_missing_tools"),
        ],
    )
    monkeypatch.setattr(tool_extensions, "_OPTIONAL_TOOL_LOW_LOAD_WARNING_THRESHOLD", 2)
    monkeypatch.setattr(tool_extensions, "_register_self_extend", lambda _registry: None)
    monkeypatch.setattr(tool_extensions, "_register_email_calendar", lambda _registry: None)
    monkeypatch.setattr(
        tool_extensions,
        "_try_import",
        lambda _module_path, func_name: _registered_tool if "present" in func_name else None,
    )

    with caplog.at_level(logging.WARNING, logger="thomas.server.tool_extensions"):
        count = tool_extensions.register_all_optional_tools(object())

    assert count == 2
    assert "Loaded only" not in caplog.text
