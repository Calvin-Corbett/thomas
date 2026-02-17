"""Model discovery helpers.

Goal: given a configured model profile, try to list model ids available at its
endpoint so REPL/UI can offer a better /model experience.

This is best-effort. Many "OpenAI-compatible" servers do not implement
`GET /models`, and some local runtimes (Ollama) use different endpoints.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from thomas.core.config import ModelConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredModel:
    """A discovered model identifier and optional metadata."""

    id: str
    raw: Dict[str, Any]


@dataclass(frozen=True)
class ModelsHandshake:
    """Result of a provider handshake attempt (model listing)."""

    ok: bool
    status: str  # ok | auth_error | unsupported | offline | error
    url: str
    http_status: Optional[int] = None
    models: List[str] = None  # type: ignore[assignment]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "status": str(self.status),
            "url": str(self.url),
            "http_status": int(self.http_status) if self.http_status is not None else None,
            "models": list(self.models or []),
            "error": str(self.error) if self.error else None,
        }


def _join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    p = path or ""
    if not p.startswith("/"):
        p = "/" + p
    return base + p


def _auth_headers(cfg: ModelConfig) -> Dict[str, str]:
    # Keep this consistent with LLMClient header behavior.
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if cfg.extra_headers:
        headers.update(cfg.extra_headers)

    if cfg.api_key:
        if cfg.provider == "anthropic":
            headers["x-api-key"] = cfg.api_key
            headers.setdefault("anthropic-version", "2023-06-01")
        else:
            header_name = cfg.api_key_header or "Authorization"
            prefix = cfg.api_key_prefix or ""
            headers[header_name] = f"{prefix}{cfg.api_key}"
    return headers


def _extract_model_ids(obj: Any, *, max_results: int = 200) -> List[str]:
    """Best-effort extraction of model ids from common response shapes."""
    out: List[str] = []

    # OpenAI-compatible: {"data": [{"id": "..."}]}
    if isinstance(obj, dict):
        data = obj.get("data")
        if isinstance(data, list):
            for item in data[:max_results]:
                if isinstance(item, dict) and item.get("id"):
                    out.append(str(item["id"]))

    # Ollama tags: {"models": [{"name": "..."}]}
    if not out and isinstance(obj, dict):
        models = obj.get("models")
        if isinstance(models, list):
            for item in models[:max_results]:
                if isinstance(item, dict) and item.get("name"):
                    out.append(str(item["name"]))

    # De-dupe while preserving order.
    seen: set[str] = set()
    out = [x for x in out if not (x in seen or seen.add(x))]
    return out


async def handshake_models_async(
    cfg: ModelConfig,
    *,
    timeout_s: float = 2.0,
    max_results: int = 200,
) -> ModelsHandshake:
    """Perform a model-list handshake for a profile.

    This is stricter than discover_models_async: it returns auth/offline errors so the UI can
    clearly show whether a cloud provider is actually usable.
    """
    if cfg.provider == "codex":
        return await _handshake_codex_async(cfg, timeout_s=timeout_s, max_results=max_results)

    headers = _auth_headers(cfg)
    params = cfg.query or None
    url = _join_url(cfg.base_url, cfg.models_path or "/models")

    async with httpx.AsyncClient(headers=headers, timeout=timeout_s) as client:
        try:
            resp = await client.get(url, params=params)
        except Exception as e:
            return ModelsHandshake(ok=False, status="offline", url=url, error=f"{type(e).__name__}: {e}", models=[])

        status = int(resp.status_code)
        if status == 200:
            try:
                j = resp.json()
            except Exception as e:
                return ModelsHandshake(ok=False, status="error", url=url, http_status=status, error=f"Invalid JSON: {e}", models=[])
            ids = _extract_model_ids(j, max_results=max_results)
            return ModelsHandshake(ok=True, status="ok", url=url, http_status=status, models=ids)

        # Common auth errors.
        if status in (401, 403):
            text = ""
            try:
                text = (await resp.aread()).decode("utf-8", errors="replace").strip()
            except Exception as e:
                log.debug("Failed to read auth error response body: %s", e)
            msg = text[:280] if text else f"HTTP {status}"
            return ModelsHandshake(ok=False, status="auth_error", url=url, http_status=status, error=msg, models=[])

        # /models not supported by some OpenAI-compatible servers.
        if status in (404, 405):
            # Try Ollama tags as a fallback (common local case).
            try:
                base = cfg.base_url.rstrip("/")
                if base.endswith("/v1"):
                    base = base[:-3]
                tags_url = _join_url(base, "/api/tags")
                tags_resp = await client.get(tags_url)
                if tags_resp.status_code == 200:
                    try:
                        tags_j = tags_resp.json()
                        ids = _extract_model_ids(tags_j, max_results=max_results)
                        if ids:
                            return ModelsHandshake(ok=True, status="ok", url=tags_url, http_status=200, models=ids)
                    except Exception as e:
                        log.debug("Failed to parse Ollama tags response at %s: %s", tags_url, e)
            except Exception as e:
                log.debug("Ollama tags fallback failed for %s: %s", cfg.base_url, e)

            return ModelsHandshake(ok=False, status="unsupported", url=url, http_status=status, error=f"HTTP {status} (no /models)", models=[])

        # Other errors.
        text = ""
        try:
            text = (await resp.aread()).decode("utf-8", errors="replace").strip()
        except Exception as e:
            log.debug("Failed to read non-auth error response body: %s", e)
        msg = text[:280] if text else f"HTTP {status}"
        return ModelsHandshake(ok=False, status="error", url=url, http_status=status, error=msg, models=[])


async def _handshake_codex_async(
    cfg: ModelConfig,
    *,
    timeout_s: float = 2.0,
    max_results: int = 200,
) -> ModelsHandshake:
    """Handshake for the Codex app-server provider (no HTTP /models)."""
    # Starting the app-server can take longer than an HTTP probe; allow a floor.
    timeout = max(float(timeout_s), 8.0)

    async def _run() -> ModelsHandshake:
        try:
            from thomas.codex.bridge import CodexBridge, CodexBridgeError
        except Exception as e:
            return ModelsHandshake(
                ok=False,
                status="unsupported",
                url="codex:app-server",
                error=f"Codex integration unavailable: {type(e).__name__}: {e}",
                models=[],
            )

        bridge = CodexBridge(cwd=None)
        try:
            await bridge.start()

            acct = await bridge.check_auth()
            if not acct.logged_in:
                return ModelsHandshake(
                    ok=False,
                    status="auth_error",
                    url="codex:app-server",
                    error="Not logged in to ChatGPT. Select the Codex profile and send a message to start the sign-in flow.",
                    models=[],
                )

            models = await bridge.list_models()
            ids: List[str] = [m.id for m in models if m.id][:max_results]
            # De-dupe while preserving order.
            seen: set[str] = set()
            ids = [x for x in ids if not (x in seen or seen.add(x))]
            return ModelsHandshake(ok=True, status="ok", url="codex:app-server", http_status=None, models=ids)

        except CodexBridgeError as e:
            msg = str(e).strip() or "Codex error"
            status = "auth_error" if "login" in msg.lower() or "auth" in msg.lower() else "error"
            return ModelsHandshake(ok=False, status=status, url="codex:app-server", error=msg, models=[])
        except Exception as e:
            return ModelsHandshake(
                ok=False,
                status="error",
                url="codex:app-server",
                error=f"{type(e).__name__}: {e}",
                models=[],
            )
        finally:
            try:
                await bridge.stop()
            except Exception as e:
                log.debug("Failed to stop Codex bridge after handshake: %s", e)

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        return ModelsHandshake(
            ok=False,
            status="offline",
            url="codex:app-server",
            error=f"Timed out starting Codex app-server after {timeout:.1f}s",
            models=[],
        )


async def discover_models_async(
    cfg: ModelConfig,
    *,
    timeout_s: float = 2.0,
    max_results: int = 200,
) -> List[DiscoveredModel]:
    """Try to discover model ids for a model profile.

    Strategies:
    1. OpenAI-compatible: GET {base_url}{models_path} expecting {"data":[{"id":...},...]}.
    2. Ollama fallback: GET {base_without_/v1}/api/tags expecting {"models":[{"name":...},...]}.
    """
    if cfg.provider == "codex":
        hs = await _handshake_codex_async(cfg, timeout_s=timeout_s, max_results=max_results)
        if hs.ok and hs.models:
            return [DiscoveredModel(id=m, raw={}) for m in (hs.models or [])]
        return []

    headers = _auth_headers(cfg)
    params = cfg.query or None

    async with httpx.AsyncClient(headers=headers, timeout=timeout_s) as client:
        # 1) OpenAI-compatible /models
        if cfg.provider != "anthropic":
            try:
                url = _join_url(cfg.base_url, cfg.models_path or "/models")
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    j = resp.json()
                    data = j.get("data", [])
                    out: List[DiscoveredModel] = []
                    for item in data[:max_results]:
                        if isinstance(item, dict) and item.get("id"):
                            out.append(DiscoveredModel(id=str(item["id"]), raw=item))
                    if out:
                        return out
            except Exception as e:
                log.debug("OpenAI-compatible model discovery failed for %s: %s", cfg.base_url, e)

        # 2) Ollama /api/tags (works even when base_url is /v1)
        try:
            base = cfg.base_url.rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            url = _join_url(base, "/api/tags")
            resp = await client.get(url)
            if resp.status_code == 200:
                j = resp.json()
                models = j.get("models", [])
                out = []
                for item in models[:max_results]:
                    if isinstance(item, dict) and item.get("name"):
                        out.append(DiscoveredModel(id=str(item["name"]), raw=item))
                return out
        except Exception as e:
            log.debug("Ollama tags discovery failed for %s: %s", cfg.base_url, e)

    return []


def discover_models(cfg: ModelConfig, *, timeout_s: float = 2.0) -> List[DiscoveredModel]:
    """Sync wrapper for discovery (for click commands)."""
    return asyncio.run(discover_models_async(cfg, timeout_s=timeout_s))


def parse_params_b(model_id: str) -> Optional[float]:
    """Best-effort parse of parameter count from an id (e.g. '7b', '30B')."""
    import re

    m = re.search(r"(\\d+(?:\\.\\d+)?)\\s*b\\b", model_id, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def model_family(model_id: str) -> str:
    """Best-effort family grouping for above/below suggestions."""
    if ":" in model_id:
        return model_id.split(":", 1)[0]
    if "/" in model_id:
        return model_id.rsplit("/", 1)[-1]
    return model_id
