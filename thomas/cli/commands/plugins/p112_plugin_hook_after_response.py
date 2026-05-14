"""CLI - P112 After-response hook.

This command is an automatable harness around the P112 after-response hook.

Example:
  python -m thomas.cli.commands.plugins.p112_plugin_hook_after_response --response "Hello" --json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from thomas.plugins.p112_plugin_hook_after_response import (
    AfterResponseHookRequest,
    config_json_schema,
    loads_json_object,
    request_json_schema,
    response_envelope_schema,
    result_json_schema,
    run_after_response_hook_enveloped,
)

app = typer.Typer(add_completion=False, help="Run the Thomas after-response hook (P112)")


def _read_text_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def _load_json_source(source_or_inline: str, *, what: str) -> dict[str, Any]:
    """Load a JSON object either from a file/stdin or inline text."""

    src = source_or_inline.strip()
    if src.startswith("{") and src.endswith("}"):
        return loads_json_object(src, what=what)
    return loads_json_object(_read_text_source(source_or_inline), what=what)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    response: str = typer.Option(
        "Hello from Thomas.",
        "--response",
        "-r",
        help="Response text to run the hook against (ignored if --request is used)",
    ),
    request: str | None = typer.Option(
        None,
        "--request",
        help="JSON request object (file path, '-' for stdin, or inline JSON)",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        help="JSON config object (file path, '-' for stdin, or inline JSON)",
    ),
    enabled: bool = typer.Option(
        False,
        "--enabled",
        help="Override config: force enabled",
    ),
    disabled: bool = typer.Option(
        False,
        "--disabled",
        help="Override config: force disabled",
    ),
    sink: str | None = typer.Option(
        None,
        "--sink",
        help="Override config: sink (none|file)",
    ),
    file_path: str | None = typer.Option(
        None,
        "--file-path",
        help="Override config: file_path (used when sink=file)",
    ),
    max_chars: int | None = typer.Option(
        None,
        "--max-chars",
        help="Override config: max_chars",
        min=1,
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    schema: str | None = typer.Option(
        None,
        "--schema",
        help="Print JSON schema: request|config|result|envelope",
    ),
) -> None:
    """Run the after-response hook (default action)."""

    if ctx.invoked_subcommand is not None:
        return
    if enabled and disabled:
        raise typer.BadParameter("--enabled and --disabled are mutually exclusive")

    if schema is not None:
        schema_key = schema.strip().lower()
        schemas = {
            "request": request_json_schema,
            "config": config_json_schema,
            "result": result_json_schema,
            "envelope": response_envelope_schema,
        }
        if schema_key not in schemas:
            raise typer.BadParameter("schema must be one of request|config|result|envelope")
        typer.echo(json.dumps(schemas[schema_key](), indent=2, sort_keys=True))
        raise typer.Exit(code=0)

    # Request
    if request is None:
        req_obj = AfterResponseHookRequest(response_text=response)
    else:
        req_obj = AfterResponseHookRequest.from_mapping(_load_json_source(request, what="request"))

    # Config
    if config is None:
        cfg_raw: dict[str, Any] = {"enabled": True, "sink": "none"}
    else:
        cfg_raw = _load_json_source(config, what="config")

    # Apply overrides deterministically (only if options provided).
    if enabled:
        cfg_raw["enabled"] = True
    if disabled:
        cfg_raw["enabled"] = False
    if sink is not None:
        cfg_raw["sink"] = sink
    if file_path is not None:
        cfg_raw["file_path"] = file_path
    if max_chars is not None:
        cfg_raw["max_chars"] = max_chars

    envelope = run_after_response_hook_enveloped(req_obj, cfg_raw)

    if as_json:
        typer.echo(json.dumps(envelope, indent=None, sort_keys=True))
        raise typer.Exit(code=0 if envelope.get("ok") else 1)

    # Human output
    if envelope.get("ok") is True:
        result = envelope["result"]
        typer.echo("After-response hook: OK")
        typer.echo(f"chars={result['char_count']} words={result['word_count']}")
        if result.get("written_to") is not None:
            typer.echo(f"written_to={result['written_to']}")
        typer.echo(f"sha256={result['sha256']}")
        return
    err = envelope.get("error") or {}
    typer.echo("After-response hook: ERROR", err=True)
    typer.echo(f"{err.get('code')}: {err.get('message')}", err=True)
    raise typer.Exit(code=1)


def register(parent_app: typer.Typer) -> None:
    """Register this command with a parent Typer app."""

    parent_app.add_typer(app, name="p112-plugin-hook-after-response")


if __name__ == "__main__":
    app()
