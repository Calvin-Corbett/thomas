from __future__ import annotations

import json
from typing import Any

import click

from thomas.plugins.p111_plugin_hook_after_tool import (
    AfterToolHookRequest,
    HookErrorInfo,
    InvalidInputError,
    ToolCompletionHookError,
    response_json_schema,
    run_after_tool_hook,
)


def _parse_json_value(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise InvalidInputError(HookErrorInfo(code="invalid_json", message="--input must be valid JSON.")) from None


def _emit_json(payload: Any) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _run(
    *,
    tool_name: str,
    tool_input_raw: str,
    config_path: str | None,
    json_out: bool,
    json_schema: bool,
) -> int:
    if json_schema:
        _emit_json(response_json_schema())
        return 0

    try:
        tool_input = _parse_json_value(tool_input_raw)
        resp = run_after_tool_hook(
            AfterToolHookRequest(tool_name=tool_name, tool_input=tool_input, config_path=config_path)
        )

        if json_out:
            _emit_json(resp.to_dict())
        else:
            click.echo(f"Tool '{tool_name}' completed. Events captured: {len(resp.events)}")
            if resp.ok:
                click.echo(f"Tool output: {resp.tool_output}")
            else:
                click.echo(f"Tool error: {resp.error.message if resp.error else 'unknown error'}", err=True)

        return 0 if resp.ok else 1

    except ToolCompletionHookError as e:
        if json_out:
            _emit_json({"ok": False, "success": False, "tool_output": None, "events": [], "error": e.info.to_dict()})
            return 1

        # ClickException prints a clean error message with exit code 1.
        raise click.ClickException(e.info.message) from None


@click.command(
    "p111-plugin-hook-after-tool",
    help="Demo command: invoke a tool and record a completion hook event.",
)
@click.option("--tool", "tool_name", default="echo", show_default=True, help="Tool name to invoke (echo/noop).")
@click.option("--input", "tool_input_raw", default="{}", show_default=True, help="Tool input as a JSON string.")
@click.option("--config", "config_path", default=None, metavar="PATH", help="Optional JSON config file.")
@click.option("--json", "json_out", is_flag=True, help="Emit machine-readable JSON output.")
@click.option("--json-schema", "json_schema", is_flag=True, help="Print the JSON schema for --json output.")
@click.pass_context
def command(
    ctx: click.Context,
    tool_name: str,
    tool_input_raw: str,
    config_path: str | None,
    json_out: bool,
    json_schema: bool,
) -> None:
    exit_code = _run(
        tool_name=tool_name,
        tool_input_raw=tool_input_raw,
        config_path=config_path,
        json_out=json_out,
        json_schema=json_schema,
    )
    ctx.exit(exit_code)


# Common discovery hooks used by various CLI loaders.
COMMAND = command


def register(group: Any) -> None:
    """Best-effort registration hook for CLI group loaders."""
    try:
        group.add_command(COMMAND)
    except (subprocess.CalledProcessError, OSError):
        return
