"""One plain ChatGPT call for a second look: no tools, no agent, no CLI, nothing written.

The two second looks (``thomas/server/precard/review.py`` before your card, ``scripts/cage/window_review.py`` inside an
express window) ran the Claude CLI, and every time its sign-in ended the reviews stopped until you signed in again. On
2026-10-25 you asked for ChatGPT instead: "make it all chat gpt for the review too ... i dont mean use codex agent i
mean use chatgpt". So this asks the model through Thomas's own ChatGPT client, on your ChatGPT sign-in, with no tools
offered: the caller puts the change and the files it touches in the prompt, and the model can only answer.

The answer comes back in the shape both callers already read -- ``{"type": "result", "is_error": ..., "result": text}``
-- so their verdict rules do not change. Requested cancellation propagates as ``CancelledError``; other handled
failures become error envelopes, and a second look with no verdict never passes anything.

The process must have a ChatGPT token resolver registered (``thomas.server.openai_codex_oauth`` does it on import; the
server imports it at start). ``thomas.core`` does not import the server, so the caller does.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx

from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import LLMError
from thomas.core.llm_slot import models

DEFAULT_MODEL = "gpt-6.1-sol"
DEFAULT_EFFORT = "high"
MAX_TOKENS = 16384
CONTEXT_WINDOW = 400_000


def envelope(text: str, *, error: bool) -> str:
    return json.dumps({"type": "result", "is_error": error, "result": text})


def ask(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    timeout: float,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[int, str]:
    """Return one answer or an error envelope; requested cancellation raises CancelledError."""
    config = ModelConfig(
        name="second-look",
        provider="openai_codex",
        model=model,
        max_tokens=MAX_TOKENS,
        context_window=CONTEXT_WINDOW,
        temperature=0.1,
        reasoning_effort=effort,
    )

    async def call() -> dict:
        if cancelled is not None and cancelled():
            raise asyncio.CancelledError
        client = models().open(config, default=LLMClient, fallback_configs=[], failover_enabled=False)
        task = asyncio.create_task(client.chat([{"role": "user", "content": prompt}], tools=None))
        try:
            async with asyncio.timeout(timeout):
                while not task.done():
                    if cancelled is not None and cancelled():
                        raise asyncio.CancelledError
                    await asyncio.wait({task}, timeout=0.1)
                return task.result()
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    try:
        answer = asyncio.run(call())
    except TimeoutError:
        return 124, envelope(f"ChatGPT did not answer within {timeout:g} s", error=True)
    # The client's own refusals (LLMError), a sign-in it cannot resolve (RuntimeError), the network (httpx, OSError)
    # and a malformed reply (ValueError, KeyError, TypeError) are each "no verdict", never a crash of the caller.
    except (LLMError, RuntimeError, httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as exc:
        return 1, envelope(f"ChatGPT gave no answer: {type(exc).__name__}: {exc}"[:600], error=True)
    if answer.get("tool_calls"):
        return 1, envelope("ChatGPT asked for a tool; a second look offers none", error=True)
    text = str(answer.get("text") or "")
    if not text.strip():
        return 1, envelope("ChatGPT answered with nothing", error=True)
    return 0, envelope(text, error=False)


__all__ = ["DEFAULT_EFFORT", "DEFAULT_MODEL", "ask", "envelope"]
