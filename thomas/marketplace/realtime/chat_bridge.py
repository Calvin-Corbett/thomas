"""Current V2 chat request and event contract for the realtime transport."""

from __future__ import annotations

import asyncio
import json
import secrets

import aiohttp

from . import keys

CONTEXT_FIELDS = (
    "session_id",
    "profile",
    "model_id",
    "reasoning_effort",
    "memory",
    "temporary",
    "external_access",
    "autonomy_level",
    "file_access",
    "thomas_guardrails",
    "project_id",
    "docs",
    "images",
)
TEXT_TYPES = {"text", "agent_text", "delta", "assistant_delta", "message_delta"}


def chat_payload(context: dict, text: str) -> dict:
    return {**{key: context[key] for key in CONTEXT_FIELDS if key in context}, "message": text, "surface_mode": "chat"}


async def http_chat_bridge(app, payload):
    request = payload.get("_request")
    if request is None:
        raise RuntimeError("Realtime chat request context is unavailable")
    port = int(request.url.port or (443 if request.scheme == "https" else 80))
    url = f"{request.scheme}://127.0.0.1:{port}/api/chat"
    headers = {key: request.headers[key] for key in ("Authorization", "X-Api-Token") if request.headers.get(key)}
    body = {key: value for key, value in payload.items() if not key.startswith("_")}
    timeout = aiohttp.ClientTimeout(total=300, sock_read=120)
    token = secrets.token_urlsafe(24)
    pending = app.get(keys.CHAT_REQUESTS, {})
    entry = {"task": None, "cancelled": False}
    pending[token] = entry
    headers["X-Thomas-Voice-Turn"] = token
    completed = False
    saw_text = False
    try:
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(url, json=body, headers=headers) as response:
                if response.status != 200:
                    raise RuntimeError(f"Voice chat request failed (HTTP {response.status})")
                async for line in response.content:
                    raw = line.decode("utf-8", errors="replace").strip()
                    if raw.startswith("data:"):
                        raw = raw[5:].strip()
                    if not raw or raw.startswith(":"):
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("Voice chat returned an invalid stream") from exc
                    if not isinstance(event, dict):
                        continue
                    kind = event.get("type")
                    if kind in TEXT_TYPES:
                        text = event.get("text", event.get("delta", event.get("content", "")))
                        if isinstance(text, str):
                            saw_text = saw_text or bool(text)
                            yield {"type": "delta", "text": text}
                    elif kind == "error":
                        raise RuntimeError(str(event.get("error") or "Voice chat could not complete this turn"))
                    elif kind in {"done", "assistant_done"}:
                        final = event.get("text") or event.get("final") or event.get("output_text")
                        if not saw_text and isinstance(final, str) and final:
                            yield {"type": "delta", "text": final}
                        completed = True
                        yield {**event, "type": "done"}
                        return
                    else:
                        yield {"type": "chat_event", "event": event}
        raise RuntimeError("Voice chat ended before a completion receipt")
    finally:
        entry["cancelled"] = not completed
        task = entry["task"]
        if not completed and task is not None and not task.done():
            task.cancel()
        if completed or task is not None:
            pending.pop(token, None)
        else:
            # An interrupted request may still be queued at the server. Its nonce
            # remains a cancellation tombstone until the wrapper sees it or expires.
            asyncio.get_running_loop().call_later(30, pending.pop, token, None)
