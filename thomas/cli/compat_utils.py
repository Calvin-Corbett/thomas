"""Utility and bootstrap commands."""

from __future__ import annotations

from pathlib import Path

import click

from thomas.core.config import load_config


@click.group(name="app")
@click.option("-c", "--config", "config_path", type=click.Path(exists=False), default="")
@click.pass_context
def app(ctx: click.Context, config_path: str) -> None:
    """
    Standalone parity app used by integration tests and automation wrappers.
    """
    path = Path(config_path).expanduser() if str(config_path or "").strip() else None
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(path)
    ctx.obj["config_path"] = str(path) if path is not None else ""


# Register compat commands on the app group (imported lazily to avoid circular imports)
def _lazy_register_compat_commands() -> None:
    from thomas.cli.compat_mcp import register_compat_commands

    register_compat_commands(app)


# Note: actual registration happens in the main CLI setup, not here
