"""
CLI command: gateway state persistence model (Thomas-native).

Intended for discovery by the Thomas CLI command loader.

Supports:
  - Human-readable default output
  - Machine-readable output via --json

Operations:
  - Show persistence model (default)
  - Set persistence model (when --mode is provided)
  - Get gateway state (--get-state)
  - Set gateway state (--set-state '{"k":"v"}')
    - Optional optimistic concurrency via --expected-version
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL_ENV_VARS = ("THOMAS_BASE_URL", "THOMAS_SERVER_URL", "THOMAS_GATEWAY_URL")
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class CliResult:
    ok: bool
    status: int
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(self.payload, indent=2, sort_keys=True)


def _resolve_base_url(args: argparse.Namespace) -> str:
    if getattr(args, "url", None):
        return args.url.rstrip("/")
    for env in DEFAULT_BASE_URL_ENV_VARS:
        val = os.environ.get(env)
        if val:
            return val.rstrip("/")
    return DEFAULT_BASE_URL


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, timeout_s: float = 10.0) -> CliResult:
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, method=method.upper(), data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw.decode("utf-8", errors="replace")}
            return CliResult(ok=True, status=getattr(resp, "status", 200), payload=payload)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", errors="replace")}
        return CliResult(ok=False, status=e.code, payload=payload)
    except urllib.error.URLError as e:
        return CliResult(ok=False, status=0, payload={"error": {"code": "connection_error", "message": str(e)}})


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "p135-gateway-state-persistence-model",
        help="Inspect or configure gateway state persistence, and read/write gateway state.",
    )
    parser.add_argument("--url", help="Base URL for the Thomas server (default from env or http://127.0.0.1:8000)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")

    # Persistence model controls
    parser.add_argument("--mode", choices=["memory", "file"], help="Set persistence mode")
    parser.add_argument("--state-dir", help="Base state directory (file mode persists under <state_dir>/gateway/)")
    parser.add_argument("--max-state-bytes", type=int, help="Maximum serialized state size (bytes)")

    # State controls
    parser.add_argument("--get-state", action="store_true", help="Fetch current gateway state")
    parser.add_argument("--set-state", help="Set gateway state from a JSON object string")
    parser.add_argument(
        "--expected-version", type=int, help="Optimistic concurrency: expected current version for --set-state"
    )

    parser.set_defaults(func=run)
    return parser


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    return build_parser(subparsers)


def run(args: argparse.Namespace) -> int:
    base = _resolve_base_url(args)

    if args.mode:
        body: dict[str, Any] = {"mode": args.mode}
        if args.state_dir:
            body["state_dir"] = args.state_dir
        if args.max_state_bytes is not None:
            body["max_state_bytes"] = args.max_state_bytes
        result = _http_json("POST", f"{base}/v1/gateway/state/persistence-model", body=body)

    elif args.get_state:
        result = _http_json("GET", f"{base}/v1/gateway/state")

    elif args.set_state:
        try:
            parsed = json.loads(args.set_state)
        except json.JSONDecodeError as e:
            err = CliResult(ok=False, status=2, payload={"error": {"code": "invalid_json", "message": str(e)}})
            _emit(err, json_mode=args.json)
            return 2
        if not isinstance(parsed, dict):
            err = CliResult(
                ok=False,
                status=2,
                payload={"error": {"code": "invalid_request", "message": "--set-state must be a JSON object"}},
            )
            _emit(err, json_mode=args.json)
            return 2

        body: dict[str, Any] = {"state": parsed}
        if args.expected_version is not None:
            body["expected_version"] = int(args.expected_version)

        result = _http_json("PUT", f"{base}/v1/gateway/state", body=body)

    else:
        result = _http_json("GET", f"{base}/v1/gateway/state/persistence-model")

    _emit(result, json_mode=args.json)
    return 0 if result.ok else 1


def _emit(result: CliResult, json_mode: bool) -> None:
    out = result.to_json() if json_mode else json.dumps(result.payload, indent=2, sort_keys=True)
    if result.ok:
        sys.stdout.write(out + "\n")
    else:
        sys.stderr.write(out + "\n")
