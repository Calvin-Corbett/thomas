"""HTTP transport lifecycle and provider-stream dispatch helpers."""

from __future__ import annotations

import inspect
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from email.utils import parsedate_to_datetime
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from thomas.core.claude_plan import chose_claude_plan
from thomas.core.event_loop_offload import off_loop
from thomas.core.llm_shared import StreamEvent
from thomas.core.llm_slot import models
from thomas.core.llm_streaming_claude_cli import stream_claude_cli


async def _coerce_async_iterator(value: Any, *, source: str) -> AsyncIterator[Any]:
    if hasattr(value, "__aiter__"):
        return value
    if inspect.isawaitable(value):
        resolved = await value
        if hasattr(resolved, "__aiter__"):
            return resolved
        raise TypeError(f"{source} returned {type(resolved)!r} after await, not an async iterator.")
    raise TypeError(f"{source} returned unsupported type {type(value)!r}; expected async iterator.")


async def get_http_client(owner: Any, *, httpx_module: Any = httpx) -> Any:
    """Return the owner's live HTTP client, creating it with provider headers."""
    if owner._client is None or owner._client.is_closed:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if owner.config.extra_headers:
            headers.update(owner.config.extra_headers)

        if owner.config.api_key:
            if owner.config.provider == "anthropic":
                headers["x-api-key"] = owner.config.api_key
                headers.setdefault("anthropic-version", "2023-06-01")
            else:
                header_name = owner.config.api_key_header or "Authorization"
                prefix = owner.config.api_key_prefix or ""
                headers[header_name] = f"{prefix}{owner.config.api_key}"

        # Building a client loads the CA bundle into an SSL context -- twice
        # when a proxy is configured -- which held the server loop for 0.4-0.8 s
        # on a chat turn's first model call. That is file reading and parsing,
        # so it runs in a worker thread like the server's other blocking work.
        client = await off_loop(
            "llm.http_client",
            httpx_module.AsyncClient,
            headers=headers,
            timeout=httpx_module.Timeout(
                connect=10.0,
                read=owner.config.timeout_s,
                write=10.0,
                pool=10.0,
            ),
        )
        if owner._client is not None and not owner._client.is_closed:
            # Another call on this owner finished building one while we waited.
            await client.aclose()
        else:
            owner._client = client
    return owner._client


async def close_http_client(owner: Any) -> None:
    """Close and clear the owner's HTTP client when it is open."""
    if owner._client and not owner._client.is_closed:
        await owner._client.aclose()
        owner._client = None


def retry_after_seconds(headers: Any, *, max_retry_after_s: float) -> float | None:
    """Parse a Retry-After header as capped seconds or an HTTP date."""
    if headers is None:
        return None
    raw = ""
    try:
        raw = str(headers.get("retry-after") or headers.get("Retry-After") or "").strip()
    except (AttributeError, TypeError):
        raw = ""
    if not raw:
        return None

    try:
        seconds = float(raw)
        if seconds >= 0:
            return min(seconds, max_retry_after_s)
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(raw)
        now = time.time()
        delta = max(0.0, float(dt.timestamp() - now))
        return min(delta, max_retry_after_s)
    except (ValueError, TypeError):
        return None


async def stream_current_provider(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    turn_user_content: Any = None,
    coerce_async_iterator: Callable[..., Awaitable[AsyncIterator[Any]]] = _coerce_async_iterator,
) -> AsyncIterator[StreamEvent]:
    """Dispatch one request to the active provider's streaming helper."""
    provider_name = str(owner.config.provider or "").strip().lower().replace("-", "_")
    # Looked up once, here, through the models slot. A stream already running keeps the function it started with, so a row
    # that turns off mid-stream does not cut it off; the next stream looks again and sees whichever adapter is registered.
    adapter = models().adapter_for(provider_name)
    if adapter is not None:
        stream_obj = await coerce_async_iterator(
            adapter(owner, messages, tools, turn_user_content=turn_user_content),
            source="model adapter",
        )
        try:
            async for event in stream_obj:
                yield event
        finally:
            close = getattr(stream_obj, "aclose", None)
            if callable(close):
                await close()
        return
    if chose_claude_plan(provider_name, getattr(owner.config, "api_key", ""), getattr(owner.config, "model", "")):
        # Your Claude plan, asked for by name: the request goes through the Claude
        # CLI and its own sign-in — the engine Build already uses. The model has to
        # be one the plan offers, not merely a profile with no key, or a turn that
        # asked for Anthropic's API would start a program on this machine instead.
        # Called here rather than through an ``owner._stream_*`` seam like the three
        # below because ``llm_client.py`` is at its size limit; this module is the seam.
        stream_obj = await coerce_async_iterator(
            stream_claude_cli(owner, messages, tools),
            source="stream_claude_cli",
        )
    elif provider_name == "openai_codex":
        stream_obj = await coerce_async_iterator(
            owner._stream_openai_codex(
                messages,
                tools,
                turn_user_content=turn_user_content,
            ),
            source="stream_openai_codex",
        )
    elif provider_name == "anthropic":
        stream_obj = await coerce_async_iterator(
            owner._stream_anthropic(messages, tools),
            source="stream_anthropic",
        )
    else:
        stream_obj = await coerce_async_iterator(
            owner._stream_openai(messages, tools),
            source="stream_openai",
        )
    async for event in stream_obj:
        yield event


async def stream_openai_events(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    stream_openai_func: Callable[..., Any],
    coerce_async_iterator: Callable[..., Awaitable[AsyncIterator[Any]]] = _coerce_async_iterator,
) -> AsyncIterator[StreamEvent]:
    """Yield events from the OpenAI-compatible streaming seam."""
    stream_obj = await coerce_async_iterator(
        stream_openai_func(owner, messages, tools),
        source="stream_openai",
    )
    async for event in stream_obj:
        yield event


async def stream_openai_codex_events(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    turn_user_content: Any,
    stream_openai_codex_func: Callable[..., Any],
    coerce_async_iterator: Callable[..., Awaitable[AsyncIterator[Any]]] = _coerce_async_iterator,
) -> AsyncIterator[StreamEvent]:
    """Yield events from the OpenAI Codex streaming seam."""
    stream_obj = await coerce_async_iterator(
        stream_openai_codex_func(
            owner,
            messages,
            tools,
            turn_user_content=turn_user_content,
        ),
        source="stream_openai_codex",
    )
    async for event in stream_obj:
        yield event


async def stream_anthropic_events(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    stream_anthropic_func: Callable[..., Any],
    coerce_async_iterator: Callable[..., Awaitable[AsyncIterator[Any]]] = _coerce_async_iterator,
) -> AsyncIterator[StreamEvent]:
    """Yield events from the Anthropic streaming seam."""
    stream_obj = await coerce_async_iterator(
        stream_anthropic_func(owner, messages, tools),
        source="stream_anthropic",
    )
    async for event in stream_obj:
        yield event
