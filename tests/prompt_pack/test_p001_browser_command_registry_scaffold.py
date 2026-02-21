from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
import types

import pytest


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"Unable to load module spec for {path}"  # nosec B101
    mod = importlib.util.module_from_spec(spec)
    # Ensure module exists in sys.modules while executing so forward references
    # under `from __future__ import annotations` resolve reliably.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


@pytest.fixture()
def registry_mod():
    root = Path(__file__).resolve().parents[2]
    path = root / "thomas" / "browser" / "p001_browser_command_registry_scaffold.py"
    return _load_module("thomas_browser_registry_scaffold", path)


@pytest.fixture()
def cli_mod():
    root = Path(__file__).resolve().parents[2]
    path = root / "thomas" / "cli" / "commands" / "browser" / "p001_browser_command_registry_scaffold.py"
    return _load_module("thomas_cli_browser_registry_scaffold", path)


def test_registry_execute_success(registry_mod):
    registry = registry_mod.BrowserCommandRegistry(name="test", version=1)

    def handler(req, ctx):
        return {"echo": req.arguments["text"]}

    registry.register(
        registry_mod.BrowserCommandDefinition(
            name="demo.echo",
            description="Echo text",
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            output_schema={"type": "object"},
        ),
        handler=handler,
    )

    result = registry.execute({"name": "demo.echo", "arguments": {"text": "hi"}})
    assert result.ok is True
    assert result.data == {"echo": "hi"}


def test_registry_invalid_input_missing_required_field(registry_mod):
    registry = registry_mod.BrowserCommandRegistry(name="test", version=1)

    registry.register(
        registry_mod.BrowserCommandDefinition(
            name="demo.echo",
            description="Echo text",
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            output_schema={"type": "object"},
        ),
        handler=lambda req, ctx: {"echo": req.arguments.get("text")},
    )

    result = registry.execute({"name": "demo.echo", "arguments": {}})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "invalid_input"
    assert "Missing required" in result.error.message


def test_registry_unknown_command(registry_mod):
    registry = registry_mod.BrowserCommandRegistry(name="test", version=1)

    result = registry.execute({"name": "nope", "arguments": {}})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "command_not_found"


def test_registry_missing_config_error(registry_mod):
    registry = registry_mod.BrowserCommandRegistry(name="test", version=1)

    def needs_config(req, ctx):
        raise registry_mod.MissingConfigError("browser config missing")

    registry.register(
        registry_mod.BrowserCommandDefinition(
            name="demo.needs_config",
            description="Requires config",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={"type": "object"},
        ),
        handler=needs_config,
    )

    result = registry.execute(
        {"name": "demo.needs_config", "arguments": {}},
        context=registry_mod.BrowserCommandContext(config=None),
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "missing_config"


def test_registry_external_failure_wrapped(registry_mod):
    registry = registry_mod.BrowserCommandRegistry(name="test", version=1)

    def boom(req, ctx):
        raise RuntimeError("kaboom")

    registry.register(
        registry_mod.BrowserCommandDefinition(
            name="demo.boom",
            description="Throws",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={"type": "object"},
        ),
        handler=boom,
    )

    result = registry.execute({"name": "demo.boom", "arguments": {}})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "external_failure"
    assert result.error.details["exception"] == "RuntimeError"


def test_cli_json_output_smoke(cli_mod, capsys):
    parser = argparse.ArgumentParser(prog="thomas")
    sub = parser.add_subparsers(dest="cmd")
    browser = sub.add_parser("browser")
    browser_sub = browser.add_subparsers(dest="browser_cmd")
    cli_mod.register_browser_subcommand(browser_sub)

    args = parser.parse_args(["browser", "registry", "--json"])
    exit_code = args.func(args)
    assert exit_code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert "registry" in payload
    assert "commands" in payload["registry"]


def test_cli_schema_output_smoke(cli_mod, capsys):
    parser = argparse.ArgumentParser(prog="thomas")
    sub = parser.add_subparsers(dest="cmd")
    browser = sub.add_parser("browser")
    browser_sub = browser.add_subparsers(dest="browser_cmd")
    cli_mod.register_browser_subcommand(browser_sub)

    args = parser.parse_args(["browser", "registry", "--schema"])
    exit_code = args.func(args)
    assert exit_code == 0

    out = capsys.readouterr().out
    schema = json.loads(out)
    assert "output" in schema
    assert "registry" in schema


def test_discovery_from_tools_browser_mapping(registry_mod):
    """The scaffold should be able to discover commands from thomas.tools.browser."""

    keys = ["thomas", "thomas.tools", "thomas.tools.browser"]
    prev = {k: sys.modules.get(k) for k in keys}

    thomas_pkg = types.ModuleType("thomas")
    thomas_pkg.__path__ = []  # type: ignore[attr-defined]

    tools_pkg = types.ModuleType("thomas.tools")
    tools_pkg.__path__ = []  # type: ignore[attr-defined]

    browser_pkg = types.ModuleType("thomas.tools.browser")

    def navigate(url: str, browser):
        """Navigate to a URL."""
        return browser.navigate(url)

    browser_pkg.COMMANDS = {"navigate": navigate}

    sys.modules["thomas"] = thomas_pkg
    sys.modules["thomas.tools"] = tools_pkg
    sys.modules["thomas.tools.browser"] = browser_pkg
    setattr(thomas_pkg, "tools", tools_pkg)
    setattr(tools_pkg, "browser", browser_pkg)

    try:
        registry = registry_mod.build_browser_command_registry_scaffold()
        command_names = [d.name for d in registry.list_definitions()]
        assert "navigate" in command_names

        class DummyBrowser:
            def navigate(self, url: str):
                return {"did": "navigate", "url": url}

        ok_result = registry.execute(
            {"name": "navigate", "arguments": {"url": "https://example.com"}},
            context=registry_mod.BrowserCommandContext(browser=DummyBrowser()),
        )
        assert ok_result.ok is True
        assert ok_result.data == {"did": "navigate", "url": "https://example.com"}

        missing_browser = registry.execute({"name": "navigate", "arguments": {"url": "x"}})
        assert missing_browser.ok is False
        assert missing_browser.error is not None
        assert missing_browser.error.code.value == "missing_config"
    finally:
        for k, v in prev.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
