"""
P044 - CLI command: nodes location get

Wires the Nodes Location action into the Thomas CLI.

This module is intentionally conservative about the surrounding CLI framework.
It provides:
- `app`: a Typer sub-app (preferred integration style)
- `register(nodes_app)`: helper to attach the sub-app under `nodes location`
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

import typer

from thomas.nodes.p044_nodes_location_action import (
    NodesLocationActionError,
    NodesLocationActionInput,
    NodesLocationActionOutput,
    handle_nodes_location_request,
)

app = typer.Typer(add_completion=False, help="Fetch and display node location information.")


def _run(coro: Any) -> Any:
    """Run an async coroutine from a synchronous Typer command.

    We intentionally fail deterministically if called from an already-running event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("CLI command cannot run inside an active event loop")


def _call_with_accepted_kwargs(fn: Any, kwargs: dict[str, Any]) -> Any:
    """Call `fn` with only kwargs it accepts (best-effort)."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**kwargs)

    accepted: dict[str, Any] = {}
    for name in sig.parameters.keys():
        if name in kwargs and kwargs[name] is not None:
            accepted[name] = kwargs[name]
    return fn(**accepted)


def _resolve_invoker(ctx: typer.Context) -> Any:
    """Discover a node invoker/client from Typer/Click context.

    Common pattern: the root CLI stores shared objects in `ctx.obj`.
    """
    obj = getattr(ctx, "obj", None)
    if isinstance(obj, dict):
        for key in ("invoker", "node_invoker", "gateway", "client", "rpc", "api"):
            if obj.get(key) is not None:
                return obj[key]

        gateway_url = obj.get("gateway_url") or obj.get("url") or obj.get("base_url")
        token = obj.get("token") or obj.get("auth_token") or obj.get("bearer_token")
        timeout_ms = obj.get("timeout_ms") or obj.get("timeout") or obj.get("invoke_timeout_ms")
    else:
        gateway_url = None
        token = None
        timeout_ms = None

    # Best-effort: try to build a client from parity_compat if present in the codebase.
    try:
        from thomas.cli import parity_compat  # type: ignore
    except ImportError:
        return None

    for fn_name in (
        "get_node_invoker",
        "get_gateway_client",
        "get_client",
        "build_gateway_client",
        "create_gateway_client",
        "gateway_client",
    ):
        fn = getattr(parity_compat, fn_name, None)
        if fn is None:
            continue
        try:
            return _call_with_accepted_kwargs(
                fn,
                {
                    "ctx": ctx,
                    "context": ctx,
                    "gateway_url": gateway_url,
                    "url": gateway_url,
                    "base_url": gateway_url,
                    "token": token,
                    "auth_token": token,
                    "timeout_ms": timeout_ms,
                    "timeout": timeout_ms,
                },
            )
        except AttributeError:
            continue

    return None


def _print_result(result: NodesLocationActionOutput, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps({"ok": True, "result": result.to_dict()}, sort_keys=True))
        return

    parts = [f"{result.lat:.6f},{result.lon:.6f}"]
    if result.accuracy_meters is not None:
        parts.append(f"±{result.accuracy_meters:g}m")
    if result.timestamp:
        parts.append(f"@ {result.timestamp}")
    if result.source:
        parts.append(f"({result.source})")
    typer.echo(" ".join(parts))


def _print_error(err: NodesLocationActionError, *, json_mode: bool) -> None:
    payload = {"ok": False, "error": err.to_dict()}
    if json_mode:
        typer.echo(json.dumps(payload, sort_keys=True))
        return
    typer.echo(f"ERROR[{err.code}]: {err.message}", err=True)


@app.command("get")
def get_command(
    ctx: typer.Context,
    node: str = typer.Option(..., "--node", "-n", help="Node id, name, or IP address."),
    accuracy: str = typer.Option(
        "balanced",
        "--accuracy",
        help="Desired accuracy: coarse, balanced, or precise.",
        show_default=True,
    ),
    max_age_ms: int = typer.Option(
        15_000,
        "--max-age",
        help="Maximum acceptable cached location age (ms).",
        show_default=True,
    ),
    location_timeout_ms: int = typer.Option(
        10_000,
        "--location-timeout",
        help="How long the device may try to obtain a fix (ms).",
        show_default=True,
    ),
    invoke_timeout_ms: int | None = typer.Option(
        None,
        "--invoke-timeout",
        help="Gateway/node invoke timeout (ms). If omitted, use CLI default.",
        show_default=False,
    ),
    idempotency_key: str | None = typer.Option(
        None,
        "--idempotency-key",
        help="Optional idempotency key for the gateway invoke.",
        show_default=False,
    ),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),  # noqa: FBT003
) -> None:
    """Fetch a node's current location (lat/lon)."""
    invoker = _resolve_invoker(ctx)
    try:
        action_input = NodesLocationActionInput(
            node=node,
            accuracy=accuracy.strip().lower() if isinstance(accuracy, str) else accuracy,  # validated downstream
            max_age_ms=max_age_ms,
            location_timeout_ms=location_timeout_ms,
            invoke_timeout_ms=invoke_timeout_ms,
            idempotency_key=idempotency_key,
        )

        # Use the shared JSON handler so CLI and HTTP layers stay consistent.
        response = _run(handle_nodes_location_request(action_input.to_dict(), invoker=invoker))

        if not isinstance(response, dict) or "ok" not in response:
            raise NodesLocationActionError("internal_error", "Unexpected handler response")

        if response.get("ok") is True:
            result = NodesLocationActionOutput.from_dict(response.get("result") or {})
            _print_result(result, json_mode=json_mode)
            return

        err_obj = response.get("error") or {}
        raise NodesLocationActionError(
            str(err_obj.get("code") or "external_failure"),
            str(err_obj.get("message") or "Node location request failed"),
            details=err_obj.get("details") if isinstance(err_obj, dict) else None,
        )
    except NodesLocationActionError as e:
        _print_error(e, json_mode=json_mode)
        raise typer.Exit(code=1)
    except Exception as e:  # pragma: no cover
        err = NodesLocationActionError(
            "internal_error",
            "Unhandled error",
            details={"exception": type(e).__name__},
        )
        _print_error(err, json_mode=json_mode)
        raise typer.Exit(code=1)


def register(nodes_app: typer.Typer) -> None:
    """Attach this module's commands to an existing `nodes` Typer app."""
    nodes_app.add_typer(app, name="location")
