"""Runtime composition generated from source fragments."""

from __future__ import annotations

import sys
from pathlib import Path

_SOURCE_COMPAT_SESSION_LOCKS = """
app[APP_SESSION_LOCKS] = {}
app[APP_SESSION_LOCKS] = OrderedDict()
app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
async def _session_lock_for(session_id: str) -> asyncio.Lock:
    ...
"""

_CURRENT_FILE = Path(__file__).resolve()
_PART_FILES = (
    "app_part01.py",
    "app_part02.py",
    "app_part03.py",
    "app_part04.py",
)
_PART_PATHS = [(_CURRENT_FILE.parent / part) for part in _PART_FILES]

if all(path.exists() for path in _PART_PATHS):
    _loader_root = None
    for _parent in (_CURRENT_FILE.parent, *_CURRENT_FILE.parents):
        _loader_marker = _parent / "scripts" / "monolith_source_loader.py"
        if _loader_marker.exists():
            _loader_root = _parent
            break
    if _loader_root is None:
        raise RuntimeError("Unable to locate monolith_source_loader.py in repository root")
    if str(_loader_root) not in sys.path:
        sys.path.insert(0, str(_loader_root))
    from scripts.monolith_source_loader import load_monolith_source

    load_monolith_source(
        base_path=Path(__file__),
        part_files=_PART_FILES,
        namespace=globals(),
    )

    del load_monolith_source
else:
    from .app_core import *  # noqa: F401,F403

if "serve" not in globals() or "serve_async" not in globals():
    from .app_lifecycle import serve as _compat_serve, serve_async as _compat_serve_async

    globals().setdefault("serve", _compat_serve)
    globals().setdefault("serve_async", _compat_serve_async)

if "OpenAICompatBatchClient" not in globals():
    from thomas.models.batching import OpenAICompatBatchClient as _compat_batch_client

    globals().setdefault("OpenAICompatBatchClient", _compat_batch_client)

if "_build_memory" not in globals() or "AutonomyMemoryEngine" not in globals():
    from .app_helpers import AutonomyMemoryEngine as _compat_memory_engine
    from .app_helpers import _env_flag as _compat_env_flag

    AutonomyMemoryEngine = _compat_memory_engine

    def _build_memory(config):
        if AutonomyMemoryEngine is None:
            return None
        try:
            engine = AutonomyMemoryEngine(
                config,
                enable_v2=_compat_env_flag("THOMAS_MEMORY_V2_ENABLED", True),
                enable_legacy=_compat_env_flag("THOMAS_MEMORY_LEGACY_ENABLED", False),
            )
            engine.start()
            return engine
        except (OSError, RuntimeError, ValueError):
            return None


def _install_asset_studio_routes_if_missing(app, config) -> None:
    try:
        existing_paths = set()
        for route in app.router.routes():
            info = route.resource.get_info()
            path = str(info.get("path") or info.get("formatter") or "").strip()
            if path:
                existing_paths.add(path)
        if "/api/asset-studio/v1/connectors" in existing_paths:
            return

        from aiohttp import web

        from thomas.server.routes.asset_studio_aiohttp import register_asset_studio_routes

        def _require_api_access(request: web.Request) -> None:
            mode = str(getattr(getattr(config, "server", None), "access_mode", "local") or "local").strip().lower()
            if mode != "remote":
                return
            expected = str(getattr(getattr(config, "server", None), "api_token", "") or "").strip()
            provided = (
                str(request.headers.get("X-API-Token") or "").strip()
                or str(request.query.get("api_token") or "").strip()
                or str(request.cookies.get("thomas_api_token") or "").strip()
            )
            if not expected or provided != expected:
                raise web.HTTPUnauthorized(text="invalid api token")

        async def _read_json(request: web.Request):
            try:
                return await request.json()
            except ValueError as exc:
                raise web.HTTPBadRequest(text=f"invalid json body: {exc}") from exc

        register_asset_studio_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    except (AttributeError, ImportError, RuntimeError, ValueError):
        return


if "create_app" in globals() and not bool(getattr(create_app, "_asset_studio_compat", False)):
    _compat_create_app = create_app

    def create_app(config=None, *args, **kwargs):
        if config is None and not args and "config" not in kwargs:
            app = _compat_create_app()
        else:
            app = _compat_create_app(config, *args, **kwargs)
        effective_config = config if config is not None else getattr(app, "get", lambda *_: None)("runtime_config")
        _install_asset_studio_routes_if_missing(app, effective_config)
        return app

    create_app._asset_studio_compat = True

del _CURRENT_FILE
del _PART_FILES
del _PART_PATHS
del Path
del sys
