"""Nodes screen capture action (Prompt P043).

Thomas-native action that asks a node to capture a screenshot.

This module is transport-agnostic: a `ScreenCaptureTransport` is responsible for
actually talking to the node (HTTP, local RPC, etc.). The default transport is
an HTTP transport that can be configured via a config mapping or environment.

Contracts:
- Input: `NodesScreenCaptureRequest` (validated by `parse_nodes_screen_capture_request`)
- Output: `NodesScreenCaptureResult` (and `.to_dict()` for JSON)

Deterministic errors:
- NodesScreenCaptureInputError   (code="invalid_input")
- NodesScreenCaptureConfigError  (code="missing_config")
- NodesScreenCaptureExternalError (code="external_failure")

Machine-readable output:
- `NodesScreenCaptureResult.to_dict()` and `NodesScreenCaptureError.to_dict()`
- `get_action_metadata()` includes JSON-schema-ish input/output descriptions.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence

PROMPT_ID = "P043"
ACTION_SLUG = "nodes.capture_screen"

DEFAULT_TIMEOUT_S = 30.0
SUPPORTED_IMAGE_FORMATS: tuple[str, ...] = ("png", "jpg", "jpeg", "webp")

DEFAULT_HTTP_PATH_TEMPLATE = "/nodes/{node_id}/screen-capture"
DEFAULT_HTTP_METHOD = "POST"

__all__ = [
    "PROMPT_ID",
    "ACTION_SLUG",
    "SUPPORTED_IMAGE_FORMATS",
    "NodesScreenCaptureError",
    "NodesScreenCaptureInputError",
    "NodesScreenCaptureConfigError",
    "NodesScreenCaptureExternalError",
    "ScreenCaptureTransport",
    "NodesScreenCaptureRequest",
    "NodesScreenCaptureResult",
    "parse_nodes_screen_capture_request",
    "HttpScreenCaptureTransport",
    "build_transport_from_config",
    "run_nodes_screen_capture",
    "run_nodes_screen_capture_sync",
    "get_action_metadata",
    "run_action_from_raw",
]


class NodesScreenCaptureError(RuntimeError):
    """Base error for the node screen capture action."""

    code: str = "screen_capture_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": str(self)}}


class NodesScreenCaptureInputError(NodesScreenCaptureError):
    """Invalid request parameters."""

    code = "invalid_input"


class NodesScreenCaptureConfigError(NodesScreenCaptureError):
    """Missing required configuration."""

    code = "missing_config"


class NodesScreenCaptureExternalError(NodesScreenCaptureError):
    """Capture failed due to external or IO reasons."""

    code = "external_failure"


class ScreenCaptureTransport(Protocol):
    """Transport that can request a node screenshot and return image bytes."""

    async def capture_screen(
        self,
        node_id: str,
        *,
        image_format: str,
        timeout_s: float,
    ) -> bytes:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True, slots=True)
class NodesScreenCaptureRequest:
    """Validated request for a node screen capture."""

    node_id: str
    image_format: str = "png"
    save_path: Optional[Path] = None
    save_path_is_dir: bool = False
    include_image_b64: bool = False
    timeout_s: float = DEFAULT_TIMEOUT_S


@dataclass(frozen=True, slots=True)
class NodesScreenCaptureResult:
    """Result of a node screen capture."""

    node_id: str
    image_format: str
    captured_at: str
    bytes_captured: int
    saved_path: Optional[str]
    image_b64: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "result": {
                "node_id": self.node_id,
                "image_format": self.image_format,
                "captured_at": self.captured_at,
                "bytes_captured": self.bytes_captured,
                "saved_path": self.saved_path,
                "image_b64": self.image_b64,
            },
        }


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_compact_timestamp() -> str:
    # Example: 20260221T021233Z
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_filename_component(value: str, *, fallback: str = "node") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        return fallback
    return cleaned[:120]


def _first_nonempty_str(config: Optional[Mapping[str, Any]], keys: Sequence[str]) -> Optional[str]:
    if not config:
        return None
    for key in keys:
        val = config.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def parse_nodes_screen_capture_request(data: Mapping[str, Any]) -> NodesScreenCaptureRequest:
    """Parse and validate raw request data into a request object."""
    node_id = data.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise NodesScreenCaptureInputError("node_id must be a non-empty string")

    image_format = data.get("image_format", data.get("format", "png"))
    if not isinstance(image_format, str) or not image_format.strip():
        raise NodesScreenCaptureInputError("image_format must be a non-empty string")
    image_format = image_format.lower().strip()
    if image_format not in SUPPORTED_IMAGE_FORMATS:
        raise NodesScreenCaptureInputError(
            f"image_format must be one of {', '.join(SUPPORTED_IMAGE_FORMATS)}"
        )

    timeout_s = data.get("timeout_s", DEFAULT_TIMEOUT_S)
    try:
        timeout_s_f = float(timeout_s)
    except Exception as e:
        raise NodesScreenCaptureInputError("timeout_s must be a number") from e
    if timeout_s_f <= 0:
        raise NodesScreenCaptureInputError("timeout_s must be > 0")

    include_image_b64 = data.get("include_image_b64", data.get("include_image", False))
    if not isinstance(include_image_b64, bool):
        raise NodesScreenCaptureInputError("include_image_b64 must be a boolean")

    save_path_raw = data.get("save_path", data.get("out"))
    save_path: Optional[Path]
    save_path_is_dir = False

    if save_path_raw is None or save_path_raw == "":
        save_path = None
    elif isinstance(save_path_raw, (str, os.PathLike)):
        # Preserve a directory-hint from trailing slash for nicer CLI UX.
        save_path_str = str(save_path_raw).strip()
        if not save_path_str:
            save_path = None
        else:
            if save_path_str.endswith(("/", "\\")):
                save_path_is_dir = True
            save_path = Path(save_path_str)
    else:
        raise NodesScreenCaptureInputError("save_path must be a path string")

    return NodesScreenCaptureRequest(
        node_id=node_id.strip(),
        image_format=image_format,
        save_path=save_path,
        save_path_is_dir=save_path_is_dir,
        include_image_b64=include_image_b64,
        timeout_s=timeout_s_f,
    )


@dataclass(frozen=True, slots=True)
class HttpScreenCaptureTransport:
    """HTTP transport to request a screenshot from a node service."""

    base_url: str
    api_key: Optional[str] = None
    path_template: str = DEFAULT_HTTP_PATH_TEMPLATE
    method: str = DEFAULT_HTTP_METHOD

    async def capture_screen(
        self,
        node_id: str,
        *,
        image_format: str,
        timeout_s: float,
    ) -> bytes:
        try:
            import aiohttp  # type: ignore
        except Exception as e:  # pragma: no cover
            raise NodesScreenCaptureExternalError("aiohttp is required for HTTP transport") from e

        url = self.base_url.rstrip("/") + self.path_template.format(node_id=node_id)
        headers: dict[str, str] = {"Accept": "application/octet-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        method = (self.method or "POST").upper().strip()

        timeout = aiohttp.ClientTimeout(total=timeout_s)  # type: ignore[attr-defined]
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:  # type: ignore[attr-defined]
                if method == "POST":
                    async with session.post(
                        url, json={"image_format": image_format}, headers=headers
                    ) as resp:
                        if resp.status != 200:
                            raise NodesScreenCaptureExternalError(
                                f"screen capture request failed (status={resp.status})"
                            )
                        return await resp.read()
                if method == "GET":
                    async with session.get(
                        url, params={"image_format": image_format}, headers=headers
                    ) as resp:
                        if resp.status != 200:
                            raise NodesScreenCaptureExternalError(
                                f"screen capture request failed (status={resp.status})"
                            )
                        return await resp.read()

                raise NodesScreenCaptureExternalError(
                    f"unsupported HTTP method for screen capture: {self.method!r}"
                )
        except NodesScreenCaptureError:
            raise
        except Exception as e:
            raise NodesScreenCaptureExternalError("screen capture request failed") from e


def build_transport_from_config(config: Optional[Mapping[str, Any]] = None) -> ScreenCaptureTransport:
    """Build the default transport from config and environment.

    Required:
        - nodes_base_url (or env THOMAS_NODES_BASE_URL)

    Optional:
        - nodes_api_key
        - nodes_screen_capture_path_template (or env THOMAS_NODES_SCREEN_CAPTURE_PATH_TEMPLATE)
        - nodes_screen_capture_method (or env THOMAS_NODES_SCREEN_CAPTURE_METHOD)
    """
    base_url = _first_nonempty_str(
        config, ("nodes_base_url", "nodes_url", "base_url", "url")
    ) or os.getenv("THOMAS_NODES_BASE_URL") or os.getenv("NODES_BASE_URL")
    if not base_url:
        raise NodesScreenCaptureConfigError("missing nodes base URL (nodes_base_url)")

    api_key = _first_nonempty_str(config, ("nodes_api_key", "api_key")) or os.getenv(
        "THOMAS_NODES_API_KEY"
    )

    path_template = _first_nonempty_str(
        config,
        (
            "nodes_screen_capture_path_template",
            "nodes_capture_screen_path_template",
            "nodes_screen_capture_endpoint",
        ),
    ) or os.getenv("THOMAS_NODES_SCREEN_CAPTURE_PATH_TEMPLATE") or DEFAULT_HTTP_PATH_TEMPLATE

    method = _first_nonempty_str(
        config, ("nodes_screen_capture_method", "method")
    ) or os.getenv("THOMAS_NODES_SCREEN_CAPTURE_METHOD") or DEFAULT_HTTP_METHOD

    return HttpScreenCaptureTransport(
        base_url=base_url,
        api_key=api_key,
        path_template=path_template,
        method=method,
    )


async def run_nodes_screen_capture(
    request: NodesScreenCaptureRequest,
    *,
    transport: Optional[ScreenCaptureTransport] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> NodesScreenCaptureResult:
    """Execute the node screen capture action."""
    tr = transport or build_transport_from_config(config)

    try:
        image_bytes = await tr.capture_screen(
            request.node_id,
            image_format=request.image_format,
            timeout_s=request.timeout_s,
        )
    except NodesScreenCaptureError:
        raise
    except Exception as e:
        raise NodesScreenCaptureExternalError("screen capture failed") from e

    if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
        raise NodesScreenCaptureExternalError("screen capture returned empty image")

    image_b = bytes(image_bytes)

    saved_path_str: Optional[str] = None
    if request.save_path is not None:
        out_path = request.save_path
        try:
            is_dir = bool(request.save_path_is_dir) or (out_path.exists() and out_path.is_dir())
            if is_dir:
                out_dir = out_path
                out_dir.mkdir(parents=True, exist_ok=True)
                base = _safe_filename_component(request.node_id)
                ts = _utc_compact_timestamp()
                out_path = out_dir / f"{base}-{ts}.{request.image_format}"
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if out_path.suffix == "":
                    out_path = out_path.with_suffix("." + request.image_format)

            out_path.write_bytes(image_b)
            saved_path_str = str(out_path)
        except Exception as e:
            raise NodesScreenCaptureExternalError("failed to write screenshot to disk") from e

    image_b64: Optional[str] = None
    if request.include_image_b64:
        image_b64 = base64.b64encode(image_b).decode("ascii")

    return NodesScreenCaptureResult(
        node_id=request.node_id,
        image_format=request.image_format,
        captured_at=_iso_utc_now(),
        bytes_captured=len(image_b),
        saved_path=saved_path_str,
        image_b64=image_b64,
    )


def run_nodes_screen_capture_sync(
    request: NodesScreenCaptureRequest,
    *,
    transport: Optional[ScreenCaptureTransport] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> NodesScreenCaptureResult:
    """Synchronous wrapper."""
    import asyncio

    return asyncio.run(run_nodes_screen_capture(request, transport=transport, config=config))


def get_action_metadata() -> dict[str, Any]:
    """Action metadata for registries and HTTP route schema generation."""
    return {
        "prompt_id": PROMPT_ID,
        "action": ACTION_SLUG,
        "description": "Capture a screenshot from a node.",
        "input": {
            "type": "object",
            "required": ["node_id"],
            "properties": {
                "node_id": {"type": "string"},
                "image_format": {"type": "string", "enum": list(SUPPORTED_IMAGE_FORMATS)},
                "save_path": {"type": ["string", "null"]},
                "include_image_b64": {"type": "boolean"},
                "timeout_s": {"type": "number"},
            },
        },
        "output": {
            "type": "object",
            "required": ["node_id", "image_format", "captured_at", "bytes_captured"],
            "properties": {
                "node_id": {"type": "string"},
                "image_format": {"type": "string"},
                "captured_at": {"type": "string"},
                "bytes_captured": {"type": "integer"},
                "saved_path": {"type": ["string", "null"]},
                "image_b64": {"type": ["string", "null"]},
            },
        },
        "errors": [
            {"code": "invalid_input"},
            {"code": "missing_config"},
            {"code": "external_failure"},
        ],
    }


async def run_action_from_raw(
    raw: Mapping[str, Any],
    *,
    transport: Optional[ScreenCaptureTransport] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """JSON-friendly entrypoint for route handlers."""
    req = parse_nodes_screen_capture_request(raw)
    res = await run_nodes_screen_capture(req, transport=transport, config=config)
    return res.to_dict()
