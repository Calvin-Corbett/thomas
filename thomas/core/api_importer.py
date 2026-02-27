from __future__ import annotations

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
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

from thomas.tools.base import ToolResult, ToolSpec

# Optional factory support (best-effort; falls back cleanly)
_FACTORY_AVAILABLE = True
try:
    from thomas.core.tool_factory import get_tool_factory  # type: ignore
except Exception:  # pragma: no cover
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


def _dataclass_field_names(cls: type) -> set[str]:
    f = getattr(cls, "__dataclass_fields__", None)
    return set(f.keys()) if f else set()


def _pydantic_field_names(cls: type) -> set[str]:
    mf = getattr(cls, "model_fields", None)
    return set(mf.keys()) if mf else set()


def _make_toolspec(name: str, description: str, parameters: dict) -> ToolSpec:
    """
    Construct ToolSpec compatibly across possible ToolSpec implementations.
    """
    if hasattr(ToolSpec, "model_validate"):
        for payload in (
            {"name": name, "description": description, "parameters": parameters},
            {"name": name, "description": description, "input_schema": parameters},
            {"tool_name": name, "description": description, "parameters": parameters},
        ):
            try:
                return ToolSpec.model_validate(payload)  # type: ignore
            except Exception:
                pass

    fields = _dataclass_field_names(ToolSpec) | _pydantic_field_names(ToolSpec)
    kwargs: dict[str, Any] = {}
    if "name" in fields:
        kwargs["name"] = name
    elif "tool_name" in fields:
        kwargs["tool_name"] = name
    else:
        try:
            return ToolSpec(name, description, parameters)  # type: ignore
        except Exception as e:
            raise TypeError(f"Unsupported ToolSpec signature: {e}")

    if "description" in fields:
        kwargs["description"] = description

    if "parameters" in fields:
        kwargs["parameters"] = parameters
    elif "input_schema" in fields:
        kwargs["input_schema"] = parameters
    elif "schema" in fields:
        kwargs["schema"] = parameters

    return ToolSpec(**kwargs)  # type: ignore


def _make_toolresult_ok(payload: Any, meta: dict | None = None) -> ToolResult:
    meta = meta or {}
    if hasattr(ToolResult, "model_validate"):
        for candidate in (
            {"ok": True, "data": payload, "meta": meta},
            {"success": True, "output": payload, "meta": meta},
            {"ok": True, "output": payload, "metadata": meta},
            {"success": True, "content": payload, "metadata": meta},
        ):
            try:
                return ToolResult.model_validate(candidate)  # type: ignore
            except Exception:
                pass

    fields = _dataclass_field_names(ToolResult) | _pydantic_field_names(ToolResult)
    kwargs: dict[str, Any] = {}
    if "ok" in fields:
        kwargs["ok"] = True
    if "success" in fields:
        kwargs["success"] = True

    for key in ("data", "output", "content", "result", "value"):
        if key in fields:
            kwargs[key] = payload
            break

    for mkey in ("meta", "metadata", "extra"):
        if mkey in fields:
            kwargs[mkey] = meta
            break

    try:
        return ToolResult(**kwargs)  # type: ignore
    except Exception:
        try:
            return ToolResult(payload)  # type: ignore
        except Exception:
            return ToolResult()  # type: ignore


def _make_toolresult_err(message: str, meta: dict | None = None) -> ToolResult:
    meta = meta or {}
    if hasattr(ToolResult, "model_validate"):
        for candidate in (
            {"ok": False, "error": message, "meta": meta},
            {"success": False, "error": message, "meta": meta},
            {"ok": False, "message": message, "meta": meta},
            {"success": False, "message": message, "metadata": meta},
        ):
            try:
                return ToolResult.model_validate(candidate)  # type: ignore
            except Exception:
                pass

    fields = _dataclass_field_names(ToolResult) | _pydantic_field_names(ToolResult)
    kwargs: dict[str, Any] = {}
    if "ok" in fields:
        kwargs["ok"] = False
    if "success" in fields:
        kwargs["success"] = False

    if "error" in fields:
        kwargs["error"] = message
    elif "message" in fields:
        kwargs["message"] = message
    elif "output" in fields:
        kwargs["output"] = message
    elif "content" in fields:
        kwargs["content"] = message

    for mkey in ("meta", "metadata", "extra"):
        if mkey in fields:
            kwargs[mkey] = meta
            break

    try:
        return ToolResult(**kwargs)  # type: ignore
    except Exception:
        return _make_toolresult_ok({"error": message, "meta": meta})


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
            if isinstance(v, (dict, list)):
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
    http_options: HttpOptions

    # response hint
    accept_header: str | None


# -----------------------------
# HTTP execution
# -----------------------------

_REDACT_HEADERS = {"authorization", "x-api-key", "api-key", "x-auth-token", "x-access-token"}


# Runtime classes are split to keep this module focused and under monolith limits.
from .api_importer_http_tool import OpenApiHttpTool  # noqa: E402,F401
from .api_importer_importer import ApiImporter  # noqa: E402,F401
