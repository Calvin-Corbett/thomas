"""
Nodes registry model (Thomas-native).

This module provides a small, strongly-validated model for describing and loading
a "nodes registry" — a list of remote nodes Thomas can talk to.

Design goals:
- Clear input/output contracts (TypedDict + dataclasses).
- Deterministic, typed errors for invalid input, missing config, and external failures.
- Pure-Python and safe by default (JSON first; YAML optional when PyYAML is installed).
- Friendly for both CLI and HTTP routing (always machine-readable with an `ok` flag).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence, TypedDict, cast, Literal
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


__all__ = [
    "SCHEMA_VERSION",
    "ENV_REGISTRY_PATH",
    "ENV_REGISTRY_PATH_FALLBACK",
    "ENV_REGISTRY_JSON",
    "NodeRecordDict",
    "NodesRegistryResponse",
    "NodesRegistryErrorDetail",
    "NodesRegistryErrorResponse",
    "NodesRegistryModelOutput",
    "NodesRegistryModelRequest",
    "NodeRecord",
    "NodesRegistry",
    "NodesRegistryError",
    "NodesRegistryConfigError",
    "NodesRegistryInputError",
    "NodesRegistryExternalError",
    "load_nodes_registry",
    "filter_nodes",
    "run_nodes_registry_model",
    "nodes_registry_model",
]


SCHEMA_VERSION: int = 1

# Environment variables supported by the loader.
ENV_REGISTRY_PATH = "THOMAS_NODES_REGISTRY_PATH"
ENV_REGISTRY_PATH_FALLBACK = "THOMAS_NODES_REGISTRY"
ENV_REGISTRY_JSON = "THOMAS_NODES_REGISTRY_JSON"


class NodeRecordDict(TypedDict):
    """Machine-facing representation of a node record."""

    id: str
    endpoint: str
    labels: list[str]
    meta: dict[str, Any]


class NodesRegistryResponse(TypedDict):
    """Machine-facing representation of a successful registry load result."""

    ok: Literal[True]
    schema_version: int
    source: str
    count: int
    nodes: list[NodeRecordDict]


class NodesRegistryErrorDetail(TypedDict):
    code: str
    message: str
    details: dict[str, Any]


class NodesRegistryErrorResponse(TypedDict):
    ok: Literal[False]
    schema_version: int
    error: NodesRegistryErrorDetail


NodesRegistryModelOutput = NodesRegistryResponse | NodesRegistryErrorResponse


class NodesRegistryModelRequest(TypedDict, total=False):
    """
    Input contract for a "nodes registry model" run.

    This is deliberately small: it's suitable for CLI flags or HTTP query params.
    """

    source: str
    label: str
    id: str
    timeout_s: float
    # Optional config and env injection (useful for tests or embedding).
    config: Mapping[str, Any]
    env: Mapping[str, str]


@dataclass(slots=True)
class NodeRecord:
    """In-memory node descriptor."""

    node_id: str
    endpoint: str
    labels: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> NodeRecordDict:
        return {
            "id": self.node_id,
            "endpoint": self.endpoint,
            "labels": list(self.labels),
            "meta": dict(self.meta),
        }


@dataclass(slots=True)
class NodesRegistry:
    """Loaded nodes registry."""

    nodes: list[NodeRecord]
    source: str

    def to_response(self) -> NodesRegistryResponse:
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "source": self.source,
            "count": len(self.nodes),
            "nodes": [n.to_dict() for n in self.nodes],
        }


class NodesRegistryError(Exception):
    """Base class for deterministic nodes registry failures."""

    code = "nodes_registry_error"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})

    def to_error_response(self) -> NodesRegistryErrorResponse:
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "error": {
                "code": self.code,
                "message": str(self),
                "details": dict(self.details),
            },
        }


class NodesRegistryConfigError(NodesRegistryError):
    """Missing/invalid configuration."""

    code = "nodes_registry_config_error"


class NodesRegistryInputError(NodesRegistryError):
    """Registry content is malformed."""

    code = "nodes_registry_input_error"


class NodesRegistryExternalError(NodesRegistryError):
    """I/O, network, or parsing failure not caused by user schema choices."""

    code = "nodes_registry_external_error"


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _is_http_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _normalise_endpoint(endpoint: str) -> str:
    """
    Normalise an endpoint.

    Accepted:
    - http(s)://host[:port][/path]
    - host:port  -> assumed http://host:port
    - host       -> assumed http://host
    """

    endpoint = endpoint.strip()
    if not endpoint:
        raise NodesRegistryInputError("Node endpoint must be a non-empty string.")
    if "://" not in endpoint:
        endpoint = "http://" + endpoint
    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise NodesRegistryInputError(
            "Node endpoint is not a valid URL.",
            details={"endpoint": endpoint},
        )
    return endpoint


def _coerce_labels(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # allow comma-separated or single label
        parts = [p.strip() for p in value.split(",")]
        return [p for p in parts if p]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        labels: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise NodesRegistryInputError(
                    "Node labels must be strings.",
                    details={"bad_label": repr(item)},
                )
            item = item.strip()
            if item:
                labels.append(item)
        return labels
    raise NodesRegistryInputError(
        "Node labels must be a string or a sequence of strings.",
        details={"labels_type": type(value).__name__},
    )


def _assert_unique_ids(nodes: list[NodeRecord], *, source: str) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for n in nodes:
        if n.node_id in seen:
            dupes.add(n.node_id)
        else:
            seen.add(n.node_id)
    if dupes:
        raise NodesRegistryInputError(
            "Duplicate node ids in registry.",
            details={"source": source, "duplicates": sorted(dupes)},
        )


def _parse_registry_payload(payload: Any, *, source: str) -> NodesRegistry:
    """
    Parse registry payload into a NodesRegistry.

    Accepted top-level forms:
    - {"nodes": [ ... ]}
    - [ ... ]
    - {"node-id": { ... }, ... } (mapping form)
    """

    raw_nodes: Any
    mapping_form = False
    if isinstance(payload, dict):
        if "nodes" in payload:
            raw_nodes = payload["nodes"]
        else:
            raw_nodes = payload
            mapping_form = True
    elif isinstance(payload, list):
        raw_nodes = payload
    else:
        raise NodesRegistryInputError(
            "Registry must be a JSON/YAML object or list.",
            details={"source": source, "type": type(payload).__name__},
        )

    nodes: list[NodeRecord] = []

    if mapping_form:
        for key, value in cast(Mapping[str, Any], raw_nodes).items():
            if not isinstance(key, str) or not key.strip():
                raise NodesRegistryInputError(
                    "Registry mapping keys must be non-empty strings.",
                    details={"source": source},
                )
            if not isinstance(value, Mapping):
                raise NodesRegistryInputError(
                    "Registry mapping values must be objects.",
                    details={"source": source, "node_id": key},
                )
            nodes.append(_parse_node_record(value, implied_id=key, source=source))
    else:
        if not isinstance(raw_nodes, list):
            raise NodesRegistryInputError(
                "Registry 'nodes' must be a list.",
                details={"source": source, "type": type(raw_nodes).__name__},
            )
        for idx, item in enumerate(raw_nodes):
            if not isinstance(item, Mapping):
                raise NodesRegistryInputError(
                    "Each node entry must be an object.",
                    details={"source": source, "index": idx},
                )
            nodes.append(_parse_node_record(item, implied_id=None, source=source))

    _assert_unique_ids(nodes, source=source)

    # Deterministic ordering.
    nodes.sort(key=lambda n: n.node_id)
    return NodesRegistry(nodes=nodes, source=source)


def _parse_node_record(item: Mapping[str, Any], *, implied_id: str | None, source: str) -> NodeRecord:
    # Explicit id fields if present.
    explicit_any = cast(Any, item.get("id") or item.get("node_id") or item.get("name"))
    if implied_id is not None and explicit_any is not None:
        if not isinstance(explicit_any, str) or not explicit_any.strip():
            raise NodesRegistryInputError(
                "Node id must be a non-empty string.",
                details={"source": source, "node_id": implied_id},
            )
        if explicit_any.strip() != implied_id:
            raise NodesRegistryInputError(
                "Node id does not match registry mapping key.",
                details={"source": source, "mapping_key": implied_id, "id": explicit_any.strip()},
            )

    node_id_any = explicit_any if explicit_any is not None else implied_id
    if not isinstance(node_id_any, str) or not node_id_any.strip():
        raise NodesRegistryInputError(
            "Node id is required and must be a non-empty string.",
            details={"source": source},
        )
    node_id = node_id_any.strip()
    if not _ID_RE.match(node_id):
        raise NodesRegistryInputError(
            "Node id contains invalid characters.",
            details={"source": source, "id": node_id},
        )

    # Endpoint
    endpoint_any = cast(
        Any,
        item.get("endpoint") or item.get("url") or item.get("base_url") or item.get("address"),
    )
    if not isinstance(endpoint_any, str):
        raise NodesRegistryInputError(
            "Node endpoint is required and must be a string.",
            details={"source": source, "id": node_id},
        )
    endpoint = _normalise_endpoint(endpoint_any)

    # Labels
    labels = _coerce_labels(item.get("labels") or item.get("tags") or item.get("capabilities"))

    # Meta: keep any remaining fields aside from the canonical ones.
    meta: dict[str, Any] = {}
    for k, v in item.items():
        if k in {
            "id",
            "node_id",
            "name",
            "endpoint",
            "url",
            "base_url",
            "address",
            "labels",
            "tags",
            "capabilities",
        }:
            continue
        # ensure JSON-serialisable-ish by best effort; if not, stringify
        try:
            json.dumps(v)
            meta[k] = v
        except TypeError:
            meta[k] = repr(v)

    return NodeRecord(node_id=node_id, endpoint=endpoint, labels=labels, meta=meta)


def _load_yaml(text: str, *, source: str) -> Any:
    try:
        import yaml  # type: ignore
    except Exception as e:  # pragma: no cover - only hits when YAML requested but dependency missing
        raise NodesRegistryExternalError(
            "YAML registry support requires PyYAML to be installed.",
            details={"source": source, "missing": "PyYAML"},
        ) from e
    try:
        return yaml.safe_load(text)
    except Exception as e:
        raise NodesRegistryExternalError(
            "Failed to parse YAML registry.",
            details={"source": source},
        ) from e


def _load_json(text: str, *, source: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise NodesRegistryExternalError(
            "Failed to parse JSON registry.",
            details={"source": source, "line": e.lineno, "col": e.colno},
        ) from e


def _decode_registry_text(raw: bytes, *, source: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise NodesRegistryExternalError(
            "Registry is not valid UTF-8.",
            details={"source": source},
        ) from e


def _load_text_from_file(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as e:
        raise NodesRegistryConfigError(
            "Nodes registry file does not exist.",
            details={"path": str(path)},
        ) from e
    except OSError as e:
        raise NodesRegistryExternalError(
            "Failed to read nodes registry file.",
            details={"path": str(path), "errno": getattr(e, "errno", None)},
        ) from e
    return _decode_registry_text(raw, source=f"file:{path}")


def _load_text_from_url(url: str, *, timeout_s: float) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.URLError as e:
        raise NodesRegistryExternalError(
            "Failed to fetch nodes registry URL.",
            details={"url": url, "reason": str(getattr(e, "reason", e))},
        ) from e
    except Exception as e:
        raise NodesRegistryExternalError(
            "Failed to fetch nodes registry URL.",
            details={"url": url, "reason": str(e)},
        ) from e
    return _decode_registry_text(raw, source=f"url:{url}")


def _maybe_load_structured(text: str, *, source: str, hint: str | None = None) -> Any:
    """
    Attempt to parse text into JSON/YAML.

    - If hint is 'json' or 'yaml', prefer that format.
    - Otherwise, try JSON first, then YAML.
    """

    hint = (hint or "").lower().strip()
    if hint == "json":
        return _load_json(text, source=source)
    if hint == "yaml":
        return _load_yaml(text, source=source)

    # auto (JSON first, then YAML)
    try:
        return _load_json(text, source=source)
    except NodesRegistryExternalError as json_err:
        try:
            return _load_yaml(text, source=source)
        except NodesRegistryExternalError as yaml_err:
            # If YAML isn't available, surface the JSON error (it's more actionable).
            if yaml_err.details.get("missing") == "PyYAML":
                raise json_err
            raise yaml_err


def _extract_source_from_config(config: Mapping[str, Any]) -> str | None:
    # Common config conventions; deliberately permissive.
    candidates = [
        config.get("nodes_registry"),
        config.get("nodes_registry_path"),
        config.get("nodesRegistry"),
        config.get("nodesRegistryPath"),
        config.get("nodes_registry_url"),
    ]
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()

    # Nested (e.g. {"nodes": {"registry_path": "..."} })
    nodes_cfg = config.get("nodes")
    if isinstance(nodes_cfg, Mapping):
        for k in ("registry_path", "registry", "registry_url", "registryPath"):
            v = nodes_cfg.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return None


def _coerce_source_to_path_string(src: str) -> str:
    """Coerce a file:-style source into a filesystem path string."""

    parsed = urllib.parse.urlparse(src)
    if parsed.scheme != "file":
        return src

    # URL-decode, then fix Windows drive-letter form if needed.
    path_str = urllib.parse.unquote(parsed.path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", path_str):
        path_str = path_str[1:]
    return path_str


def load_nodes_registry(
    source: str | Path | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 5.0,
) -> NodesRegistry:
    """
    Load a nodes registry.

    Resolution order:
    1) Explicit `source` arg.
    2) Inline config forms:
       - config["nodes"] as list/dict of node entries
       - config["nodes_registry"] as list/dict/{"nodes":[...]}
    3) Config path/url keys (see _extract_source_from_config).
    4) Env var THOMAS_NODES_REGISTRY_PATH / THOMAS_NODES_REGISTRY.
    5) Env var THOMAS_NODES_REGISTRY_JSON (inline JSON).

    Args:
        source: File path or URL.
        config: Optional config mapping.
        env: Optional environment mapping.
        timeout_s: URL fetch timeout.

    Raises:
        NodesRegistryConfigError: when no source can be resolved.
        NodesRegistryInputError: when schema is invalid.
        NodesRegistryExternalError: when I/O/parsing fails.

    Returns:
        NodesRegistry.
    """

    if source is not None and not isinstance(source, (str, Path)):
        raise NodesRegistryInputError(
            "source must be a file path or URL string.",
            details={"type": type(source).__name__},
        )
    if timeout_s <= 0:
        raise NodesRegistryInputError(
            "timeout_s must be > 0.",
            details={"timeout_s": timeout_s},
        )
    if config is not None and not isinstance(config, Mapping):
        raise NodesRegistryInputError(
            "config must be a mapping.",
            details={"type": type(config).__name__},
        )
    if env is not None and not isinstance(env, Mapping):
        raise NodesRegistryInputError(
            "env must be a mapping.",
            details={"type": type(env).__name__},
        )

    env = env or os.environ

    # 1) explicit source
    resolved: str | None
    if isinstance(source, Path):
        resolved = str(source)
    elif isinstance(source, str) and source.strip():
        resolved = source.strip()
    else:
        resolved = None

    # 2) inline config forms
    if resolved is None and config is not None:
        # If config["nodes"] is a list/dict -> treat as inline registry.
        if "nodes" in config and isinstance(config.get("nodes"), (list, dict)):
            return _parse_registry_payload(config.get("nodes"), source="config:nodes")
        if "nodes_registry" in config and isinstance(config.get("nodes_registry"), (list, dict)):
            return _parse_registry_payload(config.get("nodes_registry"), source="config:nodes_registry")

    # 3) config path/url
    if resolved is None and config is not None:
        resolved = _extract_source_from_config(config)

    # 4) env file/url
    if resolved is None:
        for key in (ENV_REGISTRY_PATH, ENV_REGISTRY_PATH_FALLBACK):
            v = env.get(key)
            if isinstance(v, str) and v.strip():
                resolved = v.strip()
                break

    # 5) env inline JSON
    if resolved is None:
        inline_json = env.get(ENV_REGISTRY_JSON)
        if isinstance(inline_json, str) and inline_json.strip():
            payload = _load_json(inline_json, source=f"env:{ENV_REGISTRY_JSON}")
            return _parse_registry_payload(payload, source=f"env:{ENV_REGISTRY_JSON}")

    if resolved is None:
        raise NodesRegistryConfigError(
            "No nodes registry source configured.",
            details={
                "expected": [ENV_REGISTRY_PATH, ENV_REGISTRY_PATH_FALLBACK, ENV_REGISTRY_JSON],
                "hint": "Pass a source path/URL or set THOMAS_NODES_REGISTRY_PATH.",
            },
        )

    # Support file: URLs.
    if resolved.startswith("file:"):
        resolved = _coerce_source_to_path_string(resolved)

    # Load from URL or file.
    if _is_http_url(resolved):
        text = _load_text_from_url(resolved, timeout_s=timeout_s)
        payload = _maybe_load_structured(text, source=f"url:{resolved}")
        return _parse_registry_payload(payload, source=f"url:{resolved}")

    # Treat as file path.
    path = Path(resolved).expanduser().resolve()
    text = _load_text_from_file(path)
    hint = None
    if path.suffix.lower() in {".yaml", ".yml"}:
        hint = "yaml"
    elif path.suffix.lower() == ".json":
        hint = "json"
    payload = _maybe_load_structured(text, source=f"file:{path}", hint=hint)
    return _parse_registry_payload(payload, source=f"file:{path}")


def filter_nodes(registry: NodesRegistry, *, label: str | None = None, node_id: str | None = None) -> NodesRegistry:
    """
    Filter a registry by label and/or node id.

    This is intentionally simple and deterministic: exact matches only.
    """

    label_norm = (label or "").strip() or None
    id_norm = (node_id or "").strip() or None

    nodes = registry.nodes
    if id_norm is not None:
        nodes = [n for n in nodes if n.node_id == id_norm]
    if label_norm is not None:
        nodes = [n for n in nodes if label_norm in n.labels]

    return NodesRegistry(nodes=list(nodes), source=registry.source)


def run_nodes_registry_model(req: NodesRegistryModelRequest | Mapping[str, Any] | None = None) -> NodesRegistryModelOutput:
    """
    Non-throwing facade suitable for automation.

    Returns a union of:
    - NodesRegistryResponse (ok=True)
    - NodesRegistryErrorResponse (ok=False)

    The request mapping may include: source, label, id, timeout_s, config, env.
    """

    if req is not None and not isinstance(req, Mapping):
        return NodesRegistryInputError(
            "Request must be a mapping.",
            details={"type": type(req).__name__},
        ).to_error_response()

    req_map: Mapping[str, Any] = cast(Mapping[str, Any], req or {})
    source = req_map.get("source")
    label = req_map.get("label")
    node_id = req_map.get("id")

    timeout_raw = req_map.get("timeout_s", 5.0)
    try:
        timeout_s = float(timeout_raw)
    except (TypeError, ValueError):
        return NodesRegistryInputError(
            "timeout_s must be a number.",
            details={"timeout_s": timeout_raw},
        ).to_error_response()
    if timeout_s <= 0:
        return NodesRegistryInputError(
            "timeout_s must be > 0.",
            details={"timeout_s": timeout_s},
        ).to_error_response()

    config = req_map.get("config")
    if config is not None and not isinstance(config, Mapping):
        return NodesRegistryInputError(
            "config must be a mapping.",
            details={"type": type(config).__name__},
        ).to_error_response()

    env = req_map.get("env")
    if env is not None and not isinstance(env, Mapping):
        return NodesRegistryInputError(
            "env must be a mapping.",
            details={"type": type(env).__name__},
        ).to_error_response()

    try:
        registry = load_nodes_registry(
            source=cast(Any, source),
            config=cast(Any, config),
            env=cast(Any, env),
            timeout_s=timeout_s,
        )
        if label or node_id:
            registry = filter_nodes(registry, label=cast(Any, label), node_id=cast(Any, node_id))
        return registry.to_response()
    except NodesRegistryError as e:
        return e.to_error_response()
    except Exception as e:  # pragma: no cover - defensive: keeps errors deterministic
        return NodesRegistryExternalError(
            "Unexpected error while building nodes registry model.",
            details={"type": type(e).__name__, "reason": str(e)},
        ).to_error_response()


# Convenience alias: some callers like a short name.
nodes_registry_model = run_nodes_registry_model
