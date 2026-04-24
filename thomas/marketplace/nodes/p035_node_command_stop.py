"""Thomas node command: stop.

Implements a Thomas-native **node stop** operation with:
- Clear input/output contracts (dataclasses / TypedDict)
- Deterministic, machine-readable errors
- A backend resolution layer that delegates to the existing Thomas node control
  implementation without hard-coding one internal API.

This module intentionally does **not** reuse legacy naming.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypedDict

__all__ = [
    "NodeCommandStopInput",
    "NodeCommandStopOutput",
    "NodeCommandStopError",
    "NodeCommandStopInvalidInputError",
    "NodeCommandStopConfigError",
    "NodeCommandStopExternalError",
    "NODE_COMMAND_STOP_REQUEST_SCHEMA",
    "NODE_COMMAND_STOP_RESPONSE_SCHEMA",
    "node_command_stop_async",
    "node_command_stop",
]


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class NodeCommandStopRequestJson(TypedDict, total=False):
    node_id: str
    force: bool
    timeout_s: float | None
    config_path: str | None


class NodeCommandStopResultJson(TypedDict):
    ok: bool
    node_id: str
    stopped: bool
    message: str


@dataclass(frozen=True, slots=True)
class NodeCommandStopInput:
    """Input contract for stopping a node."""

    node_id: str
    force: bool = False
    timeout_s: float | None = None
    config_path: str | None = None

    def to_json(self) -> NodeCommandStopRequestJson:
        return {
            "node_id": self.node_id,
            "force": bool(self.force),
            "timeout_s": self.timeout_s,
            "config_path": self.config_path,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> NodeCommandStopInput:
        """Parse a JSON-like mapping into :class:`NodeCommandStopInput`.

        This is useful for HTTP routes or automation callers.
        """
        if not isinstance(data, Mapping):
            raise NodeCommandStopInvalidInputError(
                "request must be a JSON object",
                details={"field": "<root>", "expected": "object"},
            )

        # Reject unknown keys for determinism.
        allowed = {"node_id", "force", "timeout_s", "config_path"}
        unknown = sorted([k for k in data.keys() if k not in allowed])
        if unknown:
            raise NodeCommandStopInvalidInputError(
                "request contains unknown fields",
                details={"unknown": unknown},
            )

        if "node_id" not in data:
            raise NodeCommandStopInvalidInputError(
                "node_id is required",
                details={"field": "node_id"},
            )
        node_id = data.get("node_id")
        if not isinstance(node_id, str):
            raise NodeCommandStopInvalidInputError(
                "node_id must be a string",
                details={"field": "node_id", "expected": "string"},
            )

        force = data.get("force", False)
        if not isinstance(force, bool):
            raise NodeCommandStopInvalidInputError(
                "force must be a boolean",
                details={"field": "force", "expected": "boolean"},
            )

        timeout_s = data.get("timeout_s", None)
        if timeout_s is not None and not isinstance(timeout_s, (int, float)):
            raise NodeCommandStopInvalidInputError(
                "timeout_s must be a number or null",
                details={"field": "timeout_s", "expected": "number|null"},
            )
        timeout_s_f = float(timeout_s) if timeout_s is not None else None

        config_path = data.get("config_path", None)
        if config_path is not None and not isinstance(config_path, str):
            raise NodeCommandStopInvalidInputError(
                "config_path must be a string or null",
                details={"field": "config_path", "expected": "string|null"},
            )

        inp = cls(
            node_id=node_id,
            force=force,
            timeout_s=timeout_s_f,
            config_path=config_path,
        )
        _validate_input(inp)
        return inp


@dataclass(frozen=True, slots=True)
class NodeCommandStopOutput:
    """Output contract for stopping a node."""

    ok: bool
    node_id: str
    stopped: bool
    message: str

    def to_json(self) -> NodeCommandStopResultJson:
        return {
            "ok": bool(self.ok),
            "node_id": self.node_id,
            "stopped": bool(self.stopped),
            "message": self.message,
        }


# Minimal JSON schema hints (useful for HTTP routes / automation).
NODE_COMMAND_STOP_REQUEST_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "node_id": {"type": "string", "minLength": 1},
        "force": {"type": "boolean"},
        "timeout_s": {"type": ["number", "null"], "minimum": 0},
        "config_path": {"type": ["string", "null"]},
    },
    "required": ["node_id"],
}

NODE_COMMAND_STOP_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "node_id": {"type": "string"},
        "stopped": {"type": "boolean"},
        "message": {"type": "string"},
    },
    "required": ["ok", "node_id", "stopped", "message"],
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class NodeCommandStopError(Exception):
    """Base error for the stop command."""

    code: str = "THOMAS_NODE_STOP_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self._details: Mapping[str, Any] = dict(details or {})

    @property
    def details(self) -> Mapping[str, Any]:
        return self._details

    def to_json(self) -> Mapping[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": dict(self.details),
        }


class NodeCommandStopInvalidInputError(NodeCommandStopError):
    code = "THOMAS_NODE_STOP_INVALID_INPUT"


class NodeCommandStopConfigError(NodeCommandStopError):
    code = "THOMAS_NODE_STOP_MISSING_CONFIG"


class NodeCommandStopExternalError(NodeCommandStopError):
    code = "THOMAS_NODE_STOP_EXTERNAL_FAILURE"


# ---------------------------------------------------------------------------
# Backend resolution + invocation
# ---------------------------------------------------------------------------


class StopBackend(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        ...


def _validate_input(inp: NodeCommandStopInput) -> None:
    node_id = (inp.node_id or "").strip()
    if not node_id:
        raise NodeCommandStopInvalidInputError(
            "node_id must be a non-empty string",
            details={"field": "node_id"},
        )
    if any(ord(ch) < 32 for ch in node_id):
        raise NodeCommandStopInvalidInputError(
            "node_id contains control characters",
            details={"field": "node_id"},
        )
    if inp.timeout_s is not None and inp.timeout_s < 0:
        raise NodeCommandStopInvalidInputError(
            "timeout_s must be >= 0",
            details={"field": "timeout_s"},
        )


def _load_config(path: str) -> Mapping[str, Any]:
    p = Path(path)
    if not p.exists():
        raise NodeCommandStopConfigError(
            "config_path does not exist",
            details={"config_path": str(p)},
        )
    if not p.is_file():
        raise NodeCommandStopConfigError(
            "config_path is not a file",
            details={"config_path": str(p)},
        )
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise NodeCommandStopConfigError(
            "unable to read config_path",
            details={"config_path": str(p), "reason": type(e).__name__},
        ) from e

    suffix = p.suffix.lower()
    if suffix == ".json":
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            raise NodeCommandStopConfigError(
                "unable to parse config_path",
                details={"config_path": str(p), "reason": "InvalidJson"},
            ) from e
        return parsed if isinstance(parsed, Mapping) else {}

    if suffix in {".yml", ".yaml"}:
        try:
            import yaml  # type: ignore
        except (json.JSONDecodeError, ValueError, KeyError) as e:  # ImportError or other import-time issues
            raise NodeCommandStopConfigError(
                "unable to parse config_path",
                details={
                    "config_path": str(p),
                    "reason": "MissingDependency",
                    "dependency": "PyYAML",
                },
            ) from e
        try:
            parsed = yaml.safe_load(raw)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            raise NodeCommandStopConfigError(
                "unable to parse config_path",
                details={"config_path": str(p), "reason": "InvalidYaml"},
            ) from e
        return parsed if isinstance(parsed, Mapping) else {}

    # Unknown extension: try JSON (many projects ship extension-less JSON).
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, Mapping) else {}
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise NodeCommandStopConfigError(
            "unable to parse config_path",
            details={"config_path": str(p), "reason": "UnknownFormat"},
        ) from e


def _parse_backend_spec(spec: str) -> StopBackend | None:
    """Parse THOMAS_NODE_STOP_BACKEND="module:function"."""
    if not spec or ":" not in spec:
        return None
    mod_name, attr = spec.split(":", 1)
    mod_name, attr = mod_name.strip(), attr.strip()
    if not mod_name or not attr:
        return None
    try:
        mod = importlib.import_module(mod_name)
    except (json.JSONDecodeError, ValueError, KeyError):
        return None
    fn = getattr(mod, attr, None)
    return fn if callable(fn) else None


def _find_backend_in_module(mod_name: str) -> StopBackend | None:
    try:
        mod = importlib.import_module(mod_name)
    except (ImportError, AttributeError, RuntimeError):
        return None

    # Common function names.
    for attr in ("stop_node", "node_stop", "stop"):
        fn = getattr(mod, attr, None)
        if callable(fn):
            return fn

    # Or an object that exposes stop_node().
    for attr in ("NODE_MANAGER", "node_manager", "controller", "NODE_CONTROLLER"):
        obj = getattr(mod, attr, None)
        meth = getattr(obj, "stop_node", None) if obj is not None else None
        if callable(meth):
            return meth

    return None


def _resolve_default_backend() -> StopBackend | None:
    env_spec = os.environ.get("THOMAS_NODE_STOP_BACKEND", "").strip()
    backend = _parse_backend_spec(env_spec)
    if backend is not None:
        return backend

    # Prefer explicit, stable module targets first.
    for mod_name in (
        "thomas.marketplace.nodes.control",
        "thomas.marketplace.nodes.manager",
        "thomas.marketplace.nodes.runtime",
        "thomas.marketplace.nodes.service",
        "thomas.marketplace.nodes.node_manager",
        "thomas.marketplace.nodes.node_control",
    ):
        backend = _find_backend_in_module(mod_name)
        if backend is not None:
            return backend

    # Fallback: scan thomas.nodes submodules. This increases compatibility with
    # evolving internal APIs, but we limit imports to likely candidates.
    try:
        import pkgutil

        import thomas.marketplace.nodes as nodes_pkg  # type: ignore
    except (ImportError, AttributeError, RuntimeError):
        return None

    pkg_path = getattr(nodes_pkg, "__path__", None)
    if not pkg_path:
        return None

    keywords = ("node", "manager", "control", "runtime", "service")
    for modinfo in pkgutil.iter_modules(pkg_path, nodes_pkg.__name__ + "."):
        mod_name = modinfo.name
        if mod_name.endswith("p035_node_command_stop"):
            continue
        if any(k in mod_name for k in keywords):
            backend = _find_backend_in_module(mod_name)
            if backend is not None:
                return backend

    return None


def _invoke_backend(
    backend: StopBackend,
    *,
    node_id: str,
    force: bool,
    timeout_s: float | None,
    config: Mapping[str, Any] | None,
) -> Any:
    """Invoke backend with best-effort signature adaptation."""

    try:
        sig = inspect.signature(backend)
    except (TypeError, ValueError):
        sig = None

    if sig is None:
        # Unknown signature: try the simplest.
        return backend(node_id)

    params = list(sig.parameters.values())
    supports_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)

    kwargs: MutableMapping[str, Any] = {}
    positional: list[Any] = []

    def _accepts(name: str) -> bool:
        return supports_var_kwargs or name in sig.parameters

    # node id
    node_param = None
    for cand in ("node_id", "node", "node_name", "name", "id"):
        if cand in sig.parameters:
            node_param = cand
            break

    if node_param is not None:
        kwargs[node_param] = node_id
    else:
        # If there is any positional slot, pass node_id positionally.
        if params and params[0].kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            positional.append(node_id)
        else:
            raise NodeCommandStopExternalError(
                "unable to call stop backend (no node parameter)",
                details={"backend": getattr(backend, "__name__", str(backend))},
            )

    if _accepts("force"):
        kwargs["force"] = force

    if timeout_s is not None:
        for cand in ("timeout_s", "timeout", "timeout_sec", "timeout_seconds"):
            if _accepts(cand):
                kwargs[cand] = timeout_s
                break

    if config is not None:
        for cand in ("config", "cfg", "settings"):
            if _accepts(cand):
                kwargs[cand] = config
                break

    return backend(*positional, **kwargs)


def _backend_result_is_success(result: Any) -> bool:
    """Return True if backend result indicates success, False if explicit failure.

    Explicit failure signals:
    - result is False
    - mapping with ok=False / success=False
    - mapping with a non-empty "error" field
    - string of common failure tokens
    """
    if result is None:
        return True
    if isinstance(result, bool):
        return result
    if isinstance(result, Mapping):
        for key in ("ok", "success"):
            v = result.get(key)
            if isinstance(v, bool):
                return v
        if "error" in result and result.get("error") not in (None, "", False):
            return False
    if isinstance(result, str):
        low = result.strip().lower()
        if low in {"ok", "success", "stopped", "already_stopped"}:
            return True
        if low in {"fail", "failed", "error", "not_stopped"}:
            return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def node_command_stop_async(
    inp: NodeCommandStopInput,
    *,
    backend: StopBackend | None = None,
) -> NodeCommandStopOutput:
    """Stop a node."""

    _validate_input(inp)
    node_id = inp.node_id.strip()

    config: Mapping[str, Any] | None = None
    if inp.config_path is not None:
        config = _load_config(inp.config_path)

    resolved_backend = backend or _resolve_default_backend()
    if resolved_backend is None:
        raise NodeCommandStopExternalError(
            "no node stop backend available",
            details={"node_id": node_id},
        )

    try:
        result = _invoke_backend(
            resolved_backend,
            node_id=node_id,
            force=bool(inp.force),
            timeout_s=inp.timeout_s,
            config=config,
        )
        if inspect.isawaitable(result):
            result = await result
    except NodeCommandStopError:
        raise
    except (RuntimeError, asyncio.QueueFull, ValueError) as e:
        raise NodeCommandStopExternalError(
            "failed to stop node",
            details={"node_id": node_id, "reason": type(e).__name__},
        ) from e

    if not _backend_result_is_success(result):
        raise NodeCommandStopExternalError(
            "failed to stop node",
            details={"node_id": node_id, "reason": "BackendReportedFailure"},
        )

    message = f"Node '{node_id}' stopped"
    return NodeCommandStopOutput(ok=True, node_id=node_id, stopped=True, message=message)


def node_command_stop(
    inp: NodeCommandStopInput,
    *,
    backend: StopBackend | None = None,
) -> NodeCommandStopOutput:
    """Synchronous wrapper for :func:`node_command_stop_async`."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(node_command_stop_async(inp, backend=backend))

    # If an event loop is already running, run the coroutine in a dedicated
    # thread to avoid nested loop errors.
    import queue
    import threading

    q: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            res = asyncio.run(node_command_stop_async(inp, backend=backend))
            q.put((True, res))
        except (ImportError, AttributeError, RuntimeError) as e:  # pragma: no cover
            q.put((False, e))

    t = threading.Thread(target=_runner, name="thomas-node-stop", daemon=True)
    t.start()
    ok, payload = q.get()
    t.join()

    if ok:
        return payload  # type: ignore[return-value]
    raise payload  # type: ignore[misc]
