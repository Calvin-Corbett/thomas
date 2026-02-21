"""Browser telemetry response body fetch (P015) - CLI wiring.

Adds a Thomas CLI browser command:

    thomas browser telemetry-response-body-fetch <request-id> [--max-bytes N] [--timeout S] [--json]

Machine-readable mode (--json) always prints a single JSON object:
- success: {"ok": true, "result": {...}}
- failure: {"ok": false, "error": {...}}

This module is designed to be discoverable by the existing Thomas CLI command
loader, but also exposes an explicit ``register(app)`` hook.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from thomas.browser.p015_browser_telemetry_response_body_fetch import (
    BrowserTelemetryResponseBodyFetchError,
    BrowserTelemetryResponseBodyFetchRequest,
    fetch_browser_telemetry_response_body,
)

__all__ = ["register", "telemetry_response_body_fetch_command"]

COMMAND_NAME = "telemetry-response-body-fetch"


def telemetry_response_body_fetch_command(
    request_id: str = typer.Argument(..., help="Telemetry request/response id."),  # noqa: B008
    max_bytes: int | None = typer.Option(
        None,
        "--max-bytes",
        help="Truncate the body to at most this many bytes.",
    ),
    timeout_s: float | None = typer.Option(
        None,
        "--timeout",
        help="Optional timeout (seconds) for backend fetch.",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    """Fetch the response body for a telemetry response."""

    try:
        req = BrowserTelemetryResponseBodyFetchRequest(
            request_id=request_id,
            max_bytes=max_bytes,
            timeout_s=timeout_s,
        )
        result = fetch_browser_telemetry_response_body(req)
    except BrowserTelemetryResponseBodyFetchError as e:
        if json_mode:
            typer.echo(json.dumps({"ok": False, "error": e.to_dict()}, ensure_ascii=False))
        else:
            typer.echo(f"[{e.code}] {e.message}", err=True)

        # Invalid input is a distinct exit code to support scripting.
        raise typer.Exit(code=2 if e.code == "invalid_input" else 1)

    if json_mode:
        typer.echo(json.dumps({"ok": True, "result": result.to_dict()}, ensure_ascii=False))
        return

    # Human mode: print text when possible; otherwise print base64.
    typer.echo(result.body_text if result.body_text is not None else result.body_base64)


def _register_on_typer_app(app: typer.Typer) -> None:
    # Make registration idempotent.
    for cmd in app.registered_commands:
        if cmd.name == COMMAND_NAME:
            return
    app.command(COMMAND_NAME)(telemetry_response_body_fetch_command)


def register(browser_app: Any) -> None:
    """Register this command on a browser Typer/Click app."""

    if isinstance(browser_app, typer.Typer):
        _register_on_typer_app(browser_app)
        return

    add_command = getattr(browser_app, "add_command", None)
    if callable(add_command):
        # Click-style group: convert a temporary Typer app to a click command and
        # add the specific subcommand when possible.
        tmp = typer.Typer()
        _register_on_typer_app(tmp)
        from typer.main import get_command

        click_obj = get_command(tmp)

        sub = None
        commands = getattr(click_obj, "commands", None)
        if isinstance(commands, dict):
            sub = commands.get(COMMAND_NAME)

        add_command(sub or click_obj)
        return

    raise TypeError(f"Unsupported CLI app type: {type(browser_app).__name__}")


# Best-effort auto-registration (works when the browser command group exposes a Typer app).
try:  # pragma: no cover
    from thomas.cli.commands import browser as browser_pkg  # type: ignore
    _maybe_app = getattr(browser_pkg, "app", None)
    if isinstance(_maybe_app, typer.Typer):
        _register_on_typer_app(_maybe_app)
except Exception:
    pass
