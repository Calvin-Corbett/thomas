from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any


_ACK_SYSTEM_PROMPT = (
    "You are Thomas. The user just asked you to do real work and execution is starting now. "
    "Reply naturally in one or two short sentences. Sound like a real AI assistant, not a canned autoresponder. "
    "Acknowledge that you are starting the work and optionally ask one brief follow-up only if it would help. "
    "Do not mention dispatch, workboards, task managers, hidden systems, or internal routing. "
    "Do not claim the task is already complete."
)

_ACK_FALLBACK = "I'm on it now. I'll keep it moving in the background."
_ACK_FIRST_TOKEN_TIMEOUT_SECONDS = 0.8


async def stream_task_start_acknowledgment(
    llm: Any,
    *,
    user_text: str,
    emit_text: Callable[[str], Awaitable[None]],
) -> str:
    prompt = str(user_text or "").strip()
    if not prompt or llm is None or not callable(getattr(llm, "stream_chat", None)):
        await emit_text(_ACK_FALLBACK)
        return _ACK_FALLBACK

    messages = [
        {"role": "system", "content": _ACK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "The user said:\n"
                f"{prompt}\n\n"
                "Reply to the user now while beginning the work."
            ),
        },
    ]

    parts: list[str] = []
    stream = None
    try:
        stream = llm.stream_chat(messages, tools=None)
        iterator = stream.__aiter__()
        saw_token = False
        while True:
            try:
                event = await (
                    asyncio.wait_for(iterator.__anext__(), timeout=_ACK_FIRST_TOKEN_TIMEOUT_SECONDS)
                    if not saw_token
                    else iterator.__anext__()
                )
            except StopAsyncIteration:
                break
            if str(getattr(event, "type", "") or "") != "token":
                continue
            chunk = str(getattr(event, "data", {}).get("text", "") or "")
            if not chunk:
                continue
            saw_token = True
            parts.append(chunk)
            await emit_text(chunk)
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            if stream is not None and callable(getattr(stream, "aclose", None)):
                await stream.aclose()
        await emit_text(_ACK_FALLBACK)
        return _ACK_FALLBACK
    except Exception:
        if parts:
            return "".join(parts).strip()
        await emit_text(_ACK_FALLBACK)
        return _ACK_FALLBACK
    finally:
        with contextlib.suppress(Exception):
            if stream is not None and callable(getattr(stream, "aclose", None)):
                await stream.aclose()

    final_text = "".join(parts).strip()
    if final_text:
        return final_text
    await emit_text(_ACK_FALLBACK)
    return _ACK_FALLBACK
