"""CLI command: browser type-and-press.

This module is intentionally compatibility-heavy to fit into a variety of Thomas
CLI loaders/discovery mechanisms. It provides:

* `app`: Typer sub-application
* `register(parent_app)`: optional explicit registration hook
* `add_to(parent_app)`: alias for `register`
* `command`: Click command object (Typer-exported), when available

The command supports:

* `--json` for machine-readable output
* `--schema` for input/output JSON schema emission
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import typer

from thomas.browser.p004_browser_action_type_and_press import (
    ACTION_NAME,
    TypeAndPressError,
    format_json,
    input_json_schema,
    output_json_schema,
    parse_params,
    type_and_press,
)
from thomas.cli.commands.browser._runtime_entrypoint import run_typer_app

COMMAND_NAME = "type-and-press"


app = typer.Typer(add_completion=False, help="Type into an element and press a key.")


@dataclass(frozen=True, slots=True)
class _ResolvedPage:
    page: Any
    cleanup: Callable[[], None]
    source: str


def _is_page(obj: Any) -> bool:
    if obj is None:
        return False
    if hasattr(obj, "page"):
        obj = obj.page
    return hasattr(obj, "locator")


def _noop() -> None:
    return None


def _resolve_from_thomas_modules(url: str | None) -> _ResolvedPage | None:
    """Best-effort resolution of a live Page from Thomas' own modules."""

    candidate_modules = ("thomas.cli.live_browser", "thomas.tools.browser")
    candidate_attrs = (
        # common function-like getters
        "get_live_page",
        "get_page",
        "get_active_page",
        "active_page",
        "current_page",
        "page",
    )

    for mod_name in candidate_modules:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue

        for attr in candidate_attrs:
            candidate = getattr(mod, attr, None)
            page_obj: Any = None

            if callable(candidate):
                try:
                    page_obj = candidate()
                except ImportError:
                    continue
            else:
                page_obj = candidate

            if page_obj is None and hasattr(candidate, "page"):
                page_obj = candidate.page

            if not _is_page(page_obj):
                continue

            page = getattr(page_obj, "page", page_obj)

            if url and hasattr(page, "goto"):
                try:
                    page.goto(url)
                except Exception as exc:
                    raise TypeAndPressError(
                        code="EXTERNAL_FAILURE",
                        message=f"Navigation failed: {exc.__class__.__name__}: {exc}",
                        step="goto",
                    )

            return _ResolvedPage(page=page, cleanup=_noop, source=mod_name)

    return None


def _resolve_page_with_cleanup(url: str | None) -> _ResolvedPage:
    """Resolve a Page and a cleanup function.

    Resolution order:
      1) Thomas live browser/page providers (preferred)
      2) `THOMAS_BROWSER_WS_ENDPOINT` Playwright connect
      3) Local headless browser launch (requires --url)
    """

    resolved = _resolve_from_thomas_modules(url)
    if resolved is not None:
        return resolved

    endpoint = os.environ.get("THOMAS_BROWSER_WS_ENDPOINT")
    if endpoint:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            pw = sync_playwright().start()
            try:
                if endpoint.startswith("ws://") or endpoint.startswith("wss://"):
                    browser = pw.chromium.connect(endpoint)
                else:
                    browser = pw.chromium.connect_over_cdp(endpoint)

                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                if url:
                    page.goto(url)

                def _cleanup() -> None:
                    # Best-effort cleanup; swallow errors to keep deterministic CLI behavior.
                    try:
                        browser.close()
                    except ImportError:
                        pass
                    try:
                        pw.stop()
                    except Exception:  # REVIEWED: broad catch
                        pass

                return _ResolvedPage(page=page, cleanup=_cleanup, source="endpoint")
            except Exception:  # REVIEWED: broad catch
                # Ensure Playwright is stopped if connect fails mid-way.
                try:
                    pw.stop()
                except Exception:  # REVIEWED: broad catch
                    pass
                raise
        except TypeAndPressError:
            raise
        except Exception as exc:
            raise TypeAndPressError(
                code="CONFIG_INVALID",
                message=f"Failed to connect using THOMAS_BROWSER_WS_ENDPOINT: {exc.__class__.__name__}: {exc}",
                step="connect",
            )

    if not url:
        raise TypeAndPressError(
            code="MISSING_CONFIG",
            message="No live browser available; provide --url or set THOMAS_BROWSER_WS_ENDPOINT",
            step="resolve_page",
        )

    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)

        def _cleanup() -> None:
            try:
                browser.close()
            except ImportError:
                pass
            try:
                pw.stop()
            except ImportError:
                pass

        return _ResolvedPage(page=page, cleanup=_cleanup, source="local")
    except Exception as exc:
        raise TypeAndPressError(
            code="EXTERNAL_FAILURE",
            message=f"Failed to launch local browser: {exc.__class__.__name__}: {exc}",
            step="launch",
        )


@app.callback(invoke_without_command=True, no_args_is_help=True)
def type_and_press_command(
    selector: str | None = typer.Option(None, "--selector", help="CSS/XPath selector for the target element."),
    text: str | None = typer.Option(None, "--text", help="Text to type into the element."),
    key: str = typer.Option("Enter", "--key", help="Key to press after typing (default: Enter)."),
    url: str | None = typer.Option(None, "--url", help="Optional URL to navigate before performing the action."),
    timeout_ms: int | None = typer.Option(None, "--timeout-ms", help="Optional timeout in milliseconds."),
    delay_ms: int | None = typer.Option(None, "--delay-ms", help="Optional typing delay per keystroke (ms)."),
    click_first: bool = typer.Option(True, "--click-first/--no-click-first", help="Click the element before typing."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    schema: bool = typer.Option(False, "--schema", help="Print input/output JSON schemas and exit."),
) -> None:
    """Type into an element and press a key."""

    if schema:
        payload = {
            "action": ACTION_NAME,
            "input_schema": input_json_schema(),
            "output_schema": output_json_schema(),
        }
        typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        raise typer.Exit(code=0)

    if selector is None or text is None:
        raise TypeAndPressError(
            code="INVALID_INPUT",
            message="--selector and --text are required unless --schema is used",
            step="validate",
        )

    params = parse_params(
        {
            "selector": selector,
            "text": text,
            "key": key,
            "timeout_ms": timeout_ms,
            "delay_ms": delay_ms,
            "click_first": click_first,
        }
    )

    resolved: _ResolvedPage | None = None
    try:
        resolved = _resolve_page_with_cleanup(url)
        result = type_and_press(resolved.page, params)

        if json_out:
            typer.echo(format_json(result))
        else:
            typer.echo(f"OK ({resolved.source}): typed {len(text)} chars into {selector!r} and pressed {key!r}")

    except TypeAndPressError as exc:
        if json_out:
            typer.echo(format_json(exc))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)
    finally:
        if resolved is not None:
            try:
                resolved.cleanup()
            except (ValueError, TypeError):
                # Cleanup failures should never mask action errors.
                pass


def register(parent_app: typer.Typer) -> None:
    """Explicit registration hook (optional)."""

    parent_app.add_typer(app, name=COMMAND_NAME)


def add_to(parent_app: typer.Typer) -> None:
    """Alias for register() for compatibility with alternative loaders."""

    register(parent_app)


# Compatibility shim: expose a Click command object for loaders that expect Click.
try:  # pragma: no cover
    command = typer.main.get_command(app)
except Exception:  # REVIEWED: error boundary:  # pragma: no cover
    command = None


def main(argv: Sequence[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    return run_typer_app(
        app,
        argv,
        command=f"browser {COMMAND_NAME}",
        require_args=True,
        missing_args_message="Pass --selector and --text, or use --schema for the command contract.",
    )
