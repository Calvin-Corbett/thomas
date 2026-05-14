"""
P110 - CLI parity command: plugin hook before-tool

This command exercises the P110 reference plugin that can intercept a tool call
*before* execution. It supports machine-readable JSON output for automation.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import typer

from thomas.plugins.p110_plugin_hook_before_tool import (
    BeforeToolDemoOutput,
    BeforeToolHookConfig,
    ErrorInfo,
    HookConfigError,
    P110BeforeToolHookPlugin,
    ToolCall,
    run_demo,
)


def _echo_tool(*, text: str) -> str:
    return text


def output_schema() -> dict[str, Any]:
    """A small JSON-schema-like description for automation tooling."""
    return {
        "type": "object",
        "required": ["ok", "data", "error"],
        "properties": {
            "ok": {"type": "boolean"},
            "data": {
                "type": ["object", "null"],
                "properties": {
                    "tool": {
                        "type": "object",
                        "required": ["name", "original_args", "final_args"],
                    },
                    "hook": {
                        "type": "object",
                        "required": ["action", "reason", "modified_args"],
                    },
                    "tool_executed": {"type": "boolean"},
                    "tool_result": {},
                },
            },
            "error": {
                "type": ["object", "null"],
                "properties": {
                    "code": {"type": "string"},
                    "type": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
    }


def run_p110_demo(
    *,
    mode: str = "modify",
    text: str = "hello",
    simulate_external_failure: bool = False,
) -> BeforeToolDemoOutput:
    cfg = BeforeToolHookConfig.from_mapping(
        {
            "mode": mode,
            "simulate_external_failure": simulate_external_failure,
        }
    )
    plugin = P110BeforeToolHookPlugin(config=cfg)
    call = ToolCall(name="demo.echo", args={"text": text})
    return run_demo(plugin=plugin, tool_fn=_echo_tool, call=call)


def _emit(output: BeforeToolDemoOutput, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(output.to_dict(), sort_keys=True))
        return

    if output.ok and output.data is not None:
        tool = output.data.tool
        hook = output.data.hook
        typer.echo(f"tool: {tool.name}")
        typer.echo(f"hook.action: {hook.action}")
        if hook.reason:
            typer.echo(f"hook.reason: {hook.reason}")
        typer.echo(f"original_args: {tool.original_args}")
        typer.echo(f"final_args: {tool.final_args}")
        typer.echo(f"tool_result: {output.data.tool_result}")
        return

    err = output.error
    if err is None:
        typer.echo("error: unknown failure", err=True)
    else:
        typer.echo(f"error[{err.code}]: {err.message}", err=True)


def register(app: typer.Typer) -> None:
    @app.command("p110-plugin-hook-before-tool")
    def p110_plugin_hook_before_tool(
        mode: str = typer.Option("modify", "--mode", help="allow|modify|block"),
        text: str = typer.Option("hello", "--text", help="Text passed to the demo tool"),
        simulate_external_failure: bool = typer.Option(
            False,
            "--simulate-external-failure",
            help="Simulate an external validation failure in the hook",
        ),
        as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
        json_schema: bool = typer.Option(False, "--json-schema", help="Emit output schema as JSON and exit"),
    ) -> None:
        """Demonstrate a plugin hook that runs before tool execution."""

        if json_schema:
            typer.echo(json.dumps(output_schema(), sort_keys=True))
            return

        try:
            output = run_p110_demo(
                mode=mode,
                text=text,
                simulate_external_failure=simulate_external_failure,
            )
        except HookConfigError as exc:
            output = BeforeToolDemoOutput(
                ok=False,
                data=None,
                error=ErrorInfo(code=exc.code, type=type(exc).__name__, message=str(exc)),
            )

        _emit(output, as_json=as_json)
        if not output.ok:
            raise typer.Exit(code=1)


def add_commands(app: typer.Typer) -> None:
    """Compatibility alias used by some command loaders."""
    register(app)
