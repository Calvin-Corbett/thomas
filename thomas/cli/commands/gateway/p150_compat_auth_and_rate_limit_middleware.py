"""P150 - Compat auth and rate-limit middleware (CLI helper).

This is an introspection command for automation:
  - loads env-driven config
  - prints a machine-readable JSON status with --json

It does not mutate server config.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from thomas.server.routes.gateway.p150_compat_auth_and_rate_limit_middleware import (
    compat_security_status_json,
    load_compat_security_from_env,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="thomas gateway compat-security", add_help=True)
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return p


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    scope, auth, ratelimit = load_compat_security_from_env()
    payload: dict[str, Any] = compat_security_status_json(scope, auth, ratelimit)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("Compat security config")
    print(f"- Path prefixes: {', '.join(payload['scope']['path_prefixes'])}")
    print(f"- Auth enabled: {payload['auth']['enabled']}")
    print(f"- Tokens configured: {payload['auth']['tokens_configured']}")
    print(f"- Rate limit enabled: {payload['ratelimit']['enabled']}")
    print(f"- Rate limit rps: {payload['ratelimit']['rps']}")
    print(f"- Rate limit burst: {payload['ratelimit']['burst']}")
    return 0


__all__ = ["run", "build_parser"]
