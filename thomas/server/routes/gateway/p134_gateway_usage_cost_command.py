"""Gateway usage-cost command (server route).

A Thomas-native gateway command that queries an upstream Gateway service for
aggregated usage (requests + tokens) and cost over a date range.

Design goals:
- Deterministic, machine-readable errors
- Stable output contract even if upstream payloads vary
- Shared core logic usable by both server route and CLI
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Optional, TypedDict, cast
from collections.abc import Mapping, Sequence

import aiohttp
from aiohttp import web


class GatewayUsageCostBreakdownRow(TypedDict, total=False):
    """A single breakdown row (per-day / per-model / per-project etc)."""

    date: str
    model: str
    project: str

    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class GatewayUsageCostQuery:
    """Input contract for the usage-cost command."""

    start_date: date
    end_date: date
    project: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class GatewayUsageCostReport:
    """Output contract for the usage-cost command."""

    start_date: str
    end_date: str
    currency: str
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_usd: float
    breakdown: Sequence[GatewayUsageCostBreakdownRow]

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], asdict(self))


@dataclass(frozen=True)
class GatewayUsageCostError(Exception):
    """Deterministic error for this command."""

    code: str
    message: str
    http_status: int = 400
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {"code": self.code, "message": self.message},
        }
        if self.details:
            payload["error"]["details"] = dict(self.details)
        return payload


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception as exc:  # noqa: BLE001
        raise GatewayUsageCostError(
            code="invalid_date",
            message=f"{field_name} must be in YYYY-MM-DD format",
            http_status=400,
            details={"field": field_name, "value": value},
        ) from exc


def parse_usage_cost_query(payload: Mapping[str, Any]) -> GatewayUsageCostQuery:
    """Parse + validate a JSON payload/querystring mapping into a query."""

    start_raw = payload.get("start_date")
    end_raw = payload.get("end_date")

    if not isinstance(start_raw, str) or not start_raw.strip():
        raise GatewayUsageCostError(
            code="missing_start_date",
            message="start_date is required",
            http_status=400,
        )

    if end_raw is None or (isinstance(end_raw, str) and not end_raw.strip()):
        end_raw = start_raw

    if not isinstance(end_raw, str) or not end_raw.strip():
        raise GatewayUsageCostError(
            code="missing_end_date",
            message="end_date must be a string in YYYY-MM-DD format",
            http_status=400,
        )

    start_d = _parse_date(start_raw.strip(), field_name="start_date")
    end_d = _parse_date(end_raw.strip(), field_name="end_date")
    if end_d < start_d:
        raise GatewayUsageCostError(
            code="invalid_date_range",
            message="end_date must be on or after start_date",
            http_status=400,
            details={"start_date": start_raw, "end_date": end_raw},
        )

    project = payload.get("project")
    if project is not None and not isinstance(project, str):
        raise GatewayUsageCostError(
            code="invalid_project",
            message="project must be a string",
            http_status=400,
        )

    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise GatewayUsageCostError(
            code="invalid_model",
            message="model must be a string",
            http_status=400,
        )

    return GatewayUsageCostQuery(
        start_date=start_d,
        end_date=end_d,
        project=cast(str | None, project),
        model=cast(str | None, model),
    )


def _resolve_gateway_config(
    *,
    app: Mapping[str, Any] | None = None,
    gateway_url: str | None = None,
    gateway_api_key: str | None = None,
) -> tuple[str, str]:
    """Resolve gateway URL + API key.

    Resolution order:
    1) Explicit function args
    2) Environment variables
    3) Best-effort app config mappings (if present)

    Note: We prefer env over app because env is commonly used in tests/CI and is
    easy to reason about deterministically.
    """

    url = (gateway_url or "").strip() or None
    key = (gateway_api_key or "").strip() or None

    if url is None:
        url = (
            os.environ.get("THOMAS_GATEWAY_URL")
            or os.environ.get("GATEWAY_URL")
            or ""
        ).strip() or None
    if key is None:
        key = (
            os.environ.get("THOMAS_GATEWAY_API_KEY")
            or os.environ.get("GATEWAY_API_KEY")
            or ""
        ).strip() or None

    # Best-effort: app may carry configuration.
    if app and (url is None or key is None):
        candidates: list[Mapping[str, Any]] = []
        if isinstance(app.get("config"), Mapping):
            candidates.append(cast(Mapping[str, Any], app["config"]))
        if isinstance(app.get("settings"), Mapping):
            candidates.append(cast(Mapping[str, Any], app["settings"]))
        if isinstance(app.get("cfg"), Mapping):
            candidates.append(cast(Mapping[str, Any], app["cfg"]))
        if isinstance(app.get("gateway"), Mapping):
            candidates.append(cast(Mapping[str, Any], app["gateway"]))

        for cfg in candidates:
            if url is None:
                v = cfg.get("gateway_url") or cfg.get("url") or cfg.get("gatewayUrl")
                if isinstance(v, str) and v.strip():
                    url = v.strip()
            if key is None:
                v = (
                    cfg.get("gateway_api_key")
                    or cfg.get("api_key")
                    or cfg.get("token")
                    or cfg.get("apiKey")
                )
                if isinstance(v, str) and v.strip():
                    key = v.strip()
            if url is not None and key is not None:
                break

    if url is None:
        raise GatewayUsageCostError(
            code="missing_gateway_url",
            message=(
                "Gateway URL is not configured (set THOMAS_GATEWAY_URL or pass --gateway-url)"
            ),
            http_status=500,
        )
    if key is None:
        raise GatewayUsageCostError(
            code="missing_gateway_api_key",
            message=(
                "Gateway API key is not configured (set THOMAS_GATEWAY_API_KEY or pass --gateway-api-key)"
            ),
            http_status=500,
        )
    return url, key


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _build_report(query: GatewayUsageCostQuery, raw: Mapping[str, Any]) -> GatewayUsageCostReport:
    """Normalize upstream payload into our stable output contract."""

    currency = raw.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        currency = "USD"

    breakdown_any = raw.get("breakdown") or raw.get("data") or raw.get("items") or []
    breakdown: list[GatewayUsageCostBreakdownRow] = []
    if isinstance(breakdown_any, list):
        for item in breakdown_any:
            if isinstance(item, Mapping):
                breakdown.append(cast(GatewayUsageCostBreakdownRow, dict(item)))

    requests = (
        _coerce_int(raw.get("requests"))
        or _coerce_int(raw.get("total_requests"))
        or _coerce_int(raw.get("request_count"))
    )
    input_tokens = (
        _coerce_int(raw.get("input_tokens"))
        or _coerce_int(raw.get("prompt_tokens"))
        or _coerce_int(raw.get("total_input_tokens"))
    )
    output_tokens = (
        _coerce_int(raw.get("output_tokens"))
        or _coerce_int(raw.get("completion_tokens"))
        or _coerce_int(raw.get("total_output_tokens"))
    )
    total_tokens = _coerce_int(raw.get("total_tokens"))
    total_cost_usd = (
        _coerce_float(raw.get("total_cost_usd"))
        or _coerce_float(raw.get("cost_usd"))
        or _coerce_float(raw.get("total_cost"))
        or _coerce_float(raw.get("cost"))
    )

    if breakdown and (
        requests is None
        or input_tokens is None
        or output_tokens is None
        or total_cost_usd is None
        or total_tokens is None
    ):
        sum_requests = 0
        sum_in = 0
        sum_out = 0
        sum_total = 0
        sum_cost = 0.0
        saw_cost = False

        for row in breakdown:
            sum_requests += _coerce_int(row.get("requests")) or 0
            sum_in += _coerce_int(row.get("input_tokens")) or 0
            sum_out += _coerce_int(row.get("output_tokens")) or 0
            sum_total += _coerce_int(row.get("total_tokens")) or 0
            rc = _coerce_float(row.get("cost_usd"))
            if rc is not None:
                sum_cost += rc
                saw_cost = True

        if requests is None:
            requests = sum_requests
        if input_tokens is None:
            input_tokens = sum_in
        if output_tokens is None:
            output_tokens = sum_out
        if total_tokens is None:
            total_tokens = sum_total if sum_total else (sum_in + sum_out)
        if total_cost_usd is None and saw_cost:
            total_cost_usd = sum_cost

    requests = requests if requests is not None else 0
    input_tokens = input_tokens if input_tokens is not None else 0
    output_tokens = output_tokens if output_tokens is not None else 0
    total_tokens = total_tokens if total_tokens is not None else (input_tokens + output_tokens)

    if total_cost_usd is None:
        raise GatewayUsageCostError(
            code="gateway_unexpected_response",
            message="Gateway response did not include cost information",
            http_status=502,
            details={"available_keys": sorted(list(raw.keys()))},
        )

    return GatewayUsageCostReport(
        start_date=query.start_date.isoformat(),
        end_date=query.end_date.isoformat(),
        currency=currency,
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        total_cost_usd=float(total_cost_usd),
        breakdown=breakdown,
    )


async def _fetch_gateway_usage_cost(
    *,
    gateway_url: str,
    gateway_api_key: str,
    query: GatewayUsageCostQuery,
    timeout_s: float,
) -> Mapping[str, Any]:
    """Call the upstream Gateway service.

    Defaults: POST to /usage-cost with JSON payload.

    Overrides (to tolerate heterogeneous deployments):
    - THOMAS_GATEWAY_USAGE_COST_PATH (default /usage-cost)
    - THOMAS_GATEWAY_USAGE_COST_METHOD (default POST; allowed GET/POST)
    """

    endpoint_path = (os.environ.get("THOMAS_GATEWAY_USAGE_COST_PATH") or "/usage-cost").strip()
    if not endpoint_path.startswith("/"):
        endpoint_path = "/" + endpoint_path
    method = (os.environ.get("THOMAS_GATEWAY_USAGE_COST_METHOD") or "POST").upper().strip()

    url = gateway_url.rstrip("/") + endpoint_path
    headers = {
        "Authorization": f"Bearer {gateway_api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "start_date": query.start_date.isoformat(),
        "end_date": query.end_date.isoformat(),
    }
    if query.project:
        payload["project"] = query.project
    if query.model:
        payload["model"] = query.model

    timeout = aiohttp.ClientTimeout(total=timeout_s)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if method == "GET":
                async with session.get(url, headers=headers, params=payload) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise GatewayUsageCostError(
                            code="gateway_http_error",
                            message=f"Gateway request failed with HTTP {resp.status}",
                            http_status=502,
                            details={"status": resp.status, "body": text[:1000]},
                        )
                    try:
                        return cast(Mapping[str, Any], json.loads(text))
                    except json.JSONDecodeError as exc:
                        raise GatewayUsageCostError(
                            code="gateway_invalid_json",
                            message="Gateway returned invalid JSON",
                            http_status=502,
                            details={"body": text[:1000]},
                        ) from exc
            else:
                async with session.post(url, headers=headers, json=payload) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise GatewayUsageCostError(
                            code="gateway_http_error",
                            message=f"Gateway request failed with HTTP {resp.status}",
                            http_status=502,
                            details={"status": resp.status, "body": text[:1000]},
                        )
                    try:
                        return cast(Mapping[str, Any], json.loads(text))
                    except json.JSONDecodeError as exc:
                        raise GatewayUsageCostError(
                            code="gateway_invalid_json",
                            message="Gateway returned invalid JSON",
                            http_status=502,
                            details={"body": text[:1000]},
                        ) from exc
    except asyncio.TimeoutError as exc:
        raise GatewayUsageCostError(
            code="gateway_timeout",
            message="Gateway request timed out",
            http_status=504,
        ) from exc
    except aiohttp.ClientError as exc:
        raise GatewayUsageCostError(
            code="gateway_unreachable",
            message="Gateway request failed",
            http_status=502,
            details={"exception": str(exc)},
        ) from exc


async def run_gateway_usage_cost(
    *,
    query: GatewayUsageCostQuery,
    app: Mapping[str, Any] | None = None,
    gateway_url: str | None = None,
    gateway_api_key: str | None = None,
    timeout_s: float | None = None,
) -> GatewayUsageCostReport:
    """Execute the command (shared by server + CLI)."""

    timeout_val = timeout_s
    if timeout_val is None:
        t = os.environ.get("THOMAS_GATEWAY_TIMEOUT_S")
        timeout_val = float(t) if t else 30.0

    resolved_url, resolved_key = _resolve_gateway_config(
        app=app,
        gateway_url=gateway_url,
        gateway_api_key=gateway_api_key,
    )

    try:
        raw = await _fetch_gateway_usage_cost(
            gateway_url=resolved_url,
            gateway_api_key=resolved_key,
            query=query,
            timeout_s=float(timeout_val),
        )
    except GatewayUsageCostError:
        raise
    except aiohttp.ClientError as exc:
        raise GatewayUsageCostError(
            code="gateway_unreachable",
            message="Gateway request failed",
            http_status=502,
            details={"exception": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise GatewayUsageCostError(
            code="gateway_unexpected_failure",
            message="Gateway request failed",
            http_status=502,
            details={"exception": str(exc)},
        ) from exc

    return _build_report(query, raw)


def _json_response(payload: Any, *, status: int = 200) -> web.Response:
    """Prefer shared json_response helper if available; fall back to aiohttp."""
    try:
        from thomas.server.routes import core_aiohttp  # type: ignore

        json_resp = getattr(core_aiohttp, "json_response", None)
        if callable(json_resp):
            try:
                return json_resp(payload, status=status)
            except TypeError:
                try:
                    return json_resp(payload, status)
                except TypeError:
                    return json_resp(payload)
    except Exception:
        pass
    return web.json_response(payload, status=status)


def _error_response(err: GatewayUsageCostError) -> web.Response:
    return _json_response(err.to_dict(), status=err.http_status)


routes = web.RouteTableDef()


@routes.post("/gateway/usage-cost")
@routes.get("/gateway/usage-cost")
async def gateway_usage_cost_route(request: web.Request) -> web.Response:
    """HTTP route handler.

    GET: querystring params
    POST: JSON body
    """

    try:
        if request.method == "GET":
            payload = dict(request.rel_url.query)
        else:
            try:
                body = await request.json()
            except Exception as exc:  # noqa: BLE001
                raise GatewayUsageCostError(
                    code="invalid_json",
                    message="Request body must be valid JSON",
                    http_status=400,
                ) from exc
            if not isinstance(body, Mapping):
                raise GatewayUsageCostError(
                    code="invalid_json",
                    message="Request body must be a JSON object",
                    http_status=400,
                )
            payload = cast(Mapping[str, Any], body)

        query = parse_usage_cost_query(payload)
        report = await run_gateway_usage_cost(query=query, app=cast(Mapping[str, Any], request.app))
        return _json_response({"ok": True, "data": report.to_dict()}, status=200)

    except GatewayUsageCostError as err:
        return _error_response(err)


# Common loader conventions for Thomas route registries.
ROUTES = routes


def register(app: web.Application) -> None:
    app.add_routes(routes)


def get_routes() -> web.RouteTableDef:
    return routes
