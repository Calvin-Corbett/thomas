"""
CLI wiring for P079 - channel remove command.

This module is intentionally small and delegates to the core implementation
in `thomas.channels.p079_channel_remove_command`.

It provides several registration helpers to maximize compatibility with the
existing Thomas CLI scaffolding:
- `register(subparsers)` (argparse-style) and common aliases.
- `run_from_parsed_args(args, runtime=None)` for dispatch-based CLIs.
- Optional Typer integration helpers (only if Typer is installed).

Supports machine-readable output mode: `--json`
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from thomas.channels.p079_channel_remove_command import (
    ChannelRemoveError,
    ChannelRemoveRequest,
    remove_channel,
)


@dataclass(frozen=True)
class ChannelRemoveCliResult:
    """
    Machine-readable envelope.

    Includes both `ok` and `success` for compatibility across scripts.
    """

    ok: bool
    success: bool
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False) + "\n"


def _runtime_log(runtime: Any, message: str) -> None:
    if runtime is not None:
        fn = getattr(runtime, "log", None) or getattr(runtime, "info", None) or getattr(runtime, "print", None)
        if callable(fn):
            fn(message)
            return
    print(message)


def _runtime_error(runtime: Any, message: str) -> None:
    if runtime is not None:
        fn = getattr(runtime, "error", None) or getattr(runtime, "err", None) or getattr(runtime, "print_error", None)
        if callable(fn):
            fn(message)
            return
    print(message, file=sys.stderr)


def run_channel_remove(
    *,
    channel: str,
    account: str | None = None,
    delete: bool = False,
    json_output: bool = False,
    runtime: Any = None,
    config_path: str | Path | None = None,
) -> int:
    """
    Execute the remove command.

    Returns a process exit code (0 on success).
    """
    try:
        req = ChannelRemoveRequest(
            channel=channel,
            account=account,
            delete=bool(delete),
            config_path=Path(config_path).expanduser() if config_path else None,
        )
        result = remove_channel(req)
    except ChannelRemoveError as e:
        payload = ChannelRemoveCliResult(ok=False, success=False, error=e.to_json_dict())
        if json_output:
            sys.stdout.write(payload.to_json())
        else:
            _runtime_error(runtime, f"{e.code.value}: {str(e)}")
        return e.exit_code
    except Exception as e:
        payload = ChannelRemoveCliResult(
            ok=False,
            success=False,
            error={"code": "UNEXPECTED", "message": str(e), "details": {}},
        )
        if json_output:
            sys.stdout.write(payload.to_json())
        else:
            _runtime_error(runtime, f"UNEXPECTED: {str(e)}")
        return 1

    payload = ChannelRemoveCliResult(ok=True, success=True, result=result.to_json_dict())
    if json_output:
        sys.stdout.write(payload.to_json())
    else:
        verb = "Deleted" if result.action == "deleted" else "Disabled"
        suffix = "" if result.changed else " (no change)"
        _runtime_log(runtime, f"{verb} channel '{result.channel}' (account: {result.account}).{suffix}")
    return 0


def run_from_parsed_args(args: Any, runtime: Any = None) -> int:
    """
    Adapter for argparse-based CLIs where `args` is a Namespace.
    """
    return run_channel_remove(
        channel=getattr(args, "channel", None) or "",
        account=getattr(args, "account", None),
        delete=bool(getattr(args, "delete", False)),
        json_output=bool(getattr(args, "json", False)),
        runtime=runtime,
        config_path=getattr(args, "config", None),
    )


def _safe_add_argument(parser: Any, *args: Any, **kwargs: Any) -> None:
    """
    Add an argparse argument if it isn't already present.

    This avoids conflicts when the Thomas CLI composes shared/parent parsers
    (e.g., a global --json flag).
    """
    option_strings = [a for a in args if isinstance(a, str) and a.startswith("-")]
    try:
        existing = getattr(parser, "_option_string_actions", {})  # argparse internal
    except (ValueError, TypeError):  # pragma: no cover
        existing = {}

    if option_strings and any(opt in existing for opt in option_strings):
        return

    parser.add_argument(*args, **kwargs)


def register(subparsers: Any) -> Any:
    """
    Register the `remove` subcommand with an argparse subparsers object.
    """
    add_parser = getattr(subparsers, "add_parser", None)
    if not callable(add_parser):
        return None

    parser = add_parser("remove", help="Disable or delete a channel account")

    # Support both:
    #   thomas channels remove telegram
    #   thomas channels remove --channel telegram
    _safe_add_argument(parser, "channel", nargs="?", help="Channel identifier (e.g., telegram)")
    _safe_add_argument(parser, "--channel", dest="channel", help="Channel identifier (e.g., telegram)")

    _safe_add_argument(parser, "--account", default=None, help="Account id (optional; default is 'default')")
    _safe_add_argument(parser, "--delete", action="store_true", help="Delete config entries instead of disabling")
    _safe_add_argument(parser, "--json", action="store_true", help="Output machine-readable JSON")
    _safe_add_argument(parser, "--config", default=None, help="Path to Thomas config file (optional)")

    # Dispatch patterns used by various internal CLIs.
    for key in ("_thomas_handler", "handler", "func", "run"):
        try:
            parser.set_defaults(**{key: run_from_parsed_args})
        except Exception:  # REVIEWED: broad catch
            pass

    return parser


# Aliases to maximize compatibility with existing registration patterns.
register_command = register
register_parser = register
register_subcommand = register
build_parser = register
add_parser = register


def get_typer_command():  # pragma: no cover
    """
    Optional Typer wiring. Returns a callable suitable for `@app.command()`.
    """
    try:
        import typer  # type: ignore
    except ImportError:
        return None

    def _cmd(
        channel: str = typer.Argument("", help="Channel identifier (e.g., telegram)"),
        account: str | None = typer.Option(None, "--account", help="Account id (optional)"),
        delete: bool = typer.Option(False, "--delete", help="Delete config entries instead of disabling"),
        json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
        config: Path | None = typer.Option(None, "--config", help="Path to Thomas config file (optional)"),
    ) -> None:
        code = run_channel_remove(
            channel=channel,
            account=account,
            delete=delete,
            json_output=json_output,
            config_path=str(config) if config else None,
        )
        raise typer.Exit(code)

    return _cmd


try:  # pragma: no cover
    import typer  # type: ignore

    typer_command = get_typer_command()
except ImportError:  # pragma: no cover
    typer_command = None


COMMAND_NAME = "remove"
COMMAND_HELP = "Disable or delete a channel account"


def get_command_name() -> str:
    return COMMAND_NAME
