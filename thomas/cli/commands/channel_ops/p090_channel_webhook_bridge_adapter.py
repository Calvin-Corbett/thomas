"""
CLI: Channel webhook bridge adapter

Registers a channels operation that can send a JSON payload to an HTTP webhook.
Automation friendly:
- --json for machine-readable output
- --schema to print payload JSON Schema

Environment:
- THOMAS_WEBHOOK_BRIDGE_URL can supply the default destination URL.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Optional

try:
    from thomas.marketplace.channels.p090_channel_webhook_bridge_adapter import (
        WebhookBridgeAdapterError,
        WebhookBridgeSendRequest,
        send_via_webhook_bridge,
        webhook_bridge_payload_schema,
    )
except ImportError:  # pragma: no cover
    from thomas.channels.p090_channel_webhook_bridge_adapter import (
    WebhookBridgeAdapterError,
    WebhookBridgeSendRequest,
    send_via_webhook_bridge,
    webhook_bridge_payload_schema,
)

_DEFAULT_ENV_URL = "THOMAS_WEBHOOK_BRIDGE_URL"


def _parse_header_kv(raw: str) -> tuple[str, str]:
    if ":" in raw:
        k, v = raw.split(":", 1)
    elif "=" in raw:
        k, v = raw.split("=", 1)
    else:
        raise WebhookBridgeAdapterError(code="invalid_header", message="Header must be KEY:VALUE or KEY=VALUE.", details={"header": raw})
    k = k.strip()
    v = v.strip()
    if not k:
        raise WebhookBridgeAdapterError(code="invalid_header", message="Header name cannot be empty.", details={"header": raw})
    return k, v


def _load_payload(text: Optional[str], payload_json: Optional[str]) -> Mapping[str, Any]:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
        except json.JSONDecodeError as e:
            raise WebhookBridgeAdapterError(code="invalid_payload_json", message="payload-json must be valid JSON.", details={"error": str(e)}) from e
        if not isinstance(parsed, dict):
            raise WebhookBridgeAdapterError(code="invalid_payload_json", message="payload-json must be a JSON object.", details={"payload_type": type(parsed).__name__})
        payload.update(parsed)
    if text is not None:
        payload["text"] = text
    if "text" not in payload:
        raise WebhookBridgeAdapterError(code="invalid_payload", message="Either positional TEXT or --payload-json with 'text' is required.", details={})
    return payload


def _emit(obj: Any, *, json_mode: bool) -> None:
    if json_mode or (isinstance(obj, dict) and obj.get("ok") is False):
        print(json.dumps(obj, ensure_ascii=False, sort_keys=True))
        return
    if isinstance(obj, dict) and obj.get("ok") is True:
        print(f"ok: delivered via webhook ({obj.get('status_code')})")
        return
    print(obj)


def _run_send(
    *,
    url: Optional[str],
    text: Optional[str],
    payload_json: Optional[str],
    headers: list[str],
    method: str,
    timeout_s: float,
    verify_tls: bool,
    json_mode: bool,
) -> int:
    resolved_url = url or os.getenv(_DEFAULT_ENV_URL)
    payload = _load_payload(text, payload_json)

    hdrs: dict[str, str] = {}
    for raw in headers:
        k, v = _parse_header_kv(raw)
        hdrs[k] = v

    req = WebhookBridgeSendRequest(
        url=(resolved_url or "").strip(),
        payload=payload,
        method=method.upper(),
        headers=hdrs,
        timeout_s=timeout_s,
        verify_tls=verify_tls,
    )

    try:
        result = send_via_webhook_bridge(req)
        _emit(result.to_dict(), json_mode=json_mode)
        return 0
    except WebhookBridgeAdapterError as e:
        _emit({"ok": False, "error": e.to_error_info()}, json_mode=True)
        return 1


def _run_schema(*, json_mode: bool) -> int:
    _emit(webhook_bridge_payload_schema(), json_mode=True)
    return 0


COMMAND_NAME_CANONICAL = "channel-webhook-bridge-adapter"
COMMAND_ALIASES = ("webhook-bridge-adapter", "webhook-bridge")

COMMAND = COMMAND_NAME_CANONICAL
ALIASES = COMMAND_ALIASES


def register(app_or_subparsers: Any) -> None:
    # Typer-like
    if hasattr(app_or_subparsers, "command"):
        _register_typer_like(app_or_subparsers)
        return
    # argparse subparsers
    if hasattr(app_or_subparsers, "add_parser"):
        _register_argparse(app_or_subparsers)
        return
    raise TypeError(f"Unsupported CLI registration target: {type(app_or_subparsers)!r}")


add_to_app = register
add_command = register
register_cli = register
register_command = register


def _register_typer_like(app: Any) -> None:
    import typer

    def cmd(
        text: Optional[str] = typer.Argument(None, help="Message text to deliver (sets payload.text)."),
        url: Optional[str] = typer.Option(None, "--url", help=f"Webhook URL. Can also come from ${_DEFAULT_ENV_URL}."),
        payload_json: Optional[str] = typer.Option(None, "--payload-json", help="Raw JSON object to send. If provided with TEXT, it overwrites payload.text."),
        header: list[str] = typer.Option([], "--header", help="Extra header (KEY:VALUE). Repeatable."),
        method: str = typer.Option("POST", "--method", help="HTTP method (default POST)."),
        timeout_s: float = typer.Option(10.0, "--timeout", help="Timeout seconds."),
        verify_tls: bool = typer.Option(True, "--verify-tls/--no-verify-tls", help="Verify TLS certs for https URLs."),
        json_mode: bool = typer.Option(False, "--json", help="Machine-readable output."),
        schema: bool = typer.Option(False, "--schema", help="Print payload JSON schema and exit."),
        payload_only: bool = typer.Option(False, "--payload-only", help="Do not require 'text' in payload (expert mode)."),
    ) -> None:
        if schema:
            raise typer.Exit(code=_run_schema(json_mode=json_mode))

        if payload_only:
            if payload_json is None:
                _emit({"ok": False, "error": {"code": "invalid_payload_json", "message": "payload-json is required for --payload-only", "details": {}}}, json_mode=True)
                raise typer.Exit(code=1)
            try:
                parsed = json.loads(payload_json)
            except json.JSONDecodeError as e:
                _emit({"ok": False, "error": {"code": "invalid_payload_json", "message": "payload-json must be valid JSON.", "details": {"error": str(e)}}}, json_mode=True)
                raise typer.Exit(code=1)
            if not isinstance(parsed, dict):
                _emit({"ok": False, "error": {"code": "invalid_payload_json", "message": "payload-json must be a JSON object.", "details": {"payload_type": type(parsed).__name__}}}, json_mode=True)
                raise typer.Exit(code=1)
            resolved_url = url or os.getenv(_DEFAULT_ENV_URL)
            hdrs = {k: v for (k, v) in [_parse_header_kv(h) for h in header]}
            req = WebhookBridgeSendRequest(
                url=(resolved_url or "").strip(),
                payload=parsed,
                method=method.upper(),
                headers=hdrs,
                timeout_s=timeout_s,
                verify_tls=verify_tls,
            )
            try:
                result = send_via_webhook_bridge(req)
                _emit(result.to_dict(), json_mode=json_mode)
                raise typer.Exit(code=0)
            except WebhookBridgeAdapterError as e:
                _emit({"ok": False, "error": e.to_error_info()}, json_mode=True)
                raise typer.Exit(code=1)

        raise typer.Exit(
            code=_run_send(
                url=url,
                text=text,
                payload_json=payload_json,
                headers=header,
                method=method,
                timeout_s=timeout_s,
                verify_tls=verify_tls,
                json_mode=json_mode,
            )
        )

    app.command(COMMAND_NAME_CANONICAL, help="Deliver a JSON payload to an HTTP webhook endpoint.")(cmd)
    for alias in COMMAND_ALIASES:
        app.command(alias, help=f"Alias for {COMMAND_NAME_CANONICAL}.")(cmd)


def _register_argparse(subparsers: Any) -> None:
    import argparse

    parser = subparsers.add_parser(
        COMMAND_NAME_CANONICAL,
        help="Deliver a JSON payload to an HTTP webhook endpoint.",
        aliases=list(COMMAND_ALIASES),
    )
    parser.add_argument("text", nargs="?", help="Message text to deliver (sets payload.text).")
    parser.add_argument("--url", default=None, help=f"Webhook URL. Can also come from ${_DEFAULT_ENV_URL}.")
    parser.add_argument("--payload-json", dest="payload_json", default=None, help="Raw JSON object to send.")
    parser.add_argument("--header", dest="headers", action="append", default=[], help="Extra header (KEY:VALUE). Repeatable.")
    parser.add_argument("--method", default="POST", help="HTTP method (default POST).")
    parser.add_argument("--timeout", dest="timeout_s", type=float, default=10.0, help="Timeout seconds (default 10).")
    parser.add_argument("--verify-tls", dest="verify_tls", action=argparse.BooleanOptionalAction, default=True, help="Verify TLS certs for https URLs.")
    parser.add_argument("--json", dest="json_mode", action="store_true", help="Machine-readable output.")
    parser.add_argument("--schema", dest="schema", action="store_true", help="Print payload JSON schema and exit.")
    parser.add_argument("--payload-only", dest="payload_only", action="store_true", help="Do not require 'text' in payload.")

    def _handler(ns: argparse.Namespace) -> int:
        if ns.schema:
            return _run_schema(json_mode=ns.json_mode)

        if ns.payload_only:
            if not ns.payload_json:
                _emit({"ok": False, "error": {"code": "invalid_payload_json", "message": "payload-json is required for --payload-only", "details": {}}}, json_mode=True)
                return 1
            try:
                parsed = json.loads(ns.payload_json)
            except json.JSONDecodeError as e:
                _emit({"ok": False, "error": {"code": "invalid_payload_json", "message": "payload-json must be valid JSON.", "details": {"error": str(e)}}}, json_mode=True)
                return 1
            if not isinstance(parsed, dict):
                _emit({"ok": False, "error": {"code": "invalid_payload_json", "message": "payload-json must be a JSON object.", "details": {"payload_type": type(parsed).__name__}}}, json_mode=True)
                return 1
            resolved_url = ns.url or os.getenv(_DEFAULT_ENV_URL)
            hdrs = {k: v for (k, v) in [_parse_header_kv(h) for h in (ns.headers or [])]}
            req = WebhookBridgeSendRequest(
                url=(resolved_url or "").strip(),
                payload=parsed,
                method=str(ns.method).upper(),
                headers=hdrs,
                timeout_s=float(ns.timeout_s),
                verify_tls=bool(ns.verify_tls),
            )
            try:
                res = send_via_webhook_bridge(req)
                _emit(res.to_dict(), json_mode=bool(ns.json_mode))
                return 0
            except WebhookBridgeAdapterError as e:
                _emit({"ok": False, "error": e.to_error_info()}, json_mode=True)
                return 1

        return _run_send(
            url=ns.url,
            text=ns.text,
            payload_json=ns.payload_json,
            headers=list(ns.headers or []),
            method=ns.method,
            timeout_s=float(ns.timeout_s),
            verify_tls=bool(ns.verify_tls),
            json_mode=bool(ns.json_mode),
        )

    parser.set_defaults(_thomas_handler=_handler)
