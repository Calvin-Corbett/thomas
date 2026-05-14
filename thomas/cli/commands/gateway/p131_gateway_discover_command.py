"""CLI: gateway discover.

This is the CLI companion to the server route implemented in
`thomas.server.routes.gateway.p131_gateway_discover_command`.

The surrounding Thomas CLI framework loads command modules by convention.
To stay compatible with different loaders, this module exposes a small set of
common registration entrypoints.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

from thomas.server.routes.gateway.p131_gateway_discover_command import (
    DEFAULT_DISCOVERY_DOMAIN,
    DEFAULT_DISCOVERY_TIMEOUT_MS,
    DEFAULT_SERVICE_TYPE,
    GatewayDiscoverError,
    GatewayDiscoverRequest,
    discover_gateways,
    get_discover_schema,
)

COMMAND_NAME = "discover"


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `gateway discover` subcommand with an argparse subparser."""

    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Discover Thomas gateways on the LAN (mDNS/DNS-SD)",
        description="Discover Thomas gateways advertised on the local network via mDNS/DNS-SD.",
    )
    parser.add_argument(
        "--timeout",
        "--timeout-ms",
        dest="timeout_ms",
        type=int,
        default=DEFAULT_DISCOVERY_TIMEOUT_MS,
        help=f"Discovery timeout in milliseconds (default: {DEFAULT_DISCOVERY_TIMEOUT_MS})",
    )
    parser.add_argument(
        "--domain",
        default=DEFAULT_DISCOVERY_DOMAIN,
        help=f"DNS-SD discovery domain suffix (default: {DEFAULT_DISCOVERY_DOMAIN})",
    )
    parser.add_argument(
        "--service",
        "--service-type",
        dest="service_type",
        default=DEFAULT_SERVICE_TYPE,
        help=f"DNS-SD service type (default: {DEFAULT_SERVICE_TYPE})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Emit the route schema as JSON and exit",
    )
    parser.set_defaults(_thomas_run=run_from_args)
    return parser


# Common alias names used by different CLI loaders.
register_command = build_parser
add_parser = build_parser
register = build_parser


def run_from_args(args: argparse.Namespace) -> int:
    """Execute the command. Returns a process exit code."""

    if bool(getattr(args, "schema", False)):
        print(json.dumps({"ok": True, "schema": get_discover_schema()}, sort_keys=True))
        return 0

    req = GatewayDiscoverRequest(
        timeout_ms=int(getattr(args, "timeout_ms", DEFAULT_DISCOVERY_TIMEOUT_MS)),
        domain=str(getattr(args, "domain", DEFAULT_DISCOVERY_DOMAIN)),
        service_type=str(getattr(args, "service_type", DEFAULT_SERVICE_TYPE)),
    )

    try:
        result = discover_gateways(req)
    except GatewayDiscoverError as e:
        _emit_error(e, json_mode=bool(getattr(args, "json", False)))
        return 2

    payload: dict[str, Any] = {
        "ok": True,
        "result": {
            "service_type": result.service_type,
            "domain": result.domain,
            "timeout_ms": result.timeout_ms,
            "elapsed_ms": result.elapsed_ms,
            "beacons": [
                {
                    "instance_name": b.instance_name,
                    "host": b.host,
                    "port": b.port,
                    "addresses": list(b.addresses),
                    "ws_url": b.ws_url,
                    "txt": dict(b.txt),
                }
                for b in result.beacons
            ],
        },
    }

    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
        return 0

    # Human-readable output.
    if not result.beacons:
        print("No gateways discovered.")
        return 0

    for beacon in result.beacons:
        ws = beacon.ws_url or "(no ws_url)"
        host = beacon.host or "(no host)"
        port = beacon.port if beacon.port is not None else "?"
        print(f"{ws}  [{beacon.instance_name}]  host={host} port={port}")
    return 0


def _emit_error(err: GatewayDiscoverError, *, json_mode: bool) -> None:
    if json_mode:
        payload = {
            "ok": False,
            "error": {"code": err.code, "message": str(err), "details": err.details},
        }
        print(json.dumps(payload, sort_keys=True))
        return

    print(f"ERROR: {err.code}: {err}", file=sys.stderr)
    if err.details:
        print(f"details: {json.dumps(err.details, sort_keys=True)}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Standalone entrypoint for manual testing."""

    parser = argparse.ArgumentParser(prog="thomas gateway discover")
    parser.add_argument("--timeout", "--timeout-ms", dest="timeout_ms", type=int, default=DEFAULT_DISCOVERY_TIMEOUT_MS)
    parser.add_argument("--domain", default=DEFAULT_DISCOVERY_DOMAIN)
    parser.add_argument("--service", "--service-type", dest="service_type", default=DEFAULT_SERVICE_TYPE)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--schema", action="store_true")
    args = parser.parse_args(argv)
    return run_from_args(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
