"""thomas.cli.commands.browser.p005_browser_action_hover_and_focus

Adds two browser subcommands:

- ``hover``: hover an element
- ``focus``: focus an element

Both commands support ``--json`` for machine-readable output.

This module is designed to integrate with the existing Thomas CLI wiring.
It avoids opening browsers or creating sessions; it expects an active
browser/controller object to be provided via Typer context (ctx.obj).

"""

from __future__ import annotations

import json
import sys
import types
from typing import Any, Literal, Optional, Union

import typer

from thomas.browser.p005_browser_action_hover_and_focus import (
    HoverFocusError,
    HoverFocusRequest,
    hover_or_focus_sync,
)


def _resolve_browser_app() -> typer.Typer:
    """Best-effort resolution of the existing `thomas browser` Typer app.

    We intentionally don't import extra modules here; instead we look at the
    already-importing package module.

    If we can't find it, we create a local Typer app so imports/tests don't
    explode. (In a correctly wired CLI, this path should not be used.)
    """

    pkg = sys.modules.get("thomas.cli.commands.browser")
    if pkg is not None:
        for name in ("app", "browser_app", "cli"):
            candidate = getattr(pkg, name, None)
            if isinstance(candidate, typer.Typer):
                return candidate
            if isinstance(candidate, types.ModuleType):
                inner = getattr(candidate, "app", None)
                if isinstance(inner, typer.Typer):
                    return inner

    # Fallback: isolated app.
    return typer.Typer(help="Browser commands")


_browser_app = _resolve_browser_app()


def _dumps_json(payload: dict[str, Any]) -> str:
    # Deterministic output for automation (stable key ordering).
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _emit(payload: dict[str, Any], *, json_out: bool) -> None:
    if json_out:
        typer.echo(_dumps_json(payload))
        return

    # Human output: short and readable.
    if payload.get("ok") is True:
        action = payload.get("action")
        target = payload.get("target") or {}
        if "selector" in target:
            typer.echo(f"{action}: selector={target['selector']}")
        else:
            typer.echo(f"{action}: node_id={target.get('node_id')}")
    else:
        err = payload.get("error") or {}
        typer.echo(f"error[{err.get('code')}] {err.get('message')}")


def _browser_from_ctx(ctx: Optional[typer.Context]) -> Any:
    if ctx is None:
        return None

    obj = getattr(ctx, "obj", None)
    if not isinstance(obj, dict):
        return None

    for key in ("browser", "controller", "page", "client", "session"):
        if key in obj and obj[key] is not None:
            return obj[key]

    return None


def _coerce_node_id(node_id: Optional[str]) -> Optional[Union[int, str]]:
    if node_id is None:
        return None

    if isinstance(node_id, str) and node_id.isdigit():
        return int(node_id)

    return node_id


def run_hover_or_focus(
    *,
    action: Literal["hover", "focus"],
    selector: Optional[str],
    node_id: Optional[str],
    timeout_ms: Optional[int],
    json_out: bool,
    ctx: Optional[typer.Context] = None,
    browser: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Pure helper for tests and CLI wrappers.

    Returns: (exit_code, payload)
    """

    controller = browser if browser is not None else _browser_from_ctx(ctx)

    request = HoverFocusRequest(
        action=action,
        selector=selector,
        node_id=_coerce_node_id(node_id),
        timeout_ms=timeout_ms,
    )

    try:
        result = hover_or_focus_sync(controller, request)
        payload = result.to_payload()
        return 0, payload
    except HoverFocusError as exc:
        payload = exc.to_payload(action=action)
        return exc.exit_code, payload


@_browser_app.command("hover")
def hover(
    ctx: typer.Context,
    selector: Optional[str] = typer.Option(
        None,
        "--selector",
        "-s",
        help="Target element selector (CSS/XPath/text depending on backend).",
    ),
    node_id: Optional[str] = typer.Option(
        None,
        "--node-id",
        "-n",
        help="Target node id (from a prior nodes listing).",
    ),
    timeout_ms: Optional[int] = typer.Option(
        None,
        "--timeout-ms",
        help="Optional timeout in milliseconds.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    exit_code, payload = run_hover_or_focus(
        action="hover",
        selector=selector,
        node_id=node_id,
        timeout_ms=timeout_ms,
        json_out=json_out,
        ctx=ctx,
    )

    _emit(payload, json_out=json_out)

    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@_browser_app.command("focus")
def focus(
    ctx: typer.Context,
    selector: Optional[str] = typer.Option(
        None,
        "--selector",
        "-s",
        help="Target element selector (CSS/XPath/text depending on backend).",
    ),
    node_id: Optional[str] = typer.Option(
        None,
        "--node-id",
        "-n",
        help="Target node id (from a prior nodes listing).",
    ),
    timeout_ms: Optional[int] = typer.Option(
        None,
        "--timeout-ms",
        help="Optional timeout in milliseconds.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    exit_code, payload = run_hover_or_focus(
        action="focus",
        selector=selector,
        node_id=node_id,
        timeout_ms=timeout_ms,
        json_out=json_out,
        ctx=ctx,
    )

    _emit(payload, json_out=json_out)

    if exit_code != 0:
        raise typer.Exit(code=exit_code)


# Re-export for discovery/tests.
app = _browser_app
