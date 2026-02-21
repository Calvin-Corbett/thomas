from __future__ import annotations

from typing import Any, List, Optional

from thomas.tools.base import Tool, ToolResult, ToolSpec
from thomas.core.api_importer import ApiImporter, HttpOptions, _make_toolresult_ok, _make_toolresult_err, _make_toolspec


class ApiImportTool(Tool):
    """
    Tool: api.import

    Consumer-grade import behavior:
      - freeze_spec: store a compressed snapshot of the spec so restart doesn't depend on the URL staying stable
      - persists tool list + base_url + non-secret security summary
      - supports HTTP tuning (timeout/retries/ssl verify)
    """
    def __init__(self, registry: Any, importer: Optional[ApiImporter] = None):
        self._registry = registry
        self._importer = importer or ApiImporter()
        self._spec = _make_toolspec(
            name="api.import",
            description=(
                "Import an OpenAPI/Swagger spec from a URL and register generated tools.\n"
                "Best UX features:\n"
                "- freeze_spec: saves a compressed spec snapshot for reliable restart\n"
                "- generated tools support __dry_run and __trace\n"
                "- per-call overrides: __auth, __base_url, __timeout_seconds\n\n"
                "auth_header may be a token or an exact header line 'Header-Name: value'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "OpenAPI/Swagger spec URL (JSON or YAML)."},
                    "name": {"type": "string", "description": "API short name used for tool naming (api.{name}.*)."},
                    "auth_header": {"type": "string", "description": "Optional token or 'Header: value'."},
                    "base_url": {"type": "string", "description": "Optional override for the API base URL."},
                    "freeze_spec": {"type": "boolean", "description": "If true, stores a compressed spec snapshot for restart reliability."},
                    "timeout_seconds": {"type": "number", "description": "Total request timeout (default 30)."},
                    "connect_timeout_seconds": {"type": "number", "description": "Connect timeout (default 10)."},
                    "retries": {"type": "integer", "description": "Retries on 429/5xx/network errors (default 2)."},
                    "backoff_seconds": {"type": "number", "description": "Backoff base seconds (default 0.4)."},
                    "verify_ssl": {"type": "boolean", "description": "Verify TLS certs (default true)."},
                    "follow_redirects": {"type": "boolean", "description": "Follow redirects (default true)."},
                },
                "required": ["url", "name"],
                "additionalProperties": False,
            },
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def execute(self, args: dict) -> ToolResult:
        url = (args or {}).get("url")
        name = (args or {}).get("name")
        auth_header = (args or {}).get("auth_header")
        base_url = (args or {}).get("base_url")
        freeze_spec = bool((args or {}).get("freeze_spec", False))

        if not url or not name:
            return _make_toolresult_err("Missing required args: url, name")

        # Apply HTTP options
        try:
            cur = self._importer.http_options
            self._importer.http_options = HttpOptions(
                timeout_seconds=float((args or {}).get("timeout_seconds", cur.timeout_seconds)),
                connect_timeout_seconds=float((args or {}).get("connect_timeout_seconds", cur.connect_timeout_seconds)),
                retries=int((args or {}).get("retries", cur.retries)),
                backoff_seconds=float((args or {}).get("backoff_seconds", cur.backoff_seconds)),
                verify_ssl=bool((args or {}).get("verify_ssl", cur.verify_ssl)),
                follow_redirects=bool((args or {}).get("follow_redirects", cur.follow_redirects)),
                max_text_chars=cur.max_text_chars,
                max_binary_bytes=cur.max_binary_bytes,
            )
        except Exception as e:
            return _make_toolresult_err(f"Invalid HTTP options: {e}")

        try:
            self._importer.api_name_hint = str(name)
            tools = self._importer.import_from_url(spec_url=str(url), base_url=base_url, auth_header=auth_header, freeze_spec=freeze_spec)
            self._importer.register_all(tools, self._registry)
            self._importer.save_imported_api(name=str(name), spec_url=str(url), tools=tools)

            tool_names: List[str] = []
            for t in tools:
                s = getattr(t, "spec", None)
                if callable(s):
                    s = s()
                if s is not None:
                    tool_names.append(getattr(s, "name", getattr(s, "tool_name", "unknown")))
                else:
                    tool_names.append(getattr(t, "name", "unknown"))

            return _make_toolresult_ok(
                {
                    "imported_api": str(name),
                    "registered_tools": tool_names,
                    "tool_count": len(tool_names),
                    "freeze_spec": freeze_spec,
                    "restart_auth": f"Set env THOMAS_API_AUTH_{str(name).upper()} for restart-safe tokens.",
                    "http_options": {
                        "timeout_seconds": self._importer.http_options.timeout_seconds,
                        "connect_timeout_seconds": self._importer.http_options.connect_timeout_seconds,
                        "retries": self._importer.http_options.retries,
                        "backoff_seconds": self._importer.http_options.backoff_seconds,
                        "verify_ssl": self._importer.http_options.verify_ssl,
                        "follow_redirects": self._importer.http_options.follow_redirects,
                    },
                    "generated_tool_extras": ["__dry_run", "__trace", "__auth", "__base_url", "__timeout_seconds"],
                }
            )
        except Exception as e:
            return _make_toolresult_err(f"Import failed: {e}")


class ApiListImportedTool(Tool):
    """
    Tool: api.list_imported
    Lists saved imported APIs + tool counts, and whether spec was frozen.
    """
    def __init__(self, importer: Optional[ApiImporter] = None):
        self._importer = importer or ApiImporter()
        self._spec = _make_toolspec(
            name="api.list_imported",
            description="List imported APIs saved in thomas_imported_apis.json and their tool counts.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def execute(self, args: dict) -> ToolResult:
        saved = self._importer.list_saved()
        out = []
        for name, meta in sorted(saved.items(), key=lambda kv: kv[0]):
            snap = meta.get("spec_snapshot") or {}
            frozen = bool(isinstance(snap, dict) and snap.get("format") == "gzip_base64")
            out.append(
                {
                    "name": name,
                    "spec_url": meta.get("spec_url"),
                    "base_url": meta.get("base_url"),
                    "tool_count": meta.get("tool_count", len(meta.get("tool_names") or [])),
                    "updated_at": meta.get("updated_at"),
                    "created_at": meta.get("created_at"),
                    "spec_hash": meta.get("spec_hash"),
                    "frozen_spec": frozen,
                    "security": meta.get("security"),
                    "http_options": meta.get("http_options"),
                }
            )
        return _make_toolresult_ok({"imported_apis": out, "count": len(out)})


class ApiRemoveTool(Tool):
    """
    Tool: api.remove
    params: { name: str }
    Removes all tools for an API and deletes its persisted entry.
    """
    def __init__(self, registry: Any, importer: Optional[ApiImporter] = None):
        self._registry = registry
        self._importer = importer or ApiImporter()
        self._spec = _make_toolspec(
            name="api.remove",
            description="Remove an imported API: unregister its tools and delete it from thomas_imported_apis.json.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Imported API name (as used in api.import)."}},
                "required": ["name"],
                "additionalProperties": False,
            },
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def execute(self, args: dict) -> ToolResult:
        name = (args or {}).get("name")
        if not name:
            return _make_toolresult_err("Missing required arg: name")

        removed = self._importer.remove_saved(str(name)) or {}
        tool_names = removed.get("tool_names") or []

        unregistered: List[str] = []

        # Best-effort unregister.
        try:
            if hasattr(self._registry, "unregister"):
                for tn in tool_names:
                    try:
                        self._registry.unregister(tn)
                        unregistered.append(tn)
                    except Exception:
                        pass
            else:
                tool_map = None
                for attr in ("_tools", "tools", "_registry", "registry"):
                    if hasattr(self._registry, attr):
                        cand = getattr(self._registry, attr)
                        if isinstance(cand, dict):
                            tool_map = cand
                            break
                if isinstance(tool_map, dict):
                    for tn in tool_names:
                        if tn in tool_map:
                            try:
                                del tool_map[tn]
                                unregistered.append(tn)
                            except Exception:
                                pass
        except Exception:
            pass

        return _make_toolresult_ok(
            {
                "removed_api": str(name),
                "persisted_entry_found": bool(removed),
                "requested_tool_removals": len(tool_names),
                "unregistered_tools": unregistered,
                "note": "Persisted entry removed. Unregister is best-effort based on your ToolRegistry implementation.",
            }
        )


class ApiReloadImportedTool(Tool):
    """
    Tool: api.reload_imported
    Reloads all saved imported APIs on demand.
    """
    def __init__(self, registry: Any, importer: Optional[ApiImporter] = None):
        self._registry = registry
        self._importer = importer or ApiImporter()
        self._spec = _make_toolspec(
            name="api.reload_imported",
            description="Reload all saved imported APIs from thomas_imported_apis.json (uses frozen spec snapshots when available).",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def execute(self, args: dict) -> ToolResult:
        try:
            names = self._importer.reload_saved(self._registry)
            return _make_toolresult_ok({"reloaded_tools": names, "count": len(names)})
        except Exception as e:
            return _make_toolresult_err(f"Reload failed: {e}")


def build_api_import_tools(registry: Any) -> List[Tool]:
    """
    Convenience: create management tools (import/list/remove/reload).

    Typical startup wiring:
        from thomas.tools.api_import import build_api_import_tools
        for t in build_api_import_tools(registry):
            registry.register(t)

        # optionally reload saved imports
        from thomas.core.api_importer import ApiImporter
        ApiImporter().reload_saved(registry)
    """
    importer = ApiImporter()
    return [
        ApiImportTool(registry=registry, importer=importer),
        ApiListImportedTool(importer=importer),
        ApiRemoveTool(registry=registry, importer=importer),
        ApiReloadImportedTool(registry=registry, importer=importer),
    ]
