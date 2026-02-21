from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote, urljoin, urlparse

import httpx

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

from thomas.tools.base import Tool, ToolResult, ToolSpec

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


def _make_toolresult_ok(payload: Any, meta: Optional[dict] = None) -> ToolResult:
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


def _make_toolresult_err(message: str, meta: Optional[dict] = None) -> ToolResult:
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

def _expand_server_url(server_obj: dict) -> Optional[str]:
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


def _get_default_server_url_openapi3(spec: dict) -> Optional[str]:
    servers = spec.get("servers") or []
    if not servers:
        return None
    return _expand_server_url(servers[0] or {})


def _get_default_server_url_swagger2(spec: dict) -> Optional[str]:
    host = spec.get("host")
    base_path = spec.get("basePath") or ""
    schemes = spec.get("schemes") or []
    scheme = schemes[0] if schemes else "https"
    if host:
        return f"{scheme}://{host}{base_path}"
    return None


def _get_default_server_url(spec: dict) -> Optional[str]:
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


def _normalize_ref(base_doc_url: Optional[str], ref: str) -> str:
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
        self._cache: Dict[str, Any] = {}

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


def _deref_schema(node: Any, spec: dict, base_doc_url: Optional[str], fetcher: _ExternalRefFetcher, seen: Optional[set[str]] = None) -> Any:
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
    scheme_name: Optional[str]
    scheme_type: Optional[str]  # apiKey/http/oauth2/basic
    in_: Optional[str]          # header/query/cookie for apiKey
    token_name: Optional[str]   # header/query/cookie name for apiKey
    http_scheme: Optional[str]  # bearer/basic
    description: Optional[str]


@dataclass(frozen=True)
class BodyMode:
    mode: Optional[str]         # json/form/multipart/raw/none
    content_type: Optional[str]


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
    style: Optional[str] = None         # OAS3
    explode: Optional[bool] = None      # OAS3
    allow_reserved: Optional[bool] = None
    collection_format: Optional[str] = None  # Swagger2
    schema: Optional[dict] = None


@dataclass(frozen=True)
class OpenApiOperation:
    api_name: str
    tool_name: str
    method: str
    path: str
    base_url: str
    auth_header: Optional[str]

    params: List[ParamSpec]

    # body inputs
    body_schema: Optional[dict]
    body_mode: BodyMode
    body_binary_fields: List[str]
    body_required: bool

    # auth metadata
    auth_hint: Optional[AuthSchemeHint]
    security_required: bool

    # http knobs
    http_options: HttpOptions

    # response hint
    accept_header: Optional[str]


# -----------------------------
# HTTP execution
# -----------------------------

_REDACT_HEADERS = {"authorization", "x-api-key", "api-key", "x-auth-token", "x-access-token"}


def _redact_headers(headers: Dict[str, str], extra_redact: Optional[List[str]] = None) -> Dict[str, str]:
    redact = set(_REDACT_HEADERS)
    if extra_redact:
        redact |= {h.lower() for h in extra_redact}
    out: Dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in redact:
            out[k] = "***redacted***"
        else:
            out[k] = v
    return out


def _cap_text(text: str, max_chars: int) -> str:
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…(truncated)"


def _sleep_backoff(base: float, attempt: int) -> None:
    delay = min(6.0, base * (2 ** attempt))
    time.sleep(delay)


def _coerce_query_value(v: Any) -> Any:
    if isinstance(v, dict):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    return v


def _encode_query_param_oas3(p: ParamSpec, value: Any) -> List[Tuple[str, str]]:
    """
    Implements a practical subset of OAS3 query encoding:
      - arrays: explode -> repeated, else comma-joined
      - objects: deepObject -> name[key]=v, explode -> key=v, else name=key,v,key,v
    """
    style = p.style or "form"
    explode = p.explode if p.explode is not None else True  # default explode=true for query in OAS3
    items: List[Tuple[str, str]] = []

    if value is None:
        return items

    if isinstance(value, (list, tuple)):
        if explode:
            for x in value:
                items.append((p.name, str(x)))
        else:
            items.append((p.name, ",".join(str(x) for x in value)))
        return items

    if isinstance(value, dict):
        if style == "deepObject":
            for k, v in value.items():
                items.append((f"{p.name}[{k}]", str(v)))
            return items

        if explode:
            for k, v in value.items():
                items.append((str(k), str(v)))
            return items

        flat: List[str] = []
        for k, v in value.items():
            flat.append(str(k))
            flat.append(str(v))
        items.append((p.name, ",".join(flat)))
        return items

    items.append((p.name, str(_coerce_query_value(value))))
    return items


def _encode_query_param_swagger2(p: ParamSpec, value: Any) -> List[Tuple[str, str]]:
    fmt = (p.collection_format or "csv").lower()
    items: List[Tuple[str, str]] = []
    if value is None:
        return items
    if isinstance(value, (list, tuple)):
        if fmt == "multi":
            for x in value:
                items.append((p.name, str(x)))
        else:
            sep = { "csv": ",", "ssv": " ", "tsv": "\t", "pipes": "|" }.get(fmt, ",")
            items.append((p.name, sep.join(str(x) for x in value)))
        return items
    if isinstance(value, dict):
        # swagger2 doesn't define deep object; JSON-string it as pragmatic default
        items.append((p.name, json.dumps(value, separators=(",", ":"), ensure_ascii=False)))
        return items
    items.append((p.name, str(value)))
    return items


def _coerce_file_field(field_name: str, value: Any, opened_files: List[Any]) -> Optional[Tuple[str, Any, str]]:
    """
    Coerce a value into an httpx files tuple: (filename, fileobj, content_type)

    Supported inputs:
      - string path to a local file
      - dict: {"path": "...", "filename": "...", "content_type": "..."}
      - tuple/list: (path, content_type) or (path, filename, content_type)
    """
    content_type = "application/octet-stream"
    filename = None
    path = None

    if isinstance(value, dict):
        path = value.get("path")
        filename = value.get("filename")
        content_type = value.get("content_type") or content_type
    elif isinstance(value, (tuple, list)):
        if len(value) == 2:
            path, content_type = value[0], value[1]
        elif len(value) >= 3:
            path, filename, content_type = value[0], value[1], value[2]
    elif isinstance(value, str):
        path = value

    if not path or not isinstance(path, str):
        return None
    if not os.path.exists(path):
        return None

    if filename is None:
        filename = os.path.basename(path) or field_name

    f = open(path, "rb")
    opened_files.append(f)
    return (filename, f, content_type)


class OpenApiHttpTool(Tool):
    """
    Concrete Tool implementation for a single OpenAPI/Swagger operation.
    """
    def __init__(self, spec: ToolSpec, op: OpenApiOperation):
        self._spec = spec
        self._op = op

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def execute(self, args: dict) -> ToolResult:
        try:
            return self._execute_http(args or {})
        except Exception as e:
            return _make_toolresult_err(f"Tool execution failed: {e}")

    def _execute_http(self, args: dict) -> ToolResult:
        # Consumer-loved extras
        dry_run = bool(args.get("__dry_run", False))
        trace = bool(args.get("__trace", False))
        override_auth = args.get("__auth")
        override_base_url = args.get("__base_url")
        override_timeout = args.get("__timeout_seconds")

        base_url = (override_base_url or self._op.base_url or "").strip()
        if not base_url:
            return _make_toolresult_err("No base_url configured. Provide servers[0].url or pass base_url during import.")

        method = self._op.method.upper()
        base = base_url.rstrip("/") + "/"
        path = self._op.path

        # Path params
        for p in self._op.params:
            if p.location != "path":
                continue
            if p.name not in args:
                if p.required:
                    return _make_toolresult_err(f"Missing required path param: {p.name}")
                continue
            path = path.replace("{" + p.name + "}", quote(str(args[p.name]), safe=""))

        url = urljoin(base, path.lstrip("/"))

        # Query params (order-preserving list-of-tuples is best for repeated keys)
        query_items: List[Tuple[str, str]] = []
        is_oas3 = True
        # We infer swagger2 by presence of collection_format in any param spec
        for p in self._op.params:
            if p.collection_format is not None:
                is_oas3 = False
                break

        for p in self._op.params:
            if p.location != "query":
                continue
            if p.name not in args or args[p.name] is None:
                continue
            v = args[p.name]
            if is_oas3:
                query_items.extend(_encode_query_param_oas3(p, v))
            else:
                query_items.extend(_encode_query_param_swagger2(p, v))

        # Headers from spec-defined header params
        headers: Dict[str, str] = {}
        headers["Accept"] = self._op.accept_header or _DEFAULT_ACCEPT

        for p in self._op.params:
            if p.location != "header":
                continue
            if p.name in args and args[p.name] is not None:
                headers[p.name] = str(args[p.name])

        # Cookies
        cookies: Dict[str, str] = {}
        for p in self._op.params:
            if p.location != "cookie":
                continue
            if p.name in args and args[p.name] is not None:
                cookies[p.name] = str(args[p.name])

        # Auth
        auth_headers, auth_query = self._compute_auth(args, override_auth=override_auth)
        headers.update(auth_headers)
        if auth_query:
            for k, v in auth_query.items():
                query_items.append((k, str(v)))

        # Request body
        json_body: Any = None
        data_body: Optional[Dict[str, Any]] = None
        files_body: Optional[Dict[str, Any]] = None
        raw_body: Optional[bytes] = None
        opened_files: List[Any] = []

        # A consumer-friendly escape hatch:
        # - if user provides "body" (dict/anything), prefer it
        # - else if schema is object, allow inline fields
        explicit_body = args.get("body", None)

        # Remove internal keys
        def is_internal_key(k: str) -> bool:
            return isinstance(k, str) and k.startswith("__")

        try:
            mode = (self._op.body_mode.mode or "none").lower()
            if mode == "json" and self._op.body_schema is not None:
                if explicit_body is not None:
                    json_body = explicit_body
                elif self._op.body_schema.get("type") == "object" and isinstance(self._op.body_schema.get("properties"), dict):
                    props = self._op.body_schema.get("properties") or {}
                    json_body = {k: args.get(k) for k in props.keys() if k in args and not is_internal_key(k)}
                else:
                    json_body = None

                # Merge inline fields into explicit dict body (nice UX)
                if isinstance(json_body, dict) and self._op.body_schema.get("type") == "object":
                    props = (self._op.body_schema.get("properties") or {}) if isinstance(self._op.body_schema.get("properties"), dict) else {}
                    for k in props.keys():
                        if k in args and k not in json_body and not is_internal_key(k):
                            json_body[k] = args.get(k)

                if json_body is None and self._op.body_required:
                    return _make_toolresult_err("Missing required request body. Provide `body` or required inline fields.")

                if json_body is not None:
                    headers.setdefault("Content-Type", self._op.body_mode.content_type or "application/json")

            elif mode in ("form", "multipart") and self._op.body_schema is not None:
                fields: List[str] = []
                if isinstance(explicit_body, dict):
                    fields = list(explicit_body.keys())
                elif self._op.body_schema.get("type") == "object" and isinstance(self._op.body_schema.get("properties"), dict):
                    fields = list((self._op.body_schema.get("properties") or {}).keys())

                if mode == "form":
                    data_body = {}
                    if isinstance(explicit_body, dict):
                        for k, v in explicit_body.items():
                            if v is not None:
                                data_body[k] = v
                    for f in fields:
                        if f in args and args[f] is not None:
                            data_body[f] = args[f]
                    if (not data_body) and self._op.body_required:
                        return _make_toolresult_err("Missing required form body fields. Provide `body` dict or inline fields.")
                    if data_body:
                        headers.setdefault("Content-Type", self._op.body_mode.content_type or "application/x-www-form-urlencoded")

                if mode == "multipart":
                    data_body = {}
                    files_body = {}
                    if isinstance(explicit_body, dict):
                        for k, v in explicit_body.items():
                            if v is not None:
                                args.setdefault(k, v)
                    for f in fields:
                        if f not in args or args[f] is None:
                            continue
                        v = args[f]
                        if f in self._op.body_binary_fields:
                            file_tuple = _coerce_file_field(f, v, opened_files)
                            if file_tuple is None:
                                data_body[f] = str(v)
                            else:
                                files_body[f] = file_tuple
                        else:
                            data_body[f] = v
                    if (not data_body and not files_body) and self._op.body_required:
                        return _make_toolresult_err("Missing required multipart body fields. Provide `body` dict or inline fields.")

            elif mode == "raw":
                if explicit_body is not None:
                    b = explicit_body
                else:
                    b = args.get("body")
                if b is not None:
                    if isinstance(b, bytes):
                        raw_body = b
                    else:
                        raw_body = str(b).encode("utf-8")
                    if self._op.body_mode.content_type:
                        headers.setdefault("Content-Type", self._op.body_mode.content_type)
                elif self._op.body_required:
                    return _make_toolresult_err("Missing required raw request body. Provide `body`.")

            # Dry run is a huge win for consumer trust + debugging.
            if dry_run:
                redacted = _redact_headers(headers, extra_redact=[self._op.auth_hint.token_name] if self._op.auth_hint and self._op.auth_hint.token_name else None)
                body_preview: Any = None
                if json_body is not None:
                    body_preview = json_body
                elif raw_body is not None:
                    body_preview = {"raw_bytes_len": len(raw_body), "raw_preview": _cap_text(raw_body.decode("utf-8", errors="replace"), 400)}
                elif data_body is not None or files_body is not None:
                    body_preview = {"data": data_body or {}, "files": list((files_body or {}).keys())}
                return _make_toolresult_ok(
                    {
                        "dry_run": True,
                        "request": {
                            "method": method,
                            "url": url,
                            "query": query_items,
                            "headers": redacted,
                            "cookies": cookies,
                            "body": body_preview,
                        }
                    }
                )

            # HTTP request with retry/backoff
            opts = self._op.http_options
            timeout_seconds = float(override_timeout) if override_timeout is not None else opts.timeout_seconds
            timeout = httpx.Timeout(timeout_seconds, connect=opts.connect_timeout_seconds)

            last_exc: Optional[Exception] = None
            last_resp: Optional[httpx.Response] = None
            t0 = time.time()

            with httpx.Client(timeout=timeout, follow_redirects=opts.follow_redirects, verify=opts.verify_ssl) as client:
                for attempt in range(opts.retries + 1):
                    try:
                        last_resp = client.request(
                            method,
                            url,
                            params=query_items,
                            headers=headers,
                            cookies=cookies or None,
                            json=json_body if json_body is not None else None,
                            data=data_body if (json_body is None and raw_body is None and data_body is not None and files_body is None) else None,
                            files=files_body if files_body is not None else None,
                            content=raw_body if raw_body is not None else None,
                        )

                        # Retry on 429/5xx, respecting Retry-After when present
                        if last_resp.status_code == 429 or (500 <= last_resp.status_code <= 599):
                            if attempt < opts.retries:
                                ra = last_resp.headers.get("retry-after")
                                if ra and ra.isdigit():
                                    time.sleep(min(10.0, float(ra)))
                                else:
                                    _sleep_backoff(opts.backoff_seconds, attempt)
                                continue
                        break

                    except (httpx.TimeoutException, httpx.NetworkError) as e:
                        last_exc = e
                        if attempt < opts.retries:
                            _sleep_backoff(opts.backoff_seconds, attempt)
                            continue
                        break

            if last_resp is None:
                return _make_toolresult_err(f"HTTP request failed: {last_exc}")

            resp = last_resp
            elapsed_ms = int((time.time() - t0) * 1000)
            ct = (resp.headers.get("content-type") or "").lower()

            meta = {
                "status_code": resp.status_code,
                "url": url,
                "content_type": ct,
                "elapsed_ms": elapsed_ms,
            }

            if trace:
                meta["request"] = {
                    "method": method,
                    "query": query_items,
                    "headers": _redact_headers(headers, extra_redact=[self._op.auth_hint.token_name] if self._op.auth_hint and self._op.auth_hint.token_name else None),
                    "cookies": cookies,
                }

            if resp.status_code >= 400:
                text = _cap_text(resp.text, opts.max_text_chars)
                return _make_toolresult_err(f"HTTP {resp.status_code}: {text}", meta=meta)

            if resp.status_code == 204:
                return _make_toolresult_ok("", meta=meta)

            if any(h in ct for h in _JSON_CT_HINTS):
                try:
                    return _make_toolresult_ok(resp.json(), meta=meta)
                except Exception:
                    pass

            if ct.startswith("text/") or "charset=" in ct:
                return _make_toolresult_ok(_cap_text(resp.text, opts.max_text_chars), meta=meta)

            content = resp.content or b""
            is_truncated = len(content) > opts.max_binary_bytes
            content_cut = content[: opts.max_binary_bytes]
            b64 = base64.b64encode(content_cut).decode("ascii")
            return _make_toolresult_ok(
                {
                    "binary": True,
                    "content_type": ct or None,
                    "bytes_len": len(content),
                    "truncated": is_truncated,
                    "base64": b64,
                },
                meta=meta,
            )

        finally:
            for f in opened_files:
                try:
                    f.close()
                except Exception:
                    pass

    def _compute_auth(self, args: dict, override_auth: Any = None) -> Tuple[Dict[str, str], Dict[str, Any]]:
        auth_value = override_auth if override_auth is not None else self._op.auth_header

        # Allow satisfying apiKey(header) by passing the header param explicitly
        if self._op.auth_hint and self._op.auth_hint.scheme_type == "apiKey":
            if self._op.auth_hint.in_ == "header" and self._op.auth_hint.token_name:
                hn = self._op.auth_hint.token_name
                if hn in args and args[hn]:
                    return {hn: str(args[hn])}, {}
            if self._op.auth_hint.in_ == "cookie" and self._op.auth_hint.token_name:
                cn = self._op.auth_hint.token_name
                if cn in args and args[cn]:
                    # cookie API key: treat as header-less; cookie will be set by cookie params
                    return {}, {}

        if auth_value and isinstance(auth_value, str) and ":" in auth_value and not auth_value.strip().lower().startswith(("bearer ", "basic ")):
            # Explicit header format "Header: value"
            hname, hval = auth_value.split(":", 1)
            return {hname.strip(): hval.strip()}, {}

        if not auth_value:
            return {}, {}

        auth_value = str(auth_value).strip()
        hint = self._op.auth_hint

        if hint and hint.scheme_type == "apiKey":
            if hint.in_ == "header" and hint.token_name:
                return {hint.token_name: auth_value}, {}
            if hint.in_ == "query" and hint.token_name:
                return {}, {hint.token_name: auth_value}
            if hint.in_ == "cookie" and hint.token_name:
                # cookie apiKey: user should pass cookie param; but if they provide auth_header, also set it as cookie by query dict
                return {}, {}
            return {}, {}

        if hint and hint.scheme_type in ("http", "oauth2"):
            if hint.http_scheme and hint.http_scheme.lower() == "basic":
                if auth_value.lower().startswith("basic "):
                    return {"Authorization": auth_value}, {}
                b64 = base64.b64encode(auth_value.encode("utf-8")).decode("ascii")
                return {"Authorization": f"Basic {b64}"}, {}
            if auth_value.lower().startswith("bearer "):
                return {"Authorization": auth_value}, {}
            return {"Authorization": f"Bearer {auth_value}"}, {}

        return {"Authorization": auth_value}, {}


# -----------------------------
# Importer
# -----------------------------

class ApiImporter:
    """
    OpenAPI/Swagger spec importer that generates Tool instances per operation.

    Consumer-grade features:
      - optional "freeze spec" snapshot (so restart doesn't depend on external URL staying stable)
      - "dry_run" and "trace" support for every generated tool
      - per-call overrides: __auth, __base_url, __timeout_seconds
      - better query encoding (explode/deepObject and swagger2 collectionFormat)

    Persistence:
      - Stores metadata + tool names in project-root 'thomas_imported_apis.json'
      - DOES NOT store secrets. For restart-safe tokens use:
            THOMAS_API_AUTH_{API_NAME_UPPER}
    """
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or self._default_storage_path()
        self.api_name_hint: Optional[str] = None
        self.http_options: HttpOptions = HttpOptions()

        self._last_base_url: Optional[str] = None
        self._last_spec_hash: Optional[str] = None
        self._last_security_summary: Optional[dict] = None
        self._last_spec_snapshot: Optional[dict] = None  # gzip+base64 if freeze_spec

    @staticmethod
    def _default_storage_path() -> Path:
        here = Path(__file__).resolve()
        project_root = here.parents[3]
        return project_root / "thomas_imported_apis.json"

    def import_from_url(self, spec_url: str, base_url: str = None, auth_header: str = None, freeze_spec: bool = False) -> List[Tool]:
        raw = self._fetch_text(spec_url, auth_header=auth_header)
        spec = _parse_spec(raw)
        return self._generate_tools_from_spec(spec, spec_url=spec_url, base_url=base_url, auth_header=auth_header, raw_text=raw, freeze_spec=freeze_spec)

    def import_from_file(self, spec_path: str, base_url: str = None, auth_header: str = None, freeze_spec: bool = False) -> List[Tool]:
        p = Path(spec_path)
        raw = p.read_text(encoding="utf-8")
        spec = _parse_spec(raw)
        spec_url = "file://" + p.resolve().as_posix()
        return self._generate_tools_from_spec(spec, spec_url=spec_url, base_url=base_url, auth_header=auth_header, raw_text=raw, freeze_spec=freeze_spec)

    def register_all(self, tools: List[Tool], registry: Any) -> None:
        for t in tools:
            registry.register(t)

    def save_imported_api(self, name: str, spec_url: str, tools: List[Tool]) -> None:
        data = self._read_storage()
        tool_names = [self._tool_name(t) for t in tools]
        now = datetime.now(timezone.utc).isoformat()

        entry = data.get(name) or {}
        entry.update(
            {
                "name": name,
                "spec_url": spec_url,
                "base_url": self._last_base_url,
                "spec_hash": self._last_spec_hash,
                "spec_snapshot": self._last_spec_snapshot,  # optional
                "security": self._last_security_summary,
                "http_options": {
                    "timeout_seconds": self.http_options.timeout_seconds,
                    "connect_timeout_seconds": self.http_options.connect_timeout_seconds,
                    "retries": self.http_options.retries,
                    "backoff_seconds": self.http_options.backoff_seconds,
                    "verify_ssl": self.http_options.verify_ssl,
                    "follow_redirects": self.http_options.follow_redirects,
                },
                "tool_names": tool_names,
                "tool_count": len(tool_names),
                "updated_at": now,
            }
        )
        if "created_at" not in entry:
            entry["created_at"] = now
        data[name] = entry
        self._write_storage(data)

    def list_saved(self) -> Dict[str, dict]:
        return self._read_storage()

    def remove_saved(self, name: str) -> dict:
        data = self._read_storage()
        removed = data.pop(name, None)
        self._write_storage(data)
        return removed or {}

    def reload_saved(self, registry: Any) -> List[str]:
        saved = self._read_storage()
        registered: List[str] = []
        for api_name, meta in saved.items():
            spec_url = meta.get("spec_url")
            if not spec_url:
                continue
            base_url = meta.get("base_url")
            auth = self._env_auth_for(api_name)

            ho = meta.get("http_options") or {}
            self.http_options = HttpOptions(
                timeout_seconds=float(ho.get("timeout_seconds", self.http_options.timeout_seconds)),
                connect_timeout_seconds=float(ho.get("connect_timeout_seconds", self.http_options.connect_timeout_seconds)),
                retries=int(ho.get("retries", self.http_options.retries)),
                backoff_seconds=float(ho.get("backoff_seconds", self.http_options.backoff_seconds)),
                verify_ssl=bool(ho.get("verify_ssl", self.http_options.verify_ssl)),
                follow_redirects=bool(ho.get("follow_redirects", self.http_options.follow_redirects)),
                max_text_chars=self.http_options.max_text_chars,
                max_binary_bytes=self.http_options.max_binary_bytes,
            )

            self.api_name_hint = api_name

            snapshot = meta.get("spec_snapshot")
            if snapshot and isinstance(snapshot, dict) and snapshot.get("format") == "gzip_base64":
                raw = self._decode_snapshot(snapshot)
                spec = _parse_spec(raw)
                tools = self._generate_tools_from_spec(spec, spec_url=spec_url, base_url=base_url, auth_header=auth, raw_text=raw, freeze_spec=True)
            else:
                tools = self.import_from_url(spec_url, base_url=base_url, auth_header=auth, freeze_spec=False)

            self.register_all(tools, registry)
            self.save_imported_api(api_name, spec_url, tools)
            registered.extend([self._tool_name(t) for t in tools])

        return registered

    # -----------------------------
    # Internals
    # -----------------------------

    def _env_auth_for(self, api_name: str) -> Optional[str]:
        key = f"THOMAS_API_AUTH_{_slugify(api_name).upper()}"
        return os.environ.get(key)

    def _fetch_text(self, url: str, auth_header: Optional[str] = None) -> str:
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("spec_url must be http(s). For local files, use import_from_file().")

        headers: Dict[str, str] = {}
        if auth_header:
            if ":" in auth_header:
                hname, hval = auth_header.split(":", 1)
                headers[hname.strip()] = hval.strip()
            else:
                headers["Authorization"] = auth_header.strip()

        timeout = httpx.Timeout(self.http_options.timeout_seconds, connect=self.http_options.connect_timeout_seconds)
        with httpx.Client(timeout=timeout, follow_redirects=True, verify=self.http_options.verify_ssl) as client:
            resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text

    def _encode_snapshot(self, raw_text: str) -> Optional[dict]:
        try:
            gz = gzip.compress(raw_text.encode("utf-8"))
            b64 = base64.b64encode(gz).decode("ascii")
            size = len(b64.encode("utf-8"))
            if size > _MAX_SNAPSHOT_BYTES:
                return None
            return {
                "format": "gzip_base64",
                "bytes": size,
                "sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "data": b64,
            }
        except Exception:
            return None

    def _decode_snapshot(self, snap: dict) -> str:
        b64 = snap.get("data")
        if not isinstance(b64, str):
            raise ValueError("Invalid spec_snapshot payload")
        gz = base64.b64decode(b64.encode("ascii"))
        raw = gzip.decompress(gz).decode("utf-8", errors="replace")
        return raw

    def _extract_security(self, spec: dict) -> Tuple[Dict[str, dict], List[dict]]:
        schemes: Dict[str, dict] = {}
        if "openapi" in spec:
            schemes = (spec.get("components") or {}).get("securitySchemes") or {}
        elif spec.get("swagger") == "2.0":
            schemes = spec.get("securityDefinitions") or {}
        if not isinstance(schemes, dict):
            schemes = {}
        global_security = spec.get("security") or []
        if not isinstance(global_security, list):
            global_security = []
        return schemes, global_security

    def _pick_auth_hint(self, security_reqs: List[dict], schemes_map: Dict[str, dict]) -> Tuple[Optional[AuthSchemeHint], bool]:
        # [] explicitly means "no auth required"
        if security_reqs == []:
            return None, False
        if not security_reqs:
            return None, False

        for req in security_reqs:
            if not isinstance(req, dict) or not req:
                continue
            scheme_name = next(iter(req.keys()))
            scheme = schemes_map.get(scheme_name) if isinstance(schemes_map, dict) else None
            if not isinstance(scheme, dict):
                return AuthSchemeHint(scheme_name, None, None, None, None, None), True

            scheme_type = scheme.get("type")
            in_ = scheme.get("in")
            token_name = scheme.get("name")
            http_scheme = scheme.get("scheme")
            desc = scheme.get("description")

            if scheme_type == "oauth2":
                return AuthSchemeHint(scheme_name, "oauth2", None, None, "bearer", desc), True
            if scheme_type == "http":
                return AuthSchemeHint(scheme_name, "http", None, None, http_scheme, desc), True
            if scheme_type == "apiKey":
                return AuthSchemeHint(scheme_name, "apiKey", in_, token_name, None, desc), True
            if str(scheme_type).lower() == "basic":
                return AuthSchemeHint(scheme_name, "http", None, None, "basic", desc), True

            return AuthSchemeHint(scheme_name, str(scheme_type), in_, token_name, http_scheme, desc), True

        return None, False

    def _choose_body_mode_openapi3(self, op: dict, spec: dict, base_doc_url: str, fetcher: _ExternalRefFetcher) -> Tuple[BodyMode, Optional[dict], bool]:
        request_body = op.get("requestBody")
        if not isinstance(request_body, dict):
            return BodyMode(None, None), None, False

        request_body = _deref_schema(request_body, spec, base_doc_url, fetcher)
        required = bool(request_body.get("required", False))

        content = request_body.get("content") or {}
        if not isinstance(content, dict) or not content:
            return BodyMode(None, None), None, required

        ordered_cts = list(content.keys())

        chosen_ct = None
        if "application/json" in content:
            chosen_ct = "application/json"
        else:
            chosen_ct = next((ct for ct in ordered_cts if any(h in ct for h in _JSON_CT_HINTS)), None)
        if not chosen_ct:
            chosen_ct = next((ct for ct in ordered_cts if ct in _FORM_CT_HINTS), None)
        if not chosen_ct:
            chosen_ct = next((ct for ct in ordered_cts if ct in _MULTIPART_CT_HINTS), None)
        if not chosen_ct:
            chosen_ct = ordered_cts[0]

        chosen = content.get(chosen_ct)
        if not isinstance(chosen, dict):
            return BodyMode(None, None), None, required

        schema = chosen.get("schema")
        if not isinstance(schema, dict):
            return BodyMode(None, None), None, required

        if any(h in chosen_ct for h in _JSON_CT_HINTS) or chosen_ct == "application/json":
            mode = "json"
        elif chosen_ct in _FORM_CT_HINTS:
            mode = "form"
        elif chosen_ct in _MULTIPART_CT_HINTS:
            mode = "multipart"
        else:
            mode = "raw"

        return BodyMode(mode=mode, content_type=chosen_ct), schema, required

    def _generate_tools_from_spec(
        self,
        spec: dict,
        spec_url: Optional[str],
        base_url: Optional[str],
        auth_header: Optional[str],
        raw_text: Optional[str],
        freeze_spec: bool,
    ) -> List[Tool]:
        hinted = _slugify(self.api_name_hint) if self.api_name_hint else None
        title = (spec.get("info") or {}).get("title") or "api"
        inferred = _slugify(str(title))
        api_name = hinted or inferred

        resolved_base = (base_url or _get_default_server_url(spec) or "").strip()
        self._last_base_url = resolved_base or None

        self._last_spec_hash = None
        if raw_text:
            self._last_spec_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        self._last_spec_snapshot = None
        if freeze_spec and raw_text:
            self._last_spec_snapshot = self._encode_snapshot(raw_text)

        schemes_map, global_security = self._extract_security(spec)
        self._last_security_summary = {
            "has_global_security": bool(global_security),
            "schemes": sorted(list(schemes_map.keys())) if isinstance(schemes_map, dict) else [],
        }

        fetcher = _ExternalRefFetcher(
            verify_ssl=self.http_options.verify_ssl,
            timeout_seconds=self.http_options.timeout_seconds,
        )

        tools: List[Tool] = []
        used_tool_names: set[str] = set()

        paths = spec.get("paths") or {}
        if not isinstance(paths, dict):
            return tools

        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue

            path_level_params = methods.get("parameters") if isinstance(methods.get("parameters"), list) else []

            for method, op in methods.items():
                m = str(method).lower()
                if m not in _HTTP_METHODS:
                    continue
                if not isinstance(op, dict):
                    continue

                # Operation-level servers override
                op_base = resolved_base
                if "openapi" in spec and isinstance(op.get("servers"), list) and op["servers"]:
                    u = _expand_server_url(op["servers"][0] or {})
                    if u:
                        op_base = u

                operation_id = op.get("operationId") or _op_fallback_id(m, path)
                suffix = _slugify(operation_id)
                tool_name = f"api.{api_name}.{suffix}"
                if tool_name in used_tool_names:
                    tool_name = f"{tool_name}_{_short_hash(m + ' ' + path)}"
                used_tool_names.add(tool_name)

                summary = op.get("summary") or op.get("description") or f"{m.upper()} {path}"
                description = str(summary).strip()
                description = f"{description}\n\n[HTTP] {m.upper()} {path}\n\nExtras: __dry_run, __trace, __auth, __base_url, __timeout_seconds"

                combined_params: List[dict] = []
                if isinstance(path_level_params, list):
                    combined_params.extend([p for p in path_level_params if isinstance(p, dict)])
                if isinstance(op.get("parameters"), list):
                    combined_params.extend([p for p in op["parameters"] if isinstance(p, dict)])

                base_doc_url = spec_url or None
                combined_params = [_deref_schema(p, spec, base_doc_url, fetcher) for p in combined_params]

                swagger_body_schema: Optional[dict] = None
                swagger_consumes: Optional[str] = None
                swagger_form_fields: List[dict] = []
                swagger_produces: Optional[str] = None
                if spec.get("swagger") == "2.0":
                    consumes = op.get("consumes") or spec.get("consumes") or []
                    if isinstance(consumes, list) and consumes:
                        swagger_consumes = consumes[0]
                    produces = op.get("produces") or spec.get("produces") or []
                    if isinstance(produces, list) and produces:
                        swagger_produces = produces[0]
                    for p in combined_params:
                        if p.get("in") == "body" and isinstance(p.get("schema"), dict):
                            swagger_body_schema = _deref_schema(p["schema"], spec, base_doc_url, fetcher)
                        if p.get("in") == "formData":
                            swagger_form_fields.append(p)

                params: List[ParamSpec] = []
                args_schema: dict = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

                def add_param(ps: ParamSpec, schema_hint: Optional[dict], desc: str) -> None:
                    params.append(ps)
                    prop: dict = {}
                    if isinstance(schema_hint, dict):
                        prop.update(schema_hint)
                    if desc:
                        prop["description"] = desc
                    args_schema["properties"][ps.name] = prop
                    if ps.required and ps.name not in args_schema["required"]:
                        args_schema["required"].append(ps.name)

                # Add parameters
                for p in combined_params + swagger_form_fields:
                    name = p.get("name")
                    loc = p.get("in")
                    if not name or loc not in ("path", "query", "header", "cookie", "formData"):
                        continue

                    required = bool(p.get("required", False))
                    style = p.get("style")
                    explode = p.get("explode")
                    allow_reserved = p.get("allowReserved")
                    collection_format = p.get("collectionFormat")  # swagger2

                    schema = p.get("schema")
                    if schema is None:
                        if spec.get("swagger") == "2.0":
                            schema = {k: v for k, v in p.items() if k in ("type", "format", "items", "enum", "default", "minimum", "maximum")}
                        else:
                            schema = {}

                    schema = _deref_schema(schema, spec, base_doc_url, fetcher) if isinstance(schema, (dict, list)) else schema
                    desc = p.get("description") or ""

                    if loc == "formData":
                        loc = "query"  # treat as body encoding below; schema still added to args_schema via body merge

                    add_param(
                        ParamSpec(
                            name=str(name),
                            location=str(loc),
                            required=required,
                            style=str(style) if style is not None else None,
                            explode=bool(explode) if explode is not None else None,
                            allow_reserved=bool(allow_reserved) if allow_reserved is not None else None,
                            collection_format=str(collection_format) if collection_format is not None else None,
                            schema=schema if isinstance(schema, dict) else None,
                        ),
                        schema if isinstance(schema, dict) else None,
                        desc,
                    )

                # Body parsing
                body_schema: Optional[dict] = None
                body_mode = BodyMode(None, None)
                body_binary_fields: List[str] = []
                body_required = False

                if "openapi" in spec:
                    bm, schema, req = self._choose_body_mode_openapi3(op, spec, base_doc_url, fetcher)
                    body_required = req
                    if schema is not None:
                        schema = _deref_schema(schema, spec, base_doc_url, fetcher)
                        if isinstance(schema, dict):
                            body_schema = schema
                            body_mode = bm
                            if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
                                for k, v in (schema.get("properties") or {}).items():
                                    if isinstance(v, dict) and str(v.get("format", "")).lower() == "binary":
                                        body_binary_fields.append(k)
                                body_obj = {"type": "object", "properties": schema.get("properties") or {}, "required": schema.get("required") or [], "additionalProperties": schema.get("additionalProperties", False)}
                                args_schema = _merge_object_schemas(args_schema, body_obj)
                            else:
                                args_schema["properties"]["body"] = schema
                                if body_required:
                                    args_schema["required"].append("body")

                if spec.get("swagger") == "2.0":
                    if swagger_body_schema is not None:
                        body_schema = swagger_body_schema
                        body_required = True  # swagger2 body param required indicates required; we approximate
                        if swagger_consumes in _FORM_CT_HINTS:
                            body_mode = BodyMode("form", swagger_consumes)
                        elif swagger_consumes in _MULTIPART_CT_HINTS:
                            body_mode = BodyMode("multipart", swagger_consumes)
                        else:
                            body_mode = BodyMode("json", swagger_consumes or "application/json")
                        if swagger_body_schema.get("type") == "object" and isinstance(swagger_body_schema.get("properties"), dict):
                            body_obj = {"type": "object", "properties": swagger_body_schema.get("properties") or {}, "required": swagger_body_schema.get("required") or [], "additionalProperties": swagger_body_schema.get("additionalProperties", False)}
                            args_schema = _merge_object_schemas(args_schema, body_obj)
                        else:
                            args_schema["properties"]["body"] = swagger_body_schema
                            args_schema["required"].append("body")

                    if swagger_form_fields:
                        has_file = any(p.get("type") == "file" for p in swagger_form_fields)
                        if swagger_consumes in _MULTIPART_CT_HINTS or has_file:
                            body_mode = BodyMode("multipart", swagger_consumes or "multipart/form-data")
                            for p in swagger_form_fields:
                                if p.get("type") == "file":
                                    body_binary_fields.append(p.get("name"))
                        else:
                            body_mode = BodyMode("form", swagger_consumes or "application/x-www-form-urlencoded")
                        props = {}
                        req = []
                        for p in swagger_form_fields:
                            n = p.get("name")
                            if not n:
                                continue
                            if p.get("type") == "file":
                                props[n] = {"type": "string", "format": "binary"}
                            else:
                                props[n] = {k: v for k, v in p.items() if k in ("type", "format", "items", "enum", "default", "minimum", "maximum")}
                            if p.get("required") is True:
                                req.append(n)
                        body_schema = {"type": "object", "properties": props, "required": req, "additionalProperties": False}
                        body_required = bool(req)

                # Security hint
                op_security = op.get("security")
                security_reqs = global_security
                if isinstance(op_security, list):
                    security_reqs = op_security
                auth_hint, security_required = self._pick_auth_hint(security_reqs, schemes_map)

                accept_header = None
                if spec.get("swagger") == "2.0" and swagger_produces:
                    accept_header = swagger_produces

                # Add consumer-loved internal args to schema so strict validators won't reject them
                args_schema["properties"].update(
                    {
                        "__dry_run": {"type": "boolean", "description": "If true, returns the constructed HTTP request without sending it."},
                        "__trace": {"type": "boolean", "description": "If true, returns redacted request metadata in ToolResult.meta."},
                        "__auth": {"type": "string", "description": "Per-call auth override (token or 'Header: value')."},
                        "__base_url": {"type": "string", "description": "Per-call base URL override."},
                        "__timeout_seconds": {"type": "number", "description": "Per-call total timeout override."},
                    }
                )

                args_schema["required"] = sorted(set(args_schema.get("required") or []))

                spec_obj = _make_toolspec(tool_name, description, args_schema)

                op_def = OpenApiOperation(
                    api_name=api_name,
                    tool_name=tool_name,
                    method=m,
                    path=path,
                    base_url=op_base,
                    auth_header=auth_header or self._env_auth_for(api_name),
                    params=params,
                    body_schema=body_schema,
                    body_mode=body_mode,
                    body_binary_fields=[x for x in body_binary_fields if x],
                    body_required=body_required,
                    auth_hint=auth_hint,
                    security_required=security_required,
                    http_options=self.http_options,
                    accept_header=accept_header,
                )

                tools.append(self._make_tool(spec_obj, op_def))

        self.api_name_hint = None
        return tools

    def _make_tool(self, spec_obj: ToolSpec, op_def: OpenApiOperation) -> Tool:
        def handler(args: dict) -> ToolResult:
            return OpenApiHttpTool(spec_obj, op_def).execute(args)

        if _FACTORY_AVAILABLE and get_tool_factory is not None:
            try:
                factory = get_tool_factory()
                for meth_name in ("create_generated_tool", "make_generated_tool", "build_generated_tool", "create", "make", "build"):
                    if hasattr(factory, meth_name):
                        meth = getattr(factory, meth_name)
                        for kwargs in (
                            {"spec": spec_obj, "handler": handler},
                            {"tool_spec": spec_obj, "handler": handler},
                            {"name": getattr(spec_obj, "name", None), "spec": spec_obj, "handler": handler},
                        ):
                            try:
                                t = meth(**{k: v for k, v in kwargs.items() if v is not None})
                                if isinstance(t, Tool):
                                    return t
                            except Exception:
                                pass
                try:
                    from thomas.core.tool_factory import GeneratedTool  # type: ignore
                    for kwargs in (
                        {"spec": spec_obj, "handler": handler},
                        {"tool_spec": spec_obj, "handler": handler},
                        {"name": getattr(spec_obj, "name", None), "spec": spec_obj, "handler": handler},
                    ):
                        try:
                            t = GeneratedTool(**{k: v for k, v in kwargs.items() if v is not None})  # type: ignore
                            if isinstance(t, Tool):
                                return t
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                pass

        return OpenApiHttpTool(spec_obj, op_def)

    def _tool_name(self, tool: Tool) -> str:
        s = getattr(tool, "spec", None)
        if callable(s):
            s = s()
        if s is None:
            return getattr(tool, "name", "unknown")
        return getattr(s, "name", getattr(s, "tool_name", "unknown"))

    def _read_storage(self) -> Dict[str, dict]:
        p = self.storage_path
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            backup = p.with_suffix(".json.bak")
            try:
                backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
            return {}

    def _write_storage(self, data: Dict[str, dict]) -> None:
        p = self.storage_path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
