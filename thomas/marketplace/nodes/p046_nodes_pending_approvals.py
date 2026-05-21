"""Thomas-native: list node approval requests that are pending.

This module implements **Nodes pending approvals** as a Thomas-native operation.

Storage
- Reads from the Thomas state directory.
- Default store path: ``<state_dir>/nodes/pending_approvals.json``.
- If the store file is missing, returns an empty list.

State directory resolution order
1) Explicit input ``state_dir`` (CLI: ``--state-dir``)
2) ``THOMAS_STATE_DIR`` environment variable
3) Best-effort Thomas config discovery (prefers ``thomas.cli.parity_compat``)

The implementation avoids Reference CLI naming reuse.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class NodesPendingApprovalsError(RuntimeError):
    """Deterministic error type for the nodes pending approvals operation."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details: dict[str, Any] = dict(details or {})


ERROR_INVALID_INPUT = "NODES_PENDING_APPROVALS_INVALID_INPUT"
ERROR_CONFIG_MISSING = "NODES_PENDING_APPROVALS_CONFIG_MISSING"
ERROR_EXTERNAL_FAILURE = "NODES_PENDING_APPROVALS_EXTERNAL_FAILURE"


@dataclass(frozen=True)
class NodesPendingApprovalsInput:
    """Input contract for listing pending node approvals."""

    # Optional override. When set, config discovery is bypassed.
    state_dir: str | Path | None = None

    # Optional override. Intended for tests and advanced automation.
    # If relative, it is interpreted relative to `state_dir`.
    store_path: str | Path | None = None


@dataclass(frozen=True)
class PendingNodeApproval:
    """A single pending node approval request."""

    node_id: str
    requested_at: str | None = None
    requested_by: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class NodesPendingApprovalsOutput:
    """Output contract for listing pending node approvals."""

    approvals: list[PendingNodeApproval]

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.approvals),
            "approvals": [a.to_dict() for a in self.approvals],
        }


_DEFAULT_STORE_CANDIDATES = (
    Path("nodes") / "pending_approvals.json",
    Path("nodes") / "pending-approvals.json",
    Path("nodes") / "approvals" / "pending.json",
    Path("nodes") / "approvals" / "pending_approvals.json",
)


def _coerce_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _call_if_no_required_args(fn: Any) -> Any | None:
    """Call `fn` only when it has no required positional parameters."""

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None

    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            if p.default is inspect.Parameter.empty:
                return None

    return fn()


def _extract_state_dir_from_config(cfg: Any) -> str | None:
    if cfg is None:
        return None

    # Some Thomas configs may directly return the state directory path.
    if isinstance(cfg, (str, Path)):
        val = str(cfg).strip()
        return val or None

    if isinstance(cfg, Mapping):
        for key in ("state_dir", "stateDirectory", "data_dir", "runtime_dir"):
            val = cfg.get(key)
            if isinstance(val, (str, Path)) and str(val).strip():
                return str(val).strip()
        paths = cfg.get("paths")
        if isinstance(paths, Mapping):
            for key in ("state_dir", "data_dir", "runtime_dir"):
                val = paths.get(key)
                if isinstance(val, (str, Path)) and str(val).strip():
                    return str(val).strip()
        return None

    for attr in ("state_dir", "data_dir", "runtime_dir"):
        val = getattr(cfg, attr, None)
        if isinstance(val, (str, Path)) and str(val).strip():
            return str(val).strip()

    paths = getattr(cfg, "paths", None)
    if isinstance(paths, Mapping):
        for key in ("state_dir", "data_dir", "runtime_dir"):
            val = paths.get(key)
            if isinstance(val, (str, Path)) and str(val).strip():
                return str(val).strip()

    return None


def _try_state_dir_from_parity_compat() -> str | None:
    """Best-effort state dir discovery via `thomas.cli.parity_compat`."""

    try:
        pc = importlib.import_module("thomas.cli.parity_compat")
    except (ImportError, AttributeError, RuntimeError):
        return None

    # Direct helpers
    for attr in ("get_state_dir", "state_dir", "resolve_state_dir"):
        fn = getattr(pc, attr, None)
        if callable(fn):
            try:
                val = _call_if_no_required_args(fn)
            except (ImportError, AttributeError, RuntimeError):
                return None
            if isinstance(val, (str, Path)) and str(val).strip():
                return str(val).strip()

    # Paths dict/object
    for attr in ("get_paths", "paths", "PATHS"):
        obj = getattr(pc, attr, None)
        if callable(obj):
            try:
                obj = _call_if_no_required_args(obj)
            except (ImportError, AttributeError, RuntimeError):
                obj = None
        if isinstance(obj, Mapping):
            for key in ("state_dir", "data_dir", "runtime_dir"):
                val = obj.get(key)
                if isinstance(val, (str, Path)) and str(val).strip():
                    return str(val).strip()

    # Config object
    cfg = getattr(pc, "config", None) or getattr(pc, "CONFIG", None)
    val = _extract_state_dir_from_config(cfg)
    if val:
        return val

    # Callable config getter
    for attr in ("get_config", "load_config", "load"):
        fn = getattr(pc, attr, None)
        if callable(fn):
            try:
                cfg = _call_if_no_required_args(fn)
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
            val = _extract_state_dir_from_config(cfg)
            if val:
                return val

    return None


def _try_load_thomas_config() -> Any | None:
    """Fallback config discovery (non-fatal)."""

    for mod_name in (
        "thomas.cli.parity_compat",
        "thomas.config",
        "thomas.core.config",
        "thomas.server.config",
    ):
        try:
            mod = importlib.import_module(mod_name)
        except (ImportError, AttributeError, RuntimeError):
            continue

        for fn_name in ("load_config", "get_config", "load", "config"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    cfg = _call_if_no_required_args(fn)
                except (json.JSONDecodeError, ValueError, KeyError):
                    cfg = None
                if cfg is not None:
                    return cfg

        for attr_name in ("CONFIG", "config", "settings"):
            if hasattr(mod, attr_name):
                return getattr(mod, attr_name)

    return None


def _resolve_state_dir(inp: NodesPendingApprovalsInput) -> Path:
    if inp.state_dir is not None:
        raw = str(inp.state_dir).strip()
        if not raw:
            raise NodesPendingApprovalsError(ERROR_INVALID_INPUT, "state_dir was provided but empty.")
        p = _coerce_path(raw).expanduser()
        if p.exists() and not p.is_dir():
            raise NodesPendingApprovalsError(
                ERROR_INVALID_INPUT,
                "state_dir points to a non-directory path.",
                details={"state_dir": str(p)},
            )
        return p

    env = os.getenv("THOMAS_STATE_DIR")
    if env and env.strip():
        p = Path(env.strip()).expanduser()
        if p.exists() and not p.is_dir():
            raise NodesPendingApprovalsError(
                ERROR_EXTERNAL_FAILURE,
                "Resolved THOMAS_STATE_DIR is not a directory.",
                details={"state_dir": str(p)},
            )
        return p

    pc_state = _try_state_dir_from_parity_compat()
    if pc_state:
        p = Path(pc_state).expanduser()
        if p.exists() and not p.is_dir():
            raise NodesPendingApprovalsError(
                ERROR_EXTERNAL_FAILURE,
                "Resolved state directory from parity_compat is not a directory.",
                details={"state_dir": str(p)},
            )
        return p

    cfg = _try_load_thomas_config()
    state_dir = _extract_state_dir_from_config(cfg)
    if state_dir:
        p = Path(state_dir).expanduser()
        if p.exists() and not p.is_dir():
            raise NodesPendingApprovalsError(
                ERROR_EXTERNAL_FAILURE,
                "Resolved state directory from config is not a directory.",
                details={"state_dir": str(p)},
            )
        return p

    raise NodesPendingApprovalsError(
        ERROR_CONFIG_MISSING,
        "Thomas configuration is missing: unable to resolve state directory.",
        details={"env": "THOMAS_STATE_DIR"},
    )


def _choose_store_path(state_dir: Path, inp: NodesPendingApprovalsInput) -> Path:
    if inp.store_path is not None:
        raw = str(inp.store_path).strip()
        if not raw:
            raise NodesPendingApprovalsError(ERROR_INVALID_INPUT, "store_path was provided but empty.")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = state_dir / p
        return p

    candidates = [state_dir / rel for rel in _DEFAULT_STORE_CANDIDATES]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def _normalize_store_root(data: Any, *, path: Path) -> Sequence[Mapping[str, Any]]:
    if data is None:
        return []

    if isinstance(data, list):
        items = data
    elif isinstance(data, Mapping):
        for key in ("approvals", "pending_approvals", "pending", "requests", "items"):
            maybe = data.get(key)
            if isinstance(maybe, list):
                items = maybe
                break
        else:
            raise NodesPendingApprovalsError(
                ERROR_EXTERNAL_FAILURE,
                "Pending approvals store has an unexpected shape (expected list or object containing a list).",
                details={"path": str(path), "type": type(data).__name__},
            )
    else:
        raise NodesPendingApprovalsError(
            ERROR_EXTERNAL_FAILURE,
            "Pending approvals store has an unexpected shape (expected a list).",
            details={"path": str(path), "type": type(data).__name__},
        )

    out: list[Mapping[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise NodesPendingApprovalsError(
                ERROR_EXTERNAL_FAILURE,
                "Pending approvals store contains a non-object entry.",
                details={"path": str(path), "index": idx, "type": type(item).__name__},
            )
        out.append(item)
    return out


def _read_store(path: Path) -> Sequence[Mapping[str, Any]]:
    try:
        # Accept UTF-8 with optional BOM for Windows-authored JSON files.
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    except IsADirectoryError as exc:
        raise NodesPendingApprovalsError(
            ERROR_EXTERNAL_FAILURE,
            "Pending approvals store path is a directory.",
            details={"path": str(path)},
        ) from exc
    except OSError as exc:
        raise NodesPendingApprovalsError(
            ERROR_EXTERNAL_FAILURE,
            "Failed to read pending approvals store.",
            details={"path": str(path), "exception": type(exc).__name__},
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NodesPendingApprovalsError(
            ERROR_EXTERNAL_FAILURE,
            "Pending approvals store is not valid JSON.",
            details={"path": str(path), "line": exc.lineno, "col": exc.colno},
        ) from exc

    return _normalize_store_root(data, path=path)


def _first_nonempty_str(item: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def nodes_pending_approvals(inp: NodesPendingApprovalsInput) -> NodesPendingApprovalsOutput:
    """List node approval requests that are still pending."""

    state_dir = _resolve_state_dir(inp)
    store_path = _choose_store_path(state_dir, inp)
    raw_items = _read_store(store_path)

    approvals: list[PendingNodeApproval] = []
    for idx, item in enumerate(raw_items):
        node_id = _first_nonempty_str(
            item,
            ("node_id", "nodeId", "id", "node", "device_id", "deviceId"),
        )
        if not node_id:
            raise NodesPendingApprovalsError(
                ERROR_EXTERNAL_FAILURE,
                "Pending approvals store entry is missing required field 'node_id'.",
                details={"path": str(store_path), "index": idx},
            )

        requested_at = _first_nonempty_str(
            item,
            ("requested_at", "requestedAt", "created_at", "createdAt", "timestamp"),
        )
        requested_by = _first_nonempty_str(
            item,
            ("requested_by", "requestedBy", "created_by", "createdBy", "user"),
        )
        reason = _first_nonempty_str(item, ("reason", "note", "notes"))

        metadata: dict[str, Any] = {}
        md = item.get("metadata")
        if isinstance(md, Mapping):
            metadata.update(dict(md))

        # Keep extra fields as metadata for forward-compatibility.
        reserved = {
            "metadata",
            "node_id",
            "nodeId",
            "id",
            "node",
            "device_id",
            "deviceId",
            "requested_at",
            "requestedAt",
            "created_at",
            "createdAt",
            "timestamp",
            "requested_by",
            "requestedBy",
            "created_by",
            "createdBy",
            "user",
            "reason",
            "note",
            "notes",
        }
        for k, v in item.items():
            if k in reserved:
                continue
            metadata.setdefault(k, v)

        approvals.append(
            PendingNodeApproval(
                node_id=node_id,
                requested_at=requested_at,
                requested_by=requested_by,
                reason=reason,
                metadata=metadata,
            )
        )

    approvals.sort(key=lambda a: (a.requested_at or "", a.node_id))
    return NodesPendingApprovalsOutput(approvals=approvals)


# --- Optional aiohttp exposure -------------------------------------------------

try:  # pragma: no cover
    from aiohttp import web
except (ImportError, AttributeError, RuntimeError):  # pragma: no cover
    web = None  # type: ignore


if web is not None:  # pragma: no cover
    routes = web.RouteTableDef()

    @routes.get("/nodes/pending-approvals")
    async def aiohttp_nodes_pending_approvals(request: web.Request) -> web.Response:
        try:
            result = nodes_pending_approvals(NodesPendingApprovalsInput())
            payload = {"ok": True, **result.to_dict()}
            return web.json_response(payload, status=200)
        except NodesPendingApprovalsError as exc:
            status = 400 if exc.code in (ERROR_INVALID_INPUT, ERROR_CONFIG_MISSING) else 500
            return web.json_response(
                {"ok": False, "error": {"code": exc.code, "message": str(exc), "details": exc.details}},
                status=status,
            )

    ROUTES = routes

    def register_aiohttp_routes(app: web.Application) -> None:
        app.add_routes(routes)


def get_aiohttp_routes():  # pragma: no cover
    """Return aiohttp routes for auto-registration systems."""

    if web is None:
        return None
    return globals().get("routes")


__all__ = [
    "NodesPendingApprovalsError",
    "NodesPendingApprovalsInput",
    "PendingNodeApproval",
    "NodesPendingApprovalsOutput",
    "nodes_pending_approvals",
    "ERROR_INVALID_INPUT",
    "ERROR_CONFIG_MISSING",
    "ERROR_EXTERNAL_FAILURE",
]
