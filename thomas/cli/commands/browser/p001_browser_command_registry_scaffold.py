"""CLI wiring for the browser command registry scaffold.

This module adds a *read-only* CLI subcommand that prints the browser command
registry in human-readable form by default, and machine-readable JSON with
``--json``.

It is designed to plug into Thomas' argparse-based CLI wiring. To maximize
compatibility with different loader styles, this module exposes multiple
registration hooks:

- ``register_browser_subcommand(subparsers)``
- ``register(subparsers)``
- ``add_parser(subparsers)``
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Prefer the Thomas-native registry implementation, but include a fallback that
# still works when this module is loaded directly from a file path (as some
# tests do) without the package import path configured.
try:
    from thomas.browser.p001_browser_command_registry_scaffold import (
        BrowserRegistryError,
        build_browser_command_registry_scaffold,
    )
except ImportError:  # pragma: no cover
    _core_path = Path(__file__).resolve().parents[3] / "browser" / "p001_browser_command_registry_scaffold.py"
    _spec = importlib.util.spec_from_file_location("thomas_browser_registry_scaffold_fallback", _core_path)
    if _spec is None or _spec.loader is None:
        raise
    import sys

    _core_mod = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _core_mod
    _spec.loader.exec_module(_core_mod)  # type: ignore[attr-defined]

    BrowserRegistryError = _core_mod.BrowserRegistryError
    build_browser_command_registry_scaffold = _core_mod.build_browser_command_registry_scaffold


@dataclass(frozen=True, slots=True)
class BrowserRegistryCliOutput:
    """Output contract for JSON mode."""

    ok: bool
    registry: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            out["registry"] = self.registry or {}
        else:
            out["error"] = self.error or {"code": "external_failure", "message": "Unknown error"}
        return out


def _print_human(registry_dict: dict[str, Any]) -> None:
    print(f"{registry_dict.get('name', 'thomas.browser')} v{registry_dict.get('version', '?')}")
    commands = registry_dict.get("commands") or []
    if not commands:
        print("(no commands registered)")
        return
    for cmd in commands:
        name = cmd.get("name", "?")
        desc = (cmd.get("description") or "").strip()
        if desc:
            print(f"- {name}: {desc}")
        else:
            print(f"- {name}")


def _cli_output_schema() -> dict[str, Any]:
    """JSON schema for BrowserRegistryCliOutput.to_dict()."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "registry": {"type": "object"},
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                },
            },
        },
    }


def run_browser_registry_command(args: argparse.Namespace) -> int:
    """Entry point for the `thomas browser registry` subcommand.

    Returns a process exit code.
    """
    try:
        registry = build_browser_command_registry_scaffold()

        if getattr(args, "schema", False):
            schema = {
                "output": _cli_output_schema(),
                "registry": registry.output_schema(),
            }
            print(json.dumps(schema, indent=2, sort_keys=True))
            return 0

        registry_dict = registry.to_registry_dict()
        if getattr(args, "json", False):
            payload = BrowserRegistryCliOutput(ok=True, registry=registry_dict)
            print(json.dumps(payload.to_dict(), indent=2, sort_keys=True))
        else:
            _print_human(registry_dict)
        return 0
    except BrowserRegistryError as exc:  # type: ignore[misc]
        payload = BrowserRegistryCliOutput(
            ok=False,
            error=getattr(exc, "payload", None).to_dict()
            if hasattr(exc, "payload")
            else {"code": "external_failure", "message": str(exc)},
        )
        if getattr(args, "json", False) or getattr(args, "schema", False):
            print(json.dumps(payload.to_dict(), indent=2, sort_keys=True))
        else:
            print(f"Error: {payload.to_dict()['error']['message']}")
        return 1
    except Exception as exc:  # pragma: no cover
        payload = BrowserRegistryCliOutput(
            ok=False,
            error={
                "code": "external_failure",
                "message": "Unexpected failure",
                "details": {"exception": type(exc).__name__},
            },
        )
        if getattr(args, "json", False) or getattr(args, "schema", False):
            print(json.dumps(payload.to_dict(), indent=2, sort_keys=True))
        else:
            print("Error: Unexpected failure")
        return 1


def register_browser_subcommand(browser_subparsers: Any) -> argparse.ArgumentParser:
    """Register the `registry` subcommand under an existing `browser` parser."""
    parser = browser_subparsers.add_parser(
        "registry",
        aliases=["commands"],
        help="Print the browser command registry",
        description="Describe available browser commands and their schemas.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    parser.add_argument("--schema", action="store_true", help="Emit JSON schema for --json output")
    parser.set_defaults(func=run_browser_registry_command)
    return parser


# Compatibility aliases: different parts of the CLI may look for different hooks.
register = register_browser_subcommand
add_parser = register_browser_subcommand


def main(argv: Sequence[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    parser = argparse.ArgumentParser(
        prog="browser command-registry-scaffold",
        description="Print browser command registry metadata.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    parser.add_argument("--schema", action="store_true", help="Emit output JSON schema")
    try:
        args = parser.parse_args(list(argv or []))
    except SystemExit as exc:
        return int(exc.code or 0)
    return int(run_browser_registry_command(args))
