"""Executable OpenClaw-compatible alias commands for Thomas CLI.

This is a facade module that imports and re-exports compat commands from
specialized submodules to keep individual files under the 800-line limit.
"""

from __future__ import annotations

from typing import Any

import click

from thomas.cli.parity_compat_nodes import node, nodes
from thomas.cli.parity_support import (
    utc_iso as _utc_iso,
)

try:
    from thomas.cli.parity_support import (
        compat_not_implemented_payload as _compat_not_implemented_payload,
    )
except (ImportError, ModuleNotFoundError):

    def _compat_not_implemented_payload(
        domain: str,
        action: str,
        *,
        message: str,
        hint: str = "",
        target: str = "",
        mode: str = "run",
    ) -> dict[str, Any]:
        domain_text = str(domain or "").strip() or "compat"
        action_text = str(action or "").strip()
        mode_text = str(mode or "run").strip() or "run"
        payload = {
            "ok": False,
            "command": domain_text,
            "action": action_text,
            "mode": mode_text,
            "executed": False,
            "timestamp_utc": _utc_iso(),
            "error": {
                "category": "not_implemented",
                "code": f"{domain_text}_operation_not_implemented",
                "message": str(message or "").strip() or "Operation not implemented.",
            },
        }
        hint_text = str(hint or "").strip()
        if hint_text:
            payload["error"]["hint"] = hint_text
        target_text = str(target or "").strip()
        if target_text:
            payload["target"] = target_text
        return payload


# Import all command groups and utilities from compat submodules
from thomas.cli.compat_browser import browser
from thomas.cli.compat_channels import message, messages
from thomas.cli.compat_core_help import agent_cmd, help_cmd, logs_cmd
from thomas.cli.compat_mcp import mcp
from thomas.cli.compat_memory import memory
from thomas.cli.compat_skills import completion_cmd, plugin_cmd, qr_cmd, skills
from thomas.cli.compat_tools import acp, clawbot, daemon, dns, hooks
from thomas.cli.compat_utils import app

# Import helper functions that may be referenced elsewhere
# These functions are typically registered dynamically
try:
    from thomas.cli.compat_tools import _compat_aliases, _compat_command, _compat_payload, register_compat_commands
except (ImportError, ModuleNotFoundError):

    def _compat_payload(name: str, equivalents: list[str], note: str) -> dict[str, Any]:
        return {"name": name, "equivalents": equivalents, "note": note}

    def _compat_command(name: str, equivalents: list[str], note: str) -> click.Command:
        @click.command(name=name)
        def _cmd() -> None:
            click.echo(f"compat: {note}")

        return _cmd

    def _compat_aliases() -> list[click.Command]:
        return []

    def register_compat_commands(cli: click.Group) -> None:
        pass


__all__ = [
    "node",
    "nodes",
    "help_cmd",
    "logs_cmd",
    "agent_cmd",
    "browser",
    "message",
    "messages",
    "acp",
    "clawbot",
    "daemon",
    "dns",
    "hooks",
    "memory",
    "skills",
    "completion_cmd",
    "qr_cmd",
    "plugin_cmd",
    "mcp",
    "app",
    "register_compat_commands",
    "_compat_payload",
    "_compat_command",
    "_compat_aliases",
    "_compat_not_implemented_payload",
]
