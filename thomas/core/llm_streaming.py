"""Provider-specific streaming implementations for LLMClient."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from thomas.core.codex_provider import OPENAI_CODEX_BASE_URL
from thomas.core.llm_shared import LLMError, StreamEvent, TokenUsage, ToolCallAccumulator
from thomas.core.llm_streaming_codex import (
    _build_openai_codex_request,
    _extract_responses_usage,
    _response_item,
)
from thomas.server.openai_codex_oauth import ensure_openai_codex_access_token

log = logging.getLogger(__name__)

_RETRYABLE = {429, 500, 502, 503, 504}


async def stream_openai(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamEvent]:
    base = owner.config.base_url.rstrip("/")
    path = owner.config.chat_path or "/chat/completions"
    if not path.startswith("/"):
        path = "/" + path
    url = base + path
    body = owner._build_openai_request(messages, tools, stream=True)

    client = await owner._get_client()
    params = owner.config.query or None
    last_error: Exception | None = None
    max_retries = max(1, int(owner._max_retries))
    base_delay = max(0.0, float(owner._base_retry_delay))

    for attempt in range(max_retries):
        try:
            async with client.stream("POST", url, json=body, params=params) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    if resp.status_code == 429:
                        retry_after_s = owner._retry_after_seconds(getattr(resp, "headers", None))
                        owner._mark_rate_limited(owner.config, retry_after_s)
                        wait_note = (
                            f" Retry after about {int(retry_after_s)}s."
                            if retry_after_s is not None and retry_after_s > 0
                            else ""
                        )
                        raise LLMError(
                            f"HTTP 429 rate limited.{wait_note} {error_body.decode(errors='replace')[:240]}",
                            status=429,
                            retryable=True,
                        )
                    if resp.status_code in _RETRYABLE:
                        last_error = LLMError(
                            f"HTTP {resp.status_code}: {error_body.decode(errors='replace')[:200]}",
                            status=resp.status_code,
                            retryable=True,
                        )
                        delay = base_delay * (2**attempt)
                        log.warning(
                            "LLM request failed (attempt %d/%d), retrying in %.1fs: %s",
                            attempt + 1,
                            max_retries,
                            delay,
                            last_error,
                        )
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    raise LLMError(
                        f"HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                        status=resp.status_code,
                    )

                tool_calls: dict[int, ToolCallAccumulator] = {}
                tool_call_idx_by_id: dict[str, int] = {}
                legacy_tool_idx = -1

                def _next_tool_idx() -> int:
                    idx = 0
                    while idx in tool_calls:
                        idx += 1
                    return idx

                def _infer_single_unfinished_tool_idx() -> int | None:
                    unfinished = [idx for idx, tc in tool_calls.items() if not tc.finished]
                    if len(unfinished) == 1:
                        return unfinished[0]
                    return None

                def _coerce_args_fragment(raw: Any) -> str:
                    if raw is None:
                        return ""
                    if isinstance(raw, str):
                        return raw
                    try:
                        return json.dumps(raw, ensure_ascii=False)
                    except Exception:
                        return str(raw)

                async def _emit_pending_tool_ends() -> None:
                    for tc in tool_calls.values():
                        if not tc.finished:
                            tc.finished = True
                            yield_event = StreamEvent(
                                type="tool_call_end",
                                data={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                            )
                            pending_events.append(yield_event)

                # Avoid returning from inside the streaming iterator; letting the
                # `async for` unwind cleanly prevents noisy asyncio/httpx shutdown
                # errors on some platforms.
                done_emitted = False

                async for line in resp.aiter_lines():
                    pending_events: list[StreamEvent] = []
                    if not line.startswith("data:"):
                        continue
                    # Some OpenAI-compatible providers emit "data:<json>" (no space)
                    # while others emit "data: <json>"; accept both.
                    data_str = line[5:].lstrip()
                    if data_str.strip() == "[DONE]":
                        # Emit end events for any unfinished tool calls
                        await _emit_pending_tool_ends()
                        for ev in pending_events:
                            yield ev
                        yield StreamEvent(type="done")
                        done_emitted = True
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Extract usage if present
                    if "usage" in chunk and chunk["usage"]:
                        usage = TokenUsage(
                            prompt_tokens=chunk["usage"].get("prompt_tokens", 0),
                            completion_tokens=chunk["usage"].get("completion_tokens", 0),
                            total_tokens=chunk["usage"].get("total_tokens", 0),
                        )
                        owner.session_usage.add(usage)
                        yield StreamEvent(type="usage", data={"usage": usage})

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # Text content
                    content = delta.get("content")
                    if content:
                        yield StreamEvent(type="token", data={"text": content})

                    # Tool calls (providers may emit list or a single object)
                    raw_tool_calls = delta.get("tool_calls", [])
                    if isinstance(raw_tool_calls, dict):
                        tool_deltas = [raw_tool_calls]
                    elif isinstance(raw_tool_calls, list):
                        tool_deltas = raw_tool_calls
                    else:
                        tool_deltas = []

                    for tc_delta in tool_deltas:
                        if not isinstance(tc_delta, dict):
                            continue

                        tc_id_raw = str(tc_delta.get("id", "") or "").strip()
                        idx_raw = tc_delta.get("index", None)

                        if idx_raw is not None:
                            try:
                                idx = int(idx_raw)
                            except Exception:
                                idx = tool_call_idx_by_id.get(tc_id_raw, _next_tool_idx())
                        elif tc_id_raw and tc_id_raw in tool_call_idx_by_id:
                            idx = tool_call_idx_by_id[tc_id_raw]
                        elif not tc_id_raw:
                            # Some providers omit both id/index after the first
                            # chunk for single tool calls; treat it as continuation.
                            inferred_idx = _infer_single_unfinished_tool_idx()
                            idx = inferred_idx if inferred_idx is not None else _next_tool_idx()
                        else:
                            idx = _next_tool_idx()

                        func_obj = tc_delta.get("function", {})
                        if not isinstance(func_obj, dict):
                            func_obj = {}

                        if idx not in tool_calls:
                            tc_id = tc_id_raw or f"call_{idx}"
                            raw_name = str(func_obj.get("name", "") or "")
                            # Reverse-map sanitized name back to original dotted name
                            tc_name = owner._openai_tool_name_map.get(raw_name, raw_name)
                            tool_calls[idx] = ToolCallAccumulator(id=tc_id, name=tc_name)
                            tool_call_idx_by_id[tc_id] = idx
                            if tc_id_raw:
                                tool_call_idx_by_id[tc_id_raw] = idx
                            pending_events.append(
                                StreamEvent(
                                    type="tool_call_start",
                                    data={"id": tc_id, "name": tc_name, "index": idx},
                                )
                            )
                        elif tc_id_raw:
                            tool_call_idx_by_id[tc_id_raw] = idx

                        args_delta = _coerce_args_fragment(func_obj.get("arguments", ""))
                        if args_delta:
                            tool_calls[idx].arguments += args_delta
                            pending_events.append(
                                StreamEvent(
                                    type="tool_call_delta",
                                    data={"id": tool_calls[idx].id, "delta": args_delta},
                                )
                            )

                        # Update name if it wasn't in the first chunk (reverse-map too)
                        name_delta = str(func_obj.get("name", "") or "")
                        if name_delta and not tool_calls[idx].name:
                            tool_calls[idx].name = owner._openai_tool_name_map.get(name_delta, name_delta)

                    # Legacy OpenAI function-calling stream format:
                    # delta.function_call.{name,arguments}
                    legacy_fc = delta.get("function_call", {})
                    if isinstance(legacy_fc, dict) and legacy_fc:
                        legacy_raw_name = str(legacy_fc.get("name", "") or "")
                        legacy_name = owner._openai_tool_name_map.get(legacy_raw_name, legacy_raw_name)
                        if legacy_tool_idx not in tool_calls:
                            tc_id = "call_legacy_0"
                            tool_calls[legacy_tool_idx] = ToolCallAccumulator(
                                id=tc_id,
                                name=legacy_name,
                            )
                            pending_events.append(
                                StreamEvent(
                                    type="tool_call_start",
                                    data={"id": tc_id, "name": legacy_name, "index": legacy_tool_idx},
                                )
                            )

                        if legacy_name and not tool_calls[legacy_tool_idx].name:
                            tool_calls[legacy_tool_idx].name = legacy_name

                        legacy_args = _coerce_args_fragment(legacy_fc.get("arguments", ""))
                        if legacy_args:
                            tool_calls[legacy_tool_idx].arguments += legacy_args
                            pending_events.append(
                                StreamEvent(
                                    type="tool_call_delta",
                                    data={"id": tool_calls[legacy_tool_idx].id, "delta": legacy_args},
                                )
                            )

                    # Finish reason
                    finish = choices[0].get("finish_reason")
                    if finish in ("tool_calls", "function_call", "stop"):
                        await _emit_pending_tool_ends()

                    for ev in pending_events:
                        yield ev

                # Stream completed without [DONE].
                if not done_emitted:
                    for tc in tool_calls.values():
                        if not tc.finished:
                            tc.finished = True
                            yield StreamEvent(
                                type="tool_call_end",
                                data={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                            )
                    yield StreamEvent(type="done")
                return

        except httpx.HTTPStatusError as e:
            if e.response.status_code in _RETRYABLE and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                log.warning("HTTP error %d, retrying in %.1fs", e.response.status_code, delay)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise LLMError(str(e), status=e.response.status_code)
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                log.warning("Connection error, retrying in %.1fs: %s", delay, e)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise LLMError(f"Connection failed after {max_retries} attempts: {e}")

    raise last_error or LLMError("Request failed after retries")


async def stream_openai_codex(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream through ChatGPT's native Codex Responses endpoint."""
    base = str(owner.config.base_url or OPENAI_CODEX_BASE_URL).rstrip("/")
    url = base + "/responses"
    body = _build_openai_codex_request(owner, messages, tools)
    access_token = str(getattr(owner.config, "api_key", "") or "").strip()
    if not access_token:
        access_token = await ensure_openai_codex_access_token(getattr(owner.config, "name", "") or "chatgpt")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    client = await owner._get_client()
    last_error: Exception | None = None
    max_retries = max(1, int(owner._max_retries))
    base_delay = max(0.0, float(owner._base_retry_delay))

    for attempt in range(max_retries):
        try:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    if resp.status_code == 429:
                        retry_after_s = owner._retry_after_seconds(getattr(resp, "headers", None))
                        owner._mark_rate_limited(owner.config, retry_after_s)
                        wait_note = (
                            f" Retry after about {int(retry_after_s)}s."
                            if retry_after_s is not None and retry_after_s > 0
                            else ""
                        )
                        raise LLMError(
                            f"ChatGPT/Codex HTTP 429 rate limited.{wait_note} {error_body.decode(errors='replace')[:240]}",
                            status=429,
                            retryable=True,
                        )
                    if resp.status_code in _RETRYABLE:
                        last_error = LLMError(
                            f"ChatGPT/Codex HTTP {resp.status_code}: {error_body.decode(errors='replace')[:200]}",
                            status=resp.status_code,
                            retryable=True,
                        )
                        delay = base_delay * (2**attempt)
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    raise LLMError(
                        f"ChatGPT/Codex HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                        status=resp.status_code,
                    )

                tool_calls: dict[str, ToolCallAccumulator] = {}
                event_name = ""
                data_lines: list[str] = []
                done_emitted = False

                async def _emit_pending_tool_ends() -> list[StreamEvent]:
                    pending: list[StreamEvent] = []
                    for tc in tool_calls.values():
                        if not tc.finished:
                            tc.finished = True
                            pending.append(
                                StreamEvent(
                                    type="tool_call_end",
                                    data={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                                )
                            )
                    return pending

                async def _process_sse(payload: str, sse_event: str) -> list[StreamEvent]:
                    nonlocal done_emitted
                    events: list[StreamEvent] = []
                    data_str = payload.strip()
                    if not data_str or data_str == "[DONE]":
                        events.extend(await _emit_pending_tool_ends())
                        events.append(StreamEvent(type="done"))
                        done_emitted = True
                        return events
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        return events
                    if not isinstance(chunk, dict):
                        return events

                    if "choices" in chunk:
                        # Defensive fallback for proxies that emit chat-completion chunks.
                        choices = chunk.get("choices") if isinstance(chunk.get("choices"), list) else []
                        if choices:
                            delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
                            content = delta.get("content") if isinstance(delta, dict) else ""
                            if content:
                                events.append(StreamEvent(type="token", data={"text": content}))
                        return events

                    event_type = str(chunk.get("type") or sse_event or "").strip()
                    usage = _extract_responses_usage(chunk)
                    if usage is not None:
                        owner.session_usage.add(usage)
                        events.append(StreamEvent(type="usage", data={"usage": usage}))

                    if event_type in {"response.output_text.delta", "response.refusal.delta"}:
                        delta = str(chunk.get("delta") or chunk.get("text") or "")
                        if delta:
                            events.append(StreamEvent(type="token", data={"text": delta}))
                    elif event_type in {
                        "response.reasoning_summary_text.delta",
                        "response.reasoning_text.delta",
                        "response.reasoning_summary.delta",
                    }:
                        delta = str(chunk.get("delta") or chunk.get("text") or "")
                        if delta:
                            events.append(StreamEvent(type="thinking", data={"text": delta}))
                    elif event_type == "response.output_item.added":
                        item = _response_item(chunk)
                        if str(item.get("type") or "") == "function_call":
                            call_id = str(item.get("call_id") or item.get("id") or "").strip()
                            raw_name = str(item.get("name") or "").strip()
                            name = owner._openai_tool_name_map.get(raw_name, raw_name)
                            if call_id and call_id not in tool_calls:
                                tool_calls[call_id] = ToolCallAccumulator(id=call_id, name=name)
                                events.append(StreamEvent(type="tool_call_start", data={"id": call_id, "name": name}))
                    elif event_type == "response.function_call_arguments.delta":
                        call_id = str(chunk.get("call_id") or chunk.get("item_id") or "").strip()
                        if not call_id and len(tool_calls) == 1:
                            call_id = next(iter(tool_calls.keys()))
                        delta = str(chunk.get("delta") or "")
                        if call_id and delta:
                            if call_id not in tool_calls:
                                tool_calls[call_id] = ToolCallAccumulator(id=call_id, name="")
                                events.append(StreamEvent(type="tool_call_start", data={"id": call_id, "name": ""}))
                            tool_calls[call_id].arguments += delta
                            events.append(StreamEvent(type="tool_call_delta", data={"id": call_id, "delta": delta}))
                    elif event_type == "response.output_item.done":
                        item = _response_item(chunk)
                        if str(item.get("type") or "") == "function_call":
                            call_id = str(item.get("call_id") or item.get("id") or "").strip()
                            if call_id:
                                raw_name = str(item.get("name") or "").strip()
                                name = owner._openai_tool_name_map.get(raw_name, raw_name)
                                tc = tool_calls.get(call_id) or ToolCallAccumulator(id=call_id, name=name)
                                if name:
                                    tc.name = name
                                final_args = str(item.get("arguments") or "")
                                if final_args:
                                    tc.arguments = final_args
                                tc.finished = True
                                tool_calls[call_id] = tc
                                events.append(
                                    StreamEvent(
                                        type="tool_call_end",
                                        data={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                                    )
                                )
                    elif event_type in {"response.completed", "response.incomplete"}:
                        events.extend(await _emit_pending_tool_ends())
                        events.append(StreamEvent(type="done"))
                        done_emitted = True
                    elif event_type in {"response.failed", "error"}:
                        err = chunk.get("error")
                        if isinstance(err, dict):
                            message = str(err.get("message") or err.get("code") or err)
                        else:
                            message = str(err or chunk.get("message") or "ChatGPT/Codex response failed")
                        raise LLMError(message, status=None)
                    return events

                async for line in resp.aiter_lines():
                    if line == "":
                        if data_lines:
                            for ev in await _process_sse("\n".join(data_lines), event_name):
                                yield ev
                            data_lines = []
                            event_name = ""
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

                if data_lines:
                    for ev in await _process_sse("\n".join(data_lines), event_name):
                        yield ev

                if not done_emitted:
                    for ev in await _emit_pending_tool_ends():
                        yield ev
                    yield StreamEvent(type="done")
                return

        except httpx.HTTPStatusError as e:
            if e.response.status_code in _RETRYABLE and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise LLMError(str(e), status=e.response.status_code)
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise LLMError(f"ChatGPT/Codex connection failed after {max_retries} attempts: {e}")

    raise last_error or LLMError("ChatGPT/Codex request failed after retries")


async def stream_anthropic(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamEvent]:
    url = f"{owner.config.base_url.rstrip('/')}/messages"
    body = owner._build_anthropic_request(messages, tools, stream=True)

    # Debug: log tool configuration sent to Anthropic
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

    client = await owner._get_client()
    last_error: Exception | None = None
    max_retries = max(1, int(owner._max_retries))
    base_delay = max(0.0, float(owner._base_retry_delay))

    for attempt in range(max_retries):
        try:
            async with client.stream("POST", url, json=body) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    if resp.status_code == 429:
                        retry_after_s = owner._retry_after_seconds(getattr(resp, "headers", None))
                        owner._mark_rate_limited(owner.config, retry_after_s)
                        wait_note = (
                            f" Retry after about {int(retry_after_s)}s."
                            if retry_after_s is not None and retry_after_s > 0
                            else ""
                        )
                        raise LLMError(
                            f"Anthropic HTTP 429 rate limited.{wait_note} {error_body.decode(errors='replace')[:240]}",
                            status=429,
                            retryable=True,
                        )
                    if resp.status_code in _RETRYABLE:
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
                    raise LLMError(
                        f"Anthropic HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                        status=resp.status_code,
                    )

                current_tool_id = ""
                current_tool_name = ""
                current_tool_args = ""
                prompt_tokens = 0
                completion_tokens = 0
                usage_emitted = False

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event_data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event_type = event_data.get("type", "")
                    log.debug("Anthropic SSE event: %s", event_type)
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
                            )
                            owner.session_usage.add(tu)
                            yield StreamEvent(type="usage", data={"usage": tu})
                            usage_emitted = True
                        yield StreamEvent(type="done")
                        return

                if not usage_emitted and (prompt_tokens or completion_tokens):
                    tu = TokenUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                    )
                    owner.session_usage.add(tu)
                    yield StreamEvent(type="usage", data={"usage": tu})
                yield StreamEvent(type="done")
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

    raise LLMError(
        f"Anthropic request failed after {max_retries} attempts: {last_error}",
        retryable=False,
    )
