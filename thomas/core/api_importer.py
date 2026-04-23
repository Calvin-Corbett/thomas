from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

# Optional factory support (best-effort; falls back cleanly)
_FACTORY_AVAILABLE = True
try:
    from thomas.core.tool_factory import get_tool_factory  # type: ignore
except ImportError:  # pragma: no cover
    _FACTORY_AVAILABLE = False
    get_tool_factory = None  # type: ignore


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_JSON_CT_HINTS = ("application/json", "application/problem+json", "+json")
_FORM_CT_HINTS = ("application/x-www-form-urlencoded",)
_MULTIPART_CT_HINTS = ("multipart/form-data",)
_DEFAULT_ACCEPT = "application/json, text/plain;q=0.9, */*;q=0.8"
_MAX_SNAPSHOT_BYTES = 4_000_000  # compressed+base64 included in JSON file; keep sane


# -----------------------------
# Utilities
# -----------------------------


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "api"


def _op_fallback_id(method: str, path: str) -> str:
    p = path.strip("/")
    p = re.sub(r"\{([^}]+)\}", r"by_\1", p)
    p = re.sub(r"[^a-zA-Z0-9]+", "_", p).strip("_")
    return _slugify(f"{method}_{p}")


def _short_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def _is_yaml_like(text: str) -> bool:
    t = text.lstrip()
    if t.startswith("{") or t.startswith("["):
        return False
    head = "\n".join(text.splitlines()[:30]).lower()
    return ("openapi:" in head) or ("swagger:" in head) or (":" in head and "{" not in head)


def _parse_spec(raw: str) -> dict:
    raw_strip = raw.lstrip()
    if raw_strip.startswith("{") or raw_strip.startswith("["):
        return json.loads(raw)
    if yaml is None:
        try:
            return json.loads(raw)
        except Exception as e:
            raise ValueError("Spec looks like YAML but PyYAML is not available. Install PyYAML or provide JSON.") from e
    if _is_yaml_like(raw):
        return yaml.safe_load(raw)  # type: ignore
    return json.loads(raw)


@dataclass
class _ApiToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class _ApiToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    meta: dict[str, Any] | None = None

    def to_content(self, max_len: int = 50_000) -> str:
        if not self.ok:
            return json.dumps({"ok": False, "error": self.error or "unknown error"})
        payload = self.data if self.meta is None else {"data": self.data, "meta": self.meta}
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > max_len:
            text = text[: max_len - 50] + f"\n... (truncated, {len(text)} chars total)"
        return text


def _make_toolspec(name: str, description: str, parameters: dict) -> _ApiToolSpec:
    return _ApiToolSpec(name=name, description=description, parameters=parameters)


def _make_toolresult_ok(payload: Any, meta: dict | None = None) -> _ApiToolResult:
    return _ApiToolResult(ok=True, data=payload, meta=meta or None)


def _make_toolresult_err(message: str, meta: dict | None = None) -> _ApiToolResult:
    return _ApiToolResult(ok=False, error=message, meta=meta or None)


# -----------------------------
# OpenAPI helpers
# -----------------------------


def _expand_server_url(server_obj: dict) -> str | None:
    if not isinstance(server_obj, dict):
        return None
    url = server_obj.get("url")
    if not url:
        return None
    variables = server_obj.get("variables") or {}
    if isinstance(variables, dict):
        for var_name, var_def in variables.items():
            default = (var_def or {}).get("default")
            if default is None:
                continue
            url = str(url).replace("{" + str(var_name) + "}", str(default))
    return str(url)


def _get_default_server_url_openapi3(spec: dict) -> str | None:
    servers = spec.get("servers") or []
    if not servers:
        return None
    return _expand_server_url(servers[0] or {})


def _get_default_server_url_swagger2(spec: dict) -> str | None:
    host = spec.get("host")
    base_path = spec.get("basePath") or ""
    schemes = spec.get("schemes") or []
    scheme = schemes[0] if schemes else "https"
    if host:
        return f"{scheme}://{host}{base_path}"
    return None


def _get_default_server_url(spec: dict) -> str | None:
    if "openapi" in spec:
        return _get_default_server_url_openapi3(spec)
    if spec.get("swagger") == "2.0":
        return _get_default_server_url_swagger2(spec)
    return _get_default_server_url_openapi3(spec) or _get_default_server_url_swagger2(spec)


def _resolve_json_pointer(doc: Any, pointer: str) -> Any:
    if pointer == "" or pointer == "/":
        return doc
    cur = doc
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(f"Invalid $ref pointer segment '{part}' in '{pointer}'")
    return cur


def _normalize_ref(base_doc_url: str | None, ref: str) -> str:
    if ref.startswith("#/"):
        return ref  # local pointer

    doc_part, frag = (ref.split("#", 1) + [""])[:2]
    frag_part = "#" + frag if frag else ""

    if doc_part.startswith("http://") or doc_part.startswith("https://") or doc_part.startswith("file://"):
        return doc_part + frag_part

    if not base_doc_url:
        return ref

    if base_doc_url.startswith("http://") or base_doc_url.startswith("https://"):
        from urllib.parse import urljoin

        joined = urljoin(base_doc_url, doc_part)
        return joined + frag_part

    if base_doc_url.startswith("file://"):
        base_path = Path(urlparse(base_doc_url).path)
        joined_path = (base_path.parent / doc_part).resolve()
        return "file://" + joined_path.as_posix() + frag_part

    return ref


class _ExternalRefFetcher:
    """
    Fetches and parses external $ref documents with caching and sane limits.
    """

    def __init__(self, verify_ssl: bool = True, timeout_seconds: float = 30.0, max_bytes: int = 2_000_000):
        self.verify_ssl = verify_ssl
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self._cache: dict[str, Any] = {}

    def fetch_doc(self, url: str) -> Any:
        if url in self._cache:
            return self._cache[url]

        parsed = urlparse(url)
        raw: str

        if parsed.scheme in ("http", "https"):
            timeout = httpx.Timeout(self.timeout_seconds, connect=min(10.0, self.timeout_seconds))
            with httpx.Client(timeout=timeout, follow_redirects=True, verify=self.verify_ssl) as client:
                resp = client.get(url)
            resp.raise_for_status()
            if len(resp.content) > self.max_bytes:
                raise ValueError(f"External $ref too large (> {self.max_bytes} bytes): {url}")
            raw = resp.text

        elif parsed.scheme == "file":
            p = Path(parsed.path)
            b = p.read_bytes()
            if len(b) > self.max_bytes:
                raise ValueError(f"External $ref file too large (> {self.max_bytes} bytes): {p}")
            raw = b.decode("utf-8", errors="replace")

        else:
            raise ValueError(f"Unsupported external $ref scheme: {url}")

        doc = _parse_spec(raw)
        self._cache[url] = doc
        return doc


def _deref_schema(
    node: Any, spec: dict, base_doc_url: str | None, fetcher: _ExternalRefFetcher, seen: set[str] | None = None
) -> Any:
    seen = seen or set()

    if isinstance(node, dict) and "$ref" in node:
        ref = node.get("$ref")
        if not isinstance(ref, str):
            return node

        if ref.startswith("#/"):
            if ref in seen:
                return node
            seen.add(ref)
            target = _resolve_json_pointer(spec, ref[1:])
            return _deref_schema(target, spec, base_doc_url, fetcher, seen)

        norm = _normalize_ref(base_doc_url, ref)
        if norm in seen:
            return node
        seen.add(norm)

        if norm.startswith("#/"):
            target = _resolve_json_pointer(spec, norm[1:])
            return _deref_schema(target, spec, base_doc_url, fetcher, seen)

        doc_url, frag = (norm.split("#", 1) + [""])[:2]
        doc = fetcher.fetch_doc(doc_url)

        if frag:
            pointer = frag
            if not pointer.startswith("/"):
                pointer = "/" + pointer
            target = _resolve_json_pointer(doc, pointer)
            return _deref_schema(target, doc, doc_url, fetcher, seen)
        return _deref_schema(doc, doc, doc_url, fetcher, seen)

    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if isinstance(v, dict | list):
                out[k] = _deref_schema(v, spec, base_doc_url, fetcher, seen.copy())
            else:
                out[k] = v
        return out

    if isinstance(node, list):
        return [_deref_schema(x, spec, base_doc_url, fetcher, seen.copy()) for x in node]

    return node


def _merge_object_schemas(base: dict, extra: dict) -> dict:
    if base.get("type") != "object" or extra.get("type") != "object":
        return base
    props = dict(base.get("properties") or {})
    props.update(extra.get("properties") or {})
    req = set(base.get("required") or [])
    req |= set(extra.get("required") or [])
    merged = dict(base)
    merged["properties"] = props
    if req:
        merged["required"] = sorted(req)
    # if either allows additionalProperties, allow them
    if base.get("additionalProperties") or extra.get("additionalProperties"):
        merged["additionalProperties"] = True
    return merged


# -----------------------------
# Execution structures
# -----------------------------


@dataclass(frozen=True)
class AuthSchemeHint:
    scheme_name: str | None
    scheme_type: str | None  # apiKey/http/oauth2/basic
    in_: str | None  # header/query/cookie for apiKey
    token_name: str | None  # header/query/cookie name for apiKey
    http_scheme: str | None  # bearer/basic
    description: str | None


@dataclass(frozen=True)
class BodyMode:
    mode: str | None  # json/form/multipart/raw/none
    content_type: str | None


@dataclass(frozen=True)
class HttpOptions:
    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    retries: int = 2
    backoff_seconds: float = 0.4
    verify_ssl: bool = True
    follow_redirects: bool = True
    max_text_chars: int = 8000
    max_binary_bytes: int = 250_000


@dataclass(frozen=True)
class ParamSpec:
    name: str
    location: str  # path/query/header/cookie
    required: bool = False
    style: str | None = None  # OAS3
    explode: bool | None = None  # OAS3
    allow_reserved: bool | None = None
    collection_format: str | None = None  # Swagger2
    schema: dict | None = None


@dataclass(frozen=True)
class OpenApiOperation:
    api_name: str
    tool_name: str
    method: str
    path: str
    base_url: str
    auth_header: str | None

    params: list[ParamSpec]

    # body inputs
    body_schema: dict | None
    body_mode: BodyMode
    body_binary_fields: list[str]
    body_required: bool

    # auth metadata
    auth_hint: AuthSchemeHint | None
    security_required: bool

    # http knobs


class ApiImporter:
    """Minimal OpenAPI importer compatible with the test suite."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self.api_name_hint: str = ""
        self._last_api_name: str = ""
        self._last_spec_raw: str = ""
        self._last_freeze_spec: bool = False

    def _load_store(self) -> dict[str, Any]:
        if not self.storage_path.exists():
            return {}
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            return {}
        return {}

    def _write_store(self, payload: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _tool_rows_from_spec(self, spec: dict[str, Any], *, api_name: str) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        paths = spec.get("paths") or {}
        if not isinstance(paths, dict):
            return tools
        for raw_path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                method_text = str(method or "").strip().lower()
                if method_text not in _HTTP_METHODS:
                    continue
                operation_payload = operation if isinstance(operation, dict) else {}
                tool_name = str(operation_payload.get("operationId") or _op_fallback_id(method_text, str(raw_path)))
                tools.append(
                    {
                        "name": tool_name,
                        "method": method_text,
                        "path": str(raw_path),
                        "api_name": api_name,
                    }
                )
        return tools

    def import_from_file(self, spec_path: str | Path, *, freeze_spec: bool = False) -> list[dict[str, Any]]:
        spec_file = Path(spec_path)
        raw = spec_file.read_text(encoding="utf-8")
        spec = _parse_spec(raw)
        info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
        api_name = _slugify(self.api_name_hint or str(info.get("title") or spec_file.stem))
        self._last_api_name = api_name
        self._last_spec_raw = raw
        self._last_freeze_spec = bool(freeze_spec)
        return self._tool_rows_from_spec(spec, api_name=api_name)

    def save_imported_api(self, api_name: str, source_url: str, tools: list[dict[str, Any]]) -> None:
        payload = self._load_store()
        entry: dict[str, Any] = {
            "source_url": str(source_url or "").strip(),
            "tools": list(tools),
            "tool_count": len(list(tools)),
        }
        if self._last_freeze_spec and self._last_api_name == api_name and self._last_spec_raw:
            snapshot = gzip.compress(self._last_spec_raw.encode("utf-8"))
            entry["spec_snapshot"] = {
                "format": "gzip_base64",
                "data": base64.b64encode(snapshot).decode("ascii"),
            }
        payload[str(api_name)] = entry
        self._write_store(payload)
