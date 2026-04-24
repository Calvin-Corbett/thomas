"""thomas.marketplace.nodes.p038_nodes_list_and_status

Thomas-native implementation for listing configured nodes and probing their status.

This module intentionally uses Thomas-native naming. It exposes a small,
deterministic API that can be used by CLI and server layers.

Key properties
- Deterministic contracts: structured input/output dataclasses + stable error codes.
- Deterministic ordering: results are always sorted by node_id.
- Low coupling: status probing is a TCP connect (no assumptions about HTTP routes).
- Async-first: provide an async API and a small sync wrapper for CLI usage.

Config resolution (when `config=` is not provided)
- Reads a config file path from the first-set env var:
  - THOMAS_CONFIG
  - THOMAS_CONFIG_PATH
  - THOMAS_SETTINGS
- Supports JSON (.json) and TOML (.toml/.tml).

Where nodes live in the config mapping (first match wins)
- config['nodes']
- config['cluster']['nodes']
- config['thomas']['nodes']
- config['browser']['nodes']

Supported node entry forms
- List[Mapping]:
    {'id': 'node-a', 'url': 'http://127.0.0.1:8080'}
- Mapping[node_id] -> str(url):
    {'node-a': 'http://127.0.0.1:8080'}
- Mapping[node_id] -> Mapping (merged with id):
    {'node-a': {'url': 'http://127.0.0.1:8080', 'label': 'primary'}}

Status probe
- Attempts asyncio.open_connection(host, port) with a per-node timeout.
- A successful TCP connect counts as "online". No application-level semantics.

"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore


DEFAULT_TIMEOUT_S: float = 2.0
DEFAULT_MAX_CONCURRENCY: int = 20
DEFAULT_CONFIG_ENV_VARS: tuple[str, ...] = ("THOMAS_CONFIG", "THOMAS_CONFIG_PATH", "THOMAS_SETTINGS")


class NodesListAndStatusError(Exception):
    """Deterministic, machine-readable errors for nodes list/status."""

    code: str
    details: dict[str, Any] | None

    def __init__(self, message: str, *, code: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details) if details else None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.details:
            payload["details"] = self.details
        return payload


class NodesInvalidInputError(NodesListAndStatusError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message, code="invalid_input", details=details)


class NodesConfigError(NodesListAndStatusError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message, code="missing_config", details=details)


class NodesExternalFailureError(NodesListAndStatusError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message, code="external_failure", details=details)


@dataclass(frozen=True)
class NodeDescriptor:
    """A configured node (input)."""

    node_id: str
    address: str
    label: str | None = None
    meta: Mapping[str, Any] | None = None

    @staticmethod
    def from_mapping(raw: Mapping[str, Any]) -> NodeDescriptor:
        if not isinstance(raw, Mapping):
            raise NodesInvalidInputError("Each node entry must be a mapping", details={"node": repr(raw)})

        node_id = raw.get("id") or raw.get("node_id") or raw.get("name")
        if not isinstance(node_id, str) or not node_id.strip():
            raise NodesInvalidInputError(
                "Node entry is missing required field 'id' (or 'node_id'/'name')",
                details={"node": dict(raw)},
            )
        node_id = node_id.strip()

        label_val = raw.get("label")
        label = label_val.strip() if isinstance(label_val, str) and label_val.strip() else None

        addr_val = raw.get("url") or raw.get("base_url") or raw.get("address")
        if isinstance(addr_val, str) and addr_val.strip():
            address = _normalize_address(addr_val)
        else:
            host = raw.get("host") or raw.get("hostname")
            port = raw.get("port")
            if not (isinstance(host, str) and host.strip() and isinstance(port, int)):
                raise NodesInvalidInputError(
                    "Node entry must include either 'url'/'address' or 'host' + 'port'",
                    details={"node_id": node_id},
                )
            address = _normalize_address(f"http://{host.strip()}:{port}")

        # Validate that host/port can be resolved early for deterministic failures.
        _ = _split_host_port(address)

        meta_val = raw.get("meta")
        if meta_val is not None and not isinstance(meta_val, Mapping):
            raise NodesInvalidInputError("Node entry field 'meta' must be a mapping", details={"node_id": node_id})
        meta: Mapping[str, Any] | None = dict(meta_val) if isinstance(meta_val, Mapping) else None

        return NodeDescriptor(node_id=node_id, address=address, label=label, meta=meta)

    def host_port(self) -> tuple[str, int]:
        return _split_host_port(self.address)


@dataclass(frozen=True)
class NodeStatus:
    """A probed node result (output)."""

    node_id: str
    address: str
    online: bool
    label: str | None = None
    latency_ms: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "label": self.label,
            "address": self.address,
            "status": "online" if self.online else "offline",
            "online": self.online,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class NodesListAndStatusRequest:
    """Inputs for nodes list/status."""

    timeout_s: float = DEFAULT_TIMEOUT_S
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    strict: bool = False
    # Optional override: provide nodes explicitly rather than pulling from config.
    nodes: Sequence[NodeDescriptor] | None = None


@dataclass(frozen=True)
class NodesListAndStatusResponse:
    """Outputs for nodes list/status."""

    nodes: list[NodeStatus]
    online_count: int
    offline_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "summary": {
                "online": self.online_count,
                "offline": self.offline_count,
                "total": self.online_count + self.offline_count,
            },
        }


def list_nodes_and_status(
    request: NodesListAndStatusRequest,
    *,
    config: Mapping[str, Any] | None = None,
) -> NodesListAndStatusResponse:
    """Synchronous wrapper around the async implementation.

    Raises:
      NodesInvalidInputError: if called from inside a running event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(list_nodes_and_status_async(request, config=config))

    raise NodesInvalidInputError(
        "list_nodes_and_status() cannot be called from a running event loop; use list_nodes_and_status_async()"
    )


async def list_nodes_and_status_async(
    request: NodesListAndStatusRequest,
    *,
    config: Mapping[str, Any] | None = None,
) -> NodesListAndStatusResponse:
    _validate_request(request)

    nodes: list[NodeDescriptor]
    if request.nodes is not None:
        nodes = list(request.nodes)
    else:
        nodes = _nodes_from_config(config)

    statuses = await _probe_all(nodes, timeout_s=request.timeout_s, max_concurrency=request.max_concurrency)

    # Deterministic ordering.
    statuses.sort(key=lambda s: s.node_id)

    online_count = sum(1 for s in statuses if s.online)
    offline_nodes = [s.node_id for s in statuses if not s.online]
    offline_count = len(statuses) - online_count

    if request.strict and offline_nodes:
        raise NodesExternalFailureError(
            "One or more nodes are unreachable",
            details={"offline_nodes": offline_nodes},
        )

    return NodesListAndStatusResponse(nodes=statuses, online_count=online_count, offline_count=offline_count)


def _validate_request(request: NodesListAndStatusRequest) -> None:
    if not isinstance(request.timeout_s, (int, float)) or request.timeout_s <= 0:
        raise NodesInvalidInputError("timeout_s must be a positive number", details={"timeout_s": request.timeout_s})
    if not isinstance(request.max_concurrency, int) or request.max_concurrency <= 0:
        raise NodesInvalidInputError(
            "max_concurrency must be a positive integer", details={"max_concurrency": request.max_concurrency}
        )


def _nodes_from_config(config: Mapping[str, Any] | None) -> list[NodeDescriptor]:
    resolved_config: Mapping[str, Any]
    if config is None:
        resolved_config = _load_config_from_env()
    else:
        resolved_config = config

    raw_nodes = _extract_nodes_block(resolved_config)

    nodes: list[NodeDescriptor] = [NodeDescriptor.from_mapping(entry) for entry in raw_nodes]

    if not nodes:
        raise NodesConfigError("No nodes configured")

    # Deterministic duplicate detection: fail rather than silently picking one.
    seen: set[str] = set()
    dupes: list[str] = []
    for n in nodes:
        if n.node_id in seen:
            dupes.append(n.node_id)
        seen.add(n.node_id)
    if dupes:
        raise NodesInvalidInputError("Duplicate node ids in configuration", details={"duplicates": sorted(set(dupes))})

    return nodes


def _extract_nodes_block(config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    def _get(path: Sequence[str]) -> Any:
        cur: Any = config
        for p in path:
            if not isinstance(cur, Mapping):
                return None
            cur = cur.get(p)
        return cur

    candidates: list[Any] = [
        _get(("nodes",)),
        _get(("cluster", "nodes")),
        _get(("thomas", "nodes")),
        _get(("browser", "nodes")),
    ]
    raw = next((c for c in candidates if c is not None), None)

    if raw is None:
        raise NodesConfigError(
            "No nodes configured in config",
            details={"expected_keys": ["nodes", "cluster.nodes", "thomas.marketplace.nodes", "browser.nodes"]},
        )

    if isinstance(raw, Mapping):
        out: list[Mapping[str, Any]] = []
        for node_id, val in raw.items():
            if isinstance(val, Mapping):
                merged = dict(val)
                merged.setdefault("id", str(node_id))
                out.append(merged)
            elif isinstance(val, str):
                out.append({"id": str(node_id), "url": val})
            else:
                raise NodesInvalidInputError(
                    "Invalid node entry in mapping",
                    details={"node_id": str(node_id), "value": repr(val)},
                )
        return out

    if isinstance(raw, list):
        if not all(isinstance(x, Mapping) for x in raw):
            raise NodesInvalidInputError("nodes must be a list of mappings")
        return [x for x in raw]

    raise NodesInvalidInputError(
        "Invalid nodes config: expected a list or mapping",
        details={"type": type(raw).__name__},
    )


def _load_config_from_env() -> Mapping[str, Any]:
    path = next((os.environ.get(v) for v in DEFAULT_CONFIG_ENV_VARS if os.environ.get(v)), None)
    if not path:
        raise NodesConfigError(
            "No config provided and no config env var is set",
            details={"env_vars": list(DEFAULT_CONFIG_ENV_VARS)},
        )
    return _load_config_file(path)


def _load_config_file(path: str) -> Mapping[str, Any]:
    p = pathlib.Path(path)
    try:
        raw_bytes = p.read_bytes()
    except FileNotFoundError as e:
        raise NodesConfigError("Config file not found", details={"path": str(p)}) from e
    except OSError as e:
        raise NodesConfigError("Failed to read config file", details={"path": str(p)}) from e

    suffix = p.suffix.lower()

    def _as_mapping(obj: Any) -> Mapping[str, Any]:
        if not isinstance(obj, Mapping):
            raise NodesConfigError(
                "Config root must be a mapping",
                details={"path": str(p), "type": type(obj).__name__},
            )
        return obj

    if suffix == ".json":
        try:
            return _as_mapping(json.loads(raw_bytes.decode("utf-8")))
        except json.JSONDecodeError as e:
            raise NodesConfigError("Invalid JSON config", details={"path": str(p)}) from e

    if suffix in (".toml", ".tml"):
        if tomllib is None:  # pragma: no cover
            raise NodesConfigError("TOML parsing unavailable", details={"path": str(p)})
        try:
            return _as_mapping(tomllib.loads(raw_bytes.decode("utf-8")))
        except (json.JSONDecodeError, ValueError, KeyError) as e:  # noqa: BLE001
            raise NodesConfigError("Invalid TOML config", details={"path": str(p)}) from e

    # Unknown extension: try JSON then TOML.
    try:
        return _as_mapping(json.loads(raw_bytes.decode("utf-8")))
    except (json.JSONDecodeError, ValueError, KeyError):  # noqa: BLE001
        pass

    if tomllib is None:  # pragma: no cover
        raise NodesConfigError("Unknown config format", details={"path": str(p)})

    try:
        return _as_mapping(tomllib.loads(raw_bytes.decode("utf-8")))
    except (json.JSONDecodeError, ValueError, KeyError) as e:  # noqa: BLE001
        raise NodesConfigError("Unknown config format", details={"path": str(p)}) from e


def load_config_from_path(path: str) -> Mapping[str, Any]:
    """Public wrapper around config-file parsing.

    Useful for CLI layers that may receive a config file path rather than a
    fully-materialized config mapping.
    """
    return _load_config_file(path)


def _normalize_address(address: str) -> str:
    addr = address.strip()
    if not addr:
        raise NodesInvalidInputError("Node address cannot be empty")

    # If the user provided "host:port" without scheme, urlparse() treats it as path.
    if "://" not in addr:
        addr = f"http://{addr}"

    parsed = urlparse(addr)
    if not parsed.hostname:
        raise NodesInvalidInputError("Invalid node address", details={"address": address})

    # Validate port if present (urlparse exposes it via .port and may raise ValueError).
    try:
        _ = parsed.port
    except ValueError as e:
        raise NodesInvalidInputError("Invalid node address (bad port)", details={"address": address}) from e

    return addr


def _split_host_port(address: str) -> tuple[str, int]:
    parsed = urlparse(address)
    host = parsed.hostname
    if not host:
        raise NodesInvalidInputError("Invalid node address (missing host)", details={"address": address})

    try:
        port = parsed.port
    except ValueError as e:
        raise NodesInvalidInputError("Invalid node address (bad port)", details={"address": address}) from e

    if port is None:
        scheme = (parsed.scheme or "").lower()
        if scheme == "https":
            port = 443
        else:
            # Default for http and unknown schemes.
            port = 80
    return host, int(port)


async def _probe_all(
    nodes: Sequence[NodeDescriptor],
    *,
    timeout_s: float,
    max_concurrency: int,
) -> list[NodeStatus]:
    sem = asyncio.Semaphore(max_concurrency)

    async def _guarded(node: NodeDescriptor) -> NodeStatus:
        async with sem:
            return await _probe_one(node, timeout_s=timeout_s)

    return await asyncio.gather(*[_guarded(n) for n in nodes])


async def _probe_one(node: NodeDescriptor, *, timeout_s: float) -> NodeStatus:
    host, port = node.host_port()
    start = time.perf_counter()

    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_s)
        # We do not read/write anything; a successful connect is enough.
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    except asyncio.TimeoutError:
        return NodeStatus(node_id=node.node_id, label=node.label, address=node.address, online=False, error="timeout")
    except OSError:
        return NodeStatus(
            node_id=node.node_id,
            label=node.label,
            address=node.address,
            online=False,
            error="connect_error",
        )
    except (RuntimeError, asyncio.QueueFull, ValueError):  # noqa: BLE001
        return NodeStatus(
            node_id=node.node_id,
            label=node.label,
            address=node.address,
            online=False,
            error="unknown_error",
        )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return NodeStatus(
        node_id=node.node_id,
        label=node.label,
        address=node.address,
        online=True,
        latency_ms=elapsed_ms,
    )


__all__ = [
    "DEFAULT_CONFIG_ENV_VARS",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_TIMEOUT_S",
    "NodeDescriptor",
    "NodeStatus",
    "NodesConfigError",
    "NodesExternalFailureError",
    "NodesInvalidInputError",
    "NodesListAndStatusError",
    "NodesListAndStatusRequest",
    "NodesListAndStatusResponse",
    "list_nodes_and_status",
    "list_nodes_and_status_async",
    "load_config_from_path",
]
