from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from thomas.server.routes.gateway.p126_gateway_start_command import (
    GatewayStartException,
    start_gateway_process,
)

# CLI-level state for idempotency during a single CLI process run.
_CLI_STATE: dict[str, Any] = {}


@dataclass(frozen=True)
class GatewayStartCliOptions:
    config_path: str
    force_restart: bool = False


def run_gateway_start(options: GatewayStartCliOptions) -> dict[str, Any]:
    """Start the gateway process; returns a machine-readable payload."""
    try:
        outcome = start_gateway_process(
            state=_CLI_STATE,
            config_path=options.config_path,
            force_restart=options.force_restart,
        )
        return outcome.to_response()
    except GatewayStartException as e:
        return e.to_error_payload()


def _format_human(payload: dict[str, Any]) -> str:
    if payload.get("ok") is True:
        return f"Gateway {payload.get('status')} " f"(pid={payload.get('pid')}, config={payload.get('config_path')})"
    err = payload.get("error") or {}
    return f"Gateway start failed: {err.get('type')}: {err.get('message')}"


def build_arg_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        dest="config_path",
        default=os.environ.get("THOMAS_GATEWAY_CONFIG", ""),
        help="Path to gateway config (JSON or TOML). Can also be set via THOMAS_GATEWAY_CONFIG.",
    )
    parser.add_argument(
        "--force-restart",
        action="store_true",
        help="If the gateway is already running in this process, restart it.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="thomas gateway start", add_help=True)
    build_arg_parser(parser)
    args = parser.parse_args(argv)

    if not isinstance(args.config_path, str) or not args.config_path.strip():
        payload = {
            "ok": False,
            "error": {
                "type": "missing_config",
                "message": "Missing --config (and THOMAS_GATEWAY_CONFIG is not set).",
                "details": {"field": "config_path"},
            },
        }
    else:
        payload = run_gateway_start(
            GatewayStartCliOptions(
                config_path=args.config_path,
                force_restart=bool(args.force_restart),
            )
        )

    if args.json:
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_format_human(payload) + "\n")

    return 0 if payload.get("ok") is True else 1


def run(argv: Sequence[str] | None = None) -> int:
    return main(argv)


def invoke(*, config_path: str, force_restart: bool = False) -> dict[str, Any]:
    return run_gateway_start(GatewayStartCliOptions(config_path=config_path, force_restart=force_restart))


def get_command_spec() -> dict[str, Any]:
    # Duck-typed command metadata for Thomas CLI auto-discovery.
    return {
        "group": "gateway",
        "name": "start",
        "help": "Start the gateway process described by a config file.",
        "callable": main,
    }


COMMAND_SPECS = [get_command_spec()]
COMMAND = main
COMMAND_NAME = "start"
GROUP_NAME = "gateway"
