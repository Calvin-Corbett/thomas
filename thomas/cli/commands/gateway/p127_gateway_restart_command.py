"""
Gateway restart CLI command (Thomas-native).

Requests a gateway restart via the Thomas server API:
    POST /gateway/restart

Machine-readable output:
    --json prints the raw JSON response body.

This module is deliberately self-contained so it can be called from:
- a Thomas CLI command discovery framework, or
- tests/automation via run([...]).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

DEFAULT_ROUTE_PATH = "/gateway/restart"


@dataclass(frozen=True)
class GatewayRestartInput:
    gateway: str = "default"
    force: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"gateway": self.gateway, "force": self.force}


@dataclass(frozen=True)
class GatewayRestartOutput:
    ok: bool
    gateway: str = "default"
    status: str = ""
    method: str = ""
    message: str = ""
    error: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> GatewayRestartOutput:
        ok = bool(data.get("ok", False))
        if ok:
            return cls(
                ok=True,
                gateway=str(data.get("gateway", "default")),
                status=str(data.get("status", "")),
                method=str(data.get("method", "")),
                message=str(data.get("message", "")),
                error=None,
            )
        err = data.get("error")
        if not isinstance(err, dict):
            err = {"code": "external_failure", "message": "Gateway restart failed.", "details": {}}
        return cls(
            ok=False,
            gateway=str(data.get("gateway", "default")) if data.get("gateway") else "default",
            error=err,
        )


class GatewayRestartCliError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _normalize_and_validate_server_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise GatewayRestartCliError("invalid_server_url", "Server URL must use http or https.")

    if parsed.username or parsed.password:
        raise GatewayRestartCliError("invalid_server_url", "Server URL must not include credentials.")

    if parsed.query or parsed.fragment:
        raise GatewayRestartCliError("invalid_server_url", "Server URL must not include query or fragment.")

    if parsed.path not in ("", "/"):
        raise GatewayRestartCliError("invalid_server_url", "Server URL must not include a path.")

    if not parsed.hostname:
        raise GatewayRestartCliError("invalid_server_url", "Server URL must include a hostname.")

    normalized = parsed._replace(fragment="", query="", path="").geturl().rstrip("/")
    if normalized.endswith("://"):
        raise GatewayRestartCliError("invalid_server_url", "Server URL is missing host information.")
    return normalized


def _resolve_server_url(args: argparse.Namespace) -> str:
    def _pick(raw: str) -> str:
        return _normalize_and_validate_server_url(raw.strip())

    server_url = getattr(args, "server_url", None)
    if isinstance(server_url, str) and server_url.strip():
        return _pick(server_url)

    for env_key in ("THOMAS_SERVER_URL", "THOMAS_BASE_URL", "THOMAS_URL"):
        val = os.environ.get(env_key)
        if val and val.strip():
            return _pick(val)

    raise GatewayRestartCliError("missing_config", "Missing server URL. Provide --server-url or set THOMAS_SERVER_URL.")


async def _default_requester(server_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    import aiohttp  # type: ignore

    url = f"{server_url}{DEFAULT_ROUTE_PATH}"
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session, session.post(url, json=payload) as resp:
        try:
            return await resp.json()
        except ImportError:  # noqa: BLE001
            text = await resp.text()
            return {
                "ok": False,
                "error": {
                    "code": "external_failure",
                    "message": "Non-JSON response from server.",
                    "details": {"status": resp.status, "body": text[:200]},
                },
            }


def build_arg_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--gateway", default="default", help="Gateway identifier (default: %(default)s).")
    parser.add_argument("--force", action="store_true", help="Force restart (if supported).")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    parser.add_argument("--server-url", default=None, help="Thomas server base URL (or set THOMAS_SERVER_URL).")
    return parser


def _format_human(out: GatewayRestartOutput) -> str:
    if out.ok:
        msg = out.message or "Gateway restart requested."
        return f"{msg} (gateway={out.gateway})"
    err = out.error or {"code": "external_failure", "message": "Gateway restart failed.", "details": {}}
    return f"{err.get('code', 'external_failure')}: {err.get('message', 'Gateway restart failed.')}"


def run(
    argv: Sequence[str] | None = None,
    *,
    _requester: Callable[[str, dict[str, Any]], Any] | None = None,
    _out: Any | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="thomas gateway restart", add_help=True)
    build_arg_parser(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)

    out_stream = _out if _out is not None else sys.stdout

    try:
        server_url = _resolve_server_url(args)
        inp = GatewayRestartInput(gateway=str(args.gateway), force=bool(args.force))
        payload = inp.to_json()

        requester = _requester or _default_requester
        data = requester(server_url, payload)
        if asyncio.iscoroutine(data):
            data = asyncio.run(data)  # type: ignore[arg-type]

        resp = GatewayRestartOutput.from_mapping(data if isinstance(data, Mapping) else {"ok": False})

        if bool(args.json):
            raw = data if isinstance(data, Mapping) else asdict(resp)
            out_stream.write(json.dumps(raw, sort_keys=True) + "\n")
        else:
            out_stream.write(_format_human(resp) + "\n")

        return 0 if resp.ok else 1
    except GatewayRestartCliError as e:
        if bool(getattr(args, "json", False)):
            out_stream.write(
                json.dumps({"ok": False, "error": {"code": e.code, "message": str(e), "details": {}}}, sort_keys=True)
                + "\n"
            )
        else:
            out_stream.write(f"{e.code}: {e}\n")
        return 2


def get_command_spec() -> dict[str, Any]:
    return {
        "group": "gateway",
        "name": "restart",
        "help": "Restart the gateway.",
        "method": "POST",
        "path": DEFAULT_ROUTE_PATH,
        "supports_json": True,
        "runner": run,
    }


COMMAND_SPEC = get_command_spec()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
