from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Optional, TypedDict, cast

DEFAULT_ROUTE = "/v1/gateway/metrics/snapshot"

COMMAND_NAME = "gateway-metrics-snapshot"


class GatewayMetricsSnapshotRequest(TypedDict, total=False):
    reset: bool
    window_seconds: int


class GatewayMetricsSnapshotErrorInfo(TypedDict, total=False):
    code: str
    message: str
    details: Mapping[str, Any]


class GatewayMetricsSnapshotResponse(TypedDict, total=False):
    ok: bool
    taken_at: str
    source: str
    request: GatewayMetricsSnapshotRequest
    snapshot: Mapping[str, Any]
    error: GatewayMetricsSnapshotErrorInfo


@dataclass(frozen=True)
class GatewayMetricsSnapshotParams:
    reset: bool
    window_seconds: Optional[int]


def build_request_payload(params: GatewayMetricsSnapshotParams) -> GatewayMetricsSnapshotRequest:
    payload: GatewayMetricsSnapshotRequest = {"reset": params.reset}
    if params.window_seconds is not None:
        payload["window_seconds"] = params.window_seconds
    return payload


def _resolve_server_base_url(ctx: Any = None) -> str:
    # 1) Context object hints.
    for attr in ("server_url", "base_url", "url"):
        if ctx is not None and hasattr(ctx, attr):
            value = getattr(ctx, attr)
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip("/")
    if ctx is not None and isinstance(getattr(ctx, "config", None), Mapping):
        cfg = cast(Mapping[str, Any], getattr(ctx, "config"))
        for key in ("server_url", "base_url", "thomas_url", "thomas_server_url"):
            value = cfg.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip("/")

    # 2) Environment variable override.
    env = os.getenv("THOMAS_SERVER_URL") or os.getenv("THOMAS_URL")
    if env and env.strip():
        return env.strip().rstrip("/")

    # 3) Local default.
    return "http://127.0.0.1:8080"


def _in_running_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _is_loopback_ephemeral(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    if parsed.port is None:
        return False
    return int(parsed.port) > 1024


def _fallback_inprocess_snapshot(
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: int,
) -> Optional[GatewayMetricsSnapshotResponse]:
    # When invoked from inside a running event loop (for example tests), loopback
    # HTTP to an in-process aiohttp app can deadlock. Use the registered app hook
    # when available for loopback ephemeral ports.
    if not _in_running_event_loop():
        return None
    if not _is_loopback_ephemeral(url):
        return None

    try:
        from thomas.server.routes.gateway import p138_gateway_metrics_snapshot_command as route_mod
    except Exception:
        return None

    getter = getattr(route_mod, "get_inprocess_snapshotter", None)
    if not callable(getter):
        return None
    snapshotter = getter()
    if not callable(snapshotter):
        return None

    result_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}
    reset = bool(payload.get("reset", False))
    window_seconds = payload.get("window_seconds")

    def _runner() -> None:
        try:
            value = snapshotter(reset=reset, window_seconds=window_seconds)  # type: ignore[misc]
            if hasattr(value, "__await__"):
                value = asyncio.run(cast(Any, value))
            result_box["value"] = value
        except BaseException as e:
            error_box["error"] = e

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=max(1, int(timeout_seconds)))
    if t.is_alive() or error_box:
        return None

    value = result_box.get("value")
    request_payload: GatewayMetricsSnapshotRequest = {"reset": reset}
    if window_seconds is not None:
        request_payload["window_seconds"] = int(window_seconds)
    if isinstance(value, Mapping):
        return {
            "ok": True,
            "source": "app.gateway_metrics_snapshotter",
            "request": request_payload,
            "snapshot": cast(Mapping[str, Any], value),
        }
    return {
        "ok": True,
        "source": "app.gateway_metrics_snapshotter",
        "request": request_payload,
        "snapshot": {"value": value},
    }


def _post_json(url: str, payload: Mapping[str, Any], *, timeout_seconds: int = 15) -> GatewayMetricsSnapshotResponse:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # nosec - intended HTTP client
            raw = resp.read()
            if not raw:
                return {"ok": True}
            decoded = raw.decode("utf-8", errors="replace")
            parsed = json.loads(decoded)
            if isinstance(parsed, Mapping):
                return cast(GatewayMetricsSnapshotResponse, parsed)
            return {"ok": True, "snapshot": {"value": parsed}}
    except urllib.error.HTTPError as e:
        # Prefer JSON error response if present.
        try:
            raw = e.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            if isinstance(parsed, Mapping):
                resp = cast(GatewayMetricsSnapshotResponse, parsed)
            else:
                resp = {"ok": False, "error": {"code": "http_error", "message": "HTTP error."}}
        except Exception:
            resp = {"ok": False, "error": {"code": "http_error", "message": "HTTP error."}}
        if resp.get("ok") is None:
            resp["ok"] = False
        return resp
    except (urllib.error.URLError, TimeoutError, OSError):
        fallback = _fallback_inprocess_snapshot(url, payload, timeout_seconds=timeout_seconds)
        if fallback is not None:
            return fallback
        return {"ok": False, "error": {"code": "server_unreachable", "message": "Unable to reach Thomas server."}}


def execute_gateway_metrics_snapshot(
    params: GatewayMetricsSnapshotParams,
    *,
    server_base_url: Optional[str] = None,
    client: Any = None,
) -> GatewayMetricsSnapshotResponse:
    """
    Execute the command against a running Thomas server.

    If a Thomas-native client object is provided, we attempt to use it. Otherwise we fall back
    to urllib for a simple POST.
    """
    payload = build_request_payload(params)

    if client is not None:
        # Best-effort across different client shapes.
        for method_name in ("post_json", "request_json", "request", "call"):
            method = getattr(client, method_name, None)
            if not callable(method):
                continue
            try:
                resp = method("POST", DEFAULT_ROUTE, json=payload)  # type: ignore[misc]
            except TypeError:
                try:
                    resp = method(DEFAULT_ROUTE, payload)  # type: ignore[misc]
                except TypeError:
                    continue
            if isinstance(resp, Mapping):
                return cast(GatewayMetricsSnapshotResponse, resp)

    base = (server_base_url or _resolve_server_base_url(None)).rstrip("/")
    url = urllib.parse.urljoin(base + "/", DEFAULT_ROUTE.lstrip("/"))
    return _post_json(url, payload)


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Capture a snapshot of Gateway metrics from the Thomas server.",
    )
    parser.add_argument("--reset", action="store_true", help="Reset metrics after snapshot (if supported).")
    parser.add_argument(
        "--window-seconds",
        type=int,
        default=None,
        help="Optional window size (seconds) for rolling snapshot (if supported).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.set_defaults(func=run)
    parser.set_defaults(handler=run)
    parser.set_defaults(_thomas_entrypoint=run)
    return parser


def run(args: argparse.Namespace, ctx: Any = None, **kwargs: Any) -> int:
    params = GatewayMetricsSnapshotParams(
        reset=bool(getattr(args, "reset", False)),
        window_seconds=getattr(args, "window_seconds", None),
    )

    client = kwargs.get("client") or (getattr(ctx, "client", None) if ctx is not None else None)
    server_base_url = kwargs.get("server_base_url") or _resolve_server_base_url(ctx)

    resp = execute_gateway_metrics_snapshot(params, server_base_url=server_base_url, client=client)

    as_json = bool(getattr(args, "json", False))
    if as_json:
        sys.stdout.write(json.dumps(resp, sort_keys=True))
        sys.stdout.write("\n")
    else:
        if resp.get("ok"):
            taken_at = resp.get("taken_at", "")
            source = resp.get("source", "")
            snapshot = resp.get("snapshot", {})
            sys.stdout.write(f"Gateway metrics snapshot taken_at={taken_at} source={source}\n")
            if isinstance(snapshot, Mapping):
                for k in sorted(snapshot.keys()):
                    sys.stdout.write(f"  {k}: {snapshot[k]}\n")
        else:
            err = resp.get("error", {})
            code = err.get("code", "error") if isinstance(err, Mapping) else "error"
            msg = err.get("message", "Command failed.") if isinstance(err, Mapping) else "Command failed."
            sys.stderr.write(f"{code}: {msg}\n")

    return 0 if resp.get("ok") else 1


def get_command_spec() -> Mapping[str, Any]:
    """
    Best-effort metadata for Thomas command discovery systems.
    """
    return {
        "name": COMMAND_NAME,
        "method": "POST",
        "route": DEFAULT_ROUTE,
        "add_parser": add_parser,
        "run": run,
    }
