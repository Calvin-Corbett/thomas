"""HTTP tool execution runtime for generated OpenAPI operations."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import time
from typing import Any
from urllib.parse import quote, urljoin

import httpx

# TODO(arch): This import violates the core→tools dependency rule
# (agent_safety.toml [circular_imports]).  OpenApiHttpTool subclasses Tool,
# so the import cannot be trivially deferred.  The correct fix is to relocate
# this module to thomas/tools/ where it architecturally belongs.
from thomas.tools.base import Tool, ToolResult, ToolSpec

from .api_importer import (
    _DEFAULT_ACCEPT,
    _JSON_CT_HINTS,
    _REDACT_HEADERS,
    OpenApiOperation,
    ParamSpec,
    _make_toolresult_err,
    _make_toolresult_ok,
)


def _redact_headers(headers: dict[str, str], extra_redact: list[str] | None = None) -> dict[str, str]:
    redact = set(_REDACT_HEADERS)
    if extra_redact:
        redact |= {h.lower() for h in extra_redact}
    out: dict[str, str] = {}
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
    delay = min(6.0, base * (2**attempt))
    time.sleep(delay)


def _coerce_query_value(v: Any) -> Any:
    if isinstance(v, dict):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    return v


def _encode_query_param_oas3(p: ParamSpec, value: Any) -> list[tuple[str, str]]:
    """
    Implements a practical subset of OAS3 query encoding:
      - arrays: explode -> repeated, else comma-joined
      - objects: deepObject -> name[key]=v, explode -> key=v, else name=key,v,key,v
    """
    style = p.style or "form"
    explode = p.explode if p.explode is not None else True  # default explode=true for query in OAS3
    items: list[tuple[str, str]] = []

    if value is None:
        return items

    if isinstance(value, list | tuple):
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

        flat: list[str] = []
        for k, v in value.items():
            flat.append(str(k))
            flat.append(str(v))
        items.append((p.name, ",".join(flat)))
        return items

    items.append((p.name, str(_coerce_query_value(value))))
    return items


def _encode_query_param_swagger2(p: ParamSpec, value: Any) -> list[tuple[str, str]]:
    fmt = (p.collection_format or "csv").lower()
    items: list[tuple[str, str]] = []
    if value is None:
        return items
    if isinstance(value, list | tuple):
        if fmt == "multi":
            for x in value:
                items.append((p.name, str(x)))
        else:
            sep = {"csv": ",", "ssv": " ", "tsv": "\t", "pipes": "|"}.get(fmt, ",")
            items.append((p.name, sep.join(str(x) for x in value)))
        return items
    if isinstance(value, dict):
        # swagger2 doesn't define deep object; JSON-string it as pragmatic default
        items.append((p.name, json.dumps(value, separators=(",", ":"), ensure_ascii=False)))
        return items
    items.append((p.name, str(value)))
    return items


def _coerce_file_field(field_name: str, value: Any, opened_files: list[Any]) -> tuple[str, Any, str] | None:
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
    elif isinstance(value, tuple | list):
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

    f = open(path, "rb")  # noqa: SIM115 - lifecycle is managed by opened_files/finally
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
            return _make_toolresult_err(
                "No base_url configured. Provide servers[0].url or pass base_url during import."
            )

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
        query_items: list[tuple[str, str]] = []
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
        headers: dict[str, str] = {}
        headers["Accept"] = self._op.accept_header or _DEFAULT_ACCEPT

        for p in self._op.params:
            if p.location != "header":
                continue
            if p.name in args and args[p.name] is not None:
                headers[p.name] = str(args[p.name])

        # Cookies
        cookies: dict[str, str] = {}
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
        data_body: dict[str, Any] | None = None
        files_body: dict[str, Any] | None = None
        raw_body: bytes | None = None
        opened_files: list[Any] = []

        # A consumer-friendly escape hatch:
        # - if user provides "body" (dict/anything), prefer it
        # - else if schema is object, allow inline fields
        explicit_body = args.get("body")

        # Remove internal keys
        def is_internal_key(k: str) -> bool:
            return isinstance(k, str) and k.startswith("__")

        try:
            mode = (self._op.body_mode.mode or "none").lower()
            if mode == "json" and self._op.body_schema is not None:
                if explicit_body is not None:
                    json_body = explicit_body
                elif self._op.body_schema.get("type") == "object" and isinstance(
                    self._op.body_schema.get("properties"), dict
                ):
                    props = self._op.body_schema.get("properties") or {}
                    json_body = {k: args.get(k) for k in props if k in args and not is_internal_key(k)}
                else:
                    json_body = None

                # Merge inline fields into explicit dict body (nice UX)
                if isinstance(json_body, dict) and self._op.body_schema.get("type") == "object":
                    props = (
                        (self._op.body_schema.get("properties") or {})
                        if isinstance(self._op.body_schema.get("properties"), dict)
                        else {}
                    )
                    for k in props:
                        if k in args and k not in json_body and not is_internal_key(k):
                            json_body[k] = args.get(k)

                if json_body is None and self._op.body_required:
                    return _make_toolresult_err(
                        "Missing required request body. Provide `body` or required inline fields."
                    )

                if json_body is not None:
                    headers.setdefault("Content-Type", self._op.body_mode.content_type or "application/json")

            elif mode in ("form", "multipart") and self._op.body_schema is not None:
                fields: list[str] = []
                if isinstance(explicit_body, dict):
                    fields = list(explicit_body.keys())
                elif self._op.body_schema.get("type") == "object" and isinstance(
                    self._op.body_schema.get("properties"), dict
                ):
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
                        return _make_toolresult_err(
                            "Missing required form body fields. Provide `body` dict or inline fields."
                        )
                    if data_body:
                        headers.setdefault(
                            "Content-Type", self._op.body_mode.content_type or "application/x-www-form-urlencoded"
                        )

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
                        return _make_toolresult_err(
                            "Missing required multipart body fields. Provide `body` dict or inline fields."
                        )

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
                redacted = _redact_headers(
                    headers,
                    extra_redact=[self._op.auth_hint.token_name]
                    if self._op.auth_hint and self._op.auth_hint.token_name
                    else None,
                )
                body_preview: Any = None
                if json_body is not None:
                    body_preview = json_body
                elif raw_body is not None:
                    body_preview = {
                        "raw_bytes_len": len(raw_body),
                        "raw_preview": _cap_text(raw_body.decode("utf-8", errors="replace"), 400),
                    }
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
                        },
                    }
                )

            # HTTP request with retry/backoff
            opts = self._op.http_options
            timeout_seconds = float(override_timeout) if override_timeout is not None else opts.timeout_seconds
            timeout = httpx.Timeout(timeout_seconds, connect=opts.connect_timeout_seconds)

            last_exc: Exception | None = None
            last_resp: httpx.Response | None = None
            t0 = time.time()

            with httpx.Client(
                timeout=timeout, follow_redirects=opts.follow_redirects, verify=opts.verify_ssl
            ) as client:
                for attempt in range(opts.retries + 1):
                    try:
                        last_resp = client.request(
                            method,
                            url,
                            params=query_items,
                            headers=headers,
                            cookies=cookies or None,
                            json=json_body if json_body is not None else None,
                            data=data_body
                            if (json_body is None and raw_body is None and data_body is not None and files_body is None)
                            else None,
                            files=files_body if files_body is not None else None,
                            content=raw_body if raw_body is not None else None,
                        )

                        # Retry on 429/5xx, respecting Retry-After when present
                        if (last_resp.status_code == 429 or 500 <= last_resp.status_code <= 599) and (
                            attempt < opts.retries
                        ):
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
                    "headers": _redact_headers(
                        headers,
                        extra_redact=[self._op.auth_hint.token_name]
                        if self._op.auth_hint and self._op.auth_hint.token_name
                        else None,
                    ),
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
                with contextlib.suppress(Exception):
                    f.close()

    def _compute_auth(self, args: dict, override_auth: Any = None) -> tuple[dict[str, str], dict[str, Any]]:
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

        if (
            auth_value
            and isinstance(auth_value, str)
            and ":" in auth_value
            and not auth_value.strip().lower().startswith(("bearer ", "basic "))
        ):
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
