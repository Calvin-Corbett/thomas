"""MCP (Model Context Protocol) server management commands."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import click

from thomas.cli.compat_browser import browser
from thomas.cli.compat_channels import message, messages
from thomas.cli.compat_core_help import agent_cmd, ensure_help_topics, help_cmd, logs_cmd
from thomas.cli.compat_memory import approvals, directory, memory, pairing, system
from thomas.cli.compat_skills import completion_cmd, plugin_cmd, qr_cmd, security, skills, update
from thomas.cli.compat_tools import acp, clawbot, daemon, dns, hooks
from thomas.cli.parity_compat_nodes import node, nodes
from thomas.cli.parity_support import (
    find_mcp_server as _find_mcp_server,
)
from thomas.cli.parity_support import (
    forward_main_cli as _forward_main_cli,
)
from thomas.cli.parity_support import (
    forward_passthrough as _forward_passthrough,
)
from thomas.cli.parity_support import (
    load_mcp_registry as _load_mcp_registry,
)

_PASSTHROUGH_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []}
from thomas.cli.parity_support import (
    load_token_store as _load_token_store,
)
from thomas.cli.parity_support import (
    mask_secret as _mask_secret,
)
from thomas.cli.parity_support import (
    mcp_registry_path as _mcp_registry_path,
)
from thomas.cli.parity_support import (
    save_mcp_registry as _save_mcp_registry,
)
from thomas.cli.parity_support import (
    save_token_store as _save_token_store,
)
from thomas.cli.parity_support import (
    token_store_path as _token_store_path,
)
from thomas.cli.parity_support import (
    utc_iso as _utc_iso,
)
from thomas.core.config import AppConfig


@click.group(name="mcp", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp(ctx: click.Context, as_json: bool) -> None:
    """Manage MCP server registry entries for compatibility workflows."""
    if ctx.invoked_subcommand is not None:
        return
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    payload = {
        "count": len(rows),
        "servers": rows,
        "state_file": str(_mcp_registry_path(config)),
        "note": "Use `mcp serve` to run the local Thomas gateway host.",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"MCP servers: {len(rows)}")
    for row in rows:
        click.echo(f"- {row.get('name')} | transport={row.get('transport')} | enabled={bool(row.get('enabled', True))}")
    click.echo(f"State file: {payload['state_file']}")


@mcp.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_list(ctx: click.Context, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    payload = {"count": len(rows), "servers": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"MCP servers: {len(rows)}")
    for row in rows:
        click.echo(f"- {row.get('name')} | transport={row.get('transport')} | enabled={bool(row.get('enabled', True))}")


@mcp.command("add")
@click.argument("name")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "http"], case_sensitive=False),
    default="stdio",
    show_default=True,
)
@click.option("--command", "command_value", default="", help="Executable for stdio transport.")
@click.option("--arg", "command_args", multiple=True, help="Repeatable arg for --command.")
@click.option("--url", default="", help="Server URL for sse/http transport.")
@click.option("--env", "env_pairs", multiple=True, help="Environment pair KEY=VALUE (repeatable).")
@click.option("--enable/--disable", default=True, show_default=True, help="Initial enabled state.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_add(
    ctx: click.Context,
    name: str,
    transport: str,
    command_value: str,
    command_args: tuple[str, ...],
    url: str,
    env_pairs: tuple[str, ...],
    enable: bool,
    as_json: bool,
) -> None:
    config: AppConfig = ctx.obj["config"]
    target = str(name or "").strip()
    if not target:
        raise click.ClickException("name is required")

    chosen_transport = str(transport or "stdio").strip().lower()
    command_text = str(command_value or "").strip()
    url_text = str(url or "").strip()
    if chosen_transport == "stdio" and not command_text and url_text:
        chosen_transport = "sse"
    if chosen_transport == "stdio" and not command_text:
        raise click.ClickException("--command is required for stdio transport.")
    if chosen_transport in {"sse", "http"} and not url_text:
        raise click.ClickException("--url is required for sse/http transport.")

    env_map: dict[str, str] = {}
    for pair in env_pairs:
        key, sep, value = str(pair).partition("=")
        if not sep or not key.strip():
            raise click.ClickException(f"Invalid --env entry: {pair!r}. Use KEY=VALUE.")
        env_map[key.strip()] = value

    rows = _load_mcp_registry(config)
    now = _utc_iso()
    row = _find_mcp_server(rows, target)
    payload_row = {
        "name": target,
        "transport": chosen_transport,
        "command": command_text,
        "args": [str(x) for x in command_args],
        "url": url_text,
        "env": env_map,
        "enabled": bool(enable),
        "updated_at": now,
    }
    if row is None:
        payload_row["created_at"] = now
        rows.append(payload_row)
        stored = payload_row
    else:
        row.update(payload_row)
        row.setdefault("created_at", now)
        stored = row
    _save_mcp_registry(config, rows)
    payload = {"ok": True, "server": stored}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"Saved MCP server: {stored.get('name')} "
        f"(transport={stored.get('transport')}, enabled={bool(stored.get('enabled', True))})"
    )


@mcp.command("get")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_get(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    row = _find_mcp_server(rows, name)
    if row is None:
        raise click.ClickException(f"MCP server not found: {name}")
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False, indent=2))
        return
    for key in ("name", "transport", "command", "args", "url", "enabled", "created_at", "updated_at"):
        click.echo(f"{key}: {row.get(key)}")


@mcp.command("remove")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_remove(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    target = str(name or "").strip().lower()
    kept = [row for row in rows if str((row or {}).get("name") or "").strip().lower() != target]
    removed = len(kept) != len(rows)
    if removed:
        _save_mcp_registry(config, kept)
    payload = {"ok": removed, "name": str(name or "").strip()}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if removed:
        click.echo(f"Removed MCP server: {name}")
    else:
        click.echo(f"MCP server not found: {name}")
        raise SystemExit(1)


@mcp.command(
    "serve",
    context_settings=_PASSTHROUGH_CONTEXT,
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def mcp_serve(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Compatibility alias for running the Thomas gateway host."""
    _forward_passthrough(ctx, ["gateway", "run"], args)


@click.command(
    name="install",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.option("--compat-json", "compat_json", is_flag=True, help="Print compatibility mapping JSON and exit.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def install_cmd(ctx: click.Context, compat_json: bool, args: tuple[Any, ...]) -> None:
    """Claude-style install alias that maps to Thomas setup/plugin/gateway installs."""
    payload = {
        "command": "install",
        "compatibility": "mapped",
        "equivalents": ["setup", "plugins install", "gateway install"],
        "note": "Use `install plugins ...` or `install gateway ...`; bare `install` runs the guided setup flow.",
    }
    if compat_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    extras = [str(x) for x in args]
    if not extras:
        _forward_passthrough(ctx, ["setup"], ())
        return

    topic = str(extras[0] or "").strip().lower()
    tail = tuple(extras[1:])
    if topic in {"plugin", "plugins"}:
        _forward_passthrough(ctx, ["plugins", "install"], tail)
        return
    if topic in {"gateway", "daemon", "service"}:
        _forward_passthrough(ctx, ["gateway", "install"], tail)
        return

    raise click.ClickException(
        "Unsupported install target. Use one of: `install`, `install plugins ...`, `install gateway ...`."
    )


@click.command(name="setup-token")
@click.option(
    "--provider",
    default="anthropic",
    show_default=True,
    type=click.Choice(["anthropic", "openai", "gateway", "openai_codex"], case_sensitive=False),
)
@click.option("--token", default="", help="Token value. If omitted, reads env or prompts securely.")
@click.option("--print-env", is_flag=True, help="Print shell snippet to set the environment variable.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def setup_token_cmd(
    ctx: click.Context,
    provider: str,
    token: str,
    print_env: bool,
    as_json: bool,
) -> None:
    """Set up provider token metadata for compatibility workflows."""
    config: AppConfig = ctx.obj["config"]
    provider_name = str(provider or "").strip().lower()
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gateway": "THOMAS_GATEWAY_API_KEY",
        "openai_codex": "OPENAI_API_KEY",
    }
    env_key = env_map[provider_name]

    resolved = str(token or os.environ.get(env_key) or "").strip()
    if not resolved:
        resolved = str(
            click.prompt(
                f"Enter token for {provider_name} ({env_key})",
                default="",
                show_default=False,
                hide_input=True,
            )
        ).strip()
    if not resolved:
        raise click.ClickException("Token is required.")

    os.environ[env_key] = resolved
    store = _load_token_store(config)
    rows = store.get("tokens")
    if not isinstance(rows, dict):
        rows = {}
    rows[provider_name] = {
        "provider": provider_name,
        "env_key": env_key,
        "token_masked": _mask_secret(resolved),
        "token_sha256": hashlib.sha256(resolved.encode("utf-8")).hexdigest(),
        "updated_at": _utc_iso(),
    }
    store["tokens"] = rows
    store["updated_at"] = _utc_iso()
    _save_token_store(config, store)

    env_command = f"$env:{env_key}='<paste-token>'" if os.name == "nt" else f"export {env_key}='<paste-token>'"
    payload = {
        "ok": True,
        "provider": provider_name,
        "env_key": env_key,
        "token_masked": _mask_secret(resolved),
        "state_file": str(_token_store_path(config)),
        "env_command": env_command if print_env else "",
        "note": (
            "OpenAI (ChatGPT) also supports browser sign-in via the in-app OAuth in Settings → Model."
            if provider_name == "openai_codex"
            else "Token is set for this process; persist in your shell profile for future sessions."
        ),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Token configured for {provider_name} ({env_key}).")
    click.echo(f"State file: {payload['state_file']}")
    if print_env:
        click.echo(f"Shell snippet: {env_command}")


def _compat_payload(name: str, equivalents: list[str], note: str) -> dict[str, Any]:
    return {
        "command": name,
        "compatibility": "partial",
        "equivalents": equivalents,
        "note": note,
    }


def _compat_command(
    name: str,
    *,
    equivalents: list[str],
    note: str,
    forward_to: list[str] | None = None,
) -> click.Command:
    if forward_to:

        @click.command(
            name=name,
            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        )
        @click.option("--compat-json", "compat_json", is_flag=True, help="Print compatibility mapping JSON and exit.")
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        @click.pass_context
        def _cmd(ctx: click.Context, compat_json: bool, args: tuple[Any, ...]) -> None:
            payload = _compat_payload(name, equivalents, note)
            if compat_json:
                click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
                return
            passthrough = list(forward_to)
            passthrough.extend(str(x) for x in args)
            rc = _forward_main_cli(ctx, passthrough)
            if rc != 0:
                raise SystemExit(rc)

        return _cmd

    @click.command(name=name)
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    def _cmd(as_json: bool) -> None:
        payload = _compat_payload(name, equivalents, note)
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        click.echo(f"{name}: partial compatibility alias")
        click.echo(f"equivalents: {', '.join(equivalents)}")
        click.echo(f"note: {note}")

    return _cmd


def _compat_aliases() -> list[click.Command]:
    specs: list[tuple[str, list[str], str, list[str] | None]] = [
        ("approvals", ["agents status"], "Guardrails approval APIs are exposed via server endpoints.", None),
        ("configure", ["config show", "doctor"], "Use config + doctor for setup and diagnostics.", ["config"]),
        ("directory", ["devices list"], "Use device records for local peer inventory.", None),
        ("docs", ["library list"], "Use library and repo docs for local documentation search.", ["library", "list"]),
        ("memory", ["library", "sessions"], "Use library/sessions; memory APIs are on server routes.", None),
        ("onboard", ["doctor", "status"], "Use doctor + status for onboarding checks.", ["doctor"]),
        ("pairing", ["devices pair"], "Use devices pair/verify/revoke.", None),
        ("reset", ["gateway restart"], "Use gateway restart + doctor for reset flows.", ["gateway", "restart"]),
        ("security", ["boot-doctor", "status"], "Use boot doctor and policy guardrails for security posture.", None),
        ("setup", ["doctor"], "Use doctor for setup validation and fixes.", ["doctor"]),
        ("skills", ["library"], "Use library and rules-of-road docs for skill guidance.", None),
        ("system", ["status", "health"], "Use status + health for system overview.", None),
        ("tui", ["repl"], "Use repl for terminal interactive workflow.", ["repl"]),
        ("uninstall", ["gateway uninstall"], "Use gateway uninstall lifecycle commands.", ["gateway", "uninstall"]),
        ("update", ["doppelganger"], "Use doppelganger blue/green commands for upgrade lifecycle.", None),
    ]
    return [
        _compat_command(name, equivalents=equiv, note=note, forward_to=forward_to)
        for name, equiv, note, forward_to in specs
    ]


def register_compat_commands(cli: click.Group) -> None:
    commands = [
        help_cmd,
        logs_cmd,
        agent_cmd,
        completion_cmd,
        browser,
        node,
        nodes,
        message,
        messages,
        qr_cmd,
        plugin_cmd,
        mcp,
        install_cmd,
        setup_token_cmd,
        acp,
        clawbot,
        daemon,
        dns,
        hooks,
        memory,
        system,
        approvals,
        directory,
        pairing,
        skills,
        security,
        update,
    ]
    commands.extend(_compat_aliases())
    for cmd in commands:
        name = str(getattr(cmd, "name", "") or "").strip()
        if not name:
            continue
        if name in cli.commands:
            continue
        cli.add_command(cmd)
    ensure_help_topics(tuple(cli.commands.keys()))
