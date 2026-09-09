"""
CLI: nodes api (routes + auth)

This module is intentionally small and automation-friendly.

It prints a machine-readable schema for the Nodes HTTP API and documents
the bearer-token auth contract.

Discovery / integration:
The Thomas CLI parity harness typically imports command modules and calls a
module-level registration hook. Different harnesses use different hook names,
so this module provides several aliases (register/add_parser/register_cli).

Output modes:
- human (default)
- machine-readable JSON via --json
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from thomas.nodes.p051_nodes_api_routes_and_auth import DEFAULT_TOKEN_ENV_VARS, get_nodes_api_schema


class NodesApiCliOk(TypedDict):
    ok: bool
    schema: Mapping[str, Any]


class NodesApiCliErr(TypedDict):
    ok: bool
    error: Mapping[str, Any]


@dataclass(frozen=True)
class AuthConfigProbe:
    ok: bool
    found_in_env: str | None
    expected_env_vars: tuple[str, ...]


def _probe_env_for_token() -> AuthConfigProbe:
    for k in DEFAULT_TOKEN_ENV_VARS:
        v = os.environ.get(k)
        if v and v.strip():
            return AuthConfigProbe(ok=True, found_in_env=k, expected_env_vars=DEFAULT_TOKEN_ENV_VARS)
    return AuthConfigProbe(ok=False, found_in_env=None, expected_env_vars=DEFAULT_TOKEN_ENV_VARS)


def _render_human(schema: Mapping[str, Any]) -> None:
    auth = cast(Mapping[str, Any], schema.get("auth", {}))
    routes = cast(list[Mapping[str, Any]], schema.get("routes", []))
    print("Nodes API")
    print(f"  Version: {schema.get('version')}")
    print(f"  Base prefix: {schema.get('base_prefix')}")
    print()
    print("Auth")
    print(f"  Type: {auth.get('type')}")
    print(f"  Header: {auth.get('header')} {auth.get('scheme')} <token>")
    alt = auth.get("alt_headers") or []
    if alt:
        print(f"  Alternate headers: {', '.join(alt)}")
    envs = auth.get("token_env_vars") or []
    if envs:
        print(f"  Token env vars: {', '.join(envs)}")
    print()
    print("Routes")
    for r in routes:
        print(f"  {r.get('method'):>4} {r.get('path')}  # {r.get('summary')}")


def _payload(prefix: str) -> NodesApiCliOk:
    return {"ok": True, "schema": get_nodes_api_schema(prefix=prefix)}


def _error(code: str, message: str, *, details: Mapping[str, Any] | None = None) -> NodesApiCliErr:
    return {"ok": False, "error": {"code": code, "message": message, "details": dict(details or {})}}


def _run(args: argparse.Namespace) -> int:
    prefix = getattr(args, "prefix", "/api")
    as_json = bool(getattr(args, "json", False))

    if getattr(args, "check_config", False):
        probe = _probe_env_for_token()
        if not probe.ok:
            err = _error(
                "auth_not_configured",
                "No Nodes API auth token found in the environment.",
                details={"expected_any_of_env_vars": list(probe.expected_env_vars)},
            )
            print(json.dumps(err, sort_keys=True) if as_json else err["error"]["message"])
            return 2

    ok = _payload(prefix)
    if as_json:
        print(json.dumps(ok, sort_keys=True))
    else:
        _render_human(ok["schema"])
    return 0


def register(subparsers: Any) -> None:
    """
    Register the `api` subcommand under an existing `nodes` command parser.

    This function is intentionally tolerant of different CLI harness styles:
    it only requires an object with an .add_parser(...) method.
    """
    if not hasattr(subparsers, "add_parser"):
        return

    # Avoid clobbering if another module already registered an "api" command.
    choices = getattr(subparsers, "choices", None)
    if isinstance(choices, MutableMapping) and ("api" in choices):
        return

    p = subparsers.add_parser(
        "api",
        help="Show Nodes API routes and auth requirements.",
        description="Print the Nodes HTTP API schema and auth requirements.",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    p.add_argument("--prefix", default="/api", help="Base prefix for route rendering (default: /api).")
    p.add_argument(
        "--check-config",
        dest="check_config",
        action="store_true",
        help="Exit non-zero if no auth token is configured in the environment.",
    )
    p.set_defaults(func=_run)

    # Backward-ish alias (some users like "api-info")
    if not (isinstance(choices, MutableMapping) and ("api-info" in choices)):
        p2 = subparsers.add_parser(
            "api-info",
            help="Alias for 'api'.",
            description="Alias for 'nodes api'.",
        )
        p2.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
        p2.add_argument("--prefix", default="/api", help="Base prefix for route rendering (default: /api).")
        p2.add_argument(
            "--check-config",
            dest="check_config",
            action="store_true",
            help="Exit non-zero if no auth token is configured in the environment.",
        )
        p2.set_defaults(func=_run)


# Common alternative hook names.
add_parser = register
register_cli = register
