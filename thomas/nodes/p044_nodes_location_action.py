"""
P044 - Nodes location action (Thomas-native)

Implements a small, well-typed "get node location" action usable by both CLI and HTTP layers.

Key properties:
- Clear input/output contracts
- Deterministic, structured errors (code/message/details)
- Minimal assumptions about Thomas gateway/client objects: callers provide an "invoker"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import inspect
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Literal,
    Mapping,
    Optional,
    Protocol,
    Tuple,
    TypedDict,
    Union,
    cast,
)

DesiredAccuracy = Literal["coarse", "balanced", "precise"]

NODE_COMMAND = "location.get"


class NodeInvoker(Protocol):
    """Minimal protocol for something that can invoke a node command."""

    def node_invoke(  # pragma: no cover - protocol definition only
        self,
        node: str,
        command: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        timeout_ms: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any: ...


class NodesLocationActionRequest(TypedDict, total=False):
    node: str
    accuracy: DesiredAccuracy
    max_age_ms: int
    location_timeout_ms: int
    invoke_timeout_ms: int
    idempotency_key: str


class NodesLocationActionErrorPayload(TypedDict):
    code: str
    message: str
    details: Dict[str, Any]


class NodesLocationActionResponseOk(TypedDict):
    ok: Literal[True]
    result: Dict[str, Any]


class NodesLocationActionResponseErr(TypedDict):
    ok: Literal[False]
    error: NodesLocationActionErrorPayload


NodesLocationActionResponse = Union[NodesLocationActionResponseOk, NodesLocationActionResponseErr]


@dataclass(frozen=True)
class NodesLocationActionInput:
    """Input contract for the Nodes location action."""

    node: str
    accuracy: DesiredAccuracy = "balanced"
    max_age_ms: int = 15_000
    location_timeout_ms: int = 10_000
    invoke_timeout_ms: Optional[int] = None
    idempotency_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodesLocationActionOutput:
    """Output contract for the Nodes location action."""

    lat: float
    lon: float
    accuracy_meters: Optional[float] = None
    altitude_meters: Optional[float] = None
    speed_mps: Optional[float] = None
    heading_deg: Optional[float] = None
    timestamp: str = ""
    is_precise: Optional[bool] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "NodesLocationActionOutput":
        """Rehydrate from a JSON/dict form (used by CLI tests)."""
        return NodesLocationActionOutput(
            lat=float(raw.get("lat")),
            lon=float(raw.get("lon")),
            accuracy_meters=cast(Optional[float], raw.get("accuracy_meters")),
            altitude_meters=cast(Optional[float], raw.get("altitude_meters")),
            speed_mps=cast(Optional[float], raw.get("speed_mps")),
            heading_deg=cast(Optional[float], raw.get("heading_deg")),
            timestamp=str(raw.get("timestamp") or ""),
            is_precise=cast(Optional[bool], raw.get("is_precise")),
            source=cast(Optional[str], raw.get("source")),
        )


class NodesLocationActionError(Exception):
    """Deterministic error with a stable code/message for automation."""

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details: Dict[str, Any] = dict(details or {})

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code}: {self.message}"

    def to_dict(self) -> NodesLocationActionErrorPayload:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


def _require_non_empty_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NodesLocationActionError("invalid_input", f"{field} must be a non-empty string")
    return value.strip()


def _coerce_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise NodesLocationActionError("invalid_input", f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.strip()
        if not v:
            raise NodesLocationActionError("invalid_input", f"{field} must be an integer")
        try:
            return int(v)
        except ValueError as e:
            raise NodesLocationActionError("invalid_input", f"{field} must be an integer") from e
    raise NodesLocationActionError("invalid_input", f"{field} must be an integer")


def _require_non_negative_int(value: Any, *, field: str) -> int:
    iv = _coerce_int(value, field=field)
    if iv < 0:
        raise NodesLocationActionError("invalid_input", f"{field} must be an integer >= 0")
    return iv


def _require_positive_int(value: Any, *, field: str) -> int:
    iv = _coerce_int(value, field=field)
    if iv <= 0:
        raise NodesLocationActionError("invalid_input", f"{field} must be an integer > 0")
    return iv


def _normalize_accuracy(value: Any) -> DesiredAccuracy:
    v = _require_non_empty_str(value, field="accuracy").lower()
    if v not in ("coarse", "balanced", "precise"):
        raise NodesLocationActionError("invalid_input", "accuracy must be one of: coarse, balanced, precise")
    return cast(DesiredAccuracy, v)


def _coerce_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise NodesLocationActionError("invalid_response", f"{field} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as e:
            raise NodesLocationActionError("invalid_response", f"{field} must be a number") from e
    raise NodesLocationActionError("invalid_response", f"{field} must be a number")


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _coerce_timestamp(value: Any) -> str:
    # Prefer passing through ISO8601 strings; accept epoch ms/seconds.
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        # Heuristic: > 1e11 is likely ms since epoch.
        if ts > 1e11:
            ts /= 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    raise NodesLocationActionError("invalid_response", "timestamp is required")


def _maybe_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) else None


def _get_any(payload: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in payload:
            return payload[k]
    return None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await cast(Awaitable[Any], value)
    return value


def _call_with_accepted_kwargs(fn: Callable[..., Any], kwargs: Mapping[str, Any]) -> Any:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**kwargs)

    accepted: Dict[str, Any] = {}
    for name in sig.parameters.keys():
        if name in kwargs:
            accepted[name] = kwargs[name]
    return fn(**accepted)


async def _invoke_node_command(
    invoker: Any,
    *,
    node: str,
    command: str,
    params: Mapping[str, Any],
    timeout_ms: Optional[int],
    idempotency_key: Optional[str],
) -> Any:
    if invoker is None:
        raise NodesLocationActionError("missing_config", "No node invoker is configured")

    method_candidates: Tuple[str, ...] = (
        "node_invoke",
        "invoke_node",
        "invoke",
        "call",
        "request",
    )
    for name in method_candidates:
        meth = getattr(invoker, name, None)
        if meth is None:
            continue
        try:
            return await _maybe_await(
                _call_with_accepted_kwargs(
                    meth,
                    {
                        "node": node,
                        "node_id": node,
                        "target": node,
                        "command": command,
                        "cmd": command,
                        "params": params,
                        "args": params,
                        "timeout_ms": timeout_ms,
                        "timeout": timeout_ms,
                        "invoke_timeout_ms": timeout_ms,
                        "idempotency_key": idempotency_key,
                    },
                )
            )
        except NodesLocationActionError:
            raise
        except Exception as e:
            raise NodesLocationActionError(
                "external_failure",
                "Node invocation failed",
                details={"exception": type(e).__name__},
            ) from e

    # Support passing a bare callable (useful in tests).
    if callable(invoker):
        try:
            return await _maybe_await(
                _call_with_accepted_kwargs(
                    cast(Callable[..., Any], invoker),
                    {
                        "node": node,
                        "command": command,
                        "params": params,
                        "timeout_ms": timeout_ms,
                        "idempotency_key": idempotency_key,
                    },
                )
            )
        except Exception as e:
            raise NodesLocationActionError(
                "external_failure",
                "Node invocation failed",
                details={"exception": type(e).__name__},
            ) from e

    raise NodesLocationActionError("missing_config", "Provided invoker does not support node invocation")


def _extract_payload(response: Any) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        # Common envelopes:
        # - { ok: true, result: {...} }
        # - { payload: {...} }
        # - { result: {...} }
        if response.get("ok") is False and "error" in response:
            err = response.get("error")
            if isinstance(err, Mapping):
                code = str(err.get("code") or err.get("type") or "external_failure")
                msg = str(err.get("message") or err.get("detail") or "Node returned an error")
                raise NodesLocationActionError(code, msg, details=cast(Mapping[str, Any], err))
            raise NodesLocationActionError("external_failure", "Node returned an error")

        for key in ("payload", "result", "data"):
            maybe = response.get(key)
            if isinstance(maybe, Mapping):
                return cast(Mapping[str, Any], maybe)

        return cast(Mapping[str, Any], response)

    raise NodesLocationActionError("invalid_response", "Node response must be an object")


def _find_location_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    # Some nodes wrap coordinates under nested objects. Try the common ones.
    for key in ("location", "coords", "coordinates", "position"):
        m = _maybe_mapping(payload.get(key))
        if m is not None:
            return m
    return payload


def _parse_location_payload(payload: Mapping[str, Any]) -> NodesLocationActionOutput:
    loc = payload
    lat_val = _get_any(loc, "lat", "latitude")
    lon_val = _get_any(loc, "lon", "lng", "longitude")

    if lat_val is None or lon_val is None:
        nested = _find_location_mapping(payload)
        lat_val = _get_any(nested, "lat", "latitude")
        lon_val = _get_any(nested, "lon", "lng", "longitude")
        loc = nested

    lat = _coerce_float(lat_val, field="lat")
    lon = _coerce_float(lon_val, field="lon")

    # Sanity-check geographic ranges
    if not (-90.0 <= lat <= 90.0):
        raise NodesLocationActionError("invalid_response", "lat out of range", details={"lat": lat})
    if not (-180.0 <= lon <= 180.0):
        raise NodesLocationActionError("invalid_response", "lon out of range", details={"lon": lon})

    accuracy_m = _coerce_optional_float(_get_any(loc, "accuracy_meters", "accuracyMeters", "accuracy"))
    altitude_m = _coerce_optional_float(_get_any(loc, "altitude_meters", "altitudeMeters", "altitude"))
    speed_mps = _coerce_optional_float(_get_any(loc, "speed_mps", "speedMps", "speed"))
    heading_deg = _coerce_optional_float(_get_any(loc, "heading_deg", "headingDeg", "heading"))

    ts_raw = _get_any(
        loc,
        "timestamp",
        "time",
        "t",
        "timestampMs",
        "timeMs",
        "timestamp_ms",
        "time_ms",
    )
    timestamp = _coerce_timestamp(ts_raw)

    is_precise_raw = _get_any(loc, "is_precise", "isPrecise")
    is_precise = is_precise_raw if isinstance(is_precise_raw, bool) else None

    source_raw = _get_any(loc, "source", "provider")
    source = source_raw.strip() if isinstance(source_raw, str) and source_raw.strip() else None

    return NodesLocationActionOutput(
        lat=lat,
        lon=lon,
        accuracy_meters=accuracy_m,
        altitude_meters=altitude_m,
        speed_mps=speed_mps,
        heading_deg=heading_deg,
        timestamp=timestamp,
        is_precise=is_precise,
        source=source,
    )


def validate_input(raw: Union[Mapping[str, Any], NodesLocationActionInput]) -> NodesLocationActionInput:
    if isinstance(raw, NodesLocationActionInput):
        node = _require_non_empty_str(raw.node, field="node")
        accuracy = _normalize_accuracy(raw.accuracy)
        max_age_ms = _require_non_negative_int(raw.max_age_ms, field="max_age_ms")
        location_timeout_ms = _require_positive_int(raw.location_timeout_ms, field="location_timeout_ms")

        invoke_timeout_ms: Optional[int] = raw.invoke_timeout_ms
        if invoke_timeout_ms is not None:
            invoke_timeout_ms = _require_positive_int(invoke_timeout_ms, field="invoke_timeout_ms")

        idem = raw.idempotency_key
        if idem is not None:
            idem = _require_non_empty_str(idem, field="idempotency_key")

        return NodesLocationActionInput(
            node=node,
            accuracy=accuracy,
            max_age_ms=max_age_ms,
            location_timeout_ms=location_timeout_ms,
            invoke_timeout_ms=invoke_timeout_ms,
            idempotency_key=idem,
        )

    node = _require_non_empty_str(raw.get("node"), field="node")
    accuracy = _normalize_accuracy(raw.get("accuracy", "balanced"))
    max_age_ms = _require_non_negative_int(raw.get("max_age_ms", 15_000), field="max_age_ms")
    location_timeout_ms = _require_positive_int(raw.get("location_timeout_ms", 10_000), field="location_timeout_ms")

    invoke_timeout_ms_raw = raw.get("invoke_timeout_ms")
    invoke_timeout_ms: Optional[int]
    if invoke_timeout_ms_raw is None:
        invoke_timeout_ms = None
    else:
        invoke_timeout_ms = _require_positive_int(invoke_timeout_ms_raw, field="invoke_timeout_ms")

    idem_raw = raw.get("idempotency_key")
    idempotency_key = None if idem_raw is None else _require_non_empty_str(idem_raw, field="idempotency_key")

    return NodesLocationActionInput(
        node=node,
        accuracy=accuracy,
        max_age_ms=max_age_ms,
        location_timeout_ms=location_timeout_ms,
        invoke_timeout_ms=invoke_timeout_ms,
        idempotency_key=idempotency_key,
    )


async def get_node_location(
    action_input: Union[Mapping[str, Any], NodesLocationActionInput],
    *,
    invoker: Any,
) -> NodesLocationActionOutput:
    """Fetch location from a specific node via a provided invoker/client."""
    validated = validate_input(action_input)

    node_params: Dict[str, Any] = {
        "timeoutMs": validated.location_timeout_ms,
        "maxAgeMs": validated.max_age_ms,
        "desiredAccuracy": validated.accuracy,
    }

    response = await _invoke_node_command(
        invoker,
        node=validated.node,
        command=NODE_COMMAND,
        params=node_params,
        timeout_ms=validated.invoke_timeout_ms,
        idempotency_key=validated.idempotency_key,
    )

    payload = _extract_payload(response)
    return _parse_location_payload(payload)


async def handle_nodes_location_request(
    request: Union[Mapping[str, Any], NodesLocationActionInput],
    *,
    invoker: Any,
) -> NodesLocationActionResponse:
    """Automation-friendly handler that returns a stable JSON response envelope."""
    try:
        result = await get_node_location(request, invoker=invoker)
        return {"ok": True, "result": result.to_dict()}
    except NodesLocationActionError as e:
        return {"ok": False, "error": e.to_dict()}


# Optional metadata for discovery-based registries (best-effort).
ACTION_ID = "nodes.location"
ACTION_DESCRIPTION = "Fetch a node's current device location (lat/lon)."


# Minimal JSON Schemas for server-side validation/documentation.
REQUEST_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["node"],
    "properties": {
        "node": {"type": "string", "minLength": 1},
        "accuracy": {"type": "string", "enum": ["coarse", "balanced", "precise"]},
        "max_age_ms": {"type": "integer", "minimum": 0},
        "location_timeout_ms": {"type": "integer", "minimum": 1},
        "invoke_timeout_ms": {"type": "integer", "minimum": 1},
        "idempotency_key": {"type": "string", "minLength": 1},
    },
    "additionalProperties": True,
}

RESPONSE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ok"],
    "properties": {
        "ok": {"type": "boolean"},
        "result": {"type": "object"},
        "error": {
            "type": "object",
            "required": ["code", "message", "details"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
            },
        },
    },
    "additionalProperties": True,
}
