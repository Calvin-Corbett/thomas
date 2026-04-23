"""Node command status.

This module provides a small, Thomas-native API for querying the status of a command that
was dispatched to a node. It is designed to be usable from both the CLI and HTTP routes.

Primary API:
- get_node_command_status(NodeCommandStatusRequest) -> NodeCommandStatusResponse

Backends:
1) A first-party Thomas backend (if present in the runtime environment)
2) A conservative on-disk JSON state backend (fallback)

On-disk backend format
----------------------
The on-disk backend stores one JSON document per command in a configured directory.

Default filename:
    <command_id>.json

If a node_id is provided, the backend also checks:
    <state_dir>/<node_id>/<command_id>.json

Configuration discovery order:
1) Explicit `state_dir` passed in NodeCommandStatusRequest
2) Environment variable THOMAS_NODE_COMMAND_STATE_DIR
3) Environment variable THOMAS_STATE_DIR (uses "<THOMAS_STATE_DIR>/node_commands")
4) Environment variable THOMAS_CONFIG (JSON file path) supporting:
      - node_command_state_dir
      - state_dir (uses "<state_dir>/node_commands")
5) A JSON config file at "~/.thomas/config.json" supporting the same keys

Errors are deterministic and machine-readable via `code` + stable messages.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

_ALLOWED_STATES = {"queued", "running", "succeeded", "failed", "unknown"}

# NOTE: This is intentionally restrictive to prevent path traversal when reading
# `<state_dir>/<command_id>.json`. UUIDs and typical job IDs work fine.
_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


class NodeCommandStatusError(RuntimeError):
    """Base error for node command status failures.

    The `code` is stable/machine-readable; the `message` is deterministic.
    """

    code: str = "node_command_status_error"
    exit_code: int = 1

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class NodeCommandStatusInvalidInputError(NodeCommandStatusError):
    code = "invalid_input"
    exit_code = 2


class NodeCommandStatusConfigError(NodeCommandStatusError):
    code = "missing_config"
    exit_code = 3


class NodeCommandStatusNotFoundError(NodeCommandStatusError):
    code = "not_found"
    exit_code = 4


class NodeCommandStatusExternalError(NodeCommandStatusError):
    code = "external_failure"
    exit_code = 5


class NodeCommandStatusRecord(TypedDict, total=False):
    command_id: str
    node_id: str
    state: str
    status: str
    done: bool
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    message: str
    error: str
    started_at: str
    finished_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class NodeCommandStatusRequest:
    """Input contract for node command status.

    Attributes:
        command_id: The command identifier.
        node_id: Optional node identifier (when a command_id is not globally unique).
        include_output: If True, include stdout/stderr if available.
        state_dir: Optional override for where status records are stored.
    """

    command_id: str
    node_id: str | None = None
    include_output: bool = False
    state_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class NodeCommandStatusResponse:
    """Output contract for node command status."""

    command_id: str
    node_id: str | None
    state: str
    done: bool
    success: bool | None
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    message: str | None = None
    retrieved_at_epoch_s: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        # Keep output stable + JSON-friendly.
        return asdict(self)


class _StatusBackend(Protocol):
    def get_status(self, req: NodeCommandStatusRequest) -> NodeCommandStatusResponse: ...


def get_node_command_status(req: NodeCommandStatusRequest) -> NodeCommandStatusResponse:
    """Query a node command status."""
    _validate_request(req)

    native = _try_native_backend(req)
    if native is not None:
        return native

    state_dir = _ensure_state_dir(_resolve_state_dir(req))
    record_path = _find_record_path(state_dir, req)

    if record_path is None:
        expected = state_dir / f"{req.command_id}.json"
        raise NodeCommandStatusNotFoundError(
            "command status record not found",
            detail=f"path={expected.as_posix()}",
        )

    record = _read_record_json(record_path)
    return _response_from_record(req, record)


def node_command_status_response_schema() -> dict[str, Any]:
    """A small JSON Schema for automation."""
    return {
        "type": "object",
        "required": ["command_id", "node_id", "state", "done", "success", "retrieved_at_epoch_s"],
        "properties": {
            "command_id": {"type": "string"},
            "node_id": {"type": ["string", "null"]},
            "state": {"type": "string", "enum": sorted(_ALLOWED_STATES)},
            "done": {"type": "boolean"},
            "success": {"type": ["boolean", "null"]},
            "exit_code": {"type": ["integer", "null"]},
            "stdout": {"type": ["string", "null"]},
            "stderr": {"type": ["string", "null"]},
            "message": {"type": ["string", "null"]},
            "retrieved_at_epoch_s": {"type": "integer"},
        },
        "additionalProperties": False,
    }


def _validate_request(req: NodeCommandStatusRequest) -> None:
    if not isinstance(req.command_id, str):
        raise NodeCommandStatusInvalidInputError("command_id must be a string")
    cmd = req.command_id.strip()
    if cmd != req.command_id:
        raise NodeCommandStatusInvalidInputError("command_id must not have leading/trailing whitespace")
    if not cmd:
        raise NodeCommandStatusInvalidInputError("command_id is required")

    if not _COMMAND_ID_RE.match(cmd):
        raise NodeCommandStatusInvalidInputError("command_id contains invalid characters")
    if "/" in cmd or "\\" in cmd:
        raise NodeCommandStatusInvalidInputError("command_id must not contain path separators")

    if req.node_id is not None:
        if not isinstance(req.node_id, str):
            raise NodeCommandStatusInvalidInputError("node_id must be a string when provided")
        nid = req.node_id.strip()
        if nid != req.node_id or not nid:
            raise NodeCommandStatusInvalidInputError("node_id must be non-empty and trimmed when provided")
        if re.search(r"\s", nid):
            raise NodeCommandStatusInvalidInputError("node_id must not contain whitespace")
        if "/" in nid or "\\" in nid:
            raise NodeCommandStatusInvalidInputError("node_id must not contain path separators")


def _resolve_state_dir(req: NodeCommandStatusRequest) -> Path:
    if req.state_dir is not None:
        return Path(req.state_dir)

    env_explicit = os.getenv("THOMAS_NODE_COMMAND_STATE_DIR")
    if env_explicit:
        return Path(env_explicit)

    env_state = os.getenv("THOMAS_STATE_DIR")
    if env_state:
        return Path(env_state) / "node_commands"

    env_cfg = os.getenv("THOMAS_CONFIG")
    if env_cfg:
        cfg_dir = _read_config_for_state_dir(Path(env_cfg))
        if cfg_dir is not None:
            return cfg_dir

    cfg_path = Path.home() / ".thomas" / "config.json"
    cfg_dir = _read_config_for_state_dir(cfg_path)
    if cfg_dir is not None:
        return cfg_dir

    raise NodeCommandStatusConfigError("node command status state directory is not configured")


def _read_config_for_state_dir(cfg_path: Path) -> Path | None:
    if not cfg_path.exists():
        return None
    try:
        cfg_raw = cfg_path.read_text(encoding="utf-8")
        cfg = json.loads(cfg_raw)
    except (json.JSONDecodeError, ValueError, KeyError):
        raise NodeCommandStatusConfigError("failed to load config for node command status")

    if not isinstance(cfg, dict):
        return None

    node_cmd_dir = cfg.get("node_command_state_dir")
    if isinstance(node_cmd_dir, str) and node_cmd_dir:
        return Path(node_cmd_dir)

    state_dir = cfg.get("state_dir")
    if isinstance(state_dir, str) and state_dir:
        return Path(state_dir) / "node_commands"

    return None


def _ensure_state_dir(state_dir: Path) -> Path:
    if not state_dir.exists():
        raise NodeCommandStatusConfigError(
            "node command status state directory does not exist",
            detail=f"path={state_dir.as_posix()}",
        )
    if not state_dir.is_dir():
        raise NodeCommandStatusConfigError(
            "node command status state path is not a directory",
            detail=f"path={state_dir.as_posix()}",
        )
    return state_dir


def _find_record_path(state_dir: Path, req: NodeCommandStatusRequest) -> Path | None:
    candidates: list[Path] = []
    if req.node_id:
        candidates.append(state_dir / req.node_id / f"{req.command_id}.json")
    candidates.append(state_dir / f"{req.command_id}.json")

    for p in candidates:
        if p.exists():
            return p
    return None


def _read_record_json(record_path: Path) -> NodeCommandStatusRecord:
    try:
        raw = record_path.read_text(encoding="utf-8")
    except OSError as e:
        raise NodeCommandStatusExternalError(
            "failed to read command status record",
            detail=f"oserror={type(e).__name__}",
        ) from e

    try:
        record = cast(NodeCommandStatusRecord, json.loads(raw))
    except json.JSONDecodeError as e:
        raise NodeCommandStatusExternalError(
            "command status record is not valid JSON",
            detail=f"json_error={e.msg}",
        ) from e

    if not isinstance(record, dict):
        raise NodeCommandStatusExternalError("command status record JSON must be an object")
    return record


def _response_from_record(req: NodeCommandStatusRequest, record: Mapping[str, Any]) -> NodeCommandStatusResponse:
    command_id = str(record.get("command_id") or req.command_id)

    record_node = record.get("node_id")
    node_id = str(record_node) if record_node is not None else req.node_id

    if req.node_id is not None and node_id is not None and node_id != req.node_id:
        raise NodeCommandStatusNotFoundError(
            "command status record does not match requested node_id",
            detail=f"record_node_id={node_id} requested_node_id={req.node_id}",
        )

    state = _normalize_state(record.get("state") or record.get("status"))

    done = _coerce_optional_bool(record.get("done"))
    success = _coerce_optional_bool(record.get("success"))

    if state in {"succeeded", "failed"}:
        if done is None:
            done = True
        if success is None:
            success = state == "succeeded"
    elif state in {"queued", "running"}:
        if done is None:
            done = False
    else:
        if done is None:
            done = False

    exit_code = _coerce_optional_int(record.get("exit_code"))
    message = cast(str | None, record.get("message") or record.get("error"))

    stdout = cast(str | None, record.get("stdout"))
    stderr = cast(str | None, record.get("stderr"))
    if not req.include_output:
        stdout = None
        stderr = None

    return NodeCommandStatusResponse(
        command_id=command_id,
        node_id=node_id,
        state=state,
        done=bool(done),
        success=success,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        message=message,
    )


def _normalize_state(raw: Any) -> str:
    if raw is None:
        return "unknown"
    s = str(raw).strip().lower()
    if not s:
        return "unknown"

    synonyms = {
        "pending": "queued",
        "waiting": "queued",
        "queued": "queued",
        "running": "running",
        "in_progress": "running",
        "in-progress": "running",
        "success": "succeeded",
        "succeeded": "succeeded",
        "ok": "succeeded",
        "complete": "succeeded",
        "completed": "succeeded",
        "done": "succeeded",
        "fail": "failed",
        "failed": "failed",
        "error": "failed",
        "cancelled": "failed",
        "canceled": "failed",
        "timeout": "failed",
        "timed_out": "failed",
        "timed-out": "failed",
    }
    norm = synonyms.get(s, s)
    return norm if norm in _ALLOWED_STATES else "unknown"


def _coerce_optional_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y"}:
            return True
        if s in {"0", "false", "no", "n"}:
            return False
    return None


def _coerce_optional_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(s, 10)
        except ValueError:
            return None
    return None


def _try_native_backend(req: NodeCommandStatusRequest) -> NodeCommandStatusResponse | None:
    """Try to call an existing Thomas backend if present."""
    candidates: list[tuple[str, str]] = [
        ("thomas.marketplace.nodes.command_status", "get_command_status"),
        ("thomas.marketplace.nodes.command_status", "node_command_status"),
        ("thomas.marketplace.nodes.node_commands", "get_command_status"),
        ("thomas.marketplace.nodes.node_commands", "command_status"),
        ("thomas.marketplace.nodes.commands", "get_command_status"),
        ("thomas.marketplace.nodes.commands", "command_status"),
        ("thomas.marketplace.nodes.command_store", "get_command_status"),
        ("thomas.marketplace.nodes.command_store", "read_command_status"),
    ]

    for mod_name, func_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
        except (ImportError, AttributeError, RuntimeError):
            continue
        func = getattr(mod, func_name, None)
        if not callable(func):
            continue
        try:
            result = _call_with_compatible_signature(func, req)
        except NodeCommandStatusError:
            raise
        except (ImportError, AttributeError, RuntimeError) as e:
            raise NodeCommandStatusExternalError(
                "native backend failed while querying command status",
                detail=f"backend={mod_name}.{func_name}",
            ) from e

        try:
            return _coerce_native_result(req, result)
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError):
            continue

    return None


def _call_with_compatible_signature(func: Any, req: NodeCommandStatusRequest) -> Any:
    kwargs_pool = {
        "req": req,
        "request": req,
        "command_id": req.command_id,
        "cmd_id": req.command_id,
        "id": req.command_id,
        "node_id": req.node_id,
        "node": req.node_id,
        "include_output": req.include_output,
        "with_output": req.include_output,
    }

    try:
        sig = inspect.signature(func)
        call_kwargs = {k: v for k, v in kwargs_pool.items() if k in sig.parameters}
        call_kwargs = {
            k: v
            for k, v in call_kwargs.items()
            if v is not None or sig.parameters[k].default is not inspect.Parameter.empty
        }
        return func(**call_kwargs)
    except (TypeError, ValueError):
        for attempt in (
            (req,),
            (req.command_id,),
            (req.command_id, req.node_id),
        ):
            try:
                return func(*attempt)
            except TypeError:
                continue
        return func(req.command_id)


def _coerce_native_result(req: NodeCommandStatusRequest, result: Any) -> NodeCommandStatusResponse:
    if isinstance(result, NodeCommandStatusResponse):
        return result

    if hasattr(result, "__dict__"):
        mapping = cast(Mapping[str, Any], result.__dict__)
    elif isinstance(result, Mapping):
        mapping = cast(Mapping[str, Any], result)
    else:
        raise ValueError("unsupported result type")

    record: dict[str, Any] = {}

    for key in ("command_id", "cmd_id", "id"):
        if key in mapping and mapping.get(key):
            record["command_id"] = mapping.get(key)
            break

    for key in ("node_id", "node", "node_name"):
        if key in mapping and mapping.get(key) is not None:
            record["node_id"] = mapping.get(key)
            break

    for key in ("state", "status"):
        if key in mapping and mapping.get(key) is not None:
            record["state"] = mapping.get(key)
            break

    for key in ("done", "complete", "completed", "is_done"):
        if key in mapping and mapping.get(key) is not None:
            record["done"] = mapping.get(key)
            break

    for key in ("success", "ok", "succeeded"):
        if key in mapping and mapping.get(key) is not None:
            record["success"] = mapping.get(key)
            break

    for key in ("exit_code", "return_code", "rc"):
        if key in mapping and mapping.get(key) is not None:
            record["exit_code"] = mapping.get(key)
            break

    for key in ("stdout", "output"):
        if key in mapping and mapping.get(key) is not None:
            record["stdout"] = mapping.get(key)
            break

    for key in ("stderr", "error_output"):
        if key in mapping and mapping.get(key) is not None:
            record["stderr"] = mapping.get(key)
            break

    for key in ("message", "error", "detail"):
        if key in mapping and mapping.get(key) is not None:
            record["message"] = mapping.get(key)
            break

    return _response_from_record(req, record)


# ---- Optional aiohttp route integration ------------------------------------
# The core aiohttp server in Thomas can choose to register these routes to expose
# node-command status over HTTP. This module intentionally keeps this optional
# and side-effect-free for CLI-only environments.

try:  # pragma: no cover
    from aiohttp import web as _aiohttp_web  # type: ignore
except (ImportError, AttributeError, RuntimeError):  # pragma: no cover
    _aiohttp_web = None  # type: ignore


if _aiohttp_web is not None:  # pragma: no cover
    routes = _aiohttp_web.RouteTableDef()

    @routes.get("/nodes/commands/{command_id}/status")
    async def aiohttp_node_command_status(request):  # type: ignore[no-untyped-def]
        command_id = request.match_info.get("command_id", "")
        node_id = request.query.get("node_id")
        include_output_raw = request.query.get("include_output", "0")
        include_output = str(include_output_raw).strip().lower() in {"1", "true", "yes", "y"}

        try:
            resp = get_node_command_status(
                NodeCommandStatusRequest(
                    command_id=command_id,
                    node_id=node_id,
                    include_output=include_output,
                )
            )
            return _aiohttp_web.json_response(resp.to_dict(), status=200)
        except NodeCommandStatusInvalidInputError as e:
            return _aiohttp_web.json_response(e.to_dict(), status=400)
        except NodeCommandStatusNotFoundError as e:
            return _aiohttp_web.json_response(e.to_dict(), status=404)
        except NodeCommandStatusConfigError as e:
            return _aiohttp_web.json_response(e.to_dict(), status=500)
        except NodeCommandStatusExternalError as e:
            return _aiohttp_web.json_response(e.to_dict(), status=502)

    @routes.get("/nodes/commands/status/schema")
    async def aiohttp_node_command_status_schema(request):  # type: ignore[no-untyped-def]
        _ = request
        return _aiohttp_web.json_response(node_command_status_response_schema(), status=200)
