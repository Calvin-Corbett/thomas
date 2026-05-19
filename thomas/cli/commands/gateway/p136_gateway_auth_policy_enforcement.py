from __future__ import annotations

"""\
CLI helper for Gateway auth policy enforcement.

Automation-friendly:
- describe active policy (derived from environment variables)
- evaluate a token against that policy

Exit codes:
- 0: allowed / success
- 2: denied (missing/invalid token while policy is active)
- 1: policy/config/other error
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from thomas.server.routes.gateway.p136_gateway_auth_policy_enforcement import (
    GatewayAuthPolicy,
    GatewayAuthPolicyConfigError,
    GatewayAuthPolicyError,
    GatewayAuthPolicyExternalError,
    constant_time_any_match,
    load_gateway_auth_policy,
)


@dataclass(frozen=True)
class CliEvaluationResult:
    allowed: bool
    code: str
    message: str
    policy_mode: str
    policy_scope: str
    token_configured: bool
    rate_limit_enabled: bool
    rate_limit_max_failures: int
    rate_limit_window_seconds: int

    def to_json(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "message": self.message,
            "policy": {
                "mode": self.policy_mode,
                "scope": self.policy_scope,
                "token_configured": self.token_configured,
                "rate_limit": {
                    "enabled": self.rate_limit_enabled,
                    "max_failures": self.rate_limit_max_failures,
                    "window_seconds": self.rate_limit_window_seconds,
                },
            },
        }


def _result(
    policy: GatewayAuthPolicy,
    *,
    allowed: bool,
    code: str,
    message: str,
    token_configured: bool,
) -> CliEvaluationResult:
    return CliEvaluationResult(
        allowed=allowed,
        code=code,
        message=message,
        policy_mode=policy.mode,
        policy_scope=policy.scope,
        token_configured=token_configured,
        rate_limit_enabled=policy.rate_limit_enabled,
        rate_limit_max_failures=policy.rate_limit_max_failures,
        rate_limit_window_seconds=policy.rate_limit_window_seconds,
    )


def _evaluate_token(policy: GatewayAuthPolicy, presented_token: str | None) -> CliEvaluationResult:
    if not policy.required:
        return _result(
            policy,
            allowed=True,
            code="gateway_auth_disabled",
            message="gateway auth is disabled",
            token_configured=bool(policy.tokens),
        )

    if policy.mode == "token":
        if not policy.tokens:
            return _result(
                policy,
                allowed=False,
                code="gateway_auth_misconfigured",
                message="gateway auth policy requires a token but none is configured",
                token_configured=False,
            )
        if not presented_token:
            return _result(
                policy,
                allowed=False,
                code="gateway_auth_missing",
                message="missing gateway authentication token",
                token_configured=True,
            )
        if not constant_time_any_match(presented_token, policy.tokens):
            return _result(
                policy,
                allowed=False,
                code="gateway_auth_invalid",
                message="invalid gateway authentication token",
                token_configured=True,
            )
        return _result(
            policy,
            allowed=True,
            code="gateway_auth_ok",
            message="token accepted",
            token_configured=True,
        )

    return _result(
        policy,
        allowed=False,
        code="gateway_auth_misconfigured",
        message="unsupported gateway auth policy mode",
        token_configured=bool(policy.tokens),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="thomas gateway auth-policy", add_help=True)
    p.add_argument("--token", default=None, help="Gateway token to evaluate (optional)")
    p.add_argument("--describe", action="store_true", help="Print policy info and exit")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)

    try:
        policy = load_gateway_auth_policy(None)
    except (GatewayAuthPolicyConfigError, GatewayAuthPolicyExternalError, GatewayAuthPolicyError) as e:
        payload = {"allowed": False, "code": "gateway_auth_policy_error", "message": str(e)}
        if args.json:
            sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        else:
            sys.stderr.write(payload["message"] + "\n")
        return 1

    if args.describe:
        out = {
            "mode": policy.mode,
            "required": policy.required,
            "scope": policy.scope,
            "token_configured": bool(policy.tokens),
            "allow_query_param": policy.allow_query_param,
            "exempt_paths": list(policy.exempt_paths),
            "rate_limit": {
                "enabled": policy.rate_limit_enabled,
                "max_failures": policy.rate_limit_max_failures,
                "window_seconds": policy.rate_limit_window_seconds,
            },
        }
        if args.json:
            sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
        else:
            sys.stdout.write(json.dumps(out, indent=2, sort_keys=True) + "\n")
        return 0

    result = _evaluate_token(policy, args.token)
    if args.json:
        sys.stdout.write(json.dumps(result.to_json(), sort_keys=True) + "\n")
    else:
        prefix = "ALLOWED" if result.allowed else "DENIED"
        sys.stdout.write(f"{prefix}: {result.message} (mode={result.policy_mode}, scope={result.policy_scope})\n")

    if result.allowed:
        return 0
    if result.code in ("gateway_auth_missing", "gateway_auth_invalid"):
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
