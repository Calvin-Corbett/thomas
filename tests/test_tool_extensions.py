from __future__ import annotations

import logging

from thomas.server import tool_extensions


def _registered_tool(_registry) -> None:
    return None


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
