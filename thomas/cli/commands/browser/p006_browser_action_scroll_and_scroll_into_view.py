"""P006 - CLI commands for browser scrolling actions.

Adds two commands under the existing `browser` command group:

- `scroll`
- `scroll-into-view`

This module is intentionally defensive. It tries to resolve an existing Thomas
browser executor at runtime, but failures are surfaced as deterministic,
machine-readable errors (especially in `--json` mode).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import typer

from thomas.browser.p006_browser_action_scroll_and_scroll_into_view import (
    BrowserActionError,
    ScrollIntoViewRequest,
    ViewportScrollRequest,
)


# Prefer registering onto the shared browser Typer app when it exists.
try:  # pragma: no cover - depends on surrounding Thomas CLI package structure
    from . import app as _browser_app  # type: ignore
except Exception:  # pragma: no cover
    _browser_app = typer.Typer(add_completion=False)

app = _browser_app


@dataclass(frozen=True)
class CliResult:
    ok: bool
    payload: dict[str, Any]


def _echo_result(result: CliResult, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps({"ok": result.ok, **result.payload}, ensure_ascii=False))
        return

    if result.ok:
        # Human output: keep it short and helpful.
        typer.echo(result.payload.get("message", "ok"))
    else:
        typer.echo(result.payload.get("error", "error"), err=True)


def _run_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    raise BrowserActionError(
        "ASYNC_CONTEXT",
        "Cannot execute an async browser action from a running event loop via the CLI",
    )


def _resolve_browser_executor() -> Any:
    """Resolve something capable of executing browser actions.

    The resolved executor may be:
    - a callable taking (action_name, params) or similar keyword variants
    - an object with a method like run_action/execute/perform
    - an object exposing `page` / `current_page` (fallback: we call our handler directly)

    If nothing can be resolved, raise `MISSING_CONFIG`.
    """

    # 1) Try the browser tool module (most direct).
    try:
        import thomas.tools.browser as browser_mod  # type: ignore

        for fn_name in (
            "run_browser_action",
            "execute_browser_action",
            "perform_browser_action",
            "run_action",
            "execute_action",
        ):
            fn = getattr(browser_mod, fn_name, None)
            if callable(fn):
                return fn

        for cls_name in ("BrowserTool", "Browser", "LiveBrowser"):
            cls = getattr(browser_mod, cls_name, None)
            if cls is None:
                continue
            try:
                return cls()
            except TypeError:
                continue
    except Exception:
        pass

    # 2) Try the live_browser client (if Thomas uses one).
    try:
        import thomas.cli.live_browser as live_browser_mod  # type: ignore

        for fn_name in (
            "get_client",
            "connect",
            "connect_client",
            "load_client",
            "load_live_browser",
            "get_live_browser",
        ):
            fn = getattr(live_browser_mod, fn_name, None)
            if callable(fn):
                try:
                    return fn()
                except TypeError:
                    continue

        for cls_name in ("LiveBrowserClient", "LiveBrowser"):
            cls = getattr(live_browser_mod, cls_name, None)
            if cls is None:
                continue
            try:
                return cls()
            except TypeError:
                continue
    except Exception:
        pass

    raise BrowserActionError(
        "MISSING_CONFIG",
        "No browser executor could be resolved. Start a live browser session or configure the browser tool.",
    )


def _execute_with_executor(executor: Any, action_name: str, params: Mapping[str, Any]) -> Any:
    """Attempt to execute a browser action via an unknown-but-probable executor API."""

    payload = dict(params)

    if callable(executor):
        # Probe common call shapes.
        for call in (
            lambda: executor(action_name, payload),
            lambda: executor(action=action_name, params=payload),
            lambda: executor({"action": action_name, "params": payload}),
            lambda: executor({"name": action_name, **payload}),
        ):
            try:
                return call()
            except TypeError:
                continue

    for method_name in (
        "run_action",
        "execute_action",
        "execute",
        "perform",
        "run",
        "act",
        "apply",
        "dispatch",
    ):
        method = getattr(executor, method_name, None)
        if not callable(method):
            continue
        for call in (
            lambda: method(action_name, payload),
            lambda: method(action=action_name, params=payload),
            lambda: method({"action": action_name, "params": payload}),
            lambda: method({"name": action_name, **payload}),
        ):
            try:
                return call()
            except TypeError:
                continue

    # Fallback: executor might expose a page directly.
    page = getattr(executor, "page", None) or getattr(executor, "current_page", None)
    if page is not None:
        from thomas.browser.p006_browser_action_scroll_and_scroll_into_view import ACTION_HANDLERS

        handler = ACTION_HANDLERS[action_name]
        return handler(page, payload)

    raise BrowserActionError(
        "UNSUPPORTED_BACKEND",
        "Resolved browser executor does not expose a recognized API for actions",
        details={"executor_type": type(executor).__name__},
    )


def _run_cli_action(action_name: str, params: Mapping[str, Any], *, json_output: bool) -> None:
    try:
        executor = _resolve_browser_executor()
        result = _execute_with_executor(executor, action_name, params)
        result = _run_awaitable(result)

        # Normalize result to a dict for `--json` mode.
        payload: dict[str, Any]
        if isinstance(result, Mapping):
            payload = dict(result)
        else:
            payload = {"value": result}

        _echo_result(CliResult(ok=True, payload={"result": payload}), as_json=json_output)
    except BrowserActionError as exc:
        _echo_result(CliResult(ok=False, payload={"error": exc.to_dict()}), as_json=json_output)
        raise typer.Exit(code=2)
    except Exception as exc:
        err = BrowserActionError(
            "INTERNAL_ERROR",
            "unexpected failure while executing browser command",
            details={"exc_type": type(exc).__name__},
            cause=exc,
        )
        _echo_result(CliResult(ok=False, payload={"error": err.to_dict()}), as_json=json_output)
        raise typer.Exit(code=1)


@app.command("scroll")
def cli_scroll(
    x: int = typer.Option(0, "--x", "--delta-x", help="Horizontal scroll delta in pixels"),
    y: int = typer.Option(0, "--y", "--delta-y", help="Vertical scroll delta in pixels"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    try:
        req = ViewportScrollRequest.from_dict({"delta_x": x, "delta_y": y})
    except BrowserActionError as exc:
        _echo_result(CliResult(ok=False, payload={"error": exc.to_dict()}), as_json=json_output)
        raise typer.Exit(code=2)

    _run_cli_action("scroll", {"delta_x": req.delta_x, "delta_y": req.delta_y}, json_output=json_output)


@app.command("scroll-into-view")
def cli_scroll_into_view(
    selector: str = typer.Option(
        ...,
        "--selector",
        "--css",
        "--query",
        help="Selector of the element to bring into view (CSS recommended)",
    ),
    timeout_ms: Optional[int] = typer.Option(None, "--timeout-ms", "--timeout", help="Timeout in milliseconds"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    try:
        req = ScrollIntoViewRequest.from_dict({"selector": selector, "timeout_ms": timeout_ms})
    except BrowserActionError as exc:
        _echo_result(CliResult(ok=False, payload={"error": exc.to_dict()}), as_json=json_output)
        raise typer.Exit(code=2)

    params: dict[str, Any] = {"selector": req.selector}
    if req.timeout_ms is not None:
        params["timeout_ms"] = req.timeout_ms

    _run_cli_action("scroll_into_view", params, json_output=json_output)


def register(target_app: Any) -> None:
    """Register this module's commands onto an existing Typer app."""

    if target_app is app:
        return

    target_app.command("scroll")(cli_scroll)
    target_app.command("scroll-into-view")(cli_scroll_into_view)
