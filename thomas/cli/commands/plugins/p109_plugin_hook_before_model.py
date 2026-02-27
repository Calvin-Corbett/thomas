"""CLI parity command for P109: before-model hook.

This is a small, automation-friendly wrapper to run the hook.

Machine-readable mode:
  - --json prints a single JSON object (success or failure)
  - `schema --json` prints the JSON schema for request/config/result

This module exposes:
  - a Typer app (`app`) for loaders that use Typer subcommands
  - `register(parent_app)` as a permissive fallback
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from thomas.plugins.p109_plugin_hook_before_model import BeforeModelError, hook_json_schema, run_json

app = typer.Typer(add_completion=False, help="Run the P109 before-model hook.")


def _read_text_source(value: str | None) -> str | None:
    """Read JSON text from:

    - None => None
    - '@-' => stdin
    - '@path' => file contents
    - otherwise => value
    """

    if value is None:
        return None

    s = value.strip()
    if not s:
        return None

    if s.startswith("@"):
        target = s[1:]
        if target == "-":
            return sys.stdin.read()
        return Path(target).read_text(encoding="utf-8")

    return s


def _coerce_json_object(text: str | None, *, kind: str) -> dict[str, Any] | None:
    if text is None:
        return None

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise BeforeModelError(
            code="INVALID_INPUT" if kind == "request" else "INVALID_CONFIG",
            message=f"Provided {kind} JSON is invalid.",
            details={"error": str(e)},
        )

    if not isinstance(obj, dict):
        raise BeforeModelError(
            code="INVALID_INPUT" if kind == "request" else "INVALID_CONFIG",
            message=f"Provided {kind} must be a JSON object.",
            details={"type": type(obj).__name__},
        )

    return obj


@app.command("run")
def run(
    request: str | None = typer.Option(
        None,
        "--request",
        help="Request JSON (or @file / @- for stdin). Must include {messages:[...]}",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        help="Hook config JSON (or @file / @-). Expects {inject_system: ...}",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run the before-model hook once."""

    request_text = _read_text_source(request)
    # If request isn't provided, allow stdin (common in pipelines).
    if request_text is None and not sys.stdin.isatty():
        request_text = sys.stdin.read()

    req_obj = _coerce_json_object(request_text, kind="request") if request_text else None
    cfg_obj = _coerce_json_object(_read_text_source(config), kind="config") if config else None

    # Keep the command runnable without args.
    if req_obj is None:
        req_obj = {"messages": [{"role": "user", "content": "Hello"}]}

    out_text = run_json(
        json.dumps(req_obj),
        config_json=json.dumps(cfg_obj) if cfg_obj is not None else None,
    )

    if json_output:
        typer.echo(out_text)
        try:
            payload = json.loads(out_text)
            if isinstance(payload, dict) and payload.get("ok") is False:
                raise typer.Exit(code=2)
        except typer.Exit:
            raise
        except json.JSONDecodeError:
            raise typer.Exit(code=2)
        return

    # Human output
    try:
        payload = json.loads(out_text)
    except json.JSONDecodeError:
        typer.echo(out_text)
        return

    if payload.get("ok") is True:
        res = payload.get("result", {})
        typer.echo("OK")
        typer.echo(f"applied={res.get('applied')}")
        msgs = res.get("messages", [])
        typer.echo(f"messages={len(msgs) if isinstance(msgs, list) else '??'}")
        return

    err = payload.get("error", {})
    typer.echo(f"ERROR {err.get('code')}: {err.get('message')}", err=True)
    raise typer.Exit(code=2)


@app.command("schema")
def schema(json_output: bool = typer.Option(True, "--json", help="Emit schema JSON.")) -> None:
    """Print the JSON schema for this hook."""

    sch = hook_json_schema()
    if json_output:
        typer.echo(json.dumps(sch, sort_keys=True))
    else:
        typer.echo(json.dumps(sch, indent=2, sort_keys=True))


def register(parent_app: Any) -> None:
    """Best-effort registration for CLI loaders."""

    try:
        parent_app.add_typer(app, name="p109-before-model")
    except json.JSONDecodeError:
        return


# Extra discovery aliases for differing CLI loaders.
APP = app
typer_app = app
cli = app
