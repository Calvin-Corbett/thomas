"""
P030 - Node CLI group scaffold (core)

This module provides Thomas-native node discovery and listing logic used by the
CLI "nodes" command group. It is intentionally dependency-light so it can be
imported by the CLI without pulling in the full server stack.

Design goals
- Clear input/output contracts via dataclasses.
- Deterministic, machine-readable errors.
- Safe defaults that work in automation (JSON output option handled by CLI).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Mapping, Optional, Literal
import json
import os
import re
import socket
import tomllib
import urllib.error
import urllib.parse
import urllib.request


NodeSource = Literal["config", "server"]


@dataclass(frozen=True, slots=True)
class NodeRecord:
    """A minimal description of a Thomas node."""

    node_id: str
    label: Optional[str] = None
    address: Optional[str] = None


@dataclass(frozen=True, slots=True)
class NodeListRequest:
    """Input contract for listing nodes."""

    # Explicit config file holding node definitions.
    config_path: Optional[str] = None
    # Explicit server URL to query for nodes.
    server_url: Optional[str] = None
    # Request timeout (seconds) for external calls.
    timeout_s: float = 5.0


@dataclass(frozen=True, slots=True)
class NodeListResponse:
    """Output contract for listing nodes."""

    source: NodeSource
    nodes: tuple[NodeRecord, ...] = field(default_factory=tuple)
    # When source == "server", which endpoint actually succeeded.
    endpoint: Optional[str] = None


@dataclass(frozen=True, slots=True)
class NodeGetRequest:
    """Input contract for fetching a single node by id."""

    node_id: str
    config_path: Optional[str] = None
    server_url: Optional[str] = None
    timeout_s: float = 5.0


@dataclass(frozen=True, slots=True)
class NodeGetResponse:
    """Output contract for fetching a single node by id."""

    source: NodeSource
    node: NodeRecord
    endpoint: Optional[str] = None


@dataclass(frozen=True, slots=True)
class NodeCliErrorPayload:
    """Machine-readable error contract."""

    kind: Literal["input", "config", "external", "internal"]
    code: str
    message: str


class NodeCliScaffoldError(Exception):
    """Base exception for node scaffold errors (deterministic)."""

    def __init__(self, *, kind: str, code: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.message = message

    def to_payload(self) -> NodeCliErrorPayload:
        return NodeCliErrorPayload(kind=self.kind, code=self.code, message=self.message)


class NodeCliInputError(NodeCliScaffoldError):
    def __init__(self, code: str, message: str):
        super().__init__(kind="input", code=code, message=message)


class NodeCliConfigError(NodeCliScaffoldError):
    def __init__(self, code: str, message: str):
        super().__init__(kind="config", code=code, message=message)


class NodeCliExternalError(NodeCliScaffoldError):
    def __init__(self, code: str, message: str):
        super().__init__(kind="external", code=code, message=message)


class NodeCliInternalError(NodeCliScaffoldError):
    def __init__(self, code: str, message: str):
        super().__init__(kind="internal", code=code, message=message)


def list_nodes(request: NodeListRequest, *, env: Mapping[str, str] | None = None) -> NodeListResponse:
    """
    List nodes using either a config file or a server endpoint.

    Resolution order:
    1) request.server_url (explicit)
    2) request.config_path (explicit)
    3) env THOMAS_SERVER_URL / THOMAS_API_URL
    4) env THOMAS_NODES_CONFIG / THOMAS_CONFIG
    """
    env = env or os.environ

    if request.timeout_s <= 0:
        raise NodeCliInputError("invalid_timeout", "timeout_s must be > 0")

    # Explicit server URL wins.
    server_url = (
        (request.server_url or "").strip()
        or (env.get("THOMAS_SERVER_URL") or env.get("THOMAS_API_URL") or "").strip()
    )
    if server_url:
        return _list_nodes_from_server(server_url, timeout_s=request.timeout_s)

    # Explicit config path next.
    config_path = (
        (request.config_path or "").strip()
        or (env.get("THOMAS_NODES_CONFIG") or env.get("THOMAS_CONFIG") or "").strip()
    )
    if config_path:
        return _list_nodes_from_config_file(config_path)

    raise NodeCliConfigError(
        "missing_node_source",
        "No node source configured. Provide --server, --config, or set THOMAS_SERVER_URL / THOMAS_NODES_CONFIG.",
    )


def get_node(request: NodeGetRequest, *, env: Mapping[str, str] | None = None) -> NodeGetResponse:
    """Fetch a single node by id using the same resolution rules as list_nodes()."""
    node_id = _validate_node_id(request.node_id)

    list_resp = list_nodes(
        NodeListRequest(config_path=request.config_path, server_url=request.server_url, timeout_s=request.timeout_s),
        env=env,
    )
    for n in list_resp.nodes:
        if n.node_id == node_id:
            return NodeGetResponse(source=list_resp.source, endpoint=list_resp.endpoint, node=n)

    raise NodeCliInputError("node_not_found", f"Unknown node id: {node_id}")


def node_list_to_dict(response: NodeListResponse) -> dict[str, Any]:
    """Convert a NodeListResponse into a JSON-safe dict."""
    return {
        "source": response.source,
        "endpoint": response.endpoint,
        "nodes": [{"id": n.node_id, "label": n.label, "address": n.address} for n in response.nodes],
    }


def node_get_to_dict(response: NodeGetResponse) -> dict[str, Any]:
    return {
        "source": response.source,
        "endpoint": response.endpoint,
        "node": {"id": response.node.node_id, "label": response.node.label, "address": response.node.address},
    }


def error_to_dict(err: NodeCliScaffoldError) -> dict[str, Any]:
    payload = err.to_payload()
    return {"ok": False, "error": asdict(payload)}


def ok_list_to_dict(response: NodeListResponse) -> dict[str, Any]:
    return {"ok": True, "result": node_list_to_dict(response)}


def ok_get_to_dict(response: NodeGetResponse) -> dict[str, Any]:
    return {"ok": True, "result": node_get_to_dict(response)}


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _validate_node_id(node_id: str) -> str:
    node_id = node_id.strip()
    if not node_id:
        raise NodeCliInputError("missing_node_id", "Node id is required")
    if not _ID_RE.match(node_id):
        raise NodeCliInputError("invalid_node_id", f"Invalid node id: {node_id!r}")
    return node_id


def _coerce_nodes(raw_nodes: Any) -> tuple[NodeRecord, ...]:
    if raw_nodes is None:
        return tuple()
    if not isinstance(raw_nodes, list):
        raise NodeCliConfigError("invalid_nodes", "Expected 'nodes' to be a list")
    nodes: list[NodeRecord] = []
    for idx, item in enumerate(raw_nodes):
        if not isinstance(item, Mapping):
            raise NodeCliConfigError("invalid_node_item", f"Node entry at index {idx} must be an object")
        node_id = item.get("id") or item.get("node_id") or item.get("name")
        if not isinstance(node_id, str):
            raise NodeCliConfigError("invalid_node_id", f"Node entry at index {idx} is missing a string id")
        node_id = _validate_node_id(node_id)
        label = item.get("label")
        if label is not None and not isinstance(label, str):
            raise NodeCliConfigError("invalid_node_label", f"Node {node_id!r} label must be a string")
        address = item.get("address") or item.get("host") or item.get("url")
        if address is not None and not isinstance(address, str):
            raise NodeCliConfigError("invalid_node_address", f"Node {node_id!r} address must be a string")
        nodes.append(NodeRecord(node_id=node_id, label=label, address=address))
    # Deterministic order
    nodes.sort(key=lambda n: n.node_id)
    return tuple(nodes)


def _read_config_file(path: str) -> Mapping[str, Any]:
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        raise NodeCliConfigError("config_not_found", f"Config file not found: {path}")
    if not os.path.isfile(p):
        raise NodeCliConfigError("config_not_file", f"Config path is not a file: {path}")

    try:
        with open(p, "rb") as f:
            raw_bytes = f.read()
    except OSError as e:
        raise NodeCliConfigError("config_read_failed", f"Failed to read config file: {path}") from e

    # Choose parser by extension first, but keep a fallback.
    ext = os.path.splitext(p)[1].lower()
    parsers: list[tuple[str, callable]] = []

    if ext in (".json",):
        parsers.append(("json", _parse_json_bytes))
    elif ext in (".yaml", ".yml"):
        parsers.append(("yaml", _parse_yaml_bytes))
    elif ext in (".toml",):
        parsers.append(("toml", _parse_toml_bytes))

    # Fallbacks in stable order.
    parsers.extend([("json", _parse_json_bytes), ("yaml", _parse_yaml_bytes), ("toml", _parse_toml_bytes)])

    last_err: Exception | None = None
    for name, parser in parsers:
        try:
            data = parser(raw_bytes)
            if isinstance(data, Mapping):
                return data
        except Exception as e:  # noqa: BLE001 - deterministic conversion below
            last_err = e
            continue

    raise NodeCliConfigError(
        "config_parse_failed",
        f"Unable to parse config file {path!r} as JSON/YAML/TOML",
    ) from last_err


def _parse_json_bytes(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))


def _parse_yaml_bytes(raw: bytes) -> Any:
    # Thomas keeps dependencies lean; implement a tiny YAML subset sufficient for:
    #   nodes:
    #     - id: alpha
    #       label: Alpha
    #       address: http://...
    #
    # This is NOT a full YAML parser. Unsupported YAML will raise ValueError,
    # which is converted into a deterministic config_parse_failed error.
    text = raw.decode("utf-8")
    return _simple_yaml_load(text)


def _parse_toml_bytes(raw: bytes) -> Any:
    return tomllib.loads(raw.decode("utf-8"))


def _simple_yaml_load(text: str) -> Any:
    """A tiny YAML loader for mappings + lists (subset, no anchors/tags/etc.)."""

    def strip_line(line: str) -> str | None:
        # Drop full-line comments and blanks.
        if not line.strip():
            return None
        s = line.lstrip()
        if s.startswith("#"):
            return None
        # Remove inline comments only when preceded by a space to avoid breaking URLs.
        if " #" in line:
            line = line.split(" #", 1)[0]
        return line.rstrip("\n").rstrip()

    raw_lines = [strip_line(ln) for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in raw_lines if ln is not None]
    if not lines:
        return {}

    def next_meaningful(idx: int) -> tuple[int, str] | None:
        for j in range(idx + 1, len(lines)):
            ln = lines[j]
            if ln is None:
                continue
            indent = len(ln) - len(ln.lstrip(" "))
            return indent, ln.lstrip(" ")
        return None

    def scalar(val: str) -> Any:
        v = val.strip()
        if v == "":
            return ""
        low = v.lower()
        if low in ("null", "~"):
            return None
        if low == "true":
            return True
        if low == "false":
            return False
        # Strip simple quotes.
        if (v.startswith("\"") and v.endswith("\"")) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        return v

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(0, root)]

    for i, line in enumerate(lines):
        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")

        # Unwind to the right container.
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError("Invalid YAML indentation")

        container = stack[-1][1]

        if content.startswith("-"):
            if not isinstance(container, list):
                raise ValueError("List item under non-list container")
            rest = content[1:].lstrip(" ")
            if not rest:
                item: dict[str, Any] = {}
                container.append(item)
                nm = next_meaningful(i)
                child_indent = nm[0] if nm and nm[0] > indent else indent + 2
                stack.append((child_indent, item))
                continue

            if ":" in rest:
                key, val = rest.split(":", 1)
                item = {key.strip(): scalar(val)}
                container.append(item)
                nm = next_meaningful(i)
                child_indent = nm[0] if nm and nm[0] > indent else indent + 2
                stack.append((child_indent, item))
                continue

            container.append(scalar(rest))
            continue

        # Mapping entry
        if not isinstance(container, dict):
            raise ValueError("Mapping entry under non-dict container")
        if ":" not in content:
            raise ValueError("Invalid mapping entry")

        key, val = content.split(":", 1)
        key = key.strip()
        val = val.strip()

        if val == "":
            nm = next_meaningful(i)
            if nm and nm[1].startswith("-"):
                new_container: Any = []
            else:
                new_container = {}
            container[key] = new_container
            child_indent = nm[0] if nm and nm[0] > indent else indent + 2
            stack.append((child_indent, new_container))
        else:
            container[key] = scalar(val)

    return root


def _extract_nodes_from_config(cfg: Mapping[str, Any]) -> Any:
    # Accept a few common nesting patterns while keeping the schema strict.
    if "nodes" in cfg:
        return cfg.get("nodes")
    if "thomas" in cfg and isinstance(cfg.get("thomas"), Mapping):
        t = cfg["thomas"]
        if "nodes" in t:
            return t.get("nodes")
    if "core" in cfg and isinstance(cfg.get("core"), Mapping):
        c = cfg["core"]
        if "nodes" in c:
            return c.get("nodes")
    return None


def _list_nodes_from_config_file(path: str) -> NodeListResponse:
    cfg = _read_config_file(path)
    raw_nodes = _extract_nodes_from_config(cfg)
    nodes = _coerce_nodes(raw_nodes)
    return NodeListResponse(source="config", nodes=nodes, endpoint=None)


def _list_nodes_from_server(server_url: str, *, timeout_s: float) -> NodeListResponse:
    server_url = server_url.strip()
    parsed = urllib.parse.urlparse(server_url)
    if not parsed.scheme or not parsed.netloc:
        raise NodeCliInputError("invalid_server_url", f"Invalid server URL: {server_url!r}")

    # Candidate endpoints in deterministic order (scaffold-friendly).
    base = server_url.rstrip("/")
    candidates = [
        base + "/nodes",
        base + "/api/nodes",
        base + "/api/v1/nodes",
        base + "/core/nodes",
        base + "/v1/nodes",
    ]

    last_err: Exception | None = None
    for url in candidates:
        try:
            nodes = _fetch_nodes_json(url, timeout_s=timeout_s)
            return NodeListResponse(source="server", nodes=nodes, endpoint=url)
        except NodeCliExternalError as e:
            # Only treat 404-ish errors as "try next endpoint".
            if e.code in ("http_not_found", "http_method_not_allowed"):
                last_err = e
                continue
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    if isinstance(last_err, NodeCliScaffoldError):
        raise last_err
    raise NodeCliExternalError("nodes_fetch_failed", "Failed to fetch nodes from server") from last_err


def _fetch_nodes_json(url: str, *, timeout_s: float) -> tuple[NodeRecord, ...]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = getattr(resp, "status", None) or 200
            raw = resp.read()
    except urllib.error.HTTPError as e:
        status = getattr(e, "code", None) or 0
        if status == 404:
            raise NodeCliExternalError("http_not_found", f"Endpoint not found: {url}") from e
        if status == 405:
            raise NodeCliExternalError("http_method_not_allowed", f"Method not allowed at: {url}") from e
        raise NodeCliExternalError("http_error", f"HTTP error {status} from {url}") from e
    except (urllib.error.URLError, socket.timeout) as e:
        raise NodeCliExternalError("connection_failed", f"Failed to connect to {url}") from e

    if status < 200 or status >= 300:
        raise NodeCliExternalError("http_error", f"HTTP error {status} from {url}")

    try:
        data: Any = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise NodeCliExternalError("invalid_json", f"Server returned invalid JSON from {url}") from e

    # Common wrappers:
    # - {"nodes": [...]}
    # - {"ok": true, "result": {"nodes": [...]}}
    if isinstance(data, Mapping) and "ok" in data and data.get("ok") is True and "result" in data:
        data = data.get("result")

    raw_nodes = data.get("nodes") if isinstance(data, Mapping) else data
    nodes = _coerce_nodes(raw_nodes)
    return nodes
