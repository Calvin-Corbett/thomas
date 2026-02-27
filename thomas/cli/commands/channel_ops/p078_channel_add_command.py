"""thomas.cli.commands.channel_ops.p078_channel_add_command

P078 — CLI wiring for `thomas channels add`.

This module should be loaded by the existing `channels` command group.
It exposes multiple loader hooks to maximize compatibility with different
command-discovery patterns in the Thomas codebase.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer

from thomas.channels.p078_channel_add_command import (
    ChannelAddError,
    ChannelAddRequest,
    add_channel,
)

_CONFIG_FILENAMES = (
    "config.json",
    "config.json5",
    "thomas.json",
    "thomas.json5",
    "settings.json",
)


def _resolve_config_path(ctx: typer.Context | None, explicit: str | None) -> Path:
    """Resolve config path deterministically.

    Priority:
      1) --config flag (explicit)
      2) ctx.obj (if present)
      3) env vars
      4) thomas.cli.main helpers/constants (best-effort)
      5) platform default (~/.config/thomas/config.json)
    """
    if explicit and str(explicit).strip():
        return Path(explicit)

    if ctx is not None and getattr(ctx, "obj", None):
        obj = ctx.obj
        if isinstance(obj, dict):
            for key in ("config_path", "config_file", "config", "settings_path"):
                val = obj.get(key)
                if isinstance(val, (str, os.PathLike)) and str(val).strip():
                    return Path(val)

            for key in ("home", "state_dir", "config_dir"):
                val = obj.get(key)
                if isinstance(val, (str, os.PathLike)) and str(val).strip():
                    base = Path(val)
                    for name in _CONFIG_FILENAMES:
                        cand = base / name
                        if cand.exists():
                            return cand
                    return base / "config.json"

    for env_key in ("THOMAS_CONFIG_PATH", "THOMAS_CONFIG", "THOMAS_SETTINGS"):
        env_val = os.environ.get(env_key)
        if env_val and env_val.strip():
            return Path(env_val)

    home_env = os.environ.get("THOMAS_HOME") or os.environ.get("THOMAS_STATE_DIR")
    if home_env and home_env.strip():
        base = Path(home_env)
        for name in _CONFIG_FILENAMES:
            cand = base / name
            if cand.exists():
                return cand
        return base / "config.json"

    # Best-effort: introspect thomas.cli.main for a resolver.
    try:  # pragma: no cover
        from thomas.cli import main as main_mod  # type: ignore

        for attr in ("get_config_path", "resolve_config_path", "config_path"):
            fn = getattr(main_mod, attr, None)
            if callable(fn):
                out = fn()
                if out:
                    return Path(out)
        for attr in ("CONFIG_PATH", "DEFAULT_CONFIG_PATH"):
            val = getattr(main_mod, attr, None)
            if isinstance(val, (str, os.PathLike)) and str(val).strip():
                return Path(val)
    except ImportError:
        pass

    cfg_dir = Path.home() / ".config" / "thomas"
    for name in _CONFIG_FILENAMES:
        cand = cfg_dir / name
        if cand.exists():
            return cand
    return cfg_dir / "config.json"


def _emit(payload: dict, *, json_out: bool) -> None:
    if json_out:
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    if payload.get("ok"):
        r = payload.get("result", {})
        typer.echo(f"Added channel '{r.get('channel')}' (account '{r.get('account')}') to {r.get('config_path')}")
        if r.get("verified") and r.get("verification_subject"):
            typer.echo(f"Verified: {r.get('verification_subject')}")
        return

    err = payload.get("error", {})
    typer.echo(f"Error [{err.get('code')}]: {err.get('message')}", err=True)


def channel_add_cli(
    ctx: typer.Context,
    channel: str | None = typer.Option(None, "--channel", "-c", help="Channel type to add (e.g. 'telegram')."),
    token: str | None = typer.Option(None, "--token", help="Authentication token (Telegram bot token, etc)."),
    account: str = typer.Option("default", "--account", help="Account id (for multiple accounts per channel)."),
    name: str | None = typer.Option(None, "--name", help="Optional display name for this account."),
    overwrite: bool = typer.Option(
        False, "--overwrite", "--force", help="Overwrite an existing account entry, if present."
    ),
    verify: bool = typer.Option(False, "--verify", help="Best-effort verify credentials against the external service."),
    config: str | None = typer.Option(None, "--config", help="Override config path for this command."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Add a channel account to Thomas configuration."""
    config_path = _resolve_config_path(ctx, config)

    # Non-interactive validation: keep error shape deterministic (esp. --json mode).
    if not channel:
        payload = {
            "ok": False,
            "error": {
                "code": "invalid_input",
                "message": "Missing required --channel.",
                "details": {"field": "channel"},
            },
        }
        _emit(payload, json_out=json_out)
        raise typer.Exit(code=2)

    if not token:
        payload = {
            "ok": False,
            "error": {
                "code": "invalid_input",
                "message": "Missing required --token.",
                "details": {"field": "token"},
            },
        }
        _emit(payload, json_out=json_out)
        raise typer.Exit(code=2)

    req = ChannelAddRequest(
        channel=channel,
        token=token,
        account=account,
        name=name,
        config_path=config_path,
        overwrite=overwrite,
        verify=verify,
    )

    try:
        result = add_channel(req)
    except ChannelAddError as e:
        payload = {"ok": False, "error": e.to_dict()}
        _emit(payload, json_out=json_out)
        raise typer.Exit(code=1)
    else:
        d = result.to_dict()
        payload = {"ok": True, "result": d}
        _emit(payload, json_out=json_out)


def register(app: Any) -> None:
    """Registration hook for channels command group."""
    if isinstance(app, typer.Typer) and getattr(app, "registered_callback", None) is None:
        # Keep this app in group mode so tests can invoke `add ...` as a subcommand.
        @app.callback(invoke_without_command=True)
        def _root() -> None:
            return

    try:
        app.command("add")(channel_add_cli)
    except (ValueError, TypeError):
        pass


# Loader compatibility hooks
add_to_app = register
COMMAND_NAME = "add"
COMMAND_HELP = "Add a channel account to config."


def get_command() -> Any:
    """Optional loader hook returning a click.Command."""
    return COMMAND


_COMMAND_APP = typer.Typer(rich_markup_mode=None, add_completion=False)
_COMMAND_APP.command("add")(channel_add_cli)
try:  # pragma: no cover
    from typer.main import get_command as _typer_get_command

    COMMAND = _typer_get_command(_COMMAND_APP)
except ImportError:  # pragma: no cover
    COMMAND = None  # type: ignore[assignment]
