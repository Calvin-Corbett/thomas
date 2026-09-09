"""CLI: browser error normalization.

This command is primarily for automation and debugging: it takes a raw error
blob (string or JSON) and prints the Thomas-normalized error shape.

It is intentionally conservative:

* It never raises (it always prints a normalized payload)
* It provides deterministic exit codes for missing input (2)
* It can emit machine-readable JSON (`--json`) and a minimal JSON schema (`--schema`)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import typer

from thomas.browser.p024_browser_error_normalization import (
    BrowserErrorNormalizationRequest,
    browser_error_normalization_schema,
    normalize_browser_error,
)


def _find_typer_app(module: Any) -> typer.Typer | None:
    for attr in ("app", "browser_app", "cli", "typer_app"):
        maybe = getattr(module, attr, None)
        if isinstance(maybe, typer.Typer):
            return maybe
    return None


def _resolve_browser_typer_app() -> typer.Typer | None:
    """Best-effort lookup for the existing `browser` command group."""

    mod = sys.modules.get("thomas.cli.commands.browser")
    if mod is not None:
        found = _find_typer_app(mod)
        if found is not None:
            return found

    try:
        import importlib

        browser_pkg = importlib.import_module("thomas.cli.commands.browser")
    except ImportError:
        return None

    return _find_typer_app(browser_pkg)


def _command_exists(app: typer.Typer, name: str) -> bool:
    # Typer stores registered command metadata on the Typer instance.
    for cmd in getattr(app, "registered_commands", []) or []:
        if getattr(cmd, "name", None) == name:
            return True
    return False


# Fallback app (useful for unit tests / direct module execution).
#
# NOTE: Typer can *flatten* single-command apps into a single command CLI.
# We add a no-op callback so this module behaves like a command group,
# matching the real `thomas browser ...` shape and making tests deterministic.
_app = typer.Typer(add_completion=False)


@_app.callback()
def _browser_tools_callback() -> None:
    """Browser CLI utilities."""

    return


def register_to(app: typer.Typer) -> None:
    """Register this command on the provided Typer app (idempotent)."""

    if _command_exists(app, "normalize-error"):
        return

    app.command(
        "normalize-error",
        help="Normalize a browser error into a stable JSON shape.",
    )(normalize_error)


# Some loaders prefer a generic name.
register = register_to


@_app.command("normalize-error", help="Normalize a browser error into a stable JSON shape.")
def normalize_error(
    error: str | None = typer.Argument(
        None,
        help="Raw error text, '-' to read from stdin, or a JSON object/array string containing an error.",
    ),
    operation: str | None = typer.Option(
        None,
        "--operation",
        "--op",
        help="Optional operation context (e.g., snapshot, click, navigate).",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Optional browser profile name.",
    ),
    http_status: int | None = typer.Option(
        None,
        "--http-status",
        "--status",
        help="Optional upstream HTTP status code.",
    ),
    schema: bool = typer.Option(
        False,
        "--schema",
        "--json-schema",
        help="Print the JSON schema for the output payload and exit.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON (stable keys).",
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        help="Pretty-print JSON (implies --json).",
    ),
) -> None:
    """Normalize a browser error.

    Examples:

        thomas browser normalize-error '{"error": "Failed to start CDP"}' --json
        thomas browser normalize-error "Can't reach control service" --json
        thomas browser normalize-error - --json < error.txt
    """

    if schema:
        payload = browser_error_normalization_schema()
        _emit(payload, json_output=True, pretty=pretty)
        return

    # Read from stdin when requested.
    if error == "-":
        error = sys.stdin.read()
    elif error is None:
        # Only attempt stdin if it's not an interactive TTY.
        if not sys.stdin.isatty():
            stdin_text = sys.stdin.read()
            if stdin_text.strip():
                error = stdin_text

    if error is None:
        result = normalize_browser_error(
            BrowserErrorNormalizationRequest(
                raw=None,
                operation=operation,
                profile=profile,
                http_status=http_status,
            )
        )
        _emit(result.to_dict(), json_output=json_output or pretty, pretty=pretty)
        raise typer.Exit(code=2)

    raw_obj: Any = error
    stripped = error.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            raw_obj = json.loads(error)
        except json.JSONDecodeError:
            raw_obj = error

    result = normalize_browser_error(
        BrowserErrorNormalizationRequest(
            raw=raw_obj,
            operation=operation,
            profile=profile,
            http_status=http_status,
        )
    )

    _emit(result.to_dict(), json_output=json_output or pretty, pretty=pretty)


def _emit(payload: dict, *, json_output: bool, pretty: bool) -> None:
    if json_output:
        if pretty:
            typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2))
        else:
            typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        return

    # Human-oriented output (still deterministic).
    code = payload.get("code", "unknown")
    category = payload.get("category", "unknown")
    message = payload.get("message", "")
    typer.echo(f"[{category}] {code}: {message}")
    raw = payload.get("raw")
    if isinstance(raw, str) and raw:
        typer.echo(raw)


# Attempt auto-registration with the real browser command group.
_real_browser_app = _resolve_browser_typer_app()
if _real_browser_app is not None:
    register_to(_real_browser_app)


# Export a conventional name for CLI loaders that expect `app`.
app = _app


def main(argv: Sequence[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    parser = argparse.ArgumentParser(
        prog="browser error-normalization",
        description="Normalize raw browser error payloads into a stable shape.",
    )
    parser.add_argument("error", nargs="?", default=None)
    parser.add_argument("--operation", "--op", dest="operation", default=None)
    parser.add_argument("--profile", dest="profile", default=None)
    parser.add_argument("--http-status", "--status", dest="http_status", type=int, default=None)
    parser.add_argument("--schema", "--json-schema", dest="schema", action="store_true", default=False)
    parser.add_argument("--json", dest="json_output", action="store_true", default=False)
    parser.add_argument("--pretty", dest="pretty", action="store_true", default=False)
    try:
        args = parser.parse_args(list(argv or []))
    except SystemExit as exc:
        return int(exc.code or 0)

    if bool(args.schema):
        _emit(browser_error_normalization_schema(), json_output=True, pretty=bool(args.pretty))
        return 0

    error = args.error
    if error == "-":
        error = sys.stdin.read()
    elif error is None and not sys.stdin.isatty():
        stdin_text = sys.stdin.read()
        if stdin_text.strip():
            error = stdin_text

    if error is None:
        result = normalize_browser_error(
            BrowserErrorNormalizationRequest(
                raw=None,
                operation=args.operation,
                profile=args.profile,
                http_status=args.http_status,
            )
        )
        _emit(result.to_dict(), json_output=bool(args.json_output or args.pretty), pretty=bool(args.pretty))
        return 2

    raw_obj: Any = error
    stripped = str(error).strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            raw_obj = json.loads(str(error))
        except json.JSONDecodeError:
            raw_obj = error

    result = normalize_browser_error(
        BrowserErrorNormalizationRequest(
            raw=raw_obj,
            operation=args.operation,
            profile=args.profile,
            http_status=args.http_status,
        )
    )
    _emit(result.to_dict(), json_output=bool(args.json_output or args.pretty), pretty=bool(args.pretty))
    return 0
