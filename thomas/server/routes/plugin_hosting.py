"""Hosted plugin-store routes for Thomas desktop plugins."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.desktop_plugins import build_plugin_install_deep_link
from thomas.server.desktop_plugins_manifest import _DEFAULT_PLUGIN_STORE_API_KEY

log = logging.getLogger(__name__)

PLUGIN_STORAGE_DIR = Path(
    os.environ.get(
        "THOMAS_PLUGIN_STORAGE",
        str(Path(__file__).resolve().parent.parent / "plugins_registry"),
    )
)
DOWNLOAD_TOKEN_TTL = 300
RATE_LIMIT_PER_MINUTE = 60
MAX_BUNDLE_SIZE = 50 * 1024 * 1024
TRUSTED_PUBLISHER_IDS = {"thomas-official", "approved-partner"}
DISALLOWED_PATTERNS = [
    b"eval(",
    b"__import__(",
    b"subprocess.Popen",
    b"os.system(",
    b"shutil.rmtree(",
]
_MARKETPLACE_TYPES = {"command_center", "plugin", "dependency", "integration"}
_LEFT_NAV_BEHAVIORS = {"none", "workspace"}
_DEFAULT_NAV_SECTIONS = {"command_centers", "installed"}
_DOWNLOAD_TOKENS: dict[str, dict[str, Any]] = {}


@dataclass
class PluginManifest:
    id: str
    title: str
    description: str
    version: str
    author: str
    source: str
    section: str
    sha256: str
    size_bytes: int
    min_thomas_version: str = "1.0.0"
    max_thomas_version: str = "99.0.0"
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    changelog: list[dict[str, str]] = field(default_factory=list)
    icon: str = ""
    homepage: str = ""
    repository: str = ""
    created_at: str = ""
    updated_at: str = ""
    downloads: int = 0
    rating: float = 0.0
    verified: bool = False
    publisher_id: str = "unknown-publisher"
    publisher_name: str = "Unknown Publisher"
    kind: str = "desktop_plugin"
    marketplace_type: str = "plugin"
    category: str = ""
    categories: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    left_nav_behavior: str = "none"
    default_nav_section: str = "installed"
    default_nav_order: int = 900
    mode_id: str = ""
    api_namespace: str = ""
    surface: dict[str, str] = field(default_factory=dict)
    signature: str = ""


class SimpleRateLimiter:
    def __init__(self, max_per_minute: int = RATE_LIMIT_PER_MINUTE):
        self._max = max_per_minute
        self._windows: dict[str, list[float]] = {}

    def check(self, client_ip: str) -> bool:
        now = time.time()
        window = self._windows.setdefault(client_ip, [])
        cutoff = now - 60
        self._windows[client_ip] = [ts for ts in window if ts > cutoff]
        window = self._windows[client_ip]
        if len(window) >= self._max:
            return False
        window.append(now)
        return True


_rate_limiter = SimpleRateLimiter()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _safe_text(item)
        if text and text not in out:
            out.append(text)
    return out


def _normalize_marketplace_type(data: dict[str, Any], *, mode_id: str, surface_entry_html: str) -> str:
    explicit = _safe_text(data.get("marketplace_type")).lower()
    if explicit in _MARKETPLACE_TYPES:
        return explicit
    if _safe_text(data.get("kind")).lower() == "desktop_plugin" and mode_id and surface_entry_html:
        return "command_center"
    return "plugin"


def _normalize_left_nav_behavior(data: dict[str, Any], marketplace_type: str) -> str:
    explicit = _safe_text(data.get("left_nav_behavior")).lower()
    if explicit in _LEFT_NAV_BEHAVIORS:
        return explicit
    return "workspace" if marketplace_type == "command_center" else "none"


def _normalize_default_nav_section(data: dict[str, Any], marketplace_type: str, left_nav_behavior: str) -> str:
    explicit = _safe_text(data.get("default_nav_section")).lower()
    if explicit in _DEFAULT_NAV_SECTIONS:
        return explicit
    if marketplace_type == "command_center" or left_nav_behavior == "workspace":
        return "command_centers"
    return "installed"


def _issue_download_token(plugin_id: str, expires: int) -> str:
    token = secrets.token_urlsafe(32)
    _DOWNLOAD_TOKENS[token] = {"plugin_id": plugin_id, "expires": expires}
    return token


def _verify_token(token: str) -> dict[str, Any] | None:
    token = _safe_text(token)
    payload = _DOWNLOAD_TOKENS.get(token)
    if not isinstance(payload, dict):
        return None
    expires = int(payload.get("expires") or 0)
    if time.time() > expires:
        _DOWNLOAD_TOKENS.pop(token, None)
        return None
    return dict(payload)


def _scan_bundle_content(bundle_path: Path) -> dict[str, str] | None:
    max_pattern_len = max(len(pattern) for pattern in DISALLOWED_PATTERNS)
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            for info in archive.infolist():
                entry_name = info.filename.replace("\\", "/")
                if info.is_dir():
                    continue
                if entry_name.startswith("/") or ".." in {part for part in entry_name.split("/") if part}:
                    return {"entry": info.filename, "pattern": "unsafe_path"}
                tail = b""
                with archive.open(info, "r") as entry_stream:
                    while True:
                        chunk = entry_stream.read(65536)
                        if not chunk:
                            break
                        data = tail + chunk
                        for pattern in DISALLOWED_PATTERNS:
                            if pattern in data:
                                return {"entry": info.filename, "pattern": pattern.decode("utf-8", errors="ignore")}
                        tail = data[-(max_pattern_len - 1) :] if max_pattern_len > 1 else b""
    except (OSError, zipfile.BadZipFile) as exc:
        return {"entry": bundle_path.name, "pattern": f"zip_error:{type(exc).__name__}"}
    return None


def _request_base_url(request: web.Request) -> str:
    forwarded_proto = _safe_text(request.headers.get("X-Forwarded-Proto"))
    forwarded_host = _safe_text(request.headers.get("X-Forwarded-Host"))
    scheme = forwarded_proto or request.scheme
    host = forwarded_host or request.host
    return f"{scheme}://{host}"


def _is_public_plugin(plugin: PluginManifest | None) -> bool:
    if plugin is None:
        return False
    return plugin.publisher_id in TRUSTED_PUBLISHER_IDS and bool(plugin.signature)


def _plugin_response(plugin: PluginManifest, *, base_url: str) -> dict[str, Any]:
    payload = asdict(plugin)
    payload["manual_download_url"] = f"{base_url}/api/v1/plugins/{plugin.id}/manual-download"
    payload["open_in_thomas_url"] = build_plugin_install_deep_link(plugin.id, base_url)
    payload["store_url"] = base_url
    return payload


class PluginRegistry:
    def __init__(self, storage_dir: Path):
        self._dir = storage_dir
        self._plugins_dir = storage_dir / "plugins"
        self._reports_file = storage_dir / "reports.json"
        self._catalog_cache: list[PluginManifest] | None = None
        self._catalog_mtime: float = 0.0

    def ensure_storage(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        if not self._reports_file.exists():
            self._reports_file.write_text(json.dumps({"reports": []}, indent=2), encoding="utf-8")

    def _load_manifest(self, plugin_dir: Path) -> PluginManifest | None:
        manifest_path = plugin_dir / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        surface = data.get("surface") if isinstance(data.get("surface"), dict) else {}
        publisher_id = _safe_text(data.get("publisher_id")) or (
            "thomas-official" if data.get("verified") else "unknown-publisher"
        )
        publisher_name = _safe_text(data.get("publisher_name")) or _safe_text(data.get("source")) or "Unknown Publisher"
        mode_id = _safe_text(data.get("mode_id") or data.get("mode"))
        surface_entry_html = _safe_text(surface.get("entry_html"))
        marketplace_type = _normalize_marketplace_type(data, mode_id=mode_id, surface_entry_html=surface_entry_html)
        left_nav_behavior = _normalize_left_nav_behavior(data, marketplace_type)
        category = _safe_text(data.get("category"))
        categories = _string_list(data.get("categories"))
        if category and category not in categories:
            categories.insert(0, category)
        tags = _string_list(data.get("tags"))
        for value in categories + [marketplace_type, left_nav_behavior]:
            if value and value not in tags:
                tags.append(value)
        return PluginManifest(
            id=_safe_text(data.get("plugin_id") or data.get("id") or plugin_dir.name),
            title=_safe_text(data.get("display_name") or data.get("title") or data.get("name") or plugin_dir.name),
            description=_safe_text(data.get("description")),
            version=_safe_text(data.get("version")) or "0.0.0",
            author=_safe_text(data.get("author") or publisher_name) or "Unknown",
            source=_safe_text(data.get("source")) or publisher_name,
            section=_safe_text(data.get("section")) or "apps",
            sha256=_safe_text(data.get("sha256")),
            size_bytes=int(data.get("size_bytes") or 0),
            min_thomas_version=_safe_text(data.get("min_thomas_version")) or "1.0.0",
            max_thomas_version=_safe_text(data.get("max_thomas_version")) or "99.0.0",
            tags=tags,
            capabilities=[_safe_text(item) for item in (data.get("capabilities") or []) if _safe_text(item)],
            changelog=data.get("changelog") if isinstance(data.get("changelog"), list) else [],
            icon=_safe_text(data.get("icon")),
            homepage=_safe_text(data.get("homepage")),
            repository=_safe_text(data.get("repository")),
            created_at=_safe_text(data.get("created_at")),
            updated_at=_safe_text(data.get("updated_at")),
            downloads=int(data.get("downloads") or 0),
            rating=float(data.get("rating") or 0.0),
            verified=bool(data.get("verified")),
            publisher_id=publisher_id,
            publisher_name=publisher_name,
            kind=_safe_text(data.get("kind")) or "desktop_plugin",
            marketplace_type=marketplace_type,
            category=category or (categories[0] if categories else ""),
            categories=categories,
            requires=_string_list(data.get("requires")),
            left_nav_behavior=left_nav_behavior,
            default_nav_section=_normalize_default_nav_section(data, marketplace_type, left_nav_behavior),
            default_nav_order=_safe_int(
                data.get("default_nav_order"), 400 if marketplace_type == "command_center" else 900
            ),
            mode_id=mode_id,
            api_namespace=_safe_text(data.get("api_namespace") or data.get("plugin_id") or data.get("id")),
            surface={
                "entry_html": surface_entry_html,
                "title": _safe_text(surface.get("title")),
                "surface_mode": _safe_text(surface.get("surface_mode")) or "immersive",
            },
            signature=_safe_text(data.get("signature")),
        )

    def scan_catalog(self, *, force: bool = False, public_only: bool = False) -> list[PluginManifest]:
        if not self._plugins_dir.exists():
            return []
        current_mtime = self._plugins_dir.stat().st_mtime
        if not force and self._catalog_cache is not None and current_mtime <= self._catalog_mtime:
            manifests = self._catalog_cache
        else:
            manifests: list[PluginManifest] = []
            for entry in sorted(self._plugins_dir.iterdir()):
                if not entry.is_dir():
                    continue
                manifest = self._load_manifest(entry)
                if manifest is not None:
                    manifests.append(manifest)
            self._catalog_cache = manifests
            self._catalog_mtime = current_mtime
        if public_only:
            return [manifest for manifest in manifests if _is_public_plugin(manifest)]
        return list(manifests)

    def get_plugin(self, plugin_id: str, *, public_only: bool = False) -> PluginManifest | None:
        catalog = self.scan_catalog(public_only=public_only)
        for plugin in catalog:
            if plugin.id == plugin_id:
                return plugin
        return None

    def get_bundle_path(self, plugin_id: str) -> Path | None:
        bundle = self._plugins_dir / plugin_id / "bundle.zip"
        if bundle.exists() and bundle.is_file() and bundle.stat().st_size <= MAX_BUNDLE_SIZE:
            return bundle
        return None

    def verify_bundle(self, plugin_id: str) -> dict[str, Any]:
        manifest = self.get_plugin(plugin_id, public_only=False)
        if not manifest:
            return {"valid": False, "error": "Plugin not found"}
        bundle_path = self.get_bundle_path(plugin_id)
        if not bundle_path:
            return {"valid": False, "error": "Bundle not found"}
        sha = hashlib.sha256()
        with bundle_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                sha.update(chunk)
        actual_hash = sha.hexdigest()
        if manifest.sha256 and actual_hash != manifest.sha256:
            return {
                "valid": False,
                "error": "Checksum mismatch - bundle may be corrupted or tampered with",
                "expected": manifest.sha256,
                "actual": actual_hash,
            }
        scan_hit = _scan_bundle_content(bundle_path)
        if scan_hit:
            return {
                "valid": False,
                "error": "Bundle content failed security scan",
                "entry": scan_hit["entry"],
                "pattern": scan_hit["pattern"],
            }
        return {"valid": True, "sha256": actual_hash, "size_bytes": bundle_path.stat().st_size}

    def validate_api_key(self, key: str) -> bool:
        expected = _safe_text(os.environ.get("THOMAS_PLUGIN_STORE_API_KEY")) or _DEFAULT_PLUGIN_STORE_API_KEY
        return bool(key and expected and secrets.compare_digest(key, expected))

    def record_download(self, plugin_id: str) -> None:
        manifest_path = self._plugins_dir / plugin_id / "manifest.json"
        if not manifest_path.exists():
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                return
            data["downloads"] = int(data.get("downloads") or 0) + 1
            manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return

    def add_report(self, plugin_id: str, reason: str, reporter_key: str) -> None:
        try:
            payload = json.loads(self._reports_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {"reports": []}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {"reports": []}
        reports = payload.get("reports") if isinstance(payload.get("reports"), list) else []
        reports.append(
            {
                "plugin_id": plugin_id,
                "reason": reason,
                "reporter": reporter_key[:8] + "..." if len(reporter_key) > 8 else reporter_key,
                "timestamp": time.time(),
            }
        )
        payload["reports"] = reports
        self._reports_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        _registry = PluginRegistry(PLUGIN_STORAGE_DIR)
        _registry.ensure_storage()
    return _registry


def _get_client_ip(request: web.Request) -> str:
    forwarded = _safe_text(request.headers.get("X-Forwarded-For"))
    if forwarded:
        return forwarded.split(",")[0].strip()
    peername = request.transport.get_extra_info("peername") if request.transport else None
    return peername[0] if peername else "unknown"


def _require_api_key(request: web.Request) -> str | None:
    key = _safe_text(request.headers.get("X-Thomas-API-Key")) or _safe_text(request.query.get("api_key"))
    return key if get_registry().validate_api_key(key) else None


async def api_plugin_catalog(request: web.Request) -> web.Response:
    if not _rate_limiter.check(_get_client_ip(request)):
        return web.json_response({"error": "Rate limit exceeded. Try again shortly."}, status=429)
    registry = get_registry()
    catalog = registry.scan_catalog(public_only=True)
    query = _safe_text(request.query.get("q")).lower()
    section = _safe_text(request.query.get("section")).lower()
    sort_by = _safe_text(request.query.get("sort") or "rating").lower()
    limit = min(max(int(request.query.get("limit", "50")), 1), 200)
    offset = max(int(request.query.get("offset", "0")), 0)
    results = list(catalog)
    if section and section != "all":
        results = [plugin for plugin in results if plugin.section == section]
    if query:
        results = [
            plugin
            for plugin in results
            if query in plugin.title.lower()
            or query in plugin.description.lower()
            or query in plugin.publisher_name.lower()
            or query in plugin.marketplace_type.lower()
            or any(query in tag.lower() for tag in plugin.tags)
            or any(query in category.lower() for category in plugin.categories)
        ]
    if sort_by == "downloads":
        results.sort(key=lambda plugin: (-plugin.downloads, plugin.title.lower()))
    elif sort_by == "name":
        results.sort(key=lambda plugin: plugin.title.lower())
    elif sort_by == "newest":
        results.sort(key=lambda plugin: plugin.updated_at or plugin.created_at, reverse=True)
    else:
        results.sort(key=lambda plugin: (-plugin.rating, -plugin.downloads, plugin.title.lower()))
    base_url = _request_base_url(request)
    page = results[offset : offset + limit]
    return web.json_response(
        {
            "plugins": [_plugin_response(plugin, base_url=base_url) for plugin in page],
            "total": len(results),
            "limit": limit,
            "offset": offset,
        }
    )


async def api_plugin_detail(request: web.Request) -> web.Response:
    if not _rate_limiter.check(_get_client_ip(request)):
        return web.json_response({"error": "Rate limit exceeded."}, status=429)
    plugin_id = request.match_info["id"]
    plugin = get_registry().get_plugin(plugin_id, public_only=True)
    if not plugin:
        return web.json_response({"error": f"Plugin '{plugin_id}' not found"}, status=404)
    return web.json_response(_plugin_response(plugin, base_url=_request_base_url(request)))


async def api_plugin_manual_download(request: web.Request) -> web.StreamResponse:
    if not _rate_limiter.check(_get_client_ip(request)):
        return web.json_response({"error": "Rate limit exceeded."}, status=429)
    plugin_id = request.match_info["id"]
    plugin = get_registry().get_plugin(plugin_id, public_only=True)
    if not plugin:
        return web.json_response({"error": f"Plugin '{plugin_id}' not found"}, status=404)
    token = _issue_download_token(plugin_id, int(time.time()) + DOWNLOAD_TOKEN_TTL)
    raise web.HTTPFound(location=f"/api/v1/plugins/download/{token}")


async def api_plugin_download_token(request: web.Request) -> web.Response:
    if not _rate_limiter.check(_get_client_ip(request)):
        return web.json_response({"error": "Rate limit exceeded."}, status=429)
    client_key = _require_api_key(request)
    if not client_key:
        return web.json_response({"error": "Valid API key required. Include X-Thomas-API-Key header."}, status=401)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    plugin_id = _safe_text(payload.get("plugin_id"))
    if not plugin_id:
        return web.json_response({"error": "plugin_id is required"}, status=400)
    plugin = get_registry().get_plugin(plugin_id, public_only=True)
    if not plugin:
        return web.json_response({"error": f"Plugin '{plugin_id}' not found"}, status=404)
    bundle = get_registry().get_bundle_path(plugin_id)
    if not bundle:
        return web.json_response({"error": "Plugin bundle not available for download"}, status=404)
    token = _issue_download_token(plugin_id, int(time.time()) + DOWNLOAD_TOKEN_TTL)
    return web.json_response(
        {
            "token": token,
            "expires_in": DOWNLOAD_TOKEN_TTL,
            "download_url": f"/api/v1/plugins/download/{token}",
            "sha256": plugin.sha256,
            "size_bytes": plugin.size_bytes,
        }
    )


async def api_plugin_download(request: web.Request) -> web.StreamResponse:
    if not _rate_limiter.check(_get_client_ip(request)):
        return web.json_response({"error": "Rate limit exceeded."}, status=429)
    decoded = _verify_token(request.match_info["token"])
    if not decoded:
        return web.json_response({"error": "Invalid or expired download token. Request a new one."}, status=403)
    plugin_id = decoded["plugin_id"]
    registry = get_registry()
    plugin = registry.get_plugin(plugin_id, public_only=True)
    bundle_path = registry.get_bundle_path(plugin_id)
    if not plugin or not bundle_path:
        return web.json_response({"error": "Bundle not found"}, status=404)
    registry.record_download(plugin_id)
    response = web.StreamResponse()
    response.content_type = "application/zip"
    response.headers["Content-Disposition"] = f'attachment; filename="{plugin_id}.zip"'
    response.headers["Content-Length"] = str(bundle_path.stat().st_size)
    response.headers["X-Plugin-SHA256"] = plugin.sha256
    await response.prepare(request)
    with bundle_path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            await response.write(chunk)
    await response.write_eof()
    return response


async def api_plugin_verify(request: web.Request) -> web.Response:
    if not _rate_limiter.check(_get_client_ip(request)):
        return web.json_response({"error": "Rate limit exceeded."}, status=429)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    plugin_id = _safe_text(payload.get("plugin_id"))
    if not plugin_id:
        return web.json_response({"error": "plugin_id is required"}, status=400)
    plugin = get_registry().get_plugin(plugin_id, public_only=True)
    if not plugin:
        return web.json_response({"error": f"Plugin '{plugin_id}' not found"}, status=404)
    result = get_registry().verify_bundle(plugin_id)
    status_code = 200 if result.get("valid") else 400
    return web.json_response(result, status=status_code)


async def api_plugin_report(request: web.Request) -> web.Response:
    client_key = _require_api_key(request)
    if not client_key:
        return web.json_response({"error": "API key required"}, status=401)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    plugin_id = _safe_text(payload.get("plugin_id"))
    reason = _safe_text(payload.get("reason"))
    if not plugin_id or not reason:
        return web.json_response({"error": "plugin_id and reason are required"}, status=400)
    get_registry().add_report(plugin_id, reason, client_key)
    return web.json_response({"success": True, "message": "Report submitted. Thank you."})


def register_plugin_hosting_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/plugins/catalog", api_plugin_catalog)
    app.router.add_get("/api/v1/plugins/{id}/manual-download", api_plugin_manual_download)
    app.router.add_get("/api/v1/plugins/{id}", api_plugin_detail)
    app.router.add_post("/api/v1/plugins/download-token", api_plugin_download_token)
    app.router.add_get("/api/v1/plugins/download/{token}", api_plugin_download)
    app.router.add_post("/api/v1/plugins/verify", api_plugin_verify)
    app.router.add_post("/api/v1/plugins/report", api_plugin_report)
    log.info("Plugin hosting routes registered")
