"""CLI command: report whether a Gateway is configured.

Automation-friendly behavior:
  - Default is an offline check (reads config from disk/env)
  - Optional --url probes a running Gateway over HTTP
  - --json emits a stable machine-readable object

Exit codes:
  - 0 = configured
  - 2 = not configured
  - 3 = could not determine (invalid input or network failure)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, TypedDict

from thomas.server.routes.gateway.p132_gateway_configured_command import (
    REASON_INVALID_CONFIG,
    REASON_MISSING_CONFIG,
    REASON_MISSING_GATEWAY_MODE,
    GatewayConfiguredStatus,
    evaluate_gateway_configured,
)

PROMPT_ID = "p132"

CLI_REASON_EXTERNAL_FAILURE = "external_failure"
CLI_REASON_INVALID_INPUT = "invalid_input"


class GatewayConfiguredCliOutput(TypedDict, total=False):
    configured: bool
    source: str
    reason: str | None
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class GatewayConfiguredCliResult:
    configured: bool
    source: str
    reason: str | None
    message: str
    details: dict[str, Any]

    def to_output(self) -> GatewayConfiguredCliOutput:
        return {
            "configured": self.configured,
            "source": self.source,
            "reason": self.reason,
            "message": self.message,
            "details": dict(self.details),
        }


def _status_to_cli(status: GatewayConfiguredStatus) -> GatewayConfiguredCliResult:
    return GatewayConfiguredCliResult(
        configured=status.configured,
        source=status.source,
        reason=status.reason,
        message=status.message,
        details={
            "gateway_mode": status.gateway_mode,
            "config_path": status.config_path,
            "missing": list(status.missing),
        },
    )


def _fetch_remote(url: str, *, timeout_s: float = 2.0) -> GatewayConfiguredCliResult:
    """Probe a running Gateway instance.

    We try multiple candidate paths to be resilient to router prefixing.
    """
    base = url.rstrip("/")
    candidate_paths = ("/gateway/configured", "/configured")

    last_error: str | None = None
    for path in candidate_paths:
        endpoint = f"{base}{path}"
        try:
            req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            if not isinstance(data, dict) or "configured" not in data:
                raise ValueError("Unexpected response shape")

            configured = bool(data.get("configured"))
            reason = data.get("reason")
            message = str(data.get("message") or "")
            details = {k: v for k, v in data.items() if k not in {"configured", "reason", "message"}}

            return GatewayConfiguredCliResult(
                configured=configured,
                source="remote",
                reason=reason,
                message=message or ("Gateway is configured." if configured else "Gateway is not configured."),
                details=details,
            )
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = str(e)
            break
        except Exception as e:
            last_error = str(e)

    return GatewayConfiguredCliResult(
        configured=False,
        source="remote",
        reason=CLI_REASON_EXTERNAL_FAILURE,
        message="Unable to reach the Gateway configured endpoint.",
        details={"url": url, "error": last_error or "unknown"},
    )


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Argparse integration hook."""
    parser = subparsers.add_parser("configured", help="Report whether the Gateway is configured")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--config-path", default=None, help="Override config path used for offline check")
    parser.add_argument("--url", default=None, help="Probe a running Gateway base URL (e.g. http://127.0.0.1:8000)")
    parser.add_argument("--timeout", type=float, default=2.0, help="Network timeout in seconds for --url probes")
    parser.set_defaults(func=_run_from_parsed_args)
    return parser


add_parser = build_parser  # common alias


def _run_from_parsed_args(args: argparse.Namespace) -> int:
    return run(json_mode=bool(args.json), config_path=args.config_path, url=args.url, timeout_s=float(args.timeout))


def run(*, json_mode: bool = False, config_path: str | None = None, url: str | None = None, timeout_s: float = 2.0) -> int:
    if url is not None:
        if not (url.startswith("http://") or url.startswith("https://")):
            result = GatewayConfiguredCliResult(
                configured=False,
                source="remote",
                reason=CLI_REASON_INVALID_INPUT,
                message="Invalid --url (expected http:// or https://).",
                details={"url": url},
            )
            _emit(result, json_mode=json_mode)
            return 3

        result = _fetch_remote(url, timeout_s=timeout_s)
        _emit(result, json_mode=json_mode)
        if result.reason == CLI_REASON_EXTERNAL_FAILURE:
            return 3
        return 0 if result.configured else 2

    # Offline check.
    status = evaluate_gateway_configured({}, config_path_override=config_path)
    result = _status_to_cli(status)
    _emit(result, json_mode=json_mode)
    return 0 if result.configured else 2


def _emit(result: GatewayConfiguredCliResult, *, json_mode: bool) -> None:
    if json_mode:
        sys.stdout.write(json.dumps(result.to_output(), sort_keys=True) + "\n")
        return

    sys.stdout.write(result.message.rstrip() + "\n")
    if not result.configured:
        missing = result.details.get("missing")
        if missing:
            sys.stdout.write(f"Missing: {', '.join(missing)}\n")
        cfg_path = result.details.get("config_path")
        if cfg_path:
            sys.stdout.write(f"Config path: {cfg_path}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thomas gateway configured")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config-path", default=None)
    parser.add_argument("--url", default=None)
    parser.add_argument("--timeout", type=float, default=2.0)
    ns = parser.parse_args(list(argv) if argv is not None else None)
    return run(json_mode=ns.json, config_path=ns.config_path, url=ns.url, timeout_s=ns.timeout)


COMMAND = {"id": PROMPT_ID, "group": "gateway", "name": "configured", "main": main}
