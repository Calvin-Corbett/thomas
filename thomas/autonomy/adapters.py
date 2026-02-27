from __future__ import annotations

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass
from typing import Any

import aiohttp


@dataclass
class ChatAdapterConfig:
    base_url: str = "http://127.0.0.1:8080"
    timeout_s: float = 120.0
    api_token: str | None = None


class ChatAdapter:
    """Adapter for interacting with Thomas chat sessions.

    This module is intentionally defensive: it can post into an existing chat session
    via (1) an in-process callable if provided, or (2) loopback HTTP to /api/chat.

    Your Thomas app can optionally inject:
      app["chat_submit_json"]: async callable(payload: dict) -> dict
    """

    def __init__(self, *, app: Any | None = None, cfg: ChatAdapterConfig | None = None):
        self._app = app
        self._cfg = cfg or ChatAdapterConfig()

    @staticmethod
    def _extract_first_json_object(text: Any) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None

        with contextlib.suppress(Exception):
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj

        fenced_re = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
        for match in fenced_re.finditer(raw):
            candidate = str(match.group(1) or "").strip()
            if not candidate:
                continue
            with contextlib.suppress(Exception):
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj

        start = raw.find("{")
        while start >= 0:
            depth = 0
            for idx in range(start, len(raw)):
                ch = raw[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        snippet = raw[start : idx + 1]
                        with contextlib.suppress(Exception):
                            obj = json.loads(snippet)
                            if isinstance(obj, dict):
                                return obj
                        break
            start = raw.find("{", start + 1)
        return None

    @staticmethod
    def _parse_streaming_chat_blob(blob: str) -> dict[str, Any] | None:
        events: list[dict[str, Any]] = []
        text_parts: list[str] = []
        done_event: dict[str, Any] | None = None
        for raw_line in str(blob or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            events.append(obj)
            ev_type = str(obj.get("type") or "").strip().lower()
            if ev_type == "error":
                raise RuntimeError(str(obj.get("error") or "chat stream returned error event"))
            if ev_type == "text":
                text_parts.append(str(obj.get("text") or ""))
            if ev_type == "done":
                done_event = dict(obj)
        if not events:
            return None
        out: dict[str, Any] = {
            "events": events,
            "text": "".join(text_parts),
        }
        if isinstance(done_event, dict):
            out["done"] = done_event
        return out

    async def submit_chat_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Prefer in-process hook
        if self._app is not None and hasattr(self._app, "get"):
            fn = self._app.get("chat_submit_json")
            if fn is not None:
                return await fn(payload)

        # Fallback: loopback HTTP
        headers = {"Content-Type": "application/json"}
        if self._cfg.api_token:
            headers["Authorization"] = f"Bearer {self._cfg.api_token}"

        wire_payload = dict(payload or {})
        if not str(wire_payload.get("text") or "").strip():
            msgs = wire_payload.get("messages")
            if isinstance(msgs, list):
                last_user = ""
                first_system = ""
                for msg in msgs:
                    if not isinstance(msg, dict):
                        continue
                    role = str(msg.get("role") or "").strip().lower()
                    content = str(msg.get("content") or "")
                    if role == "system" and not first_system and content.strip():
                        first_system = content.strip()
                    if role == "user" and content.strip():
                        last_user = content.strip()
                if first_system and not str(wire_payload.get("system_prompt") or "").strip():
                    wire_payload["system_prompt"] = first_system
                if last_user:
                    wire_payload["text"] = last_user
        if not str(wire_payload.get("message") or "").strip() and str(wire_payload.get("text") or "").strip():
            wire_payload["message"] = str(wire_payload.get("text") or "").strip()

        timeout = aiohttp.ClientTimeout(total=self._cfg.timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._cfg.base_url.rstrip("/") + "/api/chat", json=wire_payload, headers=headers
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"/api/chat HTTP {resp.status}: {text[:500]}")
                stream_obj = self._parse_streaming_chat_blob(text)
                if isinstance(stream_obj, dict):
                    return stream_obj
                # We don't know exact response shape; try JSON
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"raw": text}

    async def generate_json(
        self,
        *,
        schema_hint: dict[str, Any],
        session_id: str | None = None,
        # Preferred parameter names (used by some Thomas codepaths)
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        profile: str | None = None,
        model: str | None = None,
        # Aliases for compatibility with other internal helpers
        system: str | None = None,
        user: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
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
            "profile": (str(profile or "").strip() or None),
            "model_id": (str(model or "").strip() or None),
            "system_prompt": sys,
            "text": usr,
            "message": usr,
            "messages": [
                {"role": "system", "content": sys},
                {"role": "user", "content": usr},
            ],
            "response_format": {"type": "json_object"},
            "metadata": {"schema_hint": schema_hint, "source": "autonomy_engine"},
        }
        raw = await self.submit_chat_json(payload)
        if isinstance(raw, dict):
            direct = raw.get("json")
            if isinstance(direct, dict):
                return direct

            candidates: list[str] = []
            text_value = raw.get("text")
            if isinstance(text_value, str) and text_value.strip():
                candidates.append(text_value)
            done_obj = raw.get("done")
            if isinstance(done_obj, dict):
                done_text = done_obj.get("text")
                if isinstance(done_text, str) and done_text.strip():
                    candidates.append(done_text)
            raw_blob = raw.get("raw")
            if isinstance(raw_blob, str) and raw_blob.strip():
                candidates.append(raw_blob)

            for candidate in candidates:
                parsed = self._extract_first_json_object(candidate)
                if isinstance(parsed, dict):
                    return parsed

            if isinstance(text_value, str) and text_value.strip():
                raise RuntimeError("chat response was not valid JSON")

        raise RuntimeError("chat adapter did not return a JSON object")


class MemoryAdapter:
    """Adapter for reading/writing memory context.

    Thomas has a richer memory system; to keep this patch self-contained, we provide a thin
    optional integration point:
      app["memory_append"]: callable(event: dict) -> None OR async callable
      app["memory_query"]: callable(query: dict) -> dict/list OR async callable
    """

    def __init__(self, *, app: Any | None = None):
        self._app = app

    async def append(self, event: dict[str, Any]) -> None:
        if self._app is None or not hasattr(self._app, "get"):
            return
        fn = self._app.get("memory_append")
        if fn is None:
            return
        res = fn(event)
        if asyncio.iscoroutine(res):
            await res

    async def query(self, query: dict[str, Any]) -> Any:
        if self._app is None or not hasattr(self._app, "get"):
            return None
        fn = self._app.get("memory_query")
        if fn is None:
            return None
        res = fn(query)
        if asyncio.iscoroutine(res):
            return await res
        return res
