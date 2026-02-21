from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Coroutine, Mapping, Optional, Sequence, TypedDict, TypeVar, cast

import aiohttp


class NodeDescriptor(TypedDict, total=False):
    """Machine-readable representation of a node/device."""
    id: str
    name: str
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class NodesCliRequest:
    """Input contract for nodes CLI operations."""
    base_url: Optional[str] = None
    nodes_path: Optional[str] = None
    timeout_s: float = 10.0


@dataclass(frozen=True)
class NodesCliResult:
    """Output contract for nodes CLI operations."""
    ok: bool
    base_url: str
    nodes_path: str
    nodes: list[NodeDescriptor] = field(default_factory=list)
    error: Optional[dict[str, Any]] = None
    fetched_at_epoch_s: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NodesCliIntegrationError(RuntimeError):
    """Deterministic failure for nodes CLI integration.

    Error codes:
    - missing_config: required config is not provided (e.g., base URL)
    - invalid_input: malformed CLI input (bad URL/path/timeout)
    - external_failure: network/server failure (non-2xx, timeout, unreachable)
    - invalid_response: response could not be normalized to the expected shape
    """

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _strip_trailing_slash(base_url: str) -> str:
    return base_url[:-1] if base_url.endswith("/") else base_url


def resolve_base_url(explicit: Optional[str]) -> str:
    """Resolve the Thomas server base URL from explicit input or environment.

    Deterministic sources (highest priority first):
    - explicit argument
    - THOMAS_BASE_URL
    - THOMAS_SERVER_URL
    - THOMAS_URL
    """
    candidate = (
        explicit
        or os.environ.get("THOMAS_BASE_URL")
        or os.environ.get("THOMAS_SERVER_URL")
        or os.environ.get("THOMAS_URL")
    )
    if not candidate:
        raise NodesCliIntegrationError(
            "missing_config",
            "No server base URL provided. Use --base-url or set THOMAS_BASE_URL/THOMAS_SERVER_URL/THOMAS_URL.",
        )

    candidate = candidate.strip()
    if not candidate:
        raise NodesCliIntegrationError("invalid_input", "Base URL is empty/whitespace.")

    if not re.match(r"^https?://", candidate):
        raise NodesCliIntegrationError(
            "invalid_input",
            "Base URL must start with http:// or https://.",
            details={"base_url": candidate},
        )

    return _strip_trailing_slash(candidate)


def _discover_route_strings(module_name: str) -> set[str]:
    """Best-effort: import a module and scan for route/path-looking strings."""
    try:
        import importlib

        mod = importlib.import_module(module_name)
    except Exception:
        return set()

    candidates: set[str] = set()

    def visit(obj: Any, depth: int) -> None:
        if depth <= 0 or obj is None:
            return
        if isinstance(obj, str):
            if obj.startswith("/") and ("node" in obj.lower() or "device" in obj.lower()):
                candidates.add(obj)
            return
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                if isinstance(k, str) and k in {"path", "route", "url", "endpoint"} and isinstance(v, str):
                    if v.startswith("/") and ("node" in v.lower() or "device" in v.lower()):
                        candidates.add(v)
                visit(v, depth - 1)
            return
        if isinstance(obj, (list, tuple, set, frozenset)):
            for item in obj:
                visit(item, depth - 1)
            return

        # generic object attribute scan (small, shallow)
        for attr in ("path", "route", "url", "endpoint"):
            try:
                val = getattr(obj, attr)
            except Exception:
                continue
            visit(val, depth - 1)

    for name in dir(mod):
        if name.startswith("_"):
            continue
        try:
            value = getattr(mod, name)
        except Exception:
            continue
        visit(value, depth=4)

    return candidates


_DEFAULT_PATH_PREFERENCES: Sequence[str] = (
    "/nodes",
    "/api/nodes",
    "/v1/nodes",
    "/devices",
    "/api/devices",
    "/v1/devices",
)


def _pick_best_path(candidates: set[str]) -> Optional[str]:
    if not candidates:
        return None
    lowered = {c.lower(): c for c in candidates}
    for preferred in _DEFAULT_PATH_PREFERENCES:
        if preferred in lowered:
            return lowered[preferred]
    return sorted(candidates, key=len)[0]


def normalize_nodes_path(nodes_path: Optional[str]) -> str:
    """Determine the nodes endpoint path.

    Priority:
    1) explicit nodes_path
    2) best-effort discovery from server routes (thomas.server.routes.core_aiohttp)
    3) best-effort discovery from CLI parity registry (thomas.cli.parity_commands)
    4) fallback to '/nodes'
    """
    if nodes_path is not None:
        p = nodes_path.strip()
        if not p:
            raise NodesCliIntegrationError("invalid_input", "nodes_path is empty/whitespace.")
        if not p.startswith("/"):
            p = "/" + p
        return p

    # Discovery attempts (safe if modules are absent).
    for module_name in ("thomas.server.routes.core_aiohttp", "thomas.cli.parity_commands"):
        discovered = _pick_best_path(_discover_route_strings(module_name))
        if discovered:
            return discovered

    return "/nodes"


def _validate_timeout_s(timeout_s: float) -> float:
    try:
        t = float(timeout_s)
    except Exception as e:
        raise NodesCliIntegrationError("invalid_input", "timeout must be a number.", details={"timeout": timeout_s}) from e
    if not (t > 0.0):
        raise NodesCliIntegrationError("invalid_input", "timeout must be > 0.", details={"timeout": t})
    # Clamp to something sane; deterministic.
    return min(max(t, 0.1), 120.0)


def _coerce_one_node(item: Any) -> NodeDescriptor:
    if isinstance(item, str):
        return NodeDescriptor(name=item)
    if isinstance(item, Mapping):
        d: dict[str, Any] = dict(item)
        out: NodeDescriptor = {}
        if "id" in d and isinstance(d["id"], (str, int)):
            out["id"] = str(d["id"])
        if "name" in d and isinstance(d["name"], (str, int)):
            out["name"] = str(d["name"])
        # common aliases
        if "hostname" in d and "name" not in out and isinstance(d["hostname"], (str, int)):
            out["name"] = str(d["hostname"])
        if "status" in d and isinstance(d["status"], str):
            out["status"] = d["status"]
        meta = {k: v for k, v in d.items() if k not in {"id", "name", "hostname", "status"}}
        if meta:
            out["metadata"] = meta
        return out
    raise NodesCliIntegrationError(
        "invalid_response",
        f"Unexpected node element type: {type(item).__name__}.",
    )


def _coerce_nodes_payload(payload: Any) -> list[NodeDescriptor]:
    """Accept a couple of reasonable server payload shapes and normalize them."""
    if payload is None:
        return []

    if isinstance(payload, list):
        return [_coerce_one_node(item) for item in payload]

    if isinstance(payload, Mapping):
        for key in ("nodes", "devices", "items", "data", "results"):
            if key in payload and isinstance(payload[key], list):
                return [_coerce_one_node(item) for item in cast(list[Any], payload[key])]
        if any(k in payload for k in ("id", "name", "hostname")):
            return [_coerce_one_node(payload)]
        raise NodesCliIntegrationError(
            "invalid_response",
            "Unexpected JSON object shape for nodes response.",
            details={"keys": sorted(list(payload.keys()))[:50]},
        )

    raise NodesCliIntegrationError(
        "invalid_response",
        f"Unexpected JSON type for nodes response: {type(payload).__name__}.",
    )


async def fetch_nodes(request: NodesCliRequest) -> NodesCliResult:
    """Fetch nodes from the Thomas server."""
    base_url = resolve_base_url(request.base_url)
    nodes_path = normalize_nodes_path(request.nodes_path)
    timeout_s = _validate_timeout_s(request.timeout_s)
    url = f"{base_url}{nodes_path}"

    timeout = aiohttp.ClientTimeout(total=timeout_s)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                status = resp.status
                # Accept JSON even if content-type is wrong.
                try:
                    payload = await resp.json(content_type=None)
                    raw_text: Optional[str] = None
                except Exception:
                    raw_text = await resp.text()
                    payload = None
                    if raw_text:
                        try:
                            payload = json.loads(raw_text)
                        except Exception:
                            payload = None

                if status >= 400:
                    details: dict[str, Any] = {"status": status, "url": url}
                    if raw_text is not None:
                        details["body"] = raw_text[:500]
                    raise NodesCliIntegrationError(
                        "external_failure",
                        "Server returned an error response while fetching nodes.",
                        details=details,
                    )

                nodes = _coerce_nodes_payload(payload)
                return NodesCliResult(ok=True, base_url=base_url, nodes_path=nodes_path, nodes=nodes)

    except NodesCliIntegrationError:
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        raise NodesCliIntegrationError(
            "external_failure",
            "Failed to reach server while fetching nodes.",
            details={"url": url, "error": type(e).__name__, "message": str(e)},
        ) from e
    except Exception as e:
        raise NodesCliIntegrationError(
            "external_failure",
            "Unexpected failure while fetching nodes.",
            details={"url": url, "error": type(e).__name__, "message": str(e)},
        ) from e


_T = TypeVar("_T")


def _run_coro_sync(coro_factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
    """Run an async coroutine from sync code.

    - If no loop is running in this thread, we use asyncio.run().
    - If a loop *is* running, we execute the coroutine in a dedicated thread with its own event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    result_box: list[_T] = []
    error_box: list[BaseException] = []

    def _thread_main() -> None:
        try:
            result_box.append(asyncio.run(coro_factory()))
        except BaseException as e:  # pragma: no cover
            error_box.append(e)

    t = threading.Thread(target=_thread_main, name="p052-nodes-cli", daemon=True)
    t.start()
    t.join()

    if error_box:
        raise error_box[0]
    return result_box[0]


def fetch_nodes_sync(request: NodesCliRequest) -> NodesCliResult:
    """Sync wrapper for fetch_nodes (CLI-friendly)."""
    return _run_coro_sync(lambda: fetch_nodes(request))


async def run_parity_tests(request: NodesCliRequest) -> NodesCliResult:
    """Run a minimal parity check for the nodes endpoint.

    Parity contract:
    - endpoint reachable
    - parseable JSON payload with a supported shape
    - each element normalizes to a NodeDescriptor with at least id or name
    """
    result = await fetch_nodes(request)

    for i, node in enumerate(result.nodes):
        ident = (node.get("id") or "").strip()
        name = (node.get("name") or "").strip()
        if not ident and not name:
            raise NodesCliIntegrationError(
                "invalid_response",
                "Node entries must contain at least a non-empty 'id' or 'name'.",
                details={"index": i, "node": node},
            )
    return result


def run_parity_tests_sync(request: NodesCliRequest) -> NodesCliResult:
    return _run_coro_sync(lambda: run_parity_tests(request))


def format_result_human(result: NodesCliResult) -> str:
    if not result.ok:
        return f"ERROR: {result.error}"
    if not result.nodes:
        return "No nodes."
    lines: list[str] = []
    for node in result.nodes:
        label = node.get("name") or node.get("id") or "<unknown>"
        status = node.get("status")
        lines.append(f"- {label}" + (f" ({status})" if status else ""))
    return "\n".join(lines)


def format_result_json(result: NodesCliResult) -> str:
    return json.dumps(result.to_dict(), sort_keys=True)


# --- Convenience aliases (common harness naming) ---

def list_nodes_sync(request: NodesCliRequest) -> NodesCliResult:
    return fetch_nodes_sync(request)


def run_nodes_cli_integration_and_parity_tests(request: NodesCliRequest) -> NodesCliResult:
    return run_parity_tests_sync(request)


def run(request: NodesCliRequest) -> NodesCliResult:
    return run_nodes_cli_integration_and_parity_tests(request)
