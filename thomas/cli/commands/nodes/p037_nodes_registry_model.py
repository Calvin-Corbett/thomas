"""
CLI commands for the Nodes Registry model.

This module is intentionally self-contained so it can be imported by Thomas'
CLI wiring (parity or native) without requiring additional project context.

It exposes:
- `app`: a Typer app with `registry-model` and `registry` commands.
- `register(parent_app)`: a best-effort registration helper for projects that
  dynamically register command modules.

Registration behavior:
- If `parent_app` has an existing `nodes` group, commands are attached there.
- Otherwise, commands are attached directly to `parent_app` (useful when the
  caller is already operating inside the `nodes` group).
"""

from __future__ import annotations

import json
from typing import Any

import typer

from thomas.nodes.p037_nodes_registry_model import (
    NodesRegistryError,
    filter_nodes,
    load_nodes_registry,
)

app = typer.Typer(help="Work with the configured nodes registry.")


def _emit_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, sort_keys=True))


def _emit_text_registry(registry: Any) -> None:
    # Avoid fancy formatting to keep output stable across environments.
    nodes = getattr(registry, "nodes", [])
    for n in nodes:
        labels = ",".join(getattr(n, "labels", []) or [])
        if labels:
            typer.echo(f"{n.node_id}\t{n.endpoint}\t{labels}")
        else:
            typer.echo(f"{n.node_id}\t{n.endpoint}")


def _registry_model_impl(
    source: str | None,
    *,
    label: str | None,
    node_id: str | None,
    json_output: bool,
    timeout_s: float,
) -> None:
    try:
        registry = load_nodes_registry(source=source, timeout_s=timeout_s)
        if label or node_id:
            registry = filter_nodes(registry, label=label, node_id=node_id)

        if json_output:
            _emit_json(registry.to_response())
        else:
            _emit_text_registry(registry)
    except NodesRegistryError as e:
        if json_output:
            _emit_json(e.to_error_response())
        else:
            typer.echo(f"{e.code}: {e}", err=True)
        raise typer.Exit(code=2)


@app.command("registry-model")
def registry_model(
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Registry source (file path or https:// URL). If omitted, config/env is used.",
        show_default=False,
    ),
    label: str | None = typer.Option(None, "--label", help="Filter nodes by label.", show_default=False),
    node_id: str | None = typer.Option(None, "--id", help="Filter nodes by id.", show_default=False),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    timeout_s: float = typer.Option(5.0, "--timeout", help="URL fetch timeout in seconds."),
) -> None:
    """
    Print the nodes registry model.

    In human mode, prints one node per line:

        <id> <TAB> <endpoint> [<TAB> comma,separated,labels]

    In JSON mode, prints a structured response with schema_version.
    """
    _registry_model_impl(source, label=label, node_id=node_id, json_output=json_output, timeout_s=timeout_s)


@app.command("registry")
def registry_alias(
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Registry source (file path or https:// URL). If omitted, config/env is used.",
        show_default=False,
    ),
    label: str | None = typer.Option(None, "--label", help="Filter nodes by label.", show_default=False),
    node_id: str | None = typer.Option(None, "--id", help="Filter nodes by id.", show_default=False),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    timeout_s: float = typer.Option(5.0, "--timeout", help="URL fetch timeout in seconds."),
) -> None:
    """Alias for `registry-model`."""
    _registry_model_impl(source, label=label, node_id=node_id, json_output=json_output, timeout_s=timeout_s)


def _command_names(app_obj: Any) -> set[str]:
    names: set[str] = set()
    for ci in getattr(app_obj, "registered_commands", []) or []:
        n = getattr(ci, "name", None)
        if isinstance(n, str) and n:
            names.add(n)
    return names


def register(parent_app: Any) -> None:
    """
    Best-effort registration hook.

    Supports two common patterns:

    1) Root app passes itself; we try to attach under an existing `nodes` group.
    2) A `nodes` group app passes itself; we attach commands directly.

    The function is defensive: it will not raise if the parent is not a Typer app.
    """
    try:
        import typer as _typer  # local import to avoid hard dependency cycles
    except ImportError:
        return

    if not isinstance(parent_app, _typer.Typer):
        return

    def _register_into(target: _typer.Typer) -> None:
        existing = _command_names(target)
        if "registry-model" not in existing:
            target.command("registry-model")(registry_model)
        if "registry" not in existing:
            target.command("registry")(registry_alias)

    # Prefer attaching to an existing "nodes" group if present.
    for gi in getattr(parent_app, "registered_groups", []) or []:
        name = getattr(gi, "name", None)
        inst = getattr(gi, "typer_instance", None)
        if name in {"nodes", "node"} and isinstance(inst, _typer.Typer):
            _register_into(inst)
            return

    # Otherwise, treat the provided app as the correct target.
    _register_into(parent_app)
