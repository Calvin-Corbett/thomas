from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer
from typer import Exit

from thomas.nodes.p050_nodes_token_rotate_and_revoke import (
    NodesTokenError,
    NodesTokenRotateAndRevokeResult,
    rotate_node_token,
    revoke_node_token,
)

# This Typer app is intended to be mounted under:
#   thomas nodes token ...
# and expose:
#   rotate / revoke
app = typer.Typer(help="Rotate and revoke access tokens for nodes.")

# Common aliases some loaders use.
typer_app = app
token_app = app


def _emit_result(result: NodesTokenRotateAndRevokeResult, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(result.to_dict()))
        return

    if result.action == "rotate" and result.ok:
        # Token is sensitive. Rotation is the one time plaintext exists.
        # Human output prints it so an operator can copy it onto the node.
        fp = f" (fingerprint {result.token_fingerprint})" if result.token_fingerprint else ""
        typer.echo(f"{result.node_id}: new token issued{fp}\n{result.token}")
        return

    if result.ok:
        typer.echo(f"{result.node_id}: {result.status}")
        return

    # Error in human mode.
    typer.echo(result.message or "error", err=True)


def _emit_error(err: NodesTokenError, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps({"ok": False, "error": err.to_dict()}))
        return
    typer.echo(f"Error [{err.code}]: {err.message}", err=True)


@app.command("rotate")
def rotate(
    node_id: str = typer.Argument(..., help="Node identifier"),
    state: Optional[Path] = typer.Option(
        None,
        "--state",
        help="Path to token store JSON file (defaults to ~/.thomas/nodes_tokens.json or $THOMAS_NODES_TOKENS_PATH)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output"),
) -> None:
    """Rotate a node token (revokes any active token and creates a new one)."""

    try:
        result = rotate_node_token(node_id, store_path=state)
    except NodesTokenError as e:
        _emit_error(e, json_output=json_output)
        raise Exit(code=1)

    _emit_result(result, json_output=json_output)


@app.command("revoke")
def revoke(
    node_id: str = typer.Argument(..., help="Node identifier"),
    state: Optional[Path] = typer.Option(
        None,
        "--state",
        help="Path to token store JSON file (defaults to ~/.thomas/nodes_tokens.json or $THOMAS_NODES_TOKENS_PATH)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output"),
) -> None:
    """Revoke the active node token (idempotent)."""

    try:
        result = revoke_node_token(node_id, store_path=state)
    except NodesTokenError as e:
        _emit_error(e, json_output=json_output)
        raise Exit(code=1)

    _emit_result(result, json_output=json_output)


def get_click_command():
    """Return a click.Command for loaders that prefer Click over Typer."""

    from typer.main import get_command

    return get_command(app)


# Common alias.
get_command = get_click_command


def get_typer_app():
    return app


def register(parent: Any) -> None:
    """Attach this command group to a parent CLI.

    Supports:
    - Typer apps: parent.add_typer(...)
    - Click groups: parent.add_command(...)
    """

    try:
        add_typer = getattr(parent, "add_typer", None)
        if callable(add_typer):
            parent.add_typer(app, name="token")
            return

        add_command = getattr(parent, "add_command", None)
        if callable(add_command):
            parent.add_command(get_click_command(), name="token")
            return
    except Exception:
        # Best-effort: registration should never crash an import path.
        return


def __getattr__(name: str) -> Any:
    # Extra compatibility for code that looks for conventional exports.
    if name in {"cli", "command", "click_command"}:
        return get_click_command()
    raise AttributeError(name)
