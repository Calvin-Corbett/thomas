from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from thomas.nodes.p045_nodes_canvas_action import (
    CanvasActionError,
    CanvasActionInputError,
    FileCanvasStateStore,
    NodesCanvasActionRequest,
    run_nodes_canvas_action,
)


# Typer application for this command module.
#
# We include a callback so Typer generates a *group* even if this module only
# contributes a single command. That makes it safe to mount as:
# `thomas nodes canvas action ...`.
app = typer.Typer(help="Operate on the nodes canvas state.")


@app.callback()
def _canvas_group() -> None:
    """Canvas command group."""
    return


# A handful of metadata hooks that command-discovery code may look for.
# (These are intentionally simple and harmless if unused.)
CLI_PATH = ("nodes", "canvas")
CLI_GROUP = CLI_PATH
CLI_NAME = "canvas"
CLI_COMMAND = "action"

# Common aliases for different discovery styles
typer_app = app


def _resolve_json_flag(explicit: bool) -> bool:
    """Honor a higher-level `--json` flag if Thomas sets it in the Typer context."""

    if explicit:
        return True
    try:
        ctx = typer.get_current_context(silent=True)
    except Exception:  # pragma: no cover
        return explicit
    if not ctx:
        return explicit
    obj = getattr(ctx, "obj", None)
    return bool(isinstance(obj, dict) and obj.get("json") is True)



def _emit(result: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    if result.get("ok") is True:
        state = result.get("state") or {}
        viewport = state.get("viewport") or {}
        selected = state.get("selected_node_ids") or []
        typer.echo(
            f"OK canvas_id={result.get('canvas_id')} operation={result.get('operation')} "
            f"x={viewport.get('x')} y={viewport.get('y')} zoom={viewport.get('zoom')} "
            f"selected={selected}"
        )
        return

    err = result.get("error") or {}
    typer.echo(f"ERROR {err.get('code')}: {err.get('message')}")


def _error_payload(err: CanvasActionError) -> dict[str, Any]:
    return {"ok": False, "error": err.to_dict()}


def _exit_code_for(err: CanvasActionError) -> int:
    # Click/typer convention: 2 for usage/input errors.
    if isinstance(err, CanvasActionInputError):
        return 2
    return 1


@app.command("action")
def canvas_action(
    operation: str = typer.Argument(..., help="Operation: pan, zoom, select, focus, clear-selection."),
    canvas_id: str = typer.Option("default", "--canvas-id", "-c", help="Canvas identifier."),
    payload: str = typer.Option("{}", "--payload", help="JSON object payload for the operation."),
    state_path: Optional[Path] = typer.Option(
        None,
        "--state-path",
        help="Path to the persistent canvas state store JSON file.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute result but do not persist state."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Apply a nodes-canvas operation and return the updated state."""

    json_output = _resolve_json_flag(json_output)

    try:
        try:
            payload_obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError as e:
            raise CanvasActionInputError(
                "invalid_payload_json",
                f"payload must be valid JSON: {e.msg}.",
            ) from e

        store = FileCanvasStateStore(state_path) if state_path is not None else None
        req = NodesCanvasActionRequest(
            canvas_id=canvas_id,
            operation=operation,
            payload=payload_obj,
            dry_run=dry_run,
        )
        res = run_nodes_canvas_action(req, store=store)
        _emit(res.to_dict(), json_output=json_output)
        raise typer.Exit(code=0)
    except CanvasActionError as e:
        _emit(_error_payload(e), json_output=json_output)
        raise typer.Exit(code=_exit_code_for(e))


# Some parts of Thomas might prefer click.Command objects.
try:  # pragma: no cover
    import typer.main

    CLICK_COMMAND = typer.main.get_command(app)
except Exception:  # pragma: no cover
    CLICK_COMMAND = None
