"""Help, logs, and agent command support."""

from __future__ import annotations

from pathlib import Path

import click

from thomas.cli.parity_support import (
    forward_main_cli as _forward_main_cli,
)
from thomas.cli.parity_support import (
    gateway_log_file as _gateway_log_file,
)
from thomas.cli.parity_support import (
    load_gateway_state as _load_gateway_state,
)
from thomas.cli.parity_support import (
    tail_file as _tail_file,
)
from thomas.core.config import AppConfig


@click.group(name="help", invoke_without_command=True)
@click.pass_context
def help_cmd(ctx: click.Context) -> None:
    """Display CLI help."""
    if ctx.invoked_subcommand is not None:
        return
    root = ctx.find_root()
    click.echo(root.command.get_help(root))


_HELP_TOPICS: tuple[str, ...] = (
    "acp",
    "agent",
    "agents",
    "approvals",
    "browser",
    "channels",
    "clawbot",
    "completion",
    "config",
    "configure",
    "cron",
    "daemon",
    "dashboard",
    "devices",
    "directory",
    "dns",
    "docs",
    "doctor",
    "gateway",
    "health",
    "help",
    "hooks",
    "logs",
    "memory",
    "message",
    "models",
    "node",
    "nodes",
    "onboard",
    "pairing",
    "plugins",
    "qr",
    "reset",
    "sandbox",
    "security",
    "sessions",
    "setup",
    "skills",
    "status",
    "system",
    "tui",
    "uninstall",
    "update",
    "webhooks",
)


def _help_topic(topic: str) -> click.Command:
    @click.command(name=topic)
    @click.pass_context
    def _cmd(ctx: click.Context) -> None:
        rc = _forward_main_cli(ctx, [topic, "--help"])
        if rc != 0:
            raise SystemExit(rc)

    return _cmd


for _topic_name in _HELP_TOPICS:
    help_cmd.add_command(_help_topic(_topic_name))


@click.command(name="logs")
@click.option("--lines", default=120, show_default=True, type=int, help="Number of tail lines.")
@click.pass_context
def logs_cmd(ctx: click.Context, lines: int) -> None:
    """Tail local gateway logs."""
    config: AppConfig = ctx.obj["config"]
    state = _load_gateway_state(config)
    log_file = Path(str(state.get("log_file") or _gateway_log_file(config)))
    if not log_file.exists():
        click.echo(f"(no gateway log file at {log_file})")
        return
    click.echo(_tail_file(log_file, lines=max(1, int(lines))))


@click.command(name="agent")
@click.argument("prompt")
@click.option("-m", "--model", "model_name", default="", help="Model profile (forwards to `thomas chat`).")
@click.option("--autonomy-level", type=click.IntRange(1, 4), default=3, show_default=True)
@click.option("--token-economy", type=click.Choice(["cheap", "optimal", "max"], case_sensitive=False), default="")
@click.pass_context
def agent_cmd(
    ctx: click.Context,
    prompt: str,
    model_name: str,
    autonomy_level: int,
    token_economy: str,
) -> None:
    """Run one agent turn (compat wrapper over `thomas chat`)."""
    args = ["chat", str(prompt)]
    if str(model_name or "").strip():
        args.extend(["--model", str(model_name).strip()])
    args.extend(["--autonomy-level", str(int(autonomy_level))])
    if str(token_economy or "").strip():
        args.extend(["--token-economy", str(token_economy).strip().lower()])
    rc = _forward_main_cli(ctx, args)
    if rc != 0:
        raise SystemExit(rc)
