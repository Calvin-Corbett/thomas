"""Importer class that generates Tool instances from API specs."""

from __future__ import annotations

import base64
import contextlib
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# TODO(arch): This import violates the core→tools dependency rule
# (agent_safety.toml [circular_imports]).  Used for isinstance() checks and
# type annotations.  The correct fix is to relocate the api_importer family
# to thomas/tools/ where it architecturally belongs.
from thomas.tools.base import Tool, ToolResult, ToolSpec

from .api_importer import (
    _FACTORY_AVAILABLE,
    _FORM_CT_HINTS,
    _HTTP_METHODS,
    _JSON_CT_HINTS,
    _MAX_SNAPSHOT_BYTES,
    _MULTIPART_CT_HINTS,
    AuthSchemeHint,
    BodyMode,
    HttpOptions,
    OpenApiOperation,
    ParamSpec,
    _deref_schema,
    _expand_server_url,
    _ExternalRefFetcher,
    _get_default_server_url,
    _make_toolspec,
    _merge_object_schemas,
    _op_fallback_id,
    _parse_spec,
    _short_hash,
    _slugify,
    get_tool_factory,
)
from .api_importer_http_tool import OpenApiHttpTool


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

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or self._default_storage_path()
        self.api_name_hint: str | None = None
        self.http_options: HttpOptions = HttpOptions()

        self._last_base_url: str | None = None
        self._last_spec_hash: str | None = None
        self._last_security_summary: dict | None = None
        self._last_spec_snapshot: dict | None = None  # gzip+base64 if freeze_spec

    @staticmethod
    def _default_storage_path() -> Path:
        here = Path(__file__).resolve()
        project_root = here.parents[3]
        return project_root / "thomas_imported_apis.json"

    def import_from_url(
        self, spec_url: str, base_url: str = None, auth_header: str = None, freeze_spec: bool = False
    ) -> list[Tool]:
        raw = self._fetch_text(spec_url, auth_header=auth_header)
        spec = _parse_spec(raw)
        return self._generate_tools_from_spec(
            spec, spec_url=spec_url, base_url=base_url, auth_header=auth_header, raw_text=raw, freeze_spec=freeze_spec
        )

    def import_from_file(
        self, spec_path: str, base_url: str = None, auth_header: str = None, freeze_spec: bool = False
    ) -> list[Tool]:
        p = Path(spec_path)
        raw = p.read_text(encoding="utf-8")
        spec = _parse_spec(raw)
        spec_url = "file://" + p.resolve().as_posix()
        return self._generate_tools_from_spec(
            spec, spec_url=spec_url, base_url=base_url, auth_header=auth_header, raw_text=raw, freeze_spec=freeze_spec
        )

    def register_all(self, tools: list[Tool], registry: Any) -> None:
        for t in tools:
            registry.register(t)

    def save_imported_api(self, name: str, spec_url: str, tools: list[Tool]) -> None:
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

    def list_saved(self) -> dict[str, dict]:
        return self._read_storage()

    def remove_saved(self, name: str) -> dict:
        data = self._read_storage()
        removed = data.pop(name, None)
        self._write_storage(data)
        return removed or {}

    def reload_saved(self, registry: Any) -> list[str]:
        saved = self._read_storage()
        registered: list[str] = []
        for api_name, meta in saved.items():
            spec_url = meta.get("spec_url")
            if not spec_url:
                continue
            base_url = meta.get("base_url")
            auth = self._env_auth_for(api_name)

            ho = meta.get("http_options") or {}
            self.http_options = HttpOptions(
                timeout_seconds=float(ho.get("timeout_seconds", self.http_options.timeout_seconds)),
                connect_timeout_seconds=float(
                    ho.get("connect_timeout_seconds", self.http_options.connect_timeout_seconds)
                ),
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
                tools = self._generate_tools_from_spec(
                    spec, spec_url=spec_url, base_url=base_url, auth_header=auth, raw_text=raw, freeze_spec=True
                )
            else:
                tools = self.import_from_url(spec_url, base_url=base_url, auth_header=auth, freeze_spec=False)

            self.register_all(tools, registry)
            self.save_imported_api(api_name, spec_url, tools)
            registered.extend([self._tool_name(t) for t in tools])

        return registered

    # -----------------------------
    # Internals
    # -----------------------------

    def _env_auth_for(self, api_name: str) -> str | None:
        key = f"THOMAS_API_AUTH_{_slugify(api_name).upper()}"
        return os.environ.get(key)

    def _fetch_text(self, url: str, auth_header: str | None = None) -> str:
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("spec_url must be http(s). For local files, use import_from_file().")

        headers: dict[str, str] = {}
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

    def _encode_snapshot(self, raw_text: str) -> dict | None:
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

    def _extract_security(self, spec: dict) -> tuple[dict[str, dict], list[dict]]:
        schemes: dict[str, dict] = {}
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

    def _pick_auth_hint(
        self, security_reqs: list[dict], schemes_map: dict[str, dict]
    ) -> tuple[AuthSchemeHint | None, bool]:
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

    def _choose_body_mode_openapi3(
        self, op: dict, spec: dict, base_doc_url: str, fetcher: _ExternalRefFetcher
    ) -> tuple[BodyMode, dict | None, bool]:
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
        spec_url: str | None,
        base_url: str | None,
        auth_header: str | None,
        raw_text: str | None,
        freeze_spec: bool,
    ) -> list[Tool]:
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

        tools: list[Tool] = []
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

                combined_params: list[dict] = []
                if isinstance(path_level_params, list):
                    combined_params.extend([p for p in path_level_params if isinstance(p, dict)])
                if isinstance(op.get("parameters"), list):
                    combined_params.extend([p for p in op["parameters"] if isinstance(p, dict)])

                base_doc_url = spec_url or None
                combined_params = [_deref_schema(p, spec, base_doc_url, fetcher) for p in combined_params]

                swagger_body_schema: dict | None = None
                swagger_consumes: str | None = None
                swagger_form_fields: list[dict] = []
                swagger_produces: str | None = None
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

                params: list[ParamSpec] = []
                args_schema: dict = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

                def add_param(
                    ps: ParamSpec,
                    schema_hint: dict | None,
                    desc: str,
                    *,
                    _params: list[ParamSpec] = params,
                    _args_schema: dict = args_schema,
                ) -> None:
                    _params.append(ps)
                    prop: dict = {}
                    if isinstance(schema_hint, dict):
                        prop.update(schema_hint)
                    if desc:
                        prop["description"] = desc
                    _args_schema["properties"][ps.name] = prop
                    if ps.required and ps.name not in _args_schema["required"]:
                        _args_schema["required"].append(ps.name)

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
                            schema = {
                                k: v
                                for k, v in p.items()
                                if k in ("type", "format", "items", "enum", "default", "minimum", "maximum")
                            }
                        else:
                            schema = {}

                    schema = (
                        _deref_schema(schema, spec, base_doc_url, fetcher)
                        if isinstance(schema, dict | list)
                        else schema
                    )
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
                body_schema: dict | None = None
                body_mode = BodyMode(None, None)
                body_binary_fields: list[str] = []
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
                                body_obj = {
                                    "type": "object",
                                    "properties": schema.get("properties") or {},
                                    "required": schema.get("required") or [],
                                    "additionalProperties": schema.get("additionalProperties", False),
                                }
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
                        if swagger_body_schema.get("type") == "object" and isinstance(
                            swagger_body_schema.get("properties"), dict
                        ):
                            body_obj = {
                                "type": "object",
                                "properties": swagger_body_schema.get("properties") or {},
                                "required": swagger_body_schema.get("required") or [],
                                "additionalProperties": swagger_body_schema.get("additionalProperties", False),
                            }
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
                                props[n] = {
                                    k: v
                                    for k, v in p.items()
                                    if k in ("type", "format", "items", "enum", "default", "minimum", "maximum")
                                }
                            if p.get("required") is True:
                                req.append(n)
                        body_schema = {
                            "type": "object",
                            "properties": props,
                            "required": req,
                            "additionalProperties": False,
                        }
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
                        "__dry_run": {
                            "type": "boolean",
                            "description": "If true, returns the constructed HTTP request without sending it.",
                        },
                        "__trace": {
                            "type": "boolean",
                            "description": "If true, returns redacted request metadata in ToolResult.meta.",
                        },
                        "__auth": {
                            "type": "string",
                            "description": "Per-call auth override (token or 'Header: value').",
                        },
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
                for meth_name in (
                    "create_generated_tool",
                    "make_generated_tool",
                    "build_generated_tool",
                    "create",
                    "make",
                    "build",
                ):
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

    def _read_storage(self) -> dict[str, dict]:
        p = self.storage_path
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            backup = p.with_suffix(".json.bak")
            with contextlib.suppress(Exception):
                backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            return {}

    def _write_storage(self, data: dict[str, dict]) -> None:
        p = self.storage_path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
