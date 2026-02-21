"""Nodes notify-action.

This module adds a Thomas-native primitive for notifying one or more nodes that an
"action" should occur.

Design goals
------------
- Thomas-native naming (no OpenClaw naming reuse).
- Deterministic errors with stable error codes.
- Transport-agnostic core logic: the caller may inject a notifier implementation.
- Automation-friendly output: JSON-serialisable contracts + JSON schema.

The default notifier is HTTP-based and is configured via environment variables
(or a Thomas config module when available).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, MutableMapping, Protocol, TypedDict, cast


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class NodesNotifyActionInputDict(TypedDict, total=False):
    """JSON-friendly input contract."""

    node_ids: list[str]
    action: str
    payload: dict[str, Any]
    timeout_s: float


class NodeNotifyResultDict(TypedDict, total=False):
    node_id: str
    ok: bool
    status: int
    error_code: str
    error_message: str


class NodesNotifyActionOutputDict(TypedDict, total=False):
    ok: bool
    action: str
    results: list[NodeNotifyResultDict]


@dataclass(frozen=True)
class NodesNotifyActionInput:
    """Input contract for nodes notify-action."""

    node_ids: list[str]
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 10.0


@dataclass(frozen=True)
class NodeNotifyResult:
    """Per-node result for a notify-action call."""

    node_id: str
    ok: bool
    status: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class NodesNotifyActionOutput:
    ok: bool
    action: str
    results: list[NodeNotifyResult]

    def to_json_dict(self) -> NodesNotifyActionOutputDict:
        return cast(NodesNotifyActionOutputDict, _strip_nones(asdict(self)))


@dataclass(frozen=True)
class NodesNotifyActionConfig:
    """Transport configuration for the default HTTP notifier."""

    base_url: str
    notify_path: str = "/nodes/notify-action"
    api_token: str | None = None
    verify_tls: bool = True


# ---------------------------------------------------------------------------
# Deterministic errors
# ---------------------------------------------------------------------------


class NodesNotifyActionError(RuntimeError):
    """Base class for deterministic nodes notify-action errors."""

    code: str = "nodes_notify_action_error"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = dict(self.details)
        return payload


class NodesNotifyActionInvalidInputError(NodesNotifyActionError):
    code = "invalid_input"


class NodesNotifyActionConfigError(NodesNotifyActionError):
    code = "missing_config"


class NodesNotifyActionExternalError(NodesNotifyActionError):
    code = "external_failure"


# ---------------------------------------------------------------------------
# Notifier abstraction
# ---------------------------------------------------------------------------


class NodesActionNotifier(Protocol):
    async def notify(
        self,
        *,
        node_id: str,
        action: str,
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> NodeNotifyResult:
        """Notify a single node and return a per-node result."""


class HttpNodesActionNotifier:
    """Default notifier that POSTs to a node-manager style HTTP endpoint.

    This notifier is an async context manager so it can reuse a single
    aiohttp.ClientSession across multiple node notifications.
    """

    def __init__(self, config: NodesNotifyActionConfig):
        self._config = config
        self._session = None
        self._aiohttp = None
        self._connector = None

    async def __aenter__(self) -> "HttpNodesActionNotifier":
        try:
            import aiohttp  # type: ignore
        except Exception as e:  # pragma: no cover
            raise NodesNotifyActionExternalError(
                "aiohttp is required for HTTP node notifications",
                details={"reason": "dependency_missing", "dependency": "aiohttp"},
            ) from e

        self._aiohttp = aiohttp

        connector = None
        if not self._config.verify_tls:
            connector = aiohttp.TCPConnector(ssl=False)
        self._connector = connector

        # Do not set a total timeout here; we pass per-request timeouts.
        self._session = aiohttp.ClientSession(connector=connector)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        if self._connector is not None:
            await self._connector.close()
            self._connector = None

    async def notify(
        self,
        *,
        node_id: str,
        action: str,
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> NodeNotifyResult:
        if self._session is None or self._aiohttp is None:
            raise NodesNotifyActionExternalError(
                "HttpNodesActionNotifier must be used as an async context manager",
                details={"reason": "not_initialized"},
            )

        url = self._config.base_url.rstrip("/") + self._config.notify_path
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_token:
            headers["Authorization"] = f"Bearer {self._config.api_token}"

        body = {"node_id": node_id, "action": action, "payload": dict(payload)}

        aiohttp = self._aiohttp
        timeout = aiohttp.ClientTimeout(total=float(timeout_s))

        try:
            async with self._session.post(url, headers=headers, json=body, timeout=timeout) as resp:
                status = int(resp.status)
                if 200 <= status < 300:
                    return NodeNotifyResult(node_id=node_id, ok=True, status=status)

                err_msg = await _safe_read_response(resp)
                return NodeNotifyResult(
                    node_id=node_id,
                    ok=False,
                    status=status,
                    error_code="remote_error",
                    error_message=err_msg or f"Remote returned HTTP {status}",
                )

        except asyncio.TimeoutError:
            return NodeNotifyResult(
                node_id=node_id,
                ok=False,
                status=None,
                error_code="timeout",
                error_message=f"Timed out after {timeout_s:.3f}s",
            )
        except Exception as e:
            # aiohttp's exception hierarchy is fairly broad; keep this deterministic.
            return NodeNotifyResult(
                node_id=node_id,
                ok=False,
                status=None,
                error_code="network_error",
                error_message=str(e)[:500],
            )


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------


def parse_input(data: Mapping[str, Any]) -> NodesNotifyActionInput:
    """Parse and validate a mapping into :class:`NodesNotifyActionInput`."""

    node_ids_raw = data.get("node_ids")
    action_raw = data.get("action")
    payload_raw = data.get("payload", {})
    timeout_raw = data.get("timeout_s", 10.0)

    if not isinstance(node_ids_raw, list) or not node_ids_raw:
        raise NodesNotifyActionInvalidInputError(
            "node_ids must be a non-empty list",
            details={"field": "node_ids"},
        )

    node_ids: list[str] = []
    for idx, nid in enumerate(node_ids_raw):
        if not isinstance(nid, str) or not nid.strip():
            raise NodesNotifyActionInvalidInputError(
                "node_ids must contain non-empty strings",
                details={"field": "node_ids", "index": idx},
            )
        node_ids.append(nid.strip())

    if not isinstance(action_raw, str) or not action_raw.strip():
        raise NodesNotifyActionInvalidInputError(
            "action must be a non-empty string",
            details={"field": "action"},
        )
    action = action_raw.strip()

    if not isinstance(payload_raw, Mapping):
        raise NodesNotifyActionInvalidInputError(
            "payload must be an object",
            details={"field": "payload"},
        )

    try:
        timeout_s = float(timeout_raw)
    except Exception as e:
        raise NodesNotifyActionInvalidInputError(
            "timeout_s must be a number",
            details={"field": "timeout_s"},
        ) from e

    if timeout_s <= 0:
        raise NodesNotifyActionInvalidInputError(
            "timeout_s must be > 0",
            details={"field": "timeout_s"},
        )

    return NodesNotifyActionInput(
        node_ids=node_ids,
        action=action,
        payload=dict(payload_raw),
        timeout_s=timeout_s,
    )


def load_config() -> NodesNotifyActionConfig:
    """Load configuration for the default HTTP notifier.

    Supported environment variables (explicit + low-collision):
    - THOMAS_NODES_BASE_URL (required)
    - THOMAS_NODES_NOTIFY_PATH (optional; default: /nodes/notify-action)
    - THOMAS_NODES_API_TOKEN (optional; bearer token)
    - THOMAS_NODES_VERIFY_TLS (optional; "0"/"false"/"no"/"off" disables)
    """

    base_url = None
    notify_path = None
    api_token = None
    verify_tls: bool | None = None

    # 1) Try to pull from a Thomas config module if present.
    try:
        from thomas import config as thomas_config  # type: ignore

        base_url = getattr(thomas_config, "NODES_BASE_URL", None) or getattr(thomas_config, "nodes_base_url", None)
        notify_path = getattr(thomas_config, "NODES_NOTIFY_PATH", None) or getattr(
            thomas_config, "nodes_notify_path", None
        )
        api_token = getattr(thomas_config, "NODES_API_TOKEN", None) or getattr(thomas_config, "nodes_api_token", None)
        if hasattr(thomas_config, "NODES_VERIFY_TLS"):
            verify_tls = bool(getattr(thomas_config, "NODES_VERIFY_TLS"))
    except Exception:
        pass

    # 2) Fall back to env vars.
    base_url = base_url or os.getenv("THOMAS_NODES_BASE_URL")
    notify_path = notify_path or os.getenv("THOMAS_NODES_NOTIFY_PATH")
    api_token = api_token or os.getenv("THOMAS_NODES_API_TOKEN")

    if verify_tls is None:
        verify_raw = os.getenv("THOMAS_NODES_VERIFY_TLS")
        if verify_raw is None:
            verify_tls = True
        else:
            verify_tls = verify_raw.strip().lower() not in {"0", "false", "no", "off"}

    if not base_url:
        raise NodesNotifyActionConfigError(
            "Nodes base URL is not configured",
            details={"env": "THOMAS_NODES_BASE_URL"},
        )

    return NodesNotifyActionConfig(
        base_url=str(base_url),
        notify_path=str(notify_path) if notify_path else "/nodes/notify-action",
        api_token=str(api_token) if api_token else None,
        verify_tls=bool(verify_tls),
    )


async def notify_action_async(
    inp: NodesNotifyActionInput,
    *,
    notifier: NodesActionNotifier | None = None,
    config: NodesNotifyActionConfig | None = None,
) -> NodesNotifyActionOutput:
    """Notify one or more nodes.

    Raises:
        NodesNotifyActionInvalidInputError: input is invalid
        NodesNotifyActionConfigError: missing config when using the default notifier
        NodesNotifyActionExternalError: notifier misuse / internal integration errors
    """

    _validate_input(inp)

    # Default notifier path.
    if notifier is None:
        cfg = config or load_config()
        async with HttpNodesActionNotifier(cfg) as http_notifier:
            return await _notify_many(inp, notifier=http_notifier)

    return await _notify_many(inp, notifier=notifier)


def notify_action(
    inp: NodesNotifyActionInput,
    *,
    notifier: NodesActionNotifier | None = None,
    config: NodesNotifyActionConfig | None = None,
) -> NodesNotifyActionOutput:
    """Synchronous wrapper for :func:`notify_action_async`.

    This raises a deterministic error if called from within an active event loop.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise NodesNotifyActionExternalError(
            "notify_action() cannot be called from a running event loop; use notify_action_async()",
            details={"reason": "event_loop_running"},
        )

    return asyncio.run(notify_action_async(inp, notifier=notifier, config=config))


async def _notify_many(inp: NodesNotifyActionInput, *, notifier: NodesActionNotifier) -> NodesNotifyActionOutput:
    # Gather preserves order, which keeps output stable for automation.
    tasks = [
        asyncio.create_task(
            notifier.notify(
                node_id=node_id,
                action=inp.action,
                payload=inp.payload,
                timeout_s=inp.timeout_s,
            )
        )
        for node_id in inp.node_ids
    ]

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[NodeNotifyResult] = []
    for node_id, res in zip(inp.node_ids, raw_results):
        if isinstance(res, Exception):
            results.append(
                NodeNotifyResult(
                    node_id=node_id,
                    ok=False,
                    status=None,
                    error_code="notifier_exception",
                    error_message=str(res)[:500],
                )
            )
        else:
            results.append(cast(NodeNotifyResult, res))

    ok = all(r.ok for r in results)
    return NodesNotifyActionOutput(ok=ok, action=inp.action, results=results)


# ---------------------------------------------------------------------------
# JSON schemas (useful for HTTP routes / automation)
# ---------------------------------------------------------------------------


INPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["node_ids", "action"],
    "properties": {
        "node_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "action": {"type": "string", "minLength": 1},
        "payload": {"type": "object"},
        "timeout_s": {"type": "number", "exclusiveMinimum": 0},
    },
}

OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok", "action", "results"],
    "properties": {
        "ok": {"type": "boolean"},
        "action": {"type": "string"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node_id", "ok"],
                "properties": {
                    "node_id": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "status": {"type": "integer"},
                    "error_code": {"type": "string"},
                    "error_message": {"type": "string"},
                },
            },
        },
    },
}


def input_json_schema() -> dict[str, Any]:
    return dict(INPUT_JSON_SCHEMA)


def output_json_schema() -> dict[str, Any]:
    return dict(OUTPUT_JSON_SCHEMA)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def payload_from_json(payload_json: str | None) -> dict[str, Any]:
    """Parse a JSON object string into a dict."""
    if payload_json is None or payload_json == "":
        return {}
    try:
        parsed = json.loads(payload_json)
    except Exception as e:
        raise NodesNotifyActionInvalidInputError(
            "payload must be valid JSON",
            details={"field": "payload"},
        ) from e

    if not isinstance(parsed, dict):
        raise NodesNotifyActionInvalidInputError(
            "payload JSON must be an object",
            details={"field": "payload"},
        )
    return cast(dict[str, Any], parsed)


def _validate_input(inp: NodesNotifyActionInput) -> None:
    if not inp.node_ids:
        raise NodesNotifyActionInvalidInputError(
            "node_ids must be a non-empty list",
            details={"field": "node_ids"},
        )
    for idx, nid in enumerate(inp.node_ids):
        if not isinstance(nid, str) or not nid.strip():
            raise NodesNotifyActionInvalidInputError(
                "node_ids must contain non-empty strings",
                details={"field": "node_ids", "index": idx},
            )
    if not isinstance(inp.action, str) or not inp.action.strip():
        raise NodesNotifyActionInvalidInputError(
            "action must be a non-empty string",
            details={"field": "action"},
        )
    if not isinstance(inp.payload, dict):
        raise NodesNotifyActionInvalidInputError(
            "payload must be an object",
            details={"field": "payload"},
        )
    if not isinstance(inp.timeout_s, (int, float)) or float(inp.timeout_s) <= 0:
        raise NodesNotifyActionInvalidInputError(
            "timeout_s must be > 0",
            details={"field": "timeout_s"},
        )


def _strip_nones(obj: Any) -> Any:
    if isinstance(obj, dict):
        new: MutableMapping[str, Any] = {}
        for k, v in obj.items():
            if v is None:
                continue
            new[k] = _strip_nones(v)
        return dict(new)
    if isinstance(obj, list):
        return [_strip_nones(v) for v in obj if v is not None]
    return obj


async def _safe_read_response(resp: Any) -> str | None:
    """Try to read a response body in a bounded way."""
    try:
        text = await resp.text()
    except Exception:
        return None
    text = (text or "").strip()
    if not text:
        return None
    return text[:500]
