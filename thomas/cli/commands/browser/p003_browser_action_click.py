"""Thomas CLI wiring for: browser click.

This module is designed to be discoverable in a variety of CLI setups:

- argparse-style command trees (via `register_argparse` / `register`)
- Typer-based apps (via `register_typer` / module-level `typer_app`)

The actual click logic lives in: `thomas.browser.p003_browser_action_click`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any, Optional, Sequence

from thomas.browser.p003_browser_action_click import (
    BrowserClickError,
    ClickConfigError,
    ClickInputError,
    ClickRequest,
    ClickTarget,
    click,
    error_info,
)

__all__ = [
    "COMMAND_GROUP",
    "COMMAND_NAME",
    "EXIT_CONFIG",
    "EXIT_EXTERNAL",
    "EXIT_INPUT",
    "EXIT_OK",
    "NAME",
    "GROUP",
    "add_parser",
    "main",
    "register",
    "register_argparse",
    "register_typer",
    "run_cli",
    "typer_app",
]

COMMAND_NAME = "click"
COMMAND_GROUP = "browser"

# Common aliases used by different command loaders.
NAME = COMMAND_NAME
GROUP = COMMAND_GROUP

# Exit codes are stable to make scripting deterministic.
EXIT_OK = 0
EXIT_INPUT = 2
EXIT_CONFIG = 3
EXIT_EXTERNAL = 4


def register_argparse(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `browser click` command onto an argparse subparser."""
    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Click an element in the live browser",
        description="Click an element by node id (preferred) or CSS selector.",
    )

    parser.add_argument(
        "target",
        nargs="?",
        help="Node id (e.g. 12) or CSS selector (e.g. 'button.submit')",
    )

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--node-id", type=int, dest="node_id", help="Node id to click")
    group.add_argument("--selector", type=str, dest="selector", help="CSS selector to click")

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Timeout in milliseconds for the click action",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON output",
    )

    parser.set_defaults(func=_run_from_args)
    return parser


# Backwards-compatible aliases (some command loaders look for these names).
def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    return register_argparse(subparsers)


add_parser = register_argparse


def run_cli(args: argparse.Namespace) -> int:
    """Run the command given parsed argparse args."""
    return _run_from_args(args)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone entry point (helpful for local debugging).

    Note: Most Thomas usage will not call this directly; the main CLI owns the
    top-level parser and dispatch.
    """
    parser = argparse.ArgumentParser(prog="thomas browser click")
    parser.add_argument("target", nargs="?", help="Node id or CSS selector")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--node-id", type=int, dest="node_id")
    group.add_argument("--selector", type=str, dest="selector")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--json", action="store_true", dest="json_output")
    ns = parser.parse_args(list(argv) if argv is not None else None)
    return _run_from_args(ns)


def _run_from_args(args: argparse.Namespace) -> int:
    target = _parse_target_args(args)
    req = ClickRequest(target=target, timeout_ms=int(getattr(args, "timeout_ms", 30_000)))

    try:
        result = click(req)
        if getattr(args, "json_output", False):
            print(json.dumps(asdict(result), sort_keys=True))
        else:
            print(_format_human_success(result))
        return EXIT_OK
    except ClickInputError as e:
        return _handle_error(e, json_output=getattr(args, "json_output", False))
    except ClickConfigError as e:
        return _handle_error(e, json_output=getattr(args, "json_output", False))
    except BrowserClickError as e:
        return _handle_error(e, json_output=getattr(args, "json_output", False))


def _parse_target_args(args: argparse.Namespace) -> ClickTarget:
    node_id: Optional[int] = getattr(args, "node_id", None)
    selector: Optional[str] = getattr(args, "selector", None)
    raw: Optional[str] = getattr(args, "target", None)

    # If explicit flags were provided, trust them.
    if node_id is not None or selector is not None:
        return ClickTarget(node_id=node_id, selector=selector)

    # Otherwise, interpret positional.
    if raw is None:
        return ClickTarget()  # validation will raise a deterministic error

    raw = str(raw).strip()
    if raw.isdigit():
        return ClickTarget(node_id=int(raw))
    return ClickTarget(selector=raw)


def _handle_error(exc: BrowserClickError, *, json_output: bool) -> int:
    info = error_info(exc)

    if json_output:
        payload = {"ok": False, "clicked": False, "error": asdict(info)}
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"ERROR [{info.kind}]: {info.message}", file=sys.stderr)

    if info.kind == "invalid_input":
        return EXIT_INPUT
    if info.kind == "missing_config":
        return EXIT_CONFIG
    return EXIT_EXTERNAL


def _format_human_success(result: Any) -> str:
    # Keep this intentionally boring/deterministic.
    if getattr(result, "used", "") == "node_id":
        return f"Clicked node_id={result.target.node_id}"
    return f"Clicked selector={result.target.selector}"


# ---------------------------------------------------------------------------
# Optional Typer integration
# ---------------------------------------------------------------------------


def register_typer(app: Any) -> None:
    """Register the command onto an existing Typer app (if Typer is installed)."""
    try:
        import typer  # type: ignore
    except Exception:
        return

    @app.command(COMMAND_NAME)
    def click_cmd(
        target: Optional[str] = typer.Argument(None, help="Node id or CSS selector"),
        node_id: Optional[int] = typer.Option(None, "--node-id", help="Node id to click"),
        selector: Optional[str] = typer.Option(None, "--selector", help="CSS selector to click"),
        timeout_ms: int = typer.Option(30_000, "--timeout-ms", help="Timeout in milliseconds"),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output"),
    ) -> None:
        ns = argparse.Namespace(
            target=target,
            node_id=node_id,
            selector=selector,
            timeout_ms=timeout_ms,
            json_output=json_output,
        )
        raise typer.Exit(code=_run_from_args(ns))


# A standalone Typer app instance. Some CLIs auto-discover these.
try:  # pragma: no cover
    import typer  # type: ignore

    typer_app = typer.Typer(add_completion=False)
    register_typer(typer_app)

except Exception:  # pragma: no cover
    typer_app = None
