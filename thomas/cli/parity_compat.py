"""Executable Reference CLI-compatible alias commands for Thomas CLI.

This is a facade module that imports and re-exports compat commands from
specialized submodules to keep individual files under the 800-line limit.
"""

from __future__ import annotations

import importlib
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
import thomas.cli.compat_memory as _compat_memory_module
from thomas.cli.compat_browser import browser
from thomas.cli.compat_channels import message, messages
from thomas.cli.compat_core_help import agent_cmd, help_cmd, logs_cmd
from thomas.cli.compat_mcp import mcp
from thomas.cli.compat_memory import memory
from thomas.cli.compat_skills import completion_cmd, plugin_cmd, qr_cmd, skills
from thomas.cli.compat_tools import acp, clawbot, daemon, dns, hooks
from thomas.cli.compat_utils import app


def _resolve_memory_backend(
    action: str,
    *,
    module_name: str,
    symbol: str,
    target: str = "",
) -> tuple[Any | None, dict[str, Any] | None]:
    """Compatibility bridge for tests monkeypatching parity_compat internals."""
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = str(getattr(exc, "name", "") or "").strip()
        if missing == module_name:
            return None, _compat_memory_module._memory_unimplemented_payload(action, target=target)
        return None, _compat_memory_module._memory_runtime_error_payload(
            action,
            f"{type(exc).__name__}: {exc}",
            target=target,
        )
    except ImportError as exc:
        return None, _compat_memory_module._memory_runtime_error_payload(
            action,
            f"{type(exc).__name__}: {exc}",
            target=target,
        )
    except Exception as exc:
        return None, _compat_memory_module._memory_runtime_error_payload(
            action,
            f"{type(exc).__name__}: {exc}",
            target=target,
        )

    impl = getattr(module, symbol, None)
    if not callable(impl):
        return None, _compat_memory_module._memory_runtime_error_payload(
            action,
            f"AttributeError: {module_name}.{symbol} is not callable",
            target=target,
        )
    return impl, None


def _resolve_memory_backend_dispatch(
    action: str,
    *,
    module_name: str,
    symbol: str,
    target: str = "",
) -> tuple[Any | None, dict[str, Any] | None]:
    return _resolve_memory_backend(
        action,
        module_name=module_name,
        symbol=symbol,
        target=target,
    )


# Route compat-memory backend resolution through this module so monkeypatches
# on `thomas.cli.parity_compat` are observed by memory operation tests.
_compat_memory_module._resolve_memory_backend = _resolve_memory_backend_dispatch

# Import helper functions that may be referenced elsewhere
# These functions are typically registered dynamically
try:
    from thomas.cli.compat_mcp import _compat_aliases, _compat_command, _compat_payload, register_compat_commands
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
        commands = [
            help_cmd,
            logs_cmd,
            agent_cmd,
            browser,
            message,
            messages,
            acp,
            clawbot,
            daemon,
            dns,
            hooks,
            memory,
            skills,
            completion_cmd,
            qr_cmd,
            plugin_cmd,
            mcp,
            app,
            node,
            nodes,
        ]
        for cmd in commands:
            if not isinstance(cmd, click.Command):
                continue
            name = str(getattr(cmd, "name", "") or "").strip()
            if not name or name in cli.commands:
                continue
            cli.add_command(cmd)

        for alias in _compat_aliases():
            if not isinstance(alias, click.Command):
                continue
            name = str(getattr(alias, "name", "") or "").strip()
            if not name or name in cli.commands:
                continue
            cli.add_command(alias)


try:
    if isinstance(app, click.Group):
        register_compat_commands(app)
except Exception:
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
