"""Intent, privacy, voice, and cached-LLM support for Chat V2."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from thomas.core.llm import LLMClient
from thomas.server.routes.chat_v2_keys import APP_SESSION_LLM_CACHE, APP_VOICE_BRIDGE
from thomas.tools.voice import VoiceBridge

log = logging.getLogger(__name__)


@dataclass
class _CachedSessionLLM:
    llm: Any
    signature: tuple[str, str, str, str, str]
    lock: asyncio.Lock


_UNSUPPORTED_GAP_CLAIM_RE = re.compile(
    r"\b(?:missing|outstanding|unfinished|not included|wasn['â€™]?t created|weren['â€™]?t created|not yet)\b|"
    r"\b(?:other|remaining|next)\s+(?:item|task|deliverable)\b|"
    r"\b(?:item|task|deliverable)\s+(?:is|remains?)\s+(?:pending|remaining)\b|"
    r"\bstill\s+needs?\s+to\b|\bneeds?\s+to\s+be\s+(?:created|completed|finished)\b|"
    r"\b(?:isn['Ã¢â‚¬â„¢]?t|is\s+not)\s+(?:ready|done|finished|complete|completed)\b|"
    r"\b(?:i|we)\s+(?:didn['Ã¢â‚¬â„¢]?t|did\s+not|haven['Ã¢â‚¬â„¢]?t|have\s+not)\s+"
    r"(?:finish|complete|create|build|make|produce|deliver)\b|"
    r"\bstill\s+(?:pending|unfinished|outstanding|not\s+ready)\b|\bhas\s+yet\s+to\b|"
    r"\bforthcoming\b|\bcoming\s+(?:soon|shortly|later)\b|"
    r"\b(?:the\s+)?(?:rest|remainder)\s+(?:will|should|is\s+going\s+to)\s+"
    r"(?:follow|come|arrive)\b|\b(?:will|to)\s+follow\s+(?:soon|shortly|later)\b",
    re.IGNORECASE,
)
_EXTERNAL_TOOL_PREFIXES = (
    "browser.",
    "web.",
    "http.",
    "network.",
    "email.",
    "calendar.",
    "connector.",
    "channel.",
    "slack.",
    "discord.",
)


def _uploaded_audio_format(filename: str = "", content_type: str = "") -> str:
    name = str(filename or "").strip().lower()
    mime = str(content_type or "").strip().lower()
    if "." in name:
        ext = name.rsplit(".", 1)[-1]
        if ext in {"wav", "wave", "mp3", "mpeg", "ogg", "oga", "flac", "webm", "m4a", "mp4"}:
            return "wav" if ext == "wave" else ("ogg" if ext == "oga" else ("mp3" if ext == "mpeg" else ext))
    for marker, audio_format in (
        ("webm", "webm"),
        ("ogg", "ogg"),
        ("mpeg", "mp3"),
        ("mp3", "mp3"),
        ("flac", "flac"),
        ("mp4", "m4a"),
        ("m4a", "m4a"),
    ):
        if marker in mime:
            return audio_format
    return "wav"


async def _voice_bridge_for_request(app: web.Application) -> VoiceBridge:
    from thomas.server.routes import chat_v2

    bridge_type = getattr(chat_v2, "VoiceBridge", VoiceBridge)
    bridge = app.get(APP_VOICE_BRIDGE)
    if isinstance(bridge, bridge_type):
        return bridge
    bridge = bridge_type()
    app[APP_VOICE_BRIDGE] = bridge
    return bridge


def _normalize_reasoning_effort(value: str) -> str:
    level = str(value or "").strip().lower()
    return level if level in {"none", "low", "medium", "high", "xhigh", "max"} else ""


def _privacy_bool(value: Any, *, default: bool) -> bool:
    if value is None or isinstance(value, bool):
        return default if value is None else value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "allow", "allowed"}:
        return True
    if normalized in {"0", "false", "no", "off", "deny", "denied", "blocked"}:
        return False
    return default


def _resolve_privacy_controls(payload: dict[str, Any]) -> tuple[bool, bool]:
    temporary = _privacy_bool(payload.get("temporary", payload.get("temporary_chat")), default=False)
    external_access = True
    for key in ("external_access", "external_service_access", "network_access", "allow_network"):
        if key in payload:
            external_access = external_access and _privacy_bool(payload.get(key), default=True)
    return temporary, external_access


def _is_external_tool_name(name: str) -> bool:
    canonical = str(name or "").strip().lower()
    for wrapper in ("functions.", "function.", "tool.", "tools.", "mcp.", "mcp__"):
        if canonical.startswith(wrapper):
            canonical = canonical[len(wrapper) :]
            break
    return canonical.startswith(_EXTERNAL_TOOL_PREFIXES)


class _PrivacyRestrictedTools:
    """Request-scoped registry view that fails closed for external tools."""

    def __init__(self, base: Any):
        self._base = base
        self.denied: list[str] = []

    def get(self, name: str) -> Any | None:
        return None if _is_external_tool_name(name) else self._base.get(name)

    def list_tools(self, category: str | None = None) -> list[Any]:
        return [
            tool for tool in self._base.list_tools(category) if not _is_external_tool_name(getattr(tool, "name", ""))
        ]

    def list_categories(self) -> list[str]:
        return sorted(
            {str(getattr(tool, "category", "")) for tool in self.list_tools() if getattr(tool, "category", "")}
        )

    def search(self, query: str, limit: int = 10) -> list[Any]:
        return [
            tool
            for tool in self._base.search(query, limit=limit)
            if not _is_external_tool_name(getattr(tool, "name", ""))
        ][:limit]

    def get_openai_specs(self, category: str | None = None) -> list[dict[str, Any]]:
        return [tool.get_spec().to_openai() for tool in self.list_tools(category)]

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        if _is_external_tool_name(name):
            from thomas.tools.base import ToolResult

            self.denied.append(str(name))
            return ToolResult(ok=False, error="External access is disabled by this chat's privacy controls.")
        return await self._base.execute(name, args)

    def __len__(self) -> int:
        return len(self.list_tools())

    def __contains__(self, name: str) -> bool:
        return not _is_external_tool_name(name) and name in self._base

    def __iter__(self):
        return iter(self.list_tools())

    def __bool__(self) -> bool:
        return bool(self.list_tools())


def _llm_signature(model_cfg: Any) -> tuple[str, str, str, str, str]:
    return tuple(
        str(getattr(model_cfg, field, "") or "").strip().lower()
        if field == "provider"
        else str(getattr(model_cfg, field, "") or "").strip()
        for field in ("provider", "base_url", "api_key", "api_key_header", "api_key_prefix")
    )  # type: ignore[return-value]


def _refresh_cached_llm(
    entry: _CachedSessionLLM,
    *,
    model_cfg: Any,
    fallback_cfgs: list[Any],
    failover_enabled: bool,
    failover_cooldown_s: int = 300,
    failover_on_auth_error: bool = False,
    max_retries: int = 3,
    base_retry_delay_s: float = 0.8,
    request_overrides: dict[str, Any] | None = None,
) -> Any:
    llm = entry.llm
    llm.config = model_cfg
    if hasattr(llm, "_primary_config"):
        llm._primary_config = model_cfg
    if hasattr(llm, "_fallback_configs"):
        llm._fallback_configs = list(fallback_cfgs or [])
    if hasattr(llm, "_failover_enabled"):
        llm._failover_enabled = bool(failover_enabled and fallback_cfgs)
    if hasattr(llm, "_failover_cooldown_s"):
        llm._failover_cooldown_s = max(0, int(failover_cooldown_s))
    if hasattr(llm, "_failover_on_auth_error"):
        llm._failover_on_auth_error = bool(failover_on_auth_error)
    if hasattr(llm, "_max_retries"):
        llm._max_retries = max(1, int(max_retries))
    if hasattr(llm, "_base_retry_delay"):
        llm._base_retry_delay = max(0.0, float(base_retry_delay_s))
    if hasattr(llm, "_request_overrides"):
        llm._request_overrides = dict(request_overrides or {})
    return llm


async def _close_cached_llm(llm: Any) -> None:
    close = getattr(llm, "close", None)
    if callable(close):
        await close()


async def _close_cached_llm_safely(llm: Any, *, reason: str) -> None:
    try:
        await _close_cached_llm(llm)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning("Cached Chat LLM close failed during %s (%s)", reason, type(exc).__name__)


async def _get_or_create_session_llm(
    app: web.Application,
    *,
    session_id: str,
    model_cfg: Any,
    fallback_cfgs: list[Any],
    failover_enabled: bool,
    failover_cooldown_s: int = 300,
    failover_on_auth_error: bool = False,
    max_retries: int = 3,
    base_retry_delay_s: float = 0.8,
    request_overrides: dict[str, Any] | None = None,
) -> tuple[Any, asyncio.Lock]:
    cache = app[APP_SESSION_LLM_CACHE]
    signature = _llm_signature(model_cfg)
    entry = cache.get(session_id)
    if entry is not None and entry.signature == signature:
        return (
            _refresh_cached_llm(
                entry,
                model_cfg=model_cfg,
                fallback_cfgs=fallback_cfgs,
                failover_enabled=failover_enabled,
                failover_cooldown_s=failover_cooldown_s,
                failover_on_auth_error=failover_on_auth_error,
                max_retries=max_retries,
                base_retry_delay_s=base_retry_delay_s,
                request_overrides=request_overrides,
            ),
            entry.lock,
        )
    preserved_lock = entry.lock if entry is not None else asyncio.Lock()
    if entry is not None:
        await _close_cached_llm_safely(entry.llm, reason="replacement")
    # Keep the old route-level patch seam while the implementation lives here.
    from thomas.server.routes import chat_v2

    llm_type = getattr(chat_v2, "LLMClient", LLMClient)
    llm = llm_type(
        model_cfg,
        fallback_configs=fallback_cfgs,
        failover_enabled=failover_enabled,
        failover_cooldown_s=failover_cooldown_s,
        failover_on_auth_error=failover_on_auth_error,
        max_retries=max_retries,
        base_retry_delay_s=base_retry_delay_s,
        request_overrides=request_overrides,
    )
    new_entry = _CachedSessionLLM(llm=llm, signature=signature, lock=preserved_lock)
    cache[session_id] = new_entry
    return (
        _refresh_cached_llm(
            new_entry,
            model_cfg=model_cfg,
            fallback_cfgs=fallback_cfgs,
            failover_enabled=failover_enabled,
            failover_cooldown_s=failover_cooldown_s,
            failover_on_auth_error=failover_on_auth_error,
            max_retries=max_retries,
            base_retry_delay_s=base_retry_delay_s,
            request_overrides=request_overrides,
        ),
        new_entry.lock,
    )


async def _evict_session_llm(app: web.Application, session_id: str) -> None:
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    entry = cache.pop(session_id, None)
    if entry is not None:
        await _close_cached_llm_safely(entry.llm, reason="session eviction")


async def _cleanup_cached_session_llms(app: web.Application) -> None:
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    entries = list(cache.values())
    cache.clear()
    for entry in entries:
        await _close_cached_llm_safely(entry.llm, reason="application cleanup")


__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]
