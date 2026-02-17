from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp


@dataclass
class ChatAdapterConfig:
    base_url: str = "http://127.0.0.1:8080"
    timeout_s: float = 120.0
    api_token: Optional[str] = None


class ChatAdapter:
    """Adapter for interacting with Thomas chat sessions.

    This module is intentionally defensive: it can post into an existing chat session
    via (1) an in-process callable if provided, or (2) loopback HTTP to /api/chat.

    Your Thomas app can optionally inject:
      app["chat_submit_json"]: async callable(payload: dict) -> dict
    """

    def __init__(self, *, app: Optional[Any] = None, cfg: Optional[ChatAdapterConfig] = None):
        self._app = app
        self._cfg = cfg or ChatAdapterConfig()

    async def submit_chat_json(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Prefer in-process hook
        if self._app is not None and hasattr(self._app, "get"):
            fn = self._app.get("chat_submit_json")
            if fn is not None:
                return await fn(payload)

        # Fallback: loopback HTTP
        headers = {"Content-Type": "application/json"}
        if self._cfg.api_token:
            headers["Authorization"] = f"Bearer {self._cfg.api_token}"

        timeout = aiohttp.ClientTimeout(total=self._cfg.timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._cfg.base_url + "/api/chat", json=payload, headers=headers) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"/api/chat HTTP {resp.status}: {text[:500]}")
                # We don't know exact response shape; try JSON
                try:
                    return json.loads(text)
                except Exception:
                    return {"raw": text}

    async def generate_json(
        self,
        *,
        schema_hint: Dict[str, Any],
        session_id: Optional[str] = None,
        # Preferred parameter names (used by some Thomas codepaths)
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        # Aliases for compatibility with other internal helpers
        system: Optional[str] = None,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ask Thomas chat to return a JSON object.

        This adapter is intentionally flexible about argument names because
        different parts of Thomas may call it with slightly different keywords.
        """

        sys = (system_prompt if system_prompt is not None else system) or ""
        usr = (user_prompt if user_prompt is not None else user) or ""

        # The /api/chat payload shape may differ per install.
        # We send a conservative schema: system + user messages, request JSON.
        # Your in-process hook can translate this to whatever Thomas expects.
        payload = {
            "session_id": session_id,
            "messages": [
                {"role": "system", "content": sys},
                {"role": "user", "content": usr},
            ],
            "response_format": {"type": "json_object"},
            "metadata": {"schema_hint": schema_hint, "source": "autonomy_engine"},
        }
        return await self.submit_chat_json(payload)


class MemoryAdapter:
    """Adapter for reading/writing memory context.

    Thomas has a richer memory system; to keep this patch self-contained, we provide a thin
    optional integration point:
      app["memory_append"]: callable(event: dict) -> None OR async callable
      app["memory_query"]: callable(query: dict) -> dict/list OR async callable
    """

    def __init__(self, *, app: Optional[Any] = None):
        self._app = app

    async def append(self, event: Dict[str, Any]) -> None:
        if self._app is None or not hasattr(self._app, "get"):
            return
        fn = self._app.get("memory_append")
        if fn is None:
            return
        res = fn(event)
        if asyncio.iscoroutine(res):
            await res

    async def query(self, query: Dict[str, Any]) -> Any:
        if self._app is None or not hasattr(self._app, "get"):
            return None
        fn = self._app.get("memory_query")
        if fn is None:
            return None
        res = fn(query)
        if asyncio.iscoroutine(res):
            return await res
        return res
