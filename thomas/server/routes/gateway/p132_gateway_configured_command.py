"""Gateway configuration status endpoint.

This module provides a small HTTP endpoint that reports whether the running Gateway
is considered "configured".

Goals:
  - Give UI clients and automation a cheap probe for onboarding state.
  - Never crash the server for missing/invalid config; report state deterministically.
  - Provide a stable, machine-readable JSON contract.

"Configured" (conservative definition):
  - A readable config source exists (already loaded into the running app OR readable
    from disk), AND
  - A gateway mode can be determined from that config.

If the real Thomas config schema evolves, this endpoint should remain safe:
it uses best-effort extraction and never raises outward.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypedDict

# Keep this module importable even in environments where aiohttp is not installed
# (e.g., CLI-only installs). Route objects will only be defined when aiohttp exists.
try:
    from aiohttp import web  # type: ignore
except Exception:  # pragma: no cover
    web = None  # type: ignore

if web is not None:  # pragma: no cover
    CONFIG_APP_KEY = web.AppKey("config", object)
else:  # pragma: no cover
    CONFIG_APP_KEY = "config"


PROMPT_ID = "p132"


class GatewayConfiguredResponse(TypedDict):
    configured: bool
    gateway_mode: str | None
    config_path: str | None
    missing: list[str]
    reason: str | None
    message: str
    source: str


# Deterministic reason codes.
REASON_MISSING_CONFIG = "missing_config"
REASON_INVALID_CONFIG = "invalid_config"
REASON_MISSING_GATEWAY_MODE = "missing_gateway_mode"
REASON_UNEXPECTED = "unexpected_error"


@dataclass(frozen=True)
class GatewayConfiguredStatus:
    configured: bool
    gateway_mode: str | None
    config_path: str | None
    missing: tuple[str, ...]
    reason: str | None
    message: str
    source: str

    def to_response(self) -> GatewayConfiguredResponse:
        data = asdict(self)
        data["missing"] = list(self.missing)
        return data  # type: ignore[return-value]


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any | None:
    for k in keys:
        found, value = _mapping_try_get(mapping, k)
        if found:
            return value
    return None


def _mapping_try_get(mapping: Mapping[str, Any], key_name: str) -> tuple[bool, Any]:
    try:
        if key_name in mapping:
            return True, mapping[key_name]
    except Exception:
        pass
    try:
        for mk, mv in mapping.items():
            mk_name = getattr(mk, "name", "") or getattr(mk, "_name", "")
            if mk_name == key_name or str(mk_name).endswith(f".{key_name}"):
                return True, mv
    except Exception:
        pass
    return False, None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    try:
        s = str(value).strip()
        return s or None
    except Exception:
        return None


def _extract_gateway_mode(config_obj: Any) -> str | None:
    """Best-effort extraction of a gateway mode from a config object.

    Tries common shapes:
      - dict config["gateway"]["mode"]
      - dict config["gateway_mode"]
      - attribute config.gateway.mode
      - attribute config.gateway_mode
    """
    try:
        if isinstance(config_obj, Mapping):
            gateway_section = config_obj.get("gateway")
            if isinstance(gateway_section, Mapping):
                mode = _safe_str(gateway_section.get("mode"))
                if mode:
                    return mode
            mode = _safe_str(config_obj.get("gateway_mode"))
            if mode:
                return mode

        if hasattr(config_obj, "gateway_mode"):
            mode = _safe_str(config_obj.gateway_mode)
            if mode:
                return mode

        if hasattr(config_obj, "gateway"):
            gateway_obj = config_obj.gateway
            if isinstance(gateway_obj, Mapping):
                mode = _safe_str(gateway_obj.get("mode"))
                if mode:
                    return mode
            if hasattr(gateway_obj, "mode"):
                mode = _safe_str(gateway_obj.mode)
                if mode:
                    return mode
    except Exception:
        return None
    return None


def _resolve_config_path(app_like: Mapping[str, Any], config_obj: Any) -> Path | None:
    """Resolve a plausible config path.

    Preference:
      1) explicit app context values
      2) attributes on the loaded config object
      3) environment variables
      4) conventional user locations (only if they exist)
      5) otherwise, a conventional default path (even if non-existent) for display
    """
    raw = _first_present(app_like, ("config_path", "settings_path", "config_file", "thomas_config_path"))
    if raw:
        try:
            return Path(str(raw)).expanduser()
        except Exception:
            return None

    for attr in ("config_path", "path", "source_path", "file_path"):
        if hasattr(config_obj, attr):
            try:
                value = getattr(config_obj, attr)
                if value:
                    return Path(str(value)).expanduser()
            except Exception:
                pass

    for env_key in ("THOMAS_CONFIG_PATH", "THOMAS_SETTINGS_PATH", "THOMAS_CONFIG_FILE"):
        env_val = os.getenv(env_key)
        if env_val:
            try:
                return Path(env_val).expanduser()
            except Exception:
                return None

    home = Path.home()
    candidates = (home / ".thomas" / "thomas.json", home / ".config" / "thomas" / "config.json")
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _load_config_from_disk(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    """Load a JSON config file (fallback only).

    Returns (config_mapping, reason_code). If parsing fails, config_mapping is None.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, REASON_MISSING_CONFIG
    except Exception:
        return None, REASON_INVALID_CONFIG

    try:
        loaded = json.loads(raw)
    except Exception:
        return None, REASON_INVALID_CONFIG

    if isinstance(loaded, Mapping):
        return loaded, None
    return None, REASON_INVALID_CONFIG


def evaluate_gateway_configured(
    app_like: Mapping[str, Any],
    *,
    config_path_override: str | None = None,
) -> GatewayConfiguredStatus:
    """Compute whether the gateway is configured.

    This function is deliberately defensive: it should never raise.
    """
    try:
        config_obj = _first_present(
            app_like,
            (
                "config",
                "settings",
                "cfg",
                "thomas_config",
                "thomas_settings",
            ),
        )
        source = "app"

        # Determine config path (for reporting and disk fallback).
        if config_path_override is not None:
            try:
                config_path = Path(config_path_override).expanduser()
            except Exception:
                return GatewayConfiguredStatus(
                    configured=False,
                    gateway_mode=None,
                    config_path=None,
                    missing=("config_path",),
                    reason=REASON_INVALID_CONFIG,
                    message="Invalid config_path override.",
                    source="input",
                )
        else:
            config_path = _resolve_config_path(app_like, config_obj)

        disk_reason: str | None = None
        if config_obj is None and config_path is not None:
            loaded, disk_reason = _load_config_from_disk(config_path)
            config_obj = loaded
            source = "disk"

        config_path_str = str(config_path) if config_path is not None else None

        if config_obj is None:
            reason = disk_reason or REASON_MISSING_CONFIG
            return GatewayConfiguredStatus(
                configured=False,
                gateway_mode=None,
                config_path=config_path_str,
                missing=("config",),
                reason=reason,
                message="Gateway is not configured (no readable config found).",
                source=source,
            )

        gateway_mode = _extract_gateway_mode(config_obj)
        if gateway_mode is None:
            return GatewayConfiguredStatus(
                configured=False,
                gateway_mode=None,
                config_path=config_path_str,
                missing=("gateway.mode",),
                reason=REASON_MISSING_GATEWAY_MODE,
                message="Gateway is not configured (gateway mode is not set).",
                source=source,
            )

        return GatewayConfiguredStatus(
            configured=True,
            gateway_mode=gateway_mode,
            config_path=config_path_str,
            missing=(),
            reason=None,
            message="Gateway is configured.",
            source=source,
        )
    except Exception:
        return GatewayConfiguredStatus(
            configured=False,
            gateway_mode=None,
            config_path=None,
            missing=(),
            reason=REASON_UNEXPECTED,
            message="Unable to determine gateway configuration state.",
            source="unknown",
        )


# ----------------------------
# aiohttp route wiring (optional)
# ----------------------------
if web is not None:  # pragma: no cover
    routes = web.RouteTableDef()
    ROUTES = routes  # common alias used by some route loaders

    async def _handle_gateway_configured(request: web.Request) -> web.Response:
        status = evaluate_gateway_configured(request.app)
        return web.json_response(status.to_response())

    @routes.get("/configured")
    async def gateway_configured(request: web.Request) -> web.Response:
        return await _handle_gateway_configured(request)

    @routes.get("/gateway/configured")
    async def gateway_configured_with_prefix(request: web.Request) -> web.Response:
        # This extra path makes the endpoint resilient to different router prefixing strategies.
        return await _handle_gateway_configured(request)

    def get_routes() -> web.RouteTableDef:
        return routes

    def register(app: web.Application) -> None:
        """Register this module's routes into an existing aiohttp app."""
        app.add_routes(routes)

    def build_subapp() -> web.Application:
        subapp = web.Application()
        subapp.add_routes(routes)
        return subapp
else:
    # Provide stubs so importers have deterministic attributes even without aiohttp.
    routes = None  # type: ignore
    ROUTES = None  # type: ignore
