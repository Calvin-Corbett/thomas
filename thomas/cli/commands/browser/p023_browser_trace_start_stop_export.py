"""
CLI commands for browser tracing: start, stop, export.

This file is self-contained and relies on Typer plus the Thomas browser tracing core module.

Machine-readable output:
- `--json` prints a single JSON object on stdout.

Expected runtime context:
- A live browser/session object is expected on `ctx.obj` (typical Typer pattern).
  The tracing core is fairly flexible in how it resolves a BrowserContext from that object.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any, Dict, Optional

import typer

from thomas.browser.p023_browser_trace_start_stop_export import (
    BrowserTraceError,
    BrowserTraceErrorCode,
    BrowserTraceExportInput,
    BrowserTraceStartInput,
    DEFAULT_TRACE_REGISTRY,
)

COMMAND_NAME = "trace"

app = typer.Typer(help="Start, stop, and export browser traces (Playwright tracing).")


def _extract_target(ctx: typer.Context) -> Any:
    """Resolve the browser/session object for trace operations."""
    if ctx.obj is None:
        raise BrowserTraceError(
            BrowserTraceErrorCode.MISSING_SESSION,
            "No active browser session found. Run this command from a live browser session context.",
        )
    return ctx.obj


def _emit_success(action: str, payload: Any, json_mode: bool) -> None:
    if json_mode:
        out: Dict[str, Any] = {"ok": True, "action": action, "result": asdict(payload)}
        typer.echo(json.dumps(out, ensure_ascii=False, sort_keys=True))
        return

    # Human output: concise but informative
    trace_id = getattr(payload, "trace_id", None)
    if trace_id:
        typer.echo(f"{action}: ok (trace_id={trace_id})")
    else:
        typer.echo(f"{action}: ok")


def _emit_error(action: str, err: Exception, json_mode: bool) -> None:
    if isinstance(err, BrowserTraceError):
        error_payload = err.as_dict()
        exit_code = 1
    else:
        error_payload = {"code": "BROWSER_TRACE_UNEXPECTED_ERROR", "message": str(err)}
        exit_code = 1

    if json_mode:
        out: Dict[str, Any] = {"ok": False, "action": action, "error": error_payload}
        typer.echo(json.dumps(out, ensure_ascii=False, sort_keys=True))
        raise typer.Exit(code=exit_code)

    typer.echo(f"{action}: error: {error_payload.get('code')}: {error_payload.get('message')}", err=True)
    raise typer.Exit(code=exit_code)


@app.command("start")
def trace_start(
    ctx: typer.Context,
    screenshots: bool = typer.Option(True, help="Include screenshots in the trace."),
    snapshots: bool = typer.Option(True, help="Include DOM snapshots in the trace."),
    sources: bool = typer.Option(True, help="Include source files in the trace."),
    title: Optional[str] = typer.Option(None, help="Optional trace title shown in Trace Viewer."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Start tracing on the active browser context."""
    action = "browser_trace_start"
    try:
        target = _extract_target(ctx)
        result = DEFAULT_TRACE_REGISTRY.start(
            target,
            BrowserTraceStartInput(
                screenshots=screenshots,
                snapshots=snapshots,
                sources=sources,
                title=title,
            ),
        )
        _emit_success(action, result, json_output)
    except Exception as e:  # noqa: BLE001
        _emit_error(action, e, json_output)


@app.command("stop")
def trace_stop(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Stop tracing and persist a temporary trace file."""
    action = "browser_trace_stop"
    try:
        target = _extract_target(ctx)
        result = DEFAULT_TRACE_REGISTRY.stop(target)
        _emit_success(action, result, json_output)
    except Exception as e:  # noqa: BLE001
        _emit_error(action, e, json_output)


@app.command("export")
def trace_export(
    ctx: typer.Context,
    path: str = typer.Argument(
        ...,
        help="Destination path. If this is a directory, the file will be written as browser_trace_<trace_id>.zip inside it.",
    ),
    overwrite: bool = typer.Option(False, help="Overwrite the destination file if it exists."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Export the most recently stopped trace file to the given path."""
    action = "browser_trace_export"
    try:
        target = _extract_target(ctx)
        result = DEFAULT_TRACE_REGISTRY.export(target, BrowserTraceExportInput(path=path, overwrite=overwrite))
        _emit_success(action, result, json_output)
    except Exception as e:  # noqa: BLE001
        _emit_error(action, e, json_output)


# Optional hook for command auto-discovery systems.
def register(parent_app: typer.Typer) -> None:
    """Attach this `trace` sub-app to a parent Typer application."""
    parent_app.add_typer(app, name=COMMAND_NAME)


# Common alias names for auto-discovery / parity harnesses.
NAME = COMMAND_NAME
COMMAND = COMMAND_NAME
typer_app = app  # alias
cli_app = app  # alias


def as_click_command():
    """Return this Typer application as a Click command (for Click-only registries)."""
    return typer.main.get_command(app)
