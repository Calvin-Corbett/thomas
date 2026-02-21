from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional, Protocol, TypedDict


# ----------------------------
# Errors
# ----------------------------


class CanvasActionError(RuntimeError):
    """Base exception for all nodes-canvas-action failures.

    We keep a stable machine-readable `code` so both CLI and HTTP layers can
    produce deterministic error payloads.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class CanvasActionInputError(CanvasActionError):
    """Invalid user input."""


class CanvasActionConfigError(CanvasActionError):
    """Missing or invalid configuration/state."""


class CanvasActionExternalError(CanvasActionError):
    """External (I/O) failure."""


# ----------------------------
# Typed contracts
# ----------------------------


class CanvasViewportDict(TypedDict):
    x: float
    y: float
    zoom: float


class CanvasStateDict(TypedDict):
    viewport: CanvasViewportDict
    selected_node_ids: list[str]


class NodesCanvasActionRequestDict(TypedDict, total=False):
    canvas_id: str
    operation: str
    payload: dict[str, Any]
    dry_run: bool


class NodesCanvasActionResponseDict(TypedDict):
    ok: bool
    canvas_id: str
    operation: str
    applied: bool
    state: CanvasStateDict


@dataclass(slots=True)
class CanvasViewport:
    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0

    def to_dict(self) -> CanvasViewportDict:
        return {"x": float(self.x), "y": float(self.y), "zoom": float(self.zoom)}


@dataclass(slots=True)
class CanvasState:
    viewport: CanvasViewport = field(default_factory=CanvasViewport)
    selected_node_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> CanvasStateDict:
        return {"viewport": self.viewport.to_dict(), "selected_node_ids": list(self.selected_node_ids)}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CanvasState":
        viewport_raw = raw.get("viewport") or {}
        if not isinstance(viewport_raw, Mapping):
            raise CanvasActionConfigError("invalid_state", "Canvas viewport must be an object.")

        try:
            x = float(viewport_raw.get("x", 0.0))
            y = float(viewport_raw.get("y", 0.0))
            zoom = float(viewport_raw.get("zoom", 1.0))
        except Exception as e:
            raise CanvasActionConfigError("invalid_state", "Canvas viewport fields must be numbers.") from e

        selected = raw.get("selected_node_ids")
        if selected is None:
            selected_list: list[str] = []
        else:
            if not isinstance(selected, list) or any(not isinstance(xi, str) for xi in selected):
                raise CanvasActionConfigError(
                    "invalid_state",
                    "Canvas selected_node_ids must be a list of strings.",
                )
            selected_list = [xi for xi in selected]

        return cls(viewport=CanvasViewport(x=x, y=y, zoom=zoom), selected_node_ids=selected_list)


@dataclass(frozen=True, slots=True)
class NodesCanvasActionRequest:
    canvas_id: str
    operation: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def to_dict(self) -> NodesCanvasActionRequestDict:
        return {
            "canvas_id": self.canvas_id,
            "operation": self.operation,
            "payload": dict(self.payload),
            "dry_run": bool(self.dry_run),
        }


@dataclass(frozen=True, slots=True)
class NodesCanvasActionResponse:
    ok: bool
    canvas_id: str
    operation: str
    applied: bool
    state: CanvasState

    def to_dict(self) -> NodesCanvasActionResponseDict:
        return {
            "ok": bool(self.ok),
            "canvas_id": self.canvas_id,
            "operation": self.operation,
            "applied": bool(self.applied),
            "state": self.state.to_dict(),
        }


# ----------------------------
# Persistence
# ----------------------------


class CanvasStateStore(Protocol):
    def load(self, canvas_id: str) -> CanvasState: ...

    def save(self, canvas_id: str, state: CanvasState) -> None: ...


def _default_state_path() -> Path:
    """Resolve the on-disk location for persistent canvas state.

    Preference order:
      1) THOMAS_STATE_DIR env var -> <dir>/nodes_canvas_state.json
      2) ~/.thomas/state/nodes_canvas_state.json

    Notes:
      - This is *state*, not configuration. The file may not exist on first run.
    """

    env_dir = os.environ.get("THOMAS_STATE_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve() / "nodes_canvas_state.json"
    return Path.home().expanduser().resolve() / ".thomas" / "state" / "nodes_canvas_state.json"


class FileCanvasStateStore:
    """JSON file backed store.

    File format: a JSON object mapping canvas_id -> state dict.

    The store is created on first write. Missing file on load yields a default
    state.
    """

    def __init__(self, path: Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> MutableMapping[str, Any]:
        if not self._path.exists():
            return {}
        if self._path.is_dir():
            raise CanvasActionConfigError(
                "invalid_state_store",
                f"Canvas state store path '{self._path}' is a directory.",
            )
        try:
            text = self._path.read_text(encoding="utf-8")
        except Exception as e:  # pragma: no cover
            raise CanvasActionExternalError(
                "state_store_read_failed",
                f"Failed to read canvas state store at '{self._path}'.",
            ) from e
        try:
            raw = json.loads(text or "{}")
        except Exception as e:
            raise CanvasActionConfigError(
                "invalid_state_store",
                f"Canvas state store at '{self._path}' is not valid JSON.",
            ) from e
        if not isinstance(raw, dict):
            raise CanvasActionConfigError(
                "invalid_state_store",
                "Canvas state store must be a JSON object.",
            )
        return raw

    def load(self, canvas_id: str) -> CanvasState:
        raw = self._read_all()
        state_raw = raw.get(canvas_id)
        if state_raw is None:
            return CanvasState()
        if not isinstance(state_raw, Mapping):
            raise CanvasActionConfigError(
                "invalid_state",
                "Canvas state for canvas_id must be a JSON object.",
            )
        return CanvasState.from_dict(state_raw)

    def save(self, canvas_id: str, state: CanvasState) -> None:
        data = self._read_all()
        data[canvas_id] = state.to_dict()

        # Ensure parent directory exists.
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise CanvasActionExternalError(
                "state_store_write_failed",
                f"Failed to create canvas state directory '{self._path.parent}'.",
            ) from e

        # Atomic write to reduce risk of partial/corrupt files.
        try:
            payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
        except Exception as e:  # pragma: no cover
            raise CanvasActionExternalError(
                "state_store_write_failed",
                "Failed to serialize canvas state store.",
            ) from e

        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self._path.parent),
                delete=False,
                prefix=self._path.name + ".",
                suffix=".tmp",
            ) as tf:
                tmp_path = Path(tf.name)
                tf.write(payload)
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(str(tmp_path), str(self._path))
        except Exception as e:  # pragma: no cover
            try:
                if "tmp_path" in locals() and Path(tmp_path).exists():
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise CanvasActionExternalError(
                "state_store_write_failed",
                f"Failed to write canvas state store at '{self._path}'.",
            ) from e


# ----------------------------
# Action logic
# ----------------------------


_ALLOWED_OPERATIONS = {
    "pan",
    "zoom",
    "select",
    "focus",
    "clear-selection",
}


def _require_number(payload: Mapping[str, Any], key: str) -> float:
    if key not in payload:
        raise CanvasActionInputError("missing_field", f"Missing required payload field '{key}'.")
    val = payload[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise CanvasActionInputError("invalid_field", f"Payload field '{key}' must be a number.")
    return float(val)


def _require_str(payload: Mapping[str, Any], key: str) -> str:
    if key not in payload:
        raise CanvasActionInputError("missing_field", f"Missing required payload field '{key}'.")
    val = payload[key]
    if not isinstance(val, str) or not val.strip():
        raise CanvasActionInputError("invalid_field", f"Payload field '{key}' must be a non-empty string.")
    return val.strip()


def _require_str_list(payload: Mapping[str, Any], key: str) -> list[str]:
    if key not in payload:
        raise CanvasActionInputError("missing_field", f"Missing required payload field '{key}'.")
    val = payload[key]
    if not isinstance(val, list) or any(not isinstance(x, str) or not x.strip() for x in val):
        raise CanvasActionInputError("invalid_field", f"Payload field '{key}' must be a list of non-empty strings.")
    # Deduplicate while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for x in val:
        sx = x.strip()
        if sx in seen:
            continue
        seen.add(sx)
        out.append(sx)
    return out


def _apply_operation(state: CanvasState, operation: str, payload: Mapping[str, Any]) -> None:
    """Mutate state in-place according to operation."""

    if operation == "pan":
        dx = _require_number(payload, "dx")
        dy = _require_number(payload, "dy")
        state.viewport.x += dx
        state.viewport.y += dy
        return

    if operation == "zoom":
        factor = _require_number(payload, "factor")
        if factor <= 0:
            raise CanvasActionInputError("invalid_field", "Payload field 'factor' must be > 0.")
        state.viewport.zoom *= factor
        return

    if operation == "select":
        node_ids = _require_str_list(payload, "node_ids")
        state.selected_node_ids = node_ids
        return

    if operation == "focus":
        node_id = _require_str(payload, "node_id")
        state.selected_node_ids = [node_id]
        return

    if operation == "clear-selection":
        state.selected_node_ids = []
        return

    # Guardrail: should be unreachable due to validation.
    raise CanvasActionInputError("unknown_operation", f"Unknown operation '{operation}'.")


def run_nodes_canvas_action(
    request: NodesCanvasActionRequest,
    *,
    store: Optional[CanvasStateStore] = None,
) -> NodesCanvasActionResponse:
    """Apply an operation to a nodes canvas and persist state."""

    canvas_id = (request.canvas_id or "").strip()
    if not canvas_id:
        raise CanvasActionInputError("invalid_canvas_id", "canvas_id must be a non-empty string.")

    operation = (request.operation or "").strip()
    if not operation:
        raise CanvasActionInputError("invalid_operation", "operation must be a non-empty string.")
    if operation not in _ALLOWED_OPERATIONS:
        raise CanvasActionInputError(
            "unknown_operation",
            f"Unknown operation '{operation}'. Allowed operations: {', '.join(sorted(_ALLOWED_OPERATIONS))}.",
        )

    payload = request.payload or {}
    if not isinstance(payload, Mapping):
        raise CanvasActionInputError("invalid_payload", "payload must be a JSON object.")

    if store is None:
        store = FileCanvasStateStore(_default_state_path())

    # Load state.
    base_state = store.load(canvas_id)

    # Work on a copy so dry-run has no side-effects even if store returns cached objects.
    state = CanvasState.from_dict(base_state.to_dict())

    _apply_operation(state, operation, payload)

    if not request.dry_run:
        store.save(canvas_id, state)

    return NodesCanvasActionResponse(
        ok=True,
        canvas_id=canvas_id,
        operation=operation,
        applied=True,
        state=state,
    )


# ----------------------------
# JSON schema (useful for HTTP routes / automation)
# ----------------------------


REQUEST_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["canvas_id", "operation"],
    "properties": {
        "canvas_id": {"type": "string", "minLength": 1},
        "operation": {"type": "string", "minLength": 1},
        "payload": {"type": "object"},
        "dry_run": {"type": "boolean"},
    },
    "additionalProperties": False,
}

RESPONSE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ok", "canvas_id", "operation", "applied", "state"],
    "properties": {
        "ok": {"type": "boolean"},
        "canvas_id": {"type": "string"},
        "operation": {"type": "string"},
        "applied": {"type": "boolean"},
        "state": {
            "type": "object",
            "required": ["viewport", "selected_node_ids"],
            "properties": {
                "viewport": {
                    "type": "object",
                    "required": ["x", "y", "zoom"],
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "zoom": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
                "selected_node_ids": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}
