"""CLI command for `thomas browser` (P026)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from thomas.browser.p026_browser_integration_into_top_level_cli import (
    BrowserOpenRequest,
    open_url,
    result_json_schema,
)


_EXIT_CODE_BY_ERROR_KIND = {
    "invalid_input": 2,
    "missing_config": 2,
    "external_failure": 1,
    "internal_error": 1,
}


def register_browser_command(subparsers: argparse._SubParsersAction) -> None:
    """Register the top-level `browser` command onto an argparse subparsers action."""

    parser = subparsers.add_parser(
        "browser",
        help="Open a URL using the available browser backend.",
        description="Open a URL using the available browser backend.",
    )

    # Support both:
    #   thomas browser https://example.com
    #   thomas browser open https://example.com
    parser.add_argument(
        "route_args",
        nargs="*",
        help="URL to open, or `open <url>`.",
    )
    parser.add_argument(
        "--url",
        dest="url",
        default=None,
        help="Explicit URL to open (overrides positional arguments).",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Optional path to a browser config file (JSON supported).",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_s",
        type=float,
        default=None,
        help="Optional timeout in seconds (best-effort, backend dependent).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and emit output without opening a browser.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--json-schema",
        action="store_true",
        help="Print the JSON schema for --json output and exit.",
    )

    # Be compatible with different dispatch conventions across the codebase.
    parser.set_defaults(func=_handle_browser_command, _handler=_handle_browser_command)


def _pick_url(args: argparse.Namespace) -> Optional[str]:
    explicit = getattr(args, "url", None)
    if isinstance(explicit, str) and explicit.strip() != "":
        return explicit.strip()

    route_args = [str(a) for a in (getattr(args, "route_args", []) or [])]
    if not route_args:
        return None

    head = route_args[0].lower()
    if head in {"open", "launch"}:
        return route_args[1] if len(route_args) >= 2 else None

    return route_args[0]


def _emit_json(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


def _handle_browser_command(args: argparse.Namespace) -> int:
    if bool(getattr(args, "json_schema", False)):
        _emit_json(result_json_schema())
        return 0

    request = BrowserOpenRequest(
        url=_pick_url(args),
        config_path=getattr(args, "config_path", None),
        timeout_s=getattr(args, "timeout_s", None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    result = open_url(request)

    if bool(getattr(args, "json", False)):
        sys.stdout.write(result.to_json())
        sys.stdout.write("\n")
    else:
        if result.ok:
            sys.stdout.write(f"{result.message}: {result.url}\n")
        else:
            if result.error is None:
                sys.stderr.write(f"error: {result.message}\n")
            else:
                sys.stderr.write(f"{result.error.kind}: {result.error.message}\n")

    if result.ok:
        return 0

    kind = result.error.kind if result.error is not None else "internal_error"
    return int(_EXIT_CODE_BY_ERROR_KIND.get(kind, 1))
