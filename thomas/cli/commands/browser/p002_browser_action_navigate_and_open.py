"""CLI wiring for Prompt P002 (browser navigate/open).

This module registers two browser subcommands:

- ``navigate``: navigate the currently focused tab/page to a URL.
- ``open``: open a URL in a new tab/page.

Both commands support ``--json`` machine-readable output.

The registration strategy is intentionally flexible to fit different Thomas CLI
wiring patterns:

- If ``thomas.cli.commands.browser`` exposes an ``app`` (Typer instance), we
  attach commands directly to it.
- Otherwise, we expose a fallback ``app`` so tests and alternative loaders can
  still invoke the commands.
"""

from __future__ import annotations

import argparse

import typer

_fallback_app = typer.Typer(name="browser")


def register(target_app: typer.Typer) -> None:
    """Register P002 commands onto the provided Typer app."""

    if getattr(target_app, "_p002_nav_open_registered", False):
        return
    target_app._p002_nav_open_registered = True

    def _emit_success(*, result_json: str, json_mode: bool, human_message: str) -> None:
        if json_mode:
            typer.echo(result_json)
        else:
            typer.echo(human_message)

    def _emit_error(err: Exception, *, json_mode: bool) -> None:
        from thomas.browser.p002_browser_action_navigate_and_open import (
            InvalidNavigateAndOpenInput,
            MissingBrowserConfiguration,
            NavigateAndOpenError,
            format_error_as_json,
        )

        if not isinstance(err, NavigateAndOpenError):  # pragma: no cover
            typer.echo("Unexpected error.", err=True)
            raise typer.Exit(code=1)

        if json_mode:
            typer.echo(format_error_as_json(err))
        else:
            typer.echo(f"Error: {err}", err=True)

        if isinstance(err, InvalidNavigateAndOpenInput):
            raise typer.Exit(code=2)
        if isinstance(err, MissingBrowserConfiguration):
            raise typer.Exit(code=3)
        raise typer.Exit(code=1)

    def _run(action: str, url: str, *, timeout_ms: int | None, profile: str | None):
        from thomas.browser.p002_browser_action_navigate_and_open import (
            NavigateAndOpenRequest,
            format_result_as_json,
            run_p002_navigate_and_open,
        )

        req = NavigateAndOpenRequest(url=url, action=action, timeout_ms=timeout_ms, profile=profile)
        result = run_p002_navigate_and_open(req)
        return result, format_result_as_json

    @target_app.command("navigate")
    def navigate(
        url: str = typer.Argument(..., help="Absolute URL to navigate to."),
        timeout_ms: int | None = typer.Option(
            None,
            "--timeout-ms",
            min=1,
            help="Optional timeout in milliseconds.",
        ),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Optional browser profile/routing config.",
        ),
        json_mode: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON output.",
        ),
    ) -> None:
        """Navigate the active tab/page to a URL."""

        try:
            result, fmt_ok = _run("navigate", url, timeout_ms=timeout_ms, profile=profile)
            _emit_success(
                result_json=fmt_ok(result),
                json_mode=json_mode,
                human_message=(f"Navigated to {result.url}" + (f" (tab {result.tab_id})" if result.tab_id else "")),
            )
        except Exception as err:
            _emit_error(err, json_mode=json_mode)

    @target_app.command("open")
    def open_url(
        url: str = typer.Argument(..., help="Absolute URL to open in a new tab."),
        timeout_ms: int | None = typer.Option(
            None,
            "--timeout-ms",
            min=1,
            help="Optional timeout in milliseconds.",
        ),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Optional browser profile/routing config.",
        ),
        json_mode: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON output.",
        ),
    ) -> None:
        """Open a URL in a new tab/page."""

        try:
            result, fmt_ok = _run("open", url, timeout_ms=timeout_ms, profile=profile)
            _emit_success(
                result_json=fmt_ok(result),
                json_mode=json_mode,
                human_message=(f"Opened {result.url}" + (f" (tab {result.tab_id})" if result.tab_id else "")),
            )
        except Exception as err:
            _emit_error(err, json_mode=json_mode)


# Attach to the parent browser app if it exists; otherwise keep a fallback.
try:  # pragma: no cover
    from . import app as _browser_app  # type: ignore
except ImportError:  # pragma: no cover
    _browser_app = None

if isinstance(_browser_app, typer.Typer):  # pragma: no cover
    register(_browser_app)
    app = _browser_app
else:
    register(_fallback_app)
    app = _fallback_app


def main(argv: list[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    from thomas.browser.p002_browser_action_navigate_and_open import (
        InvalidNavigateAndOpenInput,
        MissingBrowserConfiguration,
        NavigateAndOpenError,
        NavigateAndOpenRequest,
        format_error_as_json,
        format_result_as_json,
        run_p002_navigate_and_open,
    )

    parser = argparse.ArgumentParser(
        prog="browser action-navigate-and-open",
        description="Navigate active page or open a URL in a new tab.",
    )
    parser.add_argument(
        "route_args",
        nargs="*",
        help="Either <url> or <action> <url>, where action is navigate|open.",
    )
    parser.add_argument("--action", choices=["navigate", "open"], default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--timeout-ms", type=int, default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true", default=False)
    try:
        args = parser.parse_args(list(argv or []))
    except SystemExit as exc:
        return int(exc.code or 0)

    route_args = [str(x) for x in (args.route_args or []) if str(x).strip()]
    action = str(args.action or "").strip().lower()
    if not action and route_args and route_args[0].lower() in {"navigate", "open"}:
        action = route_args[0].lower()

    if not action:
        action = "navigate"

    url = str(args.url or "").strip()
    if not url:
        if route_args:
            if route_args[0].lower() in {"navigate", "open"} and len(route_args) >= 2:
                url = route_args[1].strip()
            else:
                url = route_args[0].strip()

    if not url:
        err = InvalidNavigateAndOpenInput("URL is required (positional or --url).")
        if args.json_mode:
            typer.echo(format_error_as_json(err))
        else:
            typer.echo(f"Error: {err}", err=True)
        return 2

    try:
        result = run_p002_navigate_and_open(
            NavigateAndOpenRequest(
                url=url,
                action=action,
                timeout_ms=args.timeout_ms,
                profile=args.profile,
            )
        )
        if args.json_mode:
            typer.echo(format_result_as_json(result))
        else:
            typer.echo(
                f"{'Opened' if action == 'open' else 'Navigated to'} {result.url}"
                + (f" (tab {result.tab_id})" if result.tab_id else "")
            )
        return 0
    except NavigateAndOpenError as err:
        if args.json_mode:
            typer.echo(format_error_as_json(err))
        else:
            typer.echo(f"Error: {err}", err=True)
        if isinstance(err, InvalidNavigateAndOpenInput):
            return 2
        if isinstance(err, MissingBrowserConfiguration):
            return 3
        return 1
