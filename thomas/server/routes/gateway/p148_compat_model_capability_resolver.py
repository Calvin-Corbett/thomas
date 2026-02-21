from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, TypedDict


class CompatModelCapabilityResolverError(Exception):
    """Internal exception used to convert failures into deterministic, machine-readable errors."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class CompatModelCapabilityRequest(TypedDict):
    model: str


@dataclass(frozen=True)
class CompatModelCapabilities:
    """Small, conservative capability descriptor for compat layers.

    NOTE: This resolver is intentionally "boring":
      - If we can't confidently infer something, we default to False.
      - Deployments can override the result deterministically with config.
    """

    model: str
    family: str

    # API surfaces
    supports_chat_completions: bool
    supports_responses_api: bool

    # Interaction
    supports_streaming: bool
    supports_function_tools: bool
    supports_json_schema_response_format: bool

    # Hints (optional metadata for callers; safe to ignore)
    notes: Sequence[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompatModelCapabilityResolverResult:
    ok: bool
    capabilities: Optional[CompatModelCapabilities] = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        if self.ok and self.capabilities is not None:
            return {"ok": True, "capabilities": self.capabilities.to_dict()}
        return {
            "ok": False,
            "error": self.error or {"code": "unknown_error", "message": "Unknown error"},
        }


def _load_caps_override_map() -> Dict[str, Dict[str, Any]]:
    """Optional override map for deployments that want explicit control.

    Env var: THOMAS_COMPAT_MODEL_CAPS_JSON
      - either a JSON object string
      - or a filesystem path to a JSON file containing an object

    Format:
      {
        "gpt-4.1-mini": {"supports_streaming": true, ...},
        "my-prefix:*": {"supports_responses_api": false}
      }
    """

    raw = os.environ.get("THOMAS_COMPAT_MODEL_CAPS_JSON", "").strip()
    if not raw:
        return {}

    try:
        if raw.startswith("{"):
            data = json.loads(raw)
        else:
            with open(raw, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception as e:
        raise CompatModelCapabilityResolverError(
            code="invalid_config",
            message=(
                "Failed to load THOMAS_COMPAT_MODEL_CAPS_JSON "
                "(must be JSON object string or path to JSON file)."
            ),
            details={"exception": type(e).__name__},
        )

    if not isinstance(data, dict):
        raise CompatModelCapabilityResolverError(
            code="invalid_config",
            message=(
                "THOMAS_COMPAT_MODEL_CAPS_JSON must be a JSON object mapping "
                "model keys to capability objects."
            ),
        )

    out: Dict[str, Dict[str, Any]] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k] = v
    return out


def _match_override(model: str, override_map: Mapping[str, Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if model in override_map:
        return override_map[model]
    for k, v in override_map.items():
        if k.endswith(":*") and model.startswith(k[:-2]):
            return v
    return None


def _infer_family(model: str) -> str:
    m = model.lower().strip()
    if m.startswith(("gpt-", "o1", "o3", "o4")) or "openai" in m:
        return "openai_like"
    if "claude" in m:
        return "anthropic_like"
    if "gemini" in m:
        return "google_like"
    if any(tok in m for tok in ("llama", "mistral", "qwen", "deepseek", "mixtral")):
        return "oss_like"
    return "unknown"


def _heuristic_caps(model: str) -> CompatModelCapabilities:
    """Heuristic inference. Conservative by design."""

    family = _infer_family(model)
    m = model.lower().strip()
    notes = []

    supports_chat = True
    supports_responses = True
    supports_streaming = True
    supports_tools = True
    supports_schema = False

    # Enable schema only for obvious modern OpenAI-ish families.
    if (
        re.search(r"\bgpt-4(\.|-|$)", m)
        or re.search(r"\bgpt-4o(\.|-|$)", m)
        or re.search(r"\bgpt-4\.1\b", m)
    ):
        supports_schema = True
        notes.append("heuristic: gpt-4-family enables json_schema response format")

    # OSS/unknown backends are too variable; keep schema false unless overridden.
    if family in {"oss_like", "unknown"} and supports_schema:
        supports_schema = False
        notes.append("conservative: oss_like/unknown disables json_schema unless overridden")

    if family == "unknown":
        notes.append("family unknown; capabilities are conservative defaults")

    return CompatModelCapabilities(
        model=model,
        family=family,
        supports_chat_completions=supports_chat,
        supports_responses_api=supports_responses,
        supports_streaming=supports_streaming,
        supports_function_tools=supports_tools,
        supports_json_schema_response_format=supports_schema,
        notes=tuple(notes),
    )


def resolve_compat_model_capabilities(req: CompatModelCapabilityRequest) -> CompatModelCapabilityResolverResult:
    model = (req.get("model") or "").strip()
    if not model:
        return CompatModelCapabilityResolverResult(
            ok=False,
            error={"code": "invalid_input", "message": "Field 'model' is required and must be non-empty."},
        )

    try:
        override_map = _load_caps_override_map()
    except CompatModelCapabilityResolverError as e:
        return CompatModelCapabilityResolverResult(
            ok=False,
            error={"code": e.code, "message": e.message, "details": e.details},
        )

    caps = _heuristic_caps(model)

    ov = _match_override(model, override_map)
    if ov:
        merged = caps.to_dict()
        for k, v in ov.items():
            if k not in merged:
                continue
            if isinstance(merged[k], bool) and isinstance(v, bool):
                merged[k] = v
            elif isinstance(merged[k], str) and isinstance(v, str):
                merged[k] = v
            elif k == "notes" and isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v):
                merged[k] = tuple(v)
        caps = CompatModelCapabilities(**merged)  # type: ignore[arg-type]

    return CompatModelCapabilityResolverResult(ok=True, capabilities=caps)


# ----------------------------------------------------------------------------
# Route integration (best-effort, minimal coupling).
#
# We can't assume the gateway loader contract here, so we provide multiple hooks:
#   - register_routes(router)
#   - get_routes() -> list[(method, path, handler)]
# ----------------------------------------------------------------------------


async def handle_p148_compat_model_capability_resolver(request):  # pragma: no cover
    """AIOHTTP handler.

    - GET  /gateway/compat/model-capabilities?model=...
    - POST /gateway/compat/model-capabilities  {"model": "..."}
    """

    try:
        if request.method.upper() == "GET":
            model = (request.query.get("model") or "").strip()
            payload: Dict[str, Any] = {"model": model}
        else:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        result = resolve_compat_model_capabilities(payload)  # type: ignore[arg-type]
        return _aiohttp_json(result.to_dict(), status=200 if result.ok else 400)
    except Exception as e:
        err = {
            "code": "external_failure",
            "message": "Unhandled failure.",
            "details": {"exception": type(e).__name__},
        }
        return _aiohttp_json({"ok": False, "error": err}, status=500)


def get_routes() -> Sequence[Tuple[str, str, Any]]:  # pragma: no cover
    return (
        ("GET", "/gateway/compat/model-capabilities", handle_p148_compat_model_capability_resolver),
        ("POST", "/gateway/compat/model-capabilities", handle_p148_compat_model_capability_resolver),
    )


def register_routes(router) -> None:  # pragma: no cover
    for method, path, handler in get_routes():
        router.add_route(method, path, handler)


def _aiohttp_json(data: Dict[str, Any], status: int = 200):  # pragma: no cover
    from aiohttp import web

    return web.json_response(data, status=status)
