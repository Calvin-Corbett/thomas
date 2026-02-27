"""Tools, daemon, and infrastructure commands."""

from __future__ import annotations

from typing import Any

import click

from thomas.cli.parity_support import (
    forward_passthrough as _forward_passthrough,
)


@click.group(name="acp")
@click.pass_context
def acp(ctx: click.Context) -> None:
    """ACP bridge compatibility workflows."""
    _ = ctx


@acp.command(
    "client",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def acp_client(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Open an interactive client flow (maps to repl/chat)."""
    extras = [str(x) for x in args]
    if extras:
        _forward_passthrough(ctx, ["chat", " ".join(extras)], ())
        return
    _forward_passthrough(ctx, ["repl"], ())


@acp.command(
    "bridge",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def acp_bridge(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Start ACP bridge compatibility mode (maps to gateway run)."""
    _forward_passthrough(ctx, ["gateway", "run"], args)


@click.group(name="clawbot")
@click.pass_context
def clawbot(ctx: click.Context) -> None:
    """Legacy clawbot compatibility commands."""
    _ = ctx


@clawbot.command(
    "chat",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def clawbot_chat(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Run clawbot chat compatibility mode (maps to chat)."""
    prompt = " ".join(str(x) for x in args).strip()
    if not prompt:
        raise click.ClickException("clawbot chat requires a prompt.")
    _forward_passthrough(ctx, ["chat", prompt], ())


@clawbot.command(
    "qr",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def clawbot_qr(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Generate pairing QR compatibility flow (maps to qr)."""
    _forward_passthrough(ctx, ["qr"], args)


@click.group(name="daemon")
@click.pass_context
def daemon(ctx: click.Context) -> None:
    """Gateway daemon lifecycle compatibility commands."""
    _ = ctx


@daemon.command("install", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_install(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "install"], args)


@daemon.command("restart", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_restart(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "restart"], args)


@daemon.command("start", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_start(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "start"], args)


@daemon.command("status", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_status(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "status"], args)


@daemon.command("stop", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_stop(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "stop"], args)


@daemon.command("uninstall", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_uninstall(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "uninstall"], args)


@daemon.command("logs", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_logs(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "logs"], args)


@click.group(name="dns")
@click.pass_context
def dns(ctx: click.Context) -> None:
    """DNS/discovery compatibility commands."""
    _ = ctx


@dns.command("setup", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def dns_setup(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "discover"], args)


@dns.command("status", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def dns_status(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "status"], args)


@click.group(name="hooks")
@click.pass_context
def hooks(ctx: click.Context) -> None:
    """Hook compatibility commands backed by plugin controls."""
    _ = ctx


@hooks.command("check", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_check(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "doctor"], args)


@hooks.command("disable", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_disable(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "disable"], args)


@hooks.command("enable", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_enable(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "enable"], args)


@hooks.command("info", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_info(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "info"], args)


@hooks.command("install", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_install(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "install"], args)


@hooks.command("list", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_list(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "list"], args)


@hooks.command("update", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_update(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "update-planner"], args)
