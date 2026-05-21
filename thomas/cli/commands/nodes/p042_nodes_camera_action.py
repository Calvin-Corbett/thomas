from __future__ import annotations

"""
CLI: nodes camera action (P042).

This is a thin CLI wrapper around `thomas.nodes.p042_nodes_camera_action`.

Default output is human-readable. Use `--json` for machine-readable automation.
"""

import json
from typing import Any

import typer

try:
    from thomas.marketplace.nodes.p042_nodes_camera_action import (
        NodesCameraActionError,
        NodesCameraActionRequest,
        execute_nodes_camera_action,
    )
except ImportError:  # pragma: no cover
    from thomas.nodes.p042_nodes_camera_action import (
        NodesCameraActionError,
        NodesCameraActionRequest,
        execute_nodes_camera_action,
    )


def _coerce_scalar(value: str) -> Any:
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    # int (support negatives too)
    try:
        if value.strip() == value and value not in {"", "+", "-"}:
            if value.lstrip("+-").isdigit():
                return int(value)
    except ImportError:
        pass
    # float
    try:
        if any(ch in value for ch in (".", "e", "E")):
            return float(value)
    except (ValueError, TypeError):
        pass
    return value


def _parse_kv_pairs(pairs: list[str] | None) -> dict[str, Any]:
    if not pairs:
        return {}
    out: dict[str, Any] = {}
    for raw in pairs:
        if "=" not in raw:
            raise typer.BadParameter("Parameters must be in key=value format.")
        k, v = raw.split("=", 1)
        k = k.strip()
        if not k:
            raise typer.BadParameter("Parameter key must be non-empty.")
        out[k] = _coerce_scalar(v.strip())
    return out


def _emit(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(result, sort_keys=True))
        return

    if result.get("ok") is True:
        data = result.get("data") or {}
        node_id = data.get("node_id", "")
        action = data.get("action", "")
        camera = data.get("camera", None)
        artifact = data.get("artifact", None)

        lines = [f"Node: {node_id}", f"Action: {action}"]
        if camera is not None:
            lines.append(f"Camera: {camera}")
        if artifact:
            lines.append(f"Artifact: {artifact}")
        typer.echo("\n".join(lines))
        return

    err = result.get("error") or {}
    code = err.get("code", "ERROR")
    msg = err.get("message", "Unknown error.")
    typer.echo(f"{code}: {msg}", err=True)


def _run_impl(
    node_id: str,
    action: str,
    *,
    camera: int | None,
    nodes_url: str | None,
    token: str | None,
    timeout_s: float,
    options: dict[str, Any],
    as_json: bool,
) -> None:
    try:
        req = NodesCameraActionRequest(
            node_id=node_id,
            action=action,
            camera=camera,
            options=options,
            timeout_s=timeout_s,
        )
        resp = execute_nodes_camera_action(req, base_url=nodes_url, auth_token=token)
        _emit({"ok": True, "data": resp.to_dict()}, as_json=as_json)
    except NodesCameraActionError as e:
        _emit({"ok": False, "error": e.to_dict()}, as_json=as_json)
        raise typer.Exit(code=2)


# Standalone app (useful for tests, and as a fall-back entrypoint).
app = typer.Typer(add_completion=False, help="Operate a node camera (capture/record/stream).")

# Nested "nodes camera action" shape.
camera_app = typer.Typer(add_completion=False, help="Camera operations on nodes.")


@camera_app.command("action")
def camera_action(
    node_id: str = typer.Argument(..., help="Target node identifier."),
    action: str = typer.Argument(
        ...,
        help="Camera action (capture/start_recording/stop_recording/start_stream/stop_stream).",
    ),
    camera: int | None = typer.Option(None, "--camera", min=0, help="Optional camera index."),
    param: list[str] | None = typer.Option(
        None,
        "--param",
        help="Action option(s) as key=value. Can be repeated.",
    ),
    nodes_url: str | None = typer.Option(None, "--nodes-url", help="Nodes service base URL (overrides config/env)."),
    token: str | None = typer.Option(None, "--token", help="Bearer token for nodes service (overrides env)."),
    timeout_s: float = typer.Option(10.0, "--timeout", min=0.1, help="Request timeout in seconds."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run a camera action on a node."""
    options = _parse_kv_pairs(param)
    _run_impl(
        node_id,
        action,
        camera=camera,
        nodes_url=nodes_url,
        token=token,
        timeout_s=timeout_s,
        options=options,
        as_json=json_out,
    )


# Flat "nodes camera-action" shape (alias).
@app.command("camera-action")
def camera_action_flat(
    node_id: str = typer.Argument(..., help="Target node identifier."),
    action: str = typer.Argument(
        ...,
        help="Camera action (capture/start_recording/stop_recording/start_stream/stop_stream).",
    ),
    camera: int | None = typer.Option(None, "--camera", min=0, help="Optional camera index."),
    param: list[str] | None = typer.Option(
        None,
        "--param",
        help="Action option(s) as key=value. Can be repeated.",
    ),
    nodes_url: str | None = typer.Option(None, "--nodes-url", help="Nodes service base URL (overrides config/env)."),
    token: str | None = typer.Option(None, "--token", help="Bearer token for nodes service (overrides env)."),
    timeout_s: float = typer.Option(10.0, "--timeout", min=0.1, help="Request timeout in seconds."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Alias for `camera action`."""
    options = _parse_kv_pairs(param)
    _run_impl(
        node_id,
        action,
        camera=camera,
        nodes_url=nodes_url,
        token=token,
        timeout_s=timeout_s,
        options=options,
        as_json=json_out,
    )


# Attach nested group to the standalone app.
app.add_typer(camera_app, name="camera")


def register(parent: Any) -> None:
    """
    Best-effort registration hook for the main Thomas CLI.

    Different Thomas versions may wire command modules differently. This hook
    supports Typer/click-style parents and is safe to ignore if the parent
    doesn't match.
    """
    if hasattr(parent, "add_typer") and hasattr(parent, "command"):
        try:
            parent.add_typer(camera_app, name="camera")
        except AttributeError:
            pass
        try:
            parent.command("camera-action")(camera_action_flat)  # type: ignore[attr-defined]
        except AttributeError:
            pass


def get_click_command():
    """
    Return a click.Command for frameworks/parity layers that want a single command object.
    """
    import typer.main

    return typer.main.get_command(app)


def main(argv: list[str] | None = None) -> int:
    """
    Module entrypoint (useful for parity harnesses that call a module `main`).
    """
    cmd = get_click_command()
    try:
        cmd.main(args=argv, prog_name="nodes", standalone_mode=False)
    except SystemExit as e:  # pragma: no cover
        return int(e.code or 0)
    return 0


# Common discovery hooks (different Thomas layers may look for different names)
COMMAND = get_click_command()
typer_app = app

# Parity metadata (plain data; safe even if unused)
PARITY_INFO = {
    "domain": "nodes",
    "name": "camera_action",
    "aliases": ["camera-action", "camera action"],
    "machine_output_flag": "--json",
}

__all__ = [
    "app",
    "camera_app",
    "camera_action",
    "camera_action_flat",
    "register",
    "get_click_command",
    "main",
    "COMMAND",
    "typer_app",
    "PARITY_INFO",
]
