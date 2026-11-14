"""Streaming implementation for the Anthropic Messages API.

Extracted from ``thomas.core.llm_streaming`` to keep that module under the
architecture size limit. This is the whole of the Anthropic transport -- SSE
parsing, extended-thinking blocks, tool-use accumulation and usage accounting.
It shares nothing with the OpenAI-family streamers that stayed behind beyond
the primitives in ``llm_shared``, which is why this is the seam.

``thomas.core.llm_streaming`` re-exports ``stream_anthropic``, so either import
path resolves.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from thomas.core.llm_request_admission import admitted_stream, finish_admitted_attempt
from thomas.core.llm_shared import RETRYABLE_STATUS, LLMError, StreamEvent, TokenUsage, quota_error_fields

log = logging.getLogger(__name__)


def extract_anthropic_usage(event_data: dict[str, Any]) -> dict[str, int]:
    """Extract Anthropic usage fields from top-level and nested message objects."""
    raw_usage: dict[str, Any] = {}

    top_usage = event_data.get("usage")
    if isinstance(top_usage, dict):
        raw_usage.update(top_usage)

    message_obj = event_data.get("message")
    if isinstance(message_obj, dict):
        msg_usage = message_obj.get("usage")
        if isinstance(msg_usage, dict):
            for k, v in msg_usage.items():
                raw_usage.setdefault(k, v)

    out: dict[str, int] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        if key not in raw_usage:
            continue
        try:
            out[key] = max(0, int(raw_usage.get(key) or 0))
        except (TypeError, ValueError, OverflowError):
            log.debug("Ignoring invalid Anthropic usage field %s=%r", key, raw_usage.get(key))
            continue
    return out


async def stream_anthropic(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamEvent]:
    url = f"{owner.config.base_url.rstrip('/')}/messages"
    client = await owner._get_client()
    last_error: Exception | None = None
    max_retries = max(1, int(owner._max_retries))
    base_delay = max(0.0, float(owner._base_retry_delay))

    for attempt in range(max_retries):
        lease = await owner.begin_budget_attempt(messages, tools)
        attempt_state = {"started": False}
        try:
            body = owner._build_anthropic_request(
                messages,
                tools,
                stream=True,
                max_output_tokens=getattr(lease, "output_cap", None),
            )
            tool_names = [t["name"] for t in body.get("tools", [])]
            if tool_names:
                log.debug(
                    "Anthropic request: %d tools [%s], tool_choice=%s",
                    len(tool_names),
                    ", ".join(tool_names[:5]),
                    body.get("tool_choice"),
                )
            else:
                log.debug("Anthropic request: NO tools sent")
            async with admitted_stream(owner, client, "POST", url, attempt_state=attempt_state, json=body) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    if resp.status_code == 429:
                        error_code, safe_headers = quota_error_fields(error_body, resp.headers)
                        retry_after_s = owner._retry_after_seconds(getattr(resp, "headers", None))
                        wait_note = (
                            f" Retry after about {int(retry_after_s)}s."
                            if retry_after_s is not None and retry_after_s > 0
                            else ""
                        )
                        # Handed to the park as well as raised: see _parked_text.
                        detail = (
                            f"Anthropic HTTP 429 rate limited.{wait_note} {error_body.decode(errors='replace')[:240]}"
                        )
                        owner._mark_rate_limited(owner.config, retry_after_s, detail)
                        raise LLMError(
                            detail,
                            status=429,
                            retryable=True,
                            error_code=error_code,
                            response_headers=safe_headers,
                        )
                    if resp.status_code in RETRYABLE_STATUS:
                        last_error = LLMError(
                            f"Anthropic HTTP {resp.status_code}: {error_body.decode(errors='replace')[:200]}",
                            status=resp.status_code,
                            retryable=True,
                        )
                        delay = base_delay * (2**attempt)
                        log.warning(
                            "Anthropic request failed (attempt %d/%d), retrying in %.1fs: %s",
                            attempt + 1,
                            max_retries,
                            delay,
                            last_error,
                        )
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    error_code, safe_headers = quota_error_fields(error_body, resp.headers)
                    raise LLMError(
                        f"Anthropic HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                        status=resp.status_code,
                        error_code=error_code,
                        response_headers=safe_headers,
                    )

                current_tool_id = ""
                current_tool_name = ""
                current_tool_args = ""
                prompt_tokens = 0
                completion_tokens = 0
                cached_tokens = 0
                written_tokens = 0
                usage_emitted = False
                # `message.model` from message_start: the exact model Anthropic says
                # answered, carried on `done` so a Build turn can record it.
                reported_model = ""

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event_data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event_type = event_data.get("type", "")
                    log.debug("Anthropic SSE event: %s", event_type)
                    message = event_data.get("message")
                    if event_type == "message_start" and isinstance(message, dict) and message.get("model"):
                        reported_model = str(message["model"])
                    usage_fields = owner._extract_anthropic_usage(event_data)
                    if usage_fields:
                        prompt_candidate = (
                            usage_fields.get("input_tokens", 0)
                            + usage_fields.get("cache_creation_input_tokens", 0)
                            + usage_fields.get("cache_read_input_tokens", 0)
                        )
                        completion_candidate = usage_fields.get("output_tokens", 0)
                        prompt_tokens = max(prompt_tokens, prompt_candidate)
                        completion_tokens = max(completion_tokens, completion_candidate)
                        cached_tokens = max(cached_tokens, usage_fields.get("cache_read_input_tokens", 0))
                        written_tokens = max(written_tokens, usage_fields.get("cache_creation_input_tokens", 0))

                    if event_type == "content_block_start":
                        block = event_data.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool_id = block.get("id", "")
                            # Reverse-map sanitized name back to original dotted name
                            raw_name = block.get("name", "")
                            current_tool_name = owner._anthropic_tool_name_map.get(raw_name, raw_name)
                            current_tool_args = ""
                            yield StreamEvent(
                                type="tool_call_start",
                                data={"id": current_tool_id, "name": current_tool_name},
                            )
                        elif block.get("type") == "thinking":
                            # Extended thinking content block (Claude 3.7+)
                            yield StreamEvent(type="thinking", data={"text": ""})

                    elif event_type == "content_block_delta":
                        delta = event_data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield StreamEvent(type="token", data={"text": delta.get("text", "")})
                        elif delta.get("type") == "thinking_delta":
                            # Extended thinking token stream
                            yield StreamEvent(type="thinking", data={"text": delta.get("thinking", "")})
                        elif delta.get("type") == "input_json_delta":
                            partial = delta.get("partial_json", "")
                            current_tool_args += partial
                            yield StreamEvent(
                                type="tool_call_delta",
                                data={"id": current_tool_id, "delta": partial},
                            )

                    elif event_type == "content_block_stop":
                        if current_tool_id:
                            yield StreamEvent(
                                type="tool_call_end",
                                data={
                                    "id": current_tool_id,
                                    "name": current_tool_name,
                                    "arguments": current_tool_args,
                                },
                            )
                            current_tool_id = ""

                    elif event_type == "message_delta":
                        delta = event_data.get("delta", {})
                        stop = delta.get("stop_reason")
                        if stop:
                            log.debug("Anthropic stop_reason: %s", stop)

                    elif event_type == "message_stop":
                        if not usage_emitted and (prompt_tokens or completion_tokens):
                            tu = TokenUsage(
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                total_tokens=prompt_tokens + completion_tokens,
                                cached_prompt_tokens=cached_tokens,
                                cache_write_prompt_tokens=written_tokens,
                            )
                            owner.session_usage.add(tu)
                            yield StreamEvent(type="usage", data={"usage": tu})
                            usage_emitted = True
                        yield StreamEvent(type="done", data={"model": reported_model} if reported_model else {})
                        return

                if not usage_emitted and (prompt_tokens or completion_tokens):
                    tu = TokenUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                        cached_prompt_tokens=cached_tokens,
                        cache_write_prompt_tokens=written_tokens,
                    )
                    owner.session_usage.add(tu)
                    yield StreamEvent(type="usage", data={"usage": tu})
                yield StreamEvent(type="done", data={"model": reported_model} if reported_model else {})
                return

        except httpx.ConnectError as e:
            last_error = e
            delay = base_delay * (2**attempt)
            log.warning(
                "Anthropic connection failed (attempt %d/%d), retrying in %.1fs",
                attempt + 1,
                max_retries,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)
        finally:
            await finish_admitted_attempt(owner, lease, attempt_state)

    raise LLMError(
        f"Anthropic request failed after {max_retries} attempts: {last_error}",
        retryable=False,
    )
