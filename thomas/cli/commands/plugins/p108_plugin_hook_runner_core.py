"""CLI command for running plugin hooks.

This module is designed to integrate into the existing Thomas CLI plugin
command group. It exposes:

- a Typer `app` for direct invocation in tests
- a `register(parent_app)` helper commonly used by Thomas command discovery

It also supports `--json` for automation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from thomas.plugins.p108_plugin_hook_runner_core import (
    HookRunnerError,
    HookRunRequest,
    request_json_schema,
    response_json_schema,
    run_hook,
)

app = typer.Typer(add_completion=False, help="Run plugin hooks")


def register(parent_app: typer.Typer) -> None:
    """Register commands on an existing parent Typer app."""

    parent_app.command("run-hook")(run_hook_cli)
    parent_app.command("hook-schema")(schema_cli)


def _emit(obj: Any, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(obj, sort_keys=True))
    else:
        typer.echo(obj)


def _parse_payload(payload: str | None, payload_file: Path | None) -> dict[str, Any]:
    if payload and payload_file:
        raise HookRunnerError(
            "invalid_request",
            "Provide only one of --payload or --payload-file",
            details={"field": "payload"},
        )

    if payload_file is not None:
        try:
            raw = payload_file.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise HookRunnerError(
                "missing_config",
                "Payload file does not exist",
                details={"payload_file": str(payload_file)},
            ) from exc
        except OSError as exc:
            raise HookRunnerError(
                "invalid_request",
                "Failed to read payload file",
                details={"payload_file": str(payload_file), "reason": exc.__class__.__name__},
            ) from exc
        payload = raw

    if not payload:
        return {}

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HookRunnerError(
            "invalid_request",
            "Payload is not valid JSON",
            details={"line": exc.lineno, "col": exc.colno},
        ) from exc

    if not isinstance(parsed, dict):
        raise HookRunnerError(
            "invalid_request",
            "Payload JSON must be an object",
            details={"type": parsed.__class__.__name__},
        )

    return parsed


@app.command("run-hook")
def run_hook_cli(
    hook: str = typer.Argument(..., help="Hook name"),
    payload: str | None = typer.Option(None, "--payload", help="Hook payload JSON object"),
    payload_file: Path | None = typer.Option(None, "--payload-file", help="Read payload JSON from a file"),
    plugin: list[str] | None = typer.Option(None, "--plugin", help="Restrict run to specific plugin id(s)"),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to a JSON config containing a 'plugins' list (used when plugins are not provided by runtime)",
    ),
    strict: bool = typer.Option(True, "--strict/--no-strict", help="Error if a plugin does not implement the hook"),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--stop-on-error",
        help="Continue running hooks after a plugin error",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run a hook across plugins."""

    try:
        payload_obj = _parse_payload(payload, payload_file)
        req = HookRunRequest(
            hook=hook,
            payload=payload_obj,
            plugin_filter=tuple(plugin) if plugin else None,
            strict=strict,
            continue_on_error=continue_on_error,
            config_path=config,
        )
        resp = run_hook(req)

        if json_out:
            _emit(resp.to_dict(), as_json=True)
        else:
            ok_count = sum(1 for r in resp.results if r.status == "ok")
            err_count = sum(1 for r in resp.results if r.status == "error")
            skip_count = sum(1 for r in resp.results if r.status == "skipped")
            typer.echo(f"hook={resp.hook} ok={resp.ok} results(ok={ok_count} error={err_count} skipped={skip_count})")

        raise typer.Exit(code=0 if resp.ok else 1)
    except HookRunnerError as err:
        if json_out:
            _emit({"ok": False, "error": err.to_dict()}, as_json=True)
        else:
            typer.echo(f"ERROR[{err.code}]: {err.message}", err=True)
        raise typer.Exit(code=2)


@app.command("hook-schema")
def schema_cli(json_out: bool = typer.Option(True, "--json/--no-json", help="Emit JSON")) -> None:
    """Print request/response JSON schemas."""

    payload = {"request": request_json_schema(), "response": response_json_schema()}
    if json_out:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(payload)


def main(argv: list[str] | None = None) -> None:
    """Entry point for module execution."""

    app(prog_name="thomas plugins", args=argv or sys.argv[1:])
