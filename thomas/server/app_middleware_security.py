"""Security policy helpers shared by Thomas's aiohttp middleware stack."""

from __future__ import annotations

import os
import re
from typing import Any

from thomas.server.app_helpers import _env_flag

_BEARER_TOKEN_RE = re.compile(r"^Bearer\s+([^\s]+)\s*$", re.IGNORECASE)
_SANDBOXED_ARTIFACT_PREFIX = "/api/evolve/agent/artifact-content/"
_SANDBOXED_ARTIFACT_DESTINATIONS = {
    "audio",
    "font",
    "image",
    "script",
    "style",
    "track",
    "video",
    "worker",
}


def _is_passive_cross_site_asset_request(request: Any) -> bool:
    mode = str(request.headers.get("Sec-Fetch-Mode") or "").strip().lower()
    origin = str(request.headers.get("Origin") or "").strip().lower()
    opaque_sandbox_asset = (mode == "no-cors" and not origin) or (mode == "cors" and origin == "null")
    return (
        str(getattr(request, "method", "") or "").upper() in {"GET", "HEAD"}
        and str(request.headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site"
        and opaque_sandbox_asset
        and str(request.headers.get("Sec-Fetch-Dest") or "").strip().lower() in _SANDBOXED_ARTIFACT_DESTINATIONS
    )


def _is_opaque_sandbox_data_request(request: Any) -> bool:
    return (
        str(getattr(request, "method", "") or "").upper() in {"GET", "HEAD"}
        and str(request.headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site"
        and str(request.headers.get("Sec-Fetch-Mode") or "").strip().lower() == "cors"
        and str(request.headers.get("Sec-Fetch-Dest") or "").strip().lower() == "empty"
        and str(request.headers.get("Origin") or "").strip().lower() == "null"
    )


def _has_capability_path(path: str, prefix: str) -> bool:
    remainder = path.removeprefix(prefix) if path.startswith(prefix) else ""
    capability, separator, tail = remainder.partition("/")
    return (
        bool(separator and tail)
        and len(capability) == 64
        and all(char in "0123456789abcdef" for char in capability.lower())
    )


def _is_sandboxed_artifact_asset_request(request: Any) -> bool:
    """Recognize passive assets on an unguessable, server-validated preview path."""
    path = str(getattr(request, "path", "") or "")
    return _has_capability_path(path, _SANDBOXED_ARTIFACT_PREFIX) and (
        _is_passive_cross_site_asset_request(request) or _is_opaque_sandbox_data_request(request)
    )


def _is_generated_artifact_asset_request(request: Any) -> bool:
    return _is_sandboxed_artifact_asset_request(request)


def security_headers_config() -> tuple[bool, dict[str, str]]:
    """Build the configured default response-security headers."""
    enabled = _env_flag("THOMAS_SECURITY_HEADERS_ENABLED", True)
    frame_options = str(os.environ.get("THOMAS_FRAME_OPTIONS", "SAMEORIGIN") or "").strip()
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' blob: https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com; "
            "img-src 'self' data: blob:; "
            "font-src 'self' https://cdn.jsdelivr.net https://unpkg.com https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "frame-src 'self' http://127.0.0.1:*"
        ),
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-site",
        "X-Permitted-Cross-Domain-Policies": "none",
    }
    if frame_options:
        headers["X-Frame-Options"] = frame_options
    return enabled, headers


def resource_policy_for_request(request: Any) -> str:
    """Allow only validated passive generated assets into opaque-origin previews."""
    return "cross-origin" if _is_generated_artifact_asset_request(request) else "same-site"


def cors_origin_for_request(request: Any) -> str | None:
    """Authorize module/font loads from Thomas's opaque generated-app sandbox."""
    if not _is_generated_artifact_asset_request(request):
        return None
    mode = str(request.headers.get("Sec-Fetch-Mode") or "").strip().lower()
    origin = str(request.headers.get("Origin") or "").strip().lower()
    return "null" if mode == "cors" and origin == "null" else None
