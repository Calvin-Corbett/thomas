"""Nodes approve action (Prompt P047).

This module implements a small, deterministic approval record for "actions"
targeting one or more "nodes".

Design:
- Validates input.
- Resolves a configured approvals ledger path.
- Appends one JSON record per line (JSONL).

Why JSONL?
- Human-inspectable.
- Append-only.
- Low friction for automation and server use without a database.

No OpenClaw identifiers are used; this is Thomas-native behavior.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, TypedDict, cast


DEFAULT_APPROVALS_ENV_VAR = "THOMAS_NODES_APPROVALS_PATH"

# Optional, best-effort fallbacks in case the broader Thomas runtime sets them.
STATE_DIR_ENV_VARS: tuple[str, ...] = (
    "THOMAS_STATE_DIR",
    "THOMAS_STATE_PATH",
    "THOMAS_HOME",
)

DEFAULT_LEDGER_FILENAME = "nodes_approvals.jsonl"


class NodesApproveActionPayload(TypedDict, total=False):
    """Machine-facing payload for approving an action."""

    action_id: str
    node_ids: list[str]
    approver: str
    comment: str
    state_path: str
    approved_at: str


@dataclass(frozen=True, slots=True)
class NodesApproveActionRequest:
    """Validated request for approving an action."""

    action_id: str
    node_ids: tuple[str, ...] = ()
    approver: Optional[str] = None
    comment: Optional[str] = None

    # Where to write the JSONL ledger. If omitted, resolved from env/config.
    state_path: Optional[str] = None

    # Optional time injection for deterministic testing.
    approved_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class NodesApproveActionResult:
    """Result of approving an action."""

    action_id: str
    approved_nodes: tuple[str, ...]
    approver: Optional[str]
    comment: Optional[str]
    approved_at: str
    ledger_path: str
    record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "approved_nodes": list(self.approved_nodes),
            "approver": self.approver,
            "comment": self.comment,
            "approved_at": self.approved_at,
            "ledger_path": self.ledger_path,
            "record": self.record,
        }


class NodesApproveActionError(RuntimeError):
    """Base error for nodes-approve-action."""

    code: str = "nodes_approve_action_error"
    exit_code: int = 1
    http_status: int = 500

    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class NodesApproveActionInputError(NodesApproveActionError):
    code = "invalid_input"
    exit_code = 2
    http_status = 400


class NodesApproveActionConfigError(NodesApproveActionError):
    code = "missing_config"
    exit_code = 3
    http_status = 500


class NodesApproveActionExternalError(NodesApproveActionError):
    code = "external_failure"
    exit_code = 4
    http_status = 502


def approve_action(request: NodesApproveActionRequest) -> NodesApproveActionResult:
    """Approve an action for one or more nodes.

    The approval is recorded as a JSONL line in a configured ledger.

    Raises:
        NodesApproveActionInputError: if request fields are invalid.
        NodesApproveActionConfigError: if no ledger path can be resolved.
        NodesApproveActionExternalError: if writing the ledger fails.
    """

    action_id = _validate_action_id(request.action_id)
    node_ids = _validate_node_ids(request.node_ids)
    approver = _validate_optional_str("approver", request.approver)
    comment = _validate_optional_str("comment", request.comment)

    ledger_path = _resolve_ledger_path(explicit=request.state_path)

    approved_at_dt = request.approved_at or datetime.now(timezone.utc)
    approved_at = _format_dt(approved_at_dt)

    record: dict[str, Any] = {
        "schema_version": 1,
        "action_id": action_id,
        "approved": True,
        "approved_nodes": list(node_ids),
        "approver": approver,
        "comment": comment,
        "approved_at": approved_at,
        "scope": "nodes" if node_ids else "all",
    }

    _append_jsonl(Path(ledger_path), record)

    return NodesApproveActionResult(
        action_id=action_id,
        approved_nodes=node_ids,
        approver=approver,
        comment=comment,
        approved_at=approved_at,
        ledger_path=str(ledger_path),
        record=record,
    )


def approve_action_from_payload(payload: Any) -> NodesApproveActionResult:
    """Parse a loosely-typed payload and approve the action.

    Accepts both snake_case and camelCase keys for convenience.
    """

    if not isinstance(payload, Mapping):
        raise NodesApproveActionInputError(
            "JSON payload must be an object",
            details={"got": type(payload).__name__},
        )

    # Support a couple of common key shapes for automation.
    action_id = cast(Optional[str], payload.get("action_id") or payload.get("actionId"))
    node_ids_raw = (
        payload.get("node_ids")
        or payload.get("nodeIds")
        or payload.get("nodes")
        or payload.get("node_id")
        or payload.get("nodeId")
    )
    approver = cast(Optional[str], payload.get("approver"))
    comment = cast(Optional[str], payload.get("comment"))
    state_path = cast(Optional[str], payload.get("state_path") or payload.get("statePath"))
    approved_at_raw = cast(Optional[str], payload.get("approved_at") or payload.get("approvedAt"))

    node_ids: Sequence[str]
    if node_ids_raw is None:
        node_ids = ()
    elif isinstance(node_ids_raw, (list, tuple)):
        node_ids = [str(x) for x in node_ids_raw]
    elif isinstance(node_ids_raw, str):
        node_ids = (node_ids_raw,)
    else:
        raise NodesApproveActionInputError(
            "node_ids must be a list of strings",
            details={"field": "node_ids", "got": type(node_ids_raw).__name__},
        )

    approved_at: Optional[datetime] = None
    if approved_at_raw is not None:
        approved_at = _parse_iso8601(approved_at_raw)

    req = NodesApproveActionRequest(
        action_id=str(action_id) if action_id is not None else "",
        node_ids=tuple(node_ids),
        approver=approver,
        comment=comment,
        state_path=state_path,
        approved_at=approved_at,
    )
    return approve_action(req)


# -----------------
# Aiohttp route hook
# -----------------


async def aiohttp_handler(request: Any) -> Any:  # pragma: no cover
    """Aiohttp handler for approving an action.

    Written to be discoverable by route registration code that scans modules for
    handler callables. This function avoids importing aiohttp at import-time.
    """

    try:
        payload = await request.json()
        result = approve_action_from_payload(payload)
        return _aiohttp_json_response({"ok": True, "result": result.to_dict()}, status=200)
    except NodesApproveActionError as e:
        return _aiohttp_json_response({"ok": False, "error": e.to_dict()}, status=e.http_status)
    except Exception as e:  # noqa: BLE001
        err = NodesApproveActionExternalError(
            "Unhandled failure while approving action",
            details={"exc_type": type(e).__name__},
        )
        return _aiohttp_json_response({"ok": False, "error": err.to_dict()}, status=err.http_status)


def _aiohttp_json_response(payload: Mapping[str, Any], *, status: int) -> Any:  # pragma: no cover
    from aiohttp import web

    return web.json_response(payload, status=status)


# Route metadata in multiple shapes to maximize compatibility with different auto-routers.
AIOHTTP_ROUTES = (
    ("POST", "/nodes/approve-action", aiohttp_handler),
)
ROUTES = AIOHTTP_ROUTES


def get_aiohttp_route_defs() -> Any:  # pragma: no cover
    """Return aiohttp.web RouteDefs (if an auto-router prefers that form)."""
    from aiohttp import web
    return [web.post("/nodes/approve-action", aiohttp_handler)]


REQUEST_JSON_SCHEMA = {
    "type": "object",
    "required": ["action_id"],
    "properties": {
        "action_id": {"type": "string"},
        "node_ids": {"type": "array", "items": {"type": "string"}},
        "approver": {"type": "string"},
        "comment": {"type": "string"},
        "state_path": {"type": "string"},
        "approved_at": {"type": "string", "description": "ISO 8601 timestamp"},
    },
    "additionalProperties": True,
}

RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "required": ["ok"],
    "properties": {
        "ok": {"type": "boolean"},
        "result": {"type": "object"},
        "error": {"type": "object"},
    },
    "additionalProperties": True,
}


# --------------
# Helper methods
# --------------


def _validate_action_id(value: Any) -> str:
    if not isinstance(value, str):
        raise NodesApproveActionInputError(
            "action_id must be a string",
            details={"field": "action_id", "got": type(value).__name__},
        )
    action_id = value.strip()
    if not action_id:
        raise NodesApproveActionInputError("action_id is required", details={"field": "action_id"})
    if len(action_id) > 200:
        raise NodesApproveActionInputError(
            "action_id is too long",
            details={"field": "action_id", "max_len": 200},
        )
    return action_id


def _validate_node_ids(values: Sequence[Any]) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise NodesApproveActionInputError(
            "node_ids must be a list of strings",
            details={"field": "node_ids", "got": type(values).__name__},
        )
    cleaned: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise NodesApproveActionInputError(
                "node_ids must contain only strings",
                details={"field": "node_ids", "got": type(raw).__name__},
            )
        node_id = raw.strip()
        if not node_id:
            raise NodesApproveActionInputError(
                "node_ids must not contain empty values",
                details={"field": "node_ids"},
            )
        cleaned.append(node_id)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    uniq: list[str] = []
    for n in cleaned:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return tuple(uniq)


def _validate_optional_str(field_name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NodesApproveActionInputError(
            f"{field_name} must be a string",
            details={"field": field_name, "got": type(value).__name__},
        )
    s = value.strip()
    if not s:
        return None
    if len(s) > 5000:
        raise NodesApproveActionInputError(
            f"{field_name} is too long",
            details={"field": field_name, "max_len": 5000},
        )
    return s


def _resolve_ledger_path(*, explicit: Optional[str]) -> str:
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise NodesApproveActionInputError(
                "state_path must be a non-empty string",
                details={"field": "state_path"},
            )
        return explicit

    env_path = os.environ.get(DEFAULT_APPROVALS_ENV_VAR)
    if env_path:
        return env_path

    # Best-effort fallbacks to reduce friction in environments where Thomas sets a state dir.
    for env_var in STATE_DIR_ENV_VARS:
        val = os.environ.get(env_var)
        if not val:
            continue
        p = Path(val)
        # If it's a file path, take its directory; otherwise treat as directory.
        base_dir = p.parent if p.suffix else p
        return str(base_dir / DEFAULT_LEDGER_FILENAME)

    raise NodesApproveActionConfigError(
        "No approvals ledger path configured",
        details={
            "expected_env": DEFAULT_APPROVALS_ENV_VAR,
            "fallback_envs": list(STATE_DIR_ENV_VARS),
            "default_filename": DEFAULT_LEDGER_FILENAME,
        },
    )


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True))
            f.write("\n")
    except OSError as e:
        raise NodesApproveActionExternalError(
            "Failed to write approvals ledger",
            details={
                "path": str(path),
                "exc_type": type(e).__name__,
                "errno": getattr(e, "errno", None),
            },
        ) from e


def _format_dt(dt: datetime) -> str:
    # Always store UTC ISO 8601 with Z.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso8601(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NodesApproveActionInputError(
            "approved_at must be a non-empty ISO 8601 string",
            details={"field": "approved_at"},
        )
    raw = value.strip()
    # Accept trailing Z.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as e:
        raise NodesApproveActionInputError(
            "approved_at must be ISO 8601",
            details={"field": "approved_at", "value": value},
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
