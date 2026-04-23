from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol

try:
    # aiohttp is part of Thomas server stack; keep optional for pure logic tests.
    from aiohttp import web
except (json.JSONDecodeError, ValueError, KeyError):  # pragma: no cover
    web = None  # type: ignore[assignment]


# Public route path (server wires this).
NODES_RUN_ROUTE = "/v1/nodes/run"


class NodeRunErrorCode:
    """Deterministic error codes for `nodes run`.

    These codes are intended to be stable for automation.
    """

    INVALID_INPUT = "INVALID_INPUT"
    MISSING_CONFIG = "MISSING_CONFIG"
    NODE_UNAVAILABLE = "NODE_UNAVAILABLE"
    INVOKE_FAILED = "INVOKE_FAILED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"


@dataclass(frozen=True)
class NodeCommandRunRequest:
    """Input contract for running a command on a node."""

    # Node selector (id/name/ip). Optional if server has a default node context.
    node: str | None = None

    # Exactly one of `argv` or `raw` must be provided.
    argv: list[str] | None = None
    raw: str | None = None

    # Execution options.
    cwd: str | None = None
    env: dict[str, str] | None = None

    # Timeouts.
    command_timeout_ms: int | None = None
    invoke_timeout_ms: int | None = None

    # Policy/pass-through options.
    needs_screen_recording: bool = False
    agent: str | None = None
    ask: str | None = None
    security: str | None = None


@dataclass(frozen=True)
class NodeCommandRunResult:
    """Successful result contract."""

    node: str | None
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


@dataclass(frozen=True)
class NodeCommandRunError:
    """Failure contract."""

    code: str
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class NodeCommandRunResponse:
    """Output contract for `nodes run`."""

    ok: bool
    result: NodeCommandRunResult | None = None
    error: NodeCommandRunError | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"ok": self.ok}
        if self.result is not None:
            data["result"] = asdict(self.result)
        if self.error is not None:
            data["error"] = asdict(self.error)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class NodeCommandRunException(RuntimeError):
    """Exception with a stable error code."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details

    def to_error(self) -> NodeCommandRunError:
        return NodeCommandRunError(code=self.code, message=str(self), details=self.details)


class NodeCommandRunBackend(Protocol):
    async def run(self, req: NodeCommandRunRequest) -> NodeCommandRunResult:
        """Execute the request and return a normalized result."""


def _validate_request(req: NodeCommandRunRequest) -> None:
    has_argv = bool(req.argv)
    has_raw = bool(req.raw and str(req.raw).strip())

    if has_argv and has_raw:
        raise NodeCommandRunException(NodeRunErrorCode.INVALID_INPUT, "Provide either argv or raw, not both.")

    if not has_argv and not has_raw:
        raise NodeCommandRunException(
            NodeRunErrorCode.INVALID_INPUT,
            "Missing command: provide argv (positional args) or raw.",
        )

    if req.argv is not None and len(req.argv) == 0:
        raise NodeCommandRunException(NodeRunErrorCode.INVALID_INPUT, "argv must not be empty.")

    for name, val in (("command_timeout_ms", req.command_timeout_ms), ("invoke_timeout_ms", req.invoke_timeout_ms)):
        if val is None:
            continue
        if not isinstance(val, int) or val <= 0:
            raise NodeCommandRunException(
                NodeRunErrorCode.INVALID_INPUT,
                f"{name} must be a positive integer (milliseconds).",
            )

    if req.env is not None:
        for k, v in req.env.items():
            if not isinstance(k, str) or not k:
                raise NodeCommandRunException(NodeRunErrorCode.INVALID_INPUT, "env keys must be non-empty strings.")
            if not isinstance(v, str):
                raise NodeCommandRunException(NodeRunErrorCode.INVALID_INPUT, "env values must be strings.")


def _platform_shell_argv(raw: str) -> list[str]:
    if os.name == "nt":
        # cmd.exe built-in shell
        return ["cmd.exe", "/c", raw]
    return ["/bin/sh", "-lc", raw]


def _preferred_timeout_s(req: NodeCommandRunRequest) -> float | None:
    # Prefer command timeout; fall back to invoke timeout.
    timeout_ms = req.command_timeout_ms if req.command_timeout_ms is not None else req.invoke_timeout_ms
    if timeout_ms is None:
        return None
    return timeout_ms / 1000.0


class LocalSubprocessBackend:
    """Backend that runs the command locally via asyncio subprocess.

    This is primarily intended for tests and local development.
    """

    async def run(self, req: NodeCommandRunRequest) -> NodeCommandRunResult:
        _validate_request(req)

        argv = list(req.argv) if req.argv else _platform_shell_argv(req.raw or "")

        merged_env: MutableMapping[str, str] | None = None
        if req.env is not None:
            merged_env = dict(os.environ)
            for k, v in req.env.items():
                merged_env[str(k)] = str(v)

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=req.cwd,
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise NodeCommandRunException(
                NodeRunErrorCode.INVOKE_FAILED,
                f"Executable not found: {e}",
                details={"argv": argv},
            )

        timeout_s = _preferred_timeout_s(req)

        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            finally:
                await proc.communicate()
            timeout_ms = req.command_timeout_ms if req.command_timeout_ms is not None else req.invoke_timeout_ms
            raise NodeCommandRunException(
                NodeRunErrorCode.COMMAND_TIMEOUT,
                f"Command timed out after {timeout_ms}ms.",
                details={"timeout_ms": timeout_ms, "argv": argv},
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = out_b.decode(errors="replace") if out_b else ""
        stderr = err_b.decode(errors="replace") if err_b else ""

        return NodeCommandRunResult(
            node=req.node,
            argv=argv,
            exit_code=int(proc.returncode or 0),
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )


class AiohttpAppBackend:
    """Backend that delegates to a node subsystem stored in aiohttp app state.

    If no suitable node subsystem is present, this backend raises NODE_UNAVAILABLE
    rather than silently executing commands locally (safer default on gateways).
    """

    def __init__(self, app: Mapping[str, Any], *, allow_local_fallback: bool = False):
        self._app = app
        self._allow_local_fallback = allow_local_fallback

    def _find_manager(self) -> Any:
        # Common state keys seen across node/device manager patterns.
        for key in (
            "nodes",
            "node_manager",
            "nodes_manager",
            "node_service",
            "devices",
            "device_manager",
            "device_service",
            "node_registry",
        ):
            if key in self._app:
                return self._app[key]
        return None

    async def run(self, req: NodeCommandRunRequest) -> NodeCommandRunResult:
        _validate_request(req)

        manager = self._find_manager()
        if manager is None:
            if self._allow_local_fallback:
                return await LocalSubprocessBackend().run(req)
            raise NodeCommandRunException(
                NodeRunErrorCode.NODE_UNAVAILABLE,
                "No node manager is configured on this server.",
            )

        argv = list(req.argv) if req.argv else _platform_shell_argv(req.raw or "")

        # We use a "params dict" style so managers can accept future fields without changing signatures.
        params: dict[str, Any] = {
            "node": req.node,
            "argv": argv,
            "raw": req.raw,
            "cwd": req.cwd,
            "env": req.env or {},
            "command_timeout_ms": req.command_timeout_ms,
            "invoke_timeout_ms": req.invoke_timeout_ms,
            "needs_screen_recording": req.needs_screen_recording,
            "agent": req.agent,
            "ask": req.ask,
            "security": req.security,
            # Convenience seconds variant for managers that work in seconds.
            "timeout_s": _preferred_timeout_s(req),
        }

        # Try a few common invocation shapes.
        candidates: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []

        if hasattr(manager, "invoke"):
            # invoke(node, action, params, timeout_ms?)
            candidates.append((manager.invoke, (req.node, "nodes.run", params, req.invoke_timeout_ms), {}))
            candidates.append(
                (
                    manager.invoke,
                    (),
                    {"node": req.node, "action": "nodes.run", "params": params, "timeout_ms": req.invoke_timeout_ms},
                )
            )

        if hasattr(manager, "invoke_node"):
            candidates.append(
                (manager.invoke_node, (req.node, "nodes.run", params), {"timeout_ms": req.invoke_timeout_ms})
            )
            candidates.append(
                (
                    manager.invoke_node,
                    (),
                    {"node": req.node, "action": "nodes.run", "params": params, "timeout_ms": req.invoke_timeout_ms},
                )
            )

        if hasattr(manager, "run_command"):
            candidates.append(
                (
                    manager.run_command,
                    (),
                    {
                        "node": req.node,
                        "argv": argv,
                        "cwd": req.cwd,
                        "env": req.env,
                        "timeout_ms": req.command_timeout_ms,
                    },
                )
            )
            candidates.append(
                (
                    manager.run_command,
                    (req.node, argv),
                    {"cwd": req.cwd, "env": req.env, "timeout_ms": req.command_timeout_ms},
                )
            )

        if hasattr(manager, "run"):
            candidates.append((manager.run, (params,), {}))

        last_type_error: TypeError | None = None
        last_exc: Exception | None = None

        for fn, args, kwargs in candidates:
            try:
                res = fn(*args, **kwargs)
                if asyncio.iscoroutine(res):
                    res = await res
                # Allow managers to return an {ok, result, error} envelope.
                res = _unwrap_manager_envelope(res)
                return _normalize_result(req.node, argv, res)
            except TypeError as e:
                last_type_error = e
                continue
            except NodeCommandRunException:
                raise
            except (RuntimeError, asyncio.QueueFull, ValueError) as e:  # pragma: no cover
                last_exc = e
                continue

        if last_type_error is not None:
            raise NodeCommandRunException(
                NodeRunErrorCode.NODE_UNAVAILABLE,
                "Node manager found but did not accept a supported invoke signature for nodes.run.",
                details={"error": str(last_type_error), "manager_type": type(manager).__name__},
            )

        raise NodeCommandRunException(
            NodeRunErrorCode.INVOKE_FAILED,
            "Node manager invocation failed.",
            details={"manager_type": type(manager).__name__, "error": str(last_exc) if last_exc else None},
        )


def _unwrap_manager_envelope(res: Any) -> Any:
    """If the backend returns an {ok, result, error} envelope, unwrap or raise."""
    if isinstance(res, Mapping) and "ok" in res:
        ok = bool(res.get("ok"))
        if ok:
            return res.get("result", res)
        err = res.get("error") or {}
        if isinstance(err, Mapping):
            code = str(err.get("code") or NodeRunErrorCode.INVOKE_FAILED)
            # Keep codes deterministic: unknown codes collapse to INVOKE_FAILED.
            if code not in {
                NodeRunErrorCode.INVALID_INPUT,
                NodeRunErrorCode.MISSING_CONFIG,
                NodeRunErrorCode.NODE_UNAVAILABLE,
                NodeRunErrorCode.INVOKE_FAILED,
                NodeRunErrorCode.COMMAND_TIMEOUT,
            }:
                code = NodeRunErrorCode.INVOKE_FAILED
            msg = str(err.get("message") or "Node command failed.")
            details = err.get("details")
            return _raise(code, msg, details if isinstance(details, dict) else {"error": err})
        raise NodeCommandRunException(NodeRunErrorCode.INVOKE_FAILED, "Node command failed.", details={"error": res})
    return res


def _raise(code: str, message: str, details: dict[str, Any] | None) -> Any:
    raise NodeCommandRunException(code, message, details=details)


def _normalize_result(node: str | None, argv: Sequence[str], res: Any) -> NodeCommandRunResult:
    """Normalize backend result shapes into NodeCommandRunResult.

    Supported shapes:
    - NodeCommandRunResult
    - dict-like with stdout/stderr/exit_code keys (and variants)
    - (stdout, stderr, exit_code) tuple
    - object with stdout/stderr/exit_code attributes
    """

    start = time.monotonic()

    def _get(mapping: Mapping[str, Any], *keys: str) -> Any:
        for k in keys:
            if k in mapping:
                return mapping[k]
        return None

    if isinstance(res, NodeCommandRunResult):
        return res

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int | None = None

    if isinstance(res, tuple) and len(res) == 3:
        stdout = str(res[0] or "")
        stderr = str(res[1] or "")
        try:
            exit_code = int(res[2] or 0)
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError):
            exit_code = 0

    elif isinstance(res, Mapping):
        stdout_val = _get(res, "stdout", "out")
        stderr_val = _get(res, "stderr", "err")
        exit_code_val = _get(res, "exit_code", "exitCode", "code", "returncode", "return_code")
        duration_val = _get(res, "duration_ms", "durationMs", "duration")

        stdout = str(stdout_val) if stdout_val is not None else ""
        stderr = str(stderr_val) if stderr_val is not None else ""
        if exit_code_val is not None:
            try:
                exit_code = int(exit_code_val)
            except (ConnectionError, TimeoutError, RuntimeError):
                exit_code = 0
        if duration_val is not None:
            try:
                duration_ms = int(duration_val)
            except (RuntimeError, ValueError, KeyError, AttributeError, TypeError):
                duration_ms = None

    else:
        # Attribute-based fallback.
        for attr in ("stdout", "out"):
            if hasattr(res, attr):
                stdout = str(getattr(res, attr))
                break
        for attr in ("stderr", "err"):
            if hasattr(res, attr):
                stderr = str(getattr(res, attr))
                break
        for attr in ("exit_code", "exitCode", "code", "returncode", "return_code"):
            if hasattr(res, attr):
                try:
                    exit_code = int(getattr(res, attr))
                except (ImportError, AttributeError, RuntimeError):
                    exit_code = 0
                break
        for attr in ("duration_ms", "durationMs"):
            if hasattr(res, attr):
                try:
                    duration_ms = int(getattr(res, attr))
                except (ImportError, AttributeError, RuntimeError):
                    duration_ms = None
                break

    if duration_ms is None:
        duration_ms = int((time.monotonic() - start) * 1000)

    return NodeCommandRunResult(
        node=node,
        argv=list(argv),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
    )


async def node_command_run(req: NodeCommandRunRequest, backend: NodeCommandRunBackend) -> NodeCommandRunResponse:
    """Run a command on a node using the provided backend."""
    try:
        _validate_request(req)
        result = await backend.run(req)
        return NodeCommandRunResponse(ok=True, result=result)
    except NodeCommandRunException as e:
        return NodeCommandRunResponse(ok=False, error=e.to_error())
    except (ConnectionError, TimeoutError, RuntimeError) as e:  # pragma: no cover
        # Keep deterministic outer errors and avoid exposing tracebacks.
        return NodeCommandRunResponse(
            ok=False,
            error=NodeCommandRunError(
                code=NodeRunErrorCode.INVOKE_FAILED,
                message="External failure while running node command.",
                details={"type": type(e).__name__, "message": str(e)},
            ),
        )


def _coerce_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _coerce_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (RuntimeError, ValueError, KeyError, AttributeError, TypeError):
        return None


def request_from_json(data: Mapping[str, Any]) -> NodeCommandRunRequest:
    """Parse and validate JSON input into a request dataclass."""

    argv_val = data.get("argv")
    if argv_val is None:
        argv_val = data.get("command")

    argv: list[str] | None = None
    if isinstance(argv_val, list):
        argv = [str(x) for x in argv_val]

    env_val = data.get("env")
    env: dict[str, str] | None = None
    if isinstance(env_val, Mapping):
        env = {str(k): str(v) for k, v in env_val.items()}

    req = NodeCommandRunRequest(
        node=(str(data.get("node")) if data.get("node") is not None else None),
        argv=argv,
        raw=(str(data.get("raw")) if data.get("raw") is not None else None),
        cwd=(str(data.get("cwd")) if data.get("cwd") is not None else None),
        env=env,
        command_timeout_ms=_coerce_int(data.get("command_timeout_ms") or data.get("commandTimeoutMs")),
        invoke_timeout_ms=_coerce_int(data.get("invoke_timeout_ms") or data.get("invokeTimeoutMs")),
        needs_screen_recording=_coerce_bool(
            data.get("needs_screen_recording") or data.get("needsScreenRecording") or data.get("needs-screen-recording")
        ),
        agent=(str(data.get("agent")) if data.get("agent") is not None else None),
        ask=(str(data.get("ask")) if data.get("ask") is not None else None),
        security=(str(data.get("security")) if data.get("security") is not None else None),
    )
    _validate_request(req)
    return req


async def handle_nodes_run(request: Any) -> Any:
    """aiohttp handler for POST /v1/nodes/run.

    Always returns a NodeCommandRunResponse JSON contract.
    """
    if web is None:  # pragma: no cover
        raise RuntimeError("aiohttp is required to use handle_nodes_run")

    try:
        data = await request.json()
        if not isinstance(data, Mapping):
            raise ValueError("JSON body must be an object")
        req = request_from_json(data)
    except NodeCommandRunException as e:
        resp = NodeCommandRunResponse(ok=False, error=e.to_error())
        return web.json_response(resp.to_dict(), status=200)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        resp = NodeCommandRunResponse(
            ok=False,
            error=NodeCommandRunError(
                code=NodeRunErrorCode.INVALID_INPUT,
                message="Invalid JSON request.",
                details={"type": type(e).__name__, "message": str(e)},
            ),
        )
        return web.json_response(resp.to_dict(), status=200)

    backend = AiohttpAppBackend(request.app)
    resp = await node_command_run(req, backend)
    return web.json_response(resp.to_dict(), status=200)


# Alternate names to match common route registries.
handle_node_command_run = handle_nodes_run
nodes_run_handler = handle_nodes_run


def register_routes(target: Any) -> None:
    """Best-effort route registration helper.

    Supports both:
    - aiohttp RouteTableDef (decorator style via .post)
    - aiohttp web.Application (via app.router.add_post)
    """
    if web is None:  # pragma: no cover
        return

    # RouteTableDef style (callable .post decorator).
    if hasattr(target, "post") and callable(target.post):
        try:
            target.post(NODES_RUN_ROUTE)(handle_nodes_run)
            return
        except (ImportError, AttributeError, RuntimeError):
            pass

    # web.Application style.
    if hasattr(target, "router"):
        try:
            target.router.add_post(NODES_RUN_ROUTE, handle_nodes_run)
        except (ConnectionError, TimeoutError, RuntimeError):
            return


# Even more common entrypoint names (some registries look for these).
setup_routes = register_routes
setup = register_routes
init = register_routes
add_routes = register_routes


def get_routes() -> list[tuple[str, str, Any]]:
    """Return routes in a transport-agnostic shape."""
    return [("POST", NODES_RUN_ROUTE, handle_nodes_run)]


# Provide aiohttp-native RouteTableDef for registries that import `routes`.
if web is not None:  # pragma: no cover
    routes = web.RouteTableDef()

    @routes.post(NODES_RUN_ROUTE)
    async def _nodes_run_route(request: Any) -> Any:
        return await handle_nodes_run(request)

    ROUTES = routes
else:  # pragma: no cover
    routes = None  # type: ignore
    ROUTES = None  # type: ignore


__all__ = [
    "NODES_RUN_ROUTE",
    "NodeRunErrorCode",
    "NodeCommandRunRequest",
    "NodeCommandRunResult",
    "NodeCommandRunError",
    "NodeCommandRunResponse",
    "NodeCommandRunException",
    "NodeCommandRunBackend",
    "LocalSubprocessBackend",
    "AiohttpAppBackend",
    "node_command_run",
    "request_from_json",
    "handle_nodes_run",
    "handle_node_command_run",
    "nodes_run_handler",
    "register_routes",
    "setup_routes",
    "setup",
    "init",
    "add_routes",
    "get_routes",
    "routes",
    "ROUTES",
]
