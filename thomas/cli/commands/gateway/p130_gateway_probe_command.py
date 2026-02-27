"""Thomas CLI: gateway probe.

Provides:
  - an argparse-friendly subcommand binder (register / register_command)
  - a pure async helper (run_probe) that tests can call
  - a standalone main() for direct invocation

Supports machine-readable output via --json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from thomas.server.routes.gateway.p130_gateway_probe_command import (
    GatewayProbeException,
    GatewayProbeResponse,
    probe_gateway,
    resolve_gateway_target,
)

COMMAND_NAME = "probe"
HELP = "Probe configured gateway connectivity."


def build_arg_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--target",
        dest="target",
        default=None,
        help="Gateway base URL to probe (overrides config/env).",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_s",
        type=float,
        default=3.0,
        help="Timeout in seconds (default: 3.0).",
    )
    parser.add_argument(
        "--path",
        dest="path",
        default="/",
        help="Path to request on the gateway (default: /).",
    )
    parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    return parser


async def run_probe(
    *,
    target: str | None = None,
    timeout_s: float = 3.0,
    path: str = "/",
    environ: Mapping[str, str] | None = None,
) -> GatewayProbeResponse:
    resolved = resolve_gateway_target(explicit_target=target, environ=environ)
    return await probe_gateway(target=resolved, timeout_s=timeout_s, path=path)


def _render_human(result: GatewayProbeResponse) -> str:
    if result.ok:
        return f"Gateway reachable: {result.target} " f"(HTTP {result.status_code}, {result.latency_ms}ms)"
    code = result.error["code"] if result.error else "error"
    msg = result.error["message"] if result.error else "Gateway probe failed."
    tgt = result.target or "<unknown>"
    return f"Gateway probe failed: {tgt} ({code}) {msg}"


def register(subparsers: Any) -> None:
    """Register with an argparse subparser collection (best-effort)."""

    try:
        p = subparsers.add_parser(
            "probe",
            help=HELP,
            description="Probe the configured gateway target for reachability.",
        )
    except Exception:  # REVIEWED: broad catch
        return

    build_arg_parser(p)
    p.set_defaults(_thomas_handler=main)


# Compatibility aliases for different CLI loader conventions.
register_command = register
register_subcommand = register


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thomas gateway probe")
    build_arg_parser(parser)
    args = parser.parse_args(argv)

    try:
        import asyncio

        result = asyncio.run(run_probe(target=args.target, timeout_s=args.timeout_s, path=args.path))
    except GatewayProbeException as e:
        result = GatewayProbeResponse(ok=False, target=args.target or "", error=e.to_payload())
    except ImportError:
        result = GatewayProbeResponse(
            ok=False,
            target=args.target or "",
            error={"code": "internal_error", "message": "Internal error."},
        )

    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(asdict(result), sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_render_human(result))
        sys.stdout.write("\n")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
