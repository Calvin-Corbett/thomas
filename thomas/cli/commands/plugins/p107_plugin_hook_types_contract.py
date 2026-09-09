from __future__ import annotations

import json
from pathlib import Path

import typer

from thomas.plugins.p107_plugin_hook_types_contract import (
    HookTypesContractError,
    HookTypesContractRequest,
    build_hook_types_contract,
    contract_json_schema,
    load_request_from_file,
)

app = typer.Typer(
    add_completion=False,
    help="Emit Thomas' plugin hook types contract (human-readable or JSON).",
)

# Common aliases used by dynamic CLI loaders.
typer_app = app
command = app
cli = app

COMMAND_NAME = "p107-plugin-hook-types-contract"


def _render_human(contract) -> str:
    lines: list[str] = []
    lines.append(f"Plugin base: {contract.plugin_base}")
    lines.append(f"Contract version: {contract.contract_version}")
    lines.append(f"Hooks: {len(contract.hooks)}")
    lines.append("")
    for hook in contract.hooks:
        params = ", ".join(f"{p.name}: {p.annotation}" + (" = ..." if p.has_default else "") for p in hook.parameters)
        async_prefix = "async " if hook.is_async else ""
        doc = f"  # {hook.doc}" if hook.doc else ""
        lines.append(f"- {async_prefix}{hook.name}({params}) -> {hook.return_annotation}{doc}")
    if contract.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in contract.warnings:
            lines.append(f"- {w}")
    return "\n".join(lines)


def _echo_json(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.callback(invoke_without_command=True)
def main(
    plugin_base: str | None = typer.Option(
        None,
        "--plugin-base",
        help="Dotted path to the plugin base class to introspect. Defaults to Thomas' built-in plugin base.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        exists=False,
        dir_okay=False,
        file_okay=True,
        readable=True,
        help="Optional JSON/TOML config file with request options.",
    ),
    include_inherited: bool = typer.Option(
        True,
        "--include-inherited/--no-include-inherited",
        help="Include inherited hook methods.",
    ),
    include_private: bool = typer.Option(False, "--include-private", help="Include '_' prefixed methods."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    schema: bool = typer.Option(False, "--schema", help="Emit a JSON Schema for the contract output."),
) -> None:
    try:
        if schema:
            schema_payload = contract_json_schema()
            _echo_json({"ok": True, "schema": schema_payload, "result": schema_payload})
            return

        if config is not None:
            req = load_request_from_file(str(config))
        else:
            req = HookTypesContractRequest()

        # CLI options override config.
        if plugin_base is not None:
            req.plugin_base = plugin_base
        req.include_inherited = include_inherited
        req.include_private = include_private

        contract = build_hook_types_contract(req)

        if json_output:
            dumped = contract.model_dump()
            _echo_json({"ok": True, "contract": dumped, "result": dumped})
        else:
            typer.echo(_render_human(contract))
    except HookTypesContractError as e:
        if json_output or schema:
            _echo_json({"ok": False, "error": e.to_dict()})
        else:
            typer.echo(f"Error[{e.code.value}]: {e}", err=True)
        raise typer.Exit(code=2)


def register(parent_app: typer.Typer) -> None:
    """Optional integration hook for CLIs that dynamically import command modules."""
    parent_app.add_typer(app, name=COMMAND_NAME)
