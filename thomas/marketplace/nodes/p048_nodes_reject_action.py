"""Nodes reject action.

Thomas-native behavior for rejecting a pending action associated with a node.

Why this exists
--------------
Some integrations queue *actions* per node (e.g., "apply config", "restart agent").
Operators and automation need a deterministic way to refuse an action.

Public API
----------
- :class:`NodesRejectActionInput`
- :class:`NodesRejectActionOutput`
- :class:`NodesRejectActionError`
- :func:`reject_node_action`

Automation and server integration helpers
----------------------------------------
- :func:`run` (dict-in / dict-out)
- :data:`INPUT_JSON_SCHEMA`, :data:`OUTPUT_JSON_SCHEMA`
- :data:`ROUTES` (aiohttp RouteDef list, best-effort)
- :data:`AIOHTTP_ROUTES` / :data:`ROUTE_SPECS` (metadata)

Storage
-------
The default backend is a small JSON file in the Thomas *state directory*.
The state directory can be resolved from:

1. explicit argument
2. THOMAS_STATE_DIR
3. THOMAS_HOME/state
4. ~/.thomas

The store path can be overridden with THOMAS_NODE_ACTIONS_PATH.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

ACTION_NAME = "nodes.reject_action"
ACTION_VERSION = "1.0"


class NodesRejectActionError(RuntimeError):
    """Deterministic error for nodes reject-action operations."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message, "details": self.details},
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_str_field(value: Any, field: str, *, max_len: int) -> str:
    if not isinstance(value, str):
        raise NodesRejectActionError(
            "invalid_input",
            f"{field} must be a string",
            details={"field": field, "got_type": type(value).__name__},
        )
    cleaned = value.strip()
    if not cleaned:
        raise NodesRejectActionError("invalid_input", f"{field} is required", details={"field": field})
    if len(cleaned) > max_len:
        raise NodesRejectActionError(
            "invalid_input",
            f"{field} is too long",
            details={"field": field, "max_len": max_len},
        )
    return cleaned


def _as_optional_str_field(value: Any, field: str, *, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NodesRejectActionError(
            "invalid_input",
            f"{field} must be a string",
            details={"field": field, "got_type": type(value).__name__},
        )
    cleaned = value.strip() or None
    if cleaned is not None and len(cleaned) > max_len:
        raise NodesRejectActionError(
            "invalid_input",
            f"{field} is too long",
            details={"field": field, "max_len": max_len},
        )
    return cleaned


@dataclass(frozen=True, slots=True)
class NodesRejectActionInput:
    """Input contract for rejecting a node action."""

    node_id: str
    action_id: str
    reason: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> NodesRejectActionInput:
        return cls(
            node_id=_as_str_field(raw.get("node_id"), "node_id", max_len=200),
            action_id=_as_str_field(raw.get("action_id"), "action_id", max_len=200),
            reason=_as_optional_str_field(raw.get("reason"), "reason", max_len=500),
        )


@dataclass(frozen=True, slots=True)
class NodesRejectActionOutput:
    """Output contract for rejecting a node action."""

    node_id: str
    action_id: str
    status: Literal["rejected"]
    reason: str | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "result": {
                "node_id": self.node_id,
                "action_id": self.action_id,
                "status": self.status,
                "reason": self.reason,
                "updated_at": self.updated_at,
            },
        }


class ActionRecord(TypedDict, total=False):
    node_id: str
    action_id: str
    status: str
    reason: str | None
    created_at: str
    updated_at: str


@runtime_checkable
class ActionStore(Protocol):
    def reject_action(self, payload: NodesRejectActionInput) -> NodesRejectActionOutput: ...


def resolve_state_dir(explicit: str | Path | None = None) -> Path:
    """Resolve the Thomas state directory."""
    if explicit is not None:
        return Path(explicit).expanduser()

    env_state = os.environ.get("THOMAS_STATE_DIR")
    if env_state:
        return Path(env_state).expanduser()

    env_home = os.environ.get("THOMAS_HOME")
    if env_home:
        return Path(env_home).expanduser() / "state"

    return Path.home() / ".thomas"


def resolve_actions_store_path(state_dir: str | Path | None = None) -> Path:
    """Resolve the file path for the node action store."""
    env_path = os.environ.get("THOMAS_NODE_ACTIONS_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return resolve_state_dir(state_dir) / "node_actions.json"


class FileActionStore:
    """JSON-file backed store for node actions.

    File format:

    .. code-block:: json

        {
          "actions": {
            "<action_id>": {"node_id": "...", "status": "pending|rejected", ...}
          }
        }
    """

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise NodesRejectActionError(
                "missing_config",
                "Action store not found. Configure THOMAS_STATE_DIR/THOMAS_HOME or create the store.",
                details={"path": str(self.path)},
            ) from e
        except OSError as e:
            raise NodesRejectActionError(
                "external_failure",
                "Failed to read action store",
                details={"path": str(self.path)},
            ) from e

        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            raise NodesRejectActionError(
                "external_failure",
                "Action store is not valid JSON",
                details={"path": str(self.path)},
            ) from e

        if not isinstance(data, dict):
            raise NodesRejectActionError(
                "external_failure",
                "Action store has invalid structure",
                details={"path": str(self.path), "expected": "object"},
            )

        actions = data.get("actions", {})
        if actions is None:
            actions = {}
        if not isinstance(actions, dict):
            raise NodesRejectActionError(
                "external_failure",
                "Action store has invalid actions index",
                details={"path": str(self.path), "expected": "object"},
            )

        return {"actions": actions}

    def _atomic_write(self, data: dict[str, Any]) -> None:
        # Best-effort atomic update: write to temp file then replace.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            raise NodesRejectActionError(
                "external_failure",
                "Failed to write action store",
                details={"path": str(self.path)},
            ) from e
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except (OSError, ConnectionError):
                # If replace succeeded, tmp won't exist. If it didn't, cleanup is best-effort.
                pass

    def reject_action(self, payload: NodesRejectActionInput) -> NodesRejectActionOutput:
        data = self._load()
        actions: dict[str, Any] = data["actions"]

        rec_raw = actions.get(payload.action_id)
        if rec_raw is None:
            raise NodesRejectActionError(
                "not_found",
                "Action not found",
                details={"node_id": payload.node_id, "action_id": payload.action_id},
            )
        if not isinstance(rec_raw, dict):
            raise NodesRejectActionError(
                "external_failure",
                "Action record has invalid structure",
                details={"action_id": payload.action_id},
            )

        # Prevent cross-node updates.
        rec_node_id = rec_raw.get("node_id")
        if rec_node_id is not None and rec_node_id != payload.node_id:
            raise NodesRejectActionError(
                "not_found",
                "Action not found",
                details={"node_id": payload.node_id, "action_id": payload.action_id},
            )

        status = rec_raw.get("status") or "pending"
        if status == "rejected":
            return NodesRejectActionOutput(
                node_id=payload.node_id,
                action_id=payload.action_id,
                status="rejected",
                reason=rec_raw.get("reason"),
                updated_at=rec_raw.get("updated_at") or _utc_now_iso(),
            )

        rec_raw["node_id"] = payload.node_id
        rec_raw["action_id"] = payload.action_id
        rec_raw["status"] = "rejected"
        if payload.reason is not None:
            rec_raw["reason"] = payload.reason
        rec_raw["updated_at"] = _utc_now_iso()
        actions[payload.action_id] = rec_raw

        self._atomic_write({"actions": actions})

        return NodesRejectActionOutput(
            node_id=payload.node_id,
            action_id=payload.action_id,
            status="rejected",
            reason=rec_raw.get("reason"),
            updated_at=rec_raw["updated_at"],
        )


def reject_node_action(
    payload: NodesRejectActionInput,
    *,
    store: ActionStore | None = None,
    state_dir: str | Path | None = None,
) -> NodesRejectActionOutput:
    """Reject an action for a node."""
    if store is None:
        store = FileActionStore(resolve_actions_store_path(state_dir))
    return store.reject_action(payload)


# Convenience name (some loaders prefer `reject_action`).
reject_action = reject_node_action


def run(raw: dict[str, Any], *, state_dir: str | Path | None = None) -> dict[str, Any]:
    """Automation-friendly wrapper: dict-in / dict-out."""
    payload = NodesRejectActionInput.from_mapping(raw)
    return reject_node_action(payload, state_dir=state_dir).to_dict()


def http_status_for_error(code: str) -> int:
    if code in {"invalid_input"}:
        return 400
    if code in {"missing_config"}:
        return 500
    if code in {"not_found"}:
        return 404
    return 502


INPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["node_id", "action_id"],
    "properties": {
        "node_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "action_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "additionalProperties": False,
}

OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok"],
    "properties": {
        "ok": {"type": "boolean"},
        "result": {
            "type": "object",
            "required": ["node_id", "action_id", "status", "updated_at"],
            "properties": {
                "node_id": {"type": "string"},
                "action_id": {"type": "string"},
                "status": {"type": "string"},
                "reason": {"type": ["string", "null"]},
                "updated_at": {"type": "string"},
            },
        },
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
    "additionalProperties": False,
}


def _aiohttp_json(payload: dict[str, Any], *, status: int):
    from aiohttp import web

    return web.json_response(payload, status=status)


async def aiohttp_handler(request):  # pragma: no cover
    """aiohttp handler for rejecting a node action.

    - Method: POST
    - Path: /nodes/reject-action
    - JSON body: INPUT_JSON_SCHEMA
    """
    try:
        raw = await request.json()
    except (json.JSONDecodeError, ValueError, KeyError):
        err = NodesRejectActionError("invalid_input", "Invalid JSON body", details={})
        return _aiohttp_json(err.to_dict(), status=http_status_for_error(err.code))

    try:
        payload = NodesRejectActionInput.from_mapping(raw if isinstance(raw, dict) else {})
        state_dir = None
        try:
            state_dir = request.app.get("state_dir")  # type: ignore[attr-defined]
        except (json.JSONDecodeError, ValueError, KeyError):
            state_dir = None

        result = reject_node_action(payload, state_dir=state_dir)
        return _aiohttp_json(result.to_dict(), status=200)
    except NodesRejectActionError as e:
        return _aiohttp_json(e.to_dict(), status=http_status_for_error(e.code))


ROUTE_SPECS = [
    {
        "method": "POST",
        "path": "/nodes/reject-action",
        "handler": aiohttp_handler,
        "name": "nodes_reject_action",
        "input_schema": INPUT_JSON_SCHEMA,
        "output_schema": OUTPUT_JSON_SCHEMA,
    }
]

# Alias used by some route discovery implementations.
AIOHTTP_ROUTES = ROUTE_SPECS


def get_route_specs():  # pragma: no cover
    return list(ROUTE_SPECS)


# aiohttp.web.RouteDef list (compatible with app.add_routes()).
try:  # pragma: no cover
    from aiohttp import web

    ROUTES = [web.post("/nodes/reject-action", aiohttp_handler)]
except (ImportError, AttributeError, RuntimeError):  # pragma: no cover
    ROUTES = []


def register_routes(app) -> None:  # pragma: no cover
    """Best-effort hook: register routes onto an aiohttp app."""
    try:
        if ROUTES:
            app.add_routes(ROUTES)
    except (ConnectionError, TimeoutError, RuntimeError):
        # If an upstream system uses ROUTE_SPECS instead, this is fine.
        pass
