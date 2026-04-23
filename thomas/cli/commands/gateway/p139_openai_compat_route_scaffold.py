"""CLI: OpenAI-compatible gateway route scaffold.

Prints schema + config hints for the OpenAI-compat gateway route.
Supports `--json` for automation and `--with-config` to include env-derived values.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from thomas.server.routes.gateway import p139_openai_compat_route_scaffold as route_mod


COMMAND_NAME = "p139-openai-compat-route-scaffold"
HELP = "Show schema + config hints for the OpenAI-compatible gateway route."


def _build_parser(subparsers: argparse._SubParsersAction | None = None) -> argparse.ArgumentParser:
    if subparsers is None:
        parser = argparse.ArgumentParser(prog=COMMAND_NAME, description=HELP)
    else:
        parser = subparsers.add_parser(COMMAND_NAME, help=HELP, description=HELP)

    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON (schema document).")
    parser.add_argument(
        "--with-config",
        action="store_true",
        help="Include current env-derived config values in the output.",
    )

    # Common hooks some Thomas CLIs use
    parser.set_defaults(func=run, handler=run, run=run)
    return parser


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Argparse-style registration hook."""
    return _build_parser(subparsers)


# Alternate names some loaders use.
add_parser = register
build_parser = _build_parser


def run(args: argparse.Namespace) -> int:
    schema: dict[str, Any] = route_mod.get_route_schema()
    if getattr(args, "with_config", False):
        schema = {**schema, "config_values": route_mod.get_config_for_cli()}

    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        return 0

    sys.stdout.write(f"{schema['title']}\n")
    sys.stdout.write(f"ID: {schema['id']}\n\n")
    sys.stdout.write(schema["description"] + "\n\n")
    sys.stdout.write("Routes (external-first, with alt paths):\n")
    for r in schema["routes"]:
        alt = r.get("alt_paths") or []
        sys.stdout.write(f"  {r['method']:>4} {r['path']}\n")
        for a in alt:
            sys.stdout.write(f"       alt: {a}\n")
    sys.stdout.write("\nEnvironment variables:\n")
    for k, meta in schema.get("config", {}).get("env", {}).items():
        req = "required" if meta.get("required") else "optional"
        sys.stdout.write(f"  {k} ({req})\n")
    if getattr(args, "with_config", False):
        sys.stdout.write("\nCurrent env-derived values (for debugging):\n")
        for k, v in route_mod.get_config_for_cli().items():
            show = "<set>" if (k == "api_key" and v) else v
            sys.stdout.write(f"  {k}: {show}\n")
    sys.stdout.write("\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser(None)
    parsed = parser.parse_args(list(argv) if argv is not None else None)
    return run(parsed)


if __name__ == "__main__":
    raise SystemExit(main())
