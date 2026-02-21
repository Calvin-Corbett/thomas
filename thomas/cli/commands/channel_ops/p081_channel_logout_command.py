from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from thomas.channels.p081_channel_logout_command import (
    ChannelLogoutError,
    ChannelLogoutRequest,
    error_to_json,
    logout_channel,
    logout_result_to_json,
)

_COMMAND_NAME = "logout"
_REGISTERED_APP_IDS: set[int] = set()


def register(app: Any) -> None:
    """Register the channel logout command with a Typer/Click app or argparse subparsers."""
    app_id = id(app)
    if app_id in _REGISTERED_APP_IDS:
        return

    typer_mod = _safe_import("typer")
    if typer_mod is not None and isinstance(app, typer_mod.Typer):
        _register_typer_command(app, typer_mod)
        _REGISTERED_APP_IDS.add(app_id)
        return

    argparse_mod = _safe_import("argparse")
    if argparse_mod is not None and hasattr(app, "add_parser"):
        _register_argparse_command(app)
        _REGISTERED_APP_IDS.add(app_id)
        return


def _register_typer_command(app: Any, typer_mod: Any) -> None:
    Argument = typer_mod.Argument
    Option = typer_mod.Option
    Exit = typer_mod.Exit

    if getattr(app, "registered_callback", None) is None:
        # Preserve group semantics when this is the only registered command.
        @app.callback(invoke_without_command=True)
        def _root() -> None:
            return

    @app.command(_COMMAND_NAME, help="Log out of a messaging channel (remove saved auth state).")
    def logout(
        channel: str = Argument(..., help="Channel identifier, e.g. telegram."),
        json_output: bool = Option(False, "--json", help="Emit machine-readable JSON."),
        config_root: Optional[Path] = Option(None, "--config-root", help="Override Thomas config directory."),
        dry_run: bool = Option(False, "--dry-run", help="Report what would be removed without changing anything."),
        hooks: bool = Option(False, "--hooks", help="Run integration cleanup hooks (best-effort)."),
        no_integration_hints: bool = Option(False, "--no-integration-hints", help="Disable integration hint discovery."),
    ) -> None:
        try:
            result = logout_channel(
                ChannelLogoutRequest(
                    channel=channel,
                    config_root=config_root,
                    dry_run=dry_run,
                    call_integration_hooks=hooks,
                    include_integration_hints=not no_integration_hints,
                )
            )
        except ChannelLogoutError as e:
            _emit_error(e, json_output=json_output)
            raise Exit(code=1) from e

        if json_output:
            sys.stdout.write(json.dumps(logout_result_to_json(result)) + "\n")
        else:
            suffix = " (dry-run)" if dry_run else ""
            sys.stdout.write(f"Logged out of '{result.channel}'{suffix}.\n")


def _register_argparse_command(subparsers: Any) -> None:
    parser = subparsers.add_parser(_COMMAND_NAME, help="Log out of a messaging channel")
    parser.add_argument("channel", help="Channel identifier, e.g. telegram.")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Emit JSON output.")
    parser.add_argument("--config-root", dest="config_root", default=None, help="Override Thomas config directory.")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Report without changing anything.")
    parser.add_argument("--hooks", dest="hooks", action="store_true", help="Run integration cleanup hooks.")
    parser.add_argument(
        "--no-integration-hints",
        dest="no_integration_hints",
        action="store_true",
        help="Disable integration hint discovery.",
    )
    parser.set_defaults(func=_handle_argparse)


def _handle_argparse(args: Any) -> int:
    try:
        result = logout_channel(
            ChannelLogoutRequest(
                channel=args.channel,
                config_root=Path(args.config_root) if getattr(args, "config_root", None) else None,
                dry_run=bool(getattr(args, "dry_run", False)),
                call_integration_hooks=bool(getattr(args, "hooks", False)),
                include_integration_hints=not bool(getattr(args, "no_integration_hints", False)),
            )
        )
    except ChannelLogoutError as e:
        _emit_error(e, json_output=bool(getattr(args, "json_output", False)))
        return 1

    if getattr(args, "json_output", False):
        sys.stdout.write(json.dumps(logout_result_to_json(result)) + "\n")
    else:
        suffix = " (dry-run)" if bool(getattr(args, "dry_run", False)) else ""
        sys.stdout.write(f"Logged out of '{result.channel}'{suffix}.\n")
    return 0


def _emit_error(error: ChannelLogoutError, *, json_output: bool) -> None:
    if json_output:
        sys.stdout.write(json.dumps(error_to_json(error)) + "\n")
        return
    sys.stderr.write(f"ERROR [{error.code}]: {error.message}\n")


def _safe_import(name: str) -> Optional[Any]:
    try:
        return __import__(name)
    except Exception:
        return None


def _auto_register_if_channels_module_loaded() -> None:
    """Register into thomas.cli.commands.channels if it's already been imported.

    This avoids importing thomas.cli.commands.channels as a side-effect (important for tests),
    while still enabling auto-wiring in typical CLI boot flows.
    """
    import sys as _sys

    mod = _sys.modules.get("thomas.cli.commands.channels")
    if mod is None:
        return

    typer_mod = _safe_import("typer")
    if typer_mod is None:
        return

    for obj in vars(mod).values():
        if isinstance(obj, typer_mod.Typer):
            register(obj)
            return


_auto_register_if_channels_module_loaded()
