"""Provider-specific streaming implementations for LLMClient.

The OpenAI-family transports live here: ``stream_openai`` speaks Chat
Completions to any OpenAI-compatible endpoint, and ``stream_openai_codex``
speaks the Responses API to ChatGPT's Codex endpoint. The Anthropic transport
moved to ``thomas.core.llm_streaming_anthropic`` and is re-exported below, so
callers can keep importing all three streamers from this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from thomas.core import provider_trouble
from thomas.core.codex_auth import current_access_token, recover_rejected_token, resolve_access_token
from thomas.core.codex_provider import OPENAI_CODEX_BASE_URL
from thomas.core.llm_request_admission import admitted_stream, finish_admitted_attempt
from thomas.core.llm_shared import (
    RETRYABLE_STATUS,
    LLMError,
    StreamEvent,
    TokenUsage,
    ToolCallAccumulator,
    embedded_tool_call,
    quota_error_fields,
)
from thomas.core.llm_stream_args import coerce_args_fragment
from thomas.core.llm_streaming_anthropic import stream_anthropic
from thomas.core.llm_streaming_codex import (
    _build_openai_codex_request,
    _extract_responses_usage,
    _remember_reasoning,
    _replayable_reasoning,
    _response_item,
)

log = logging.getLogger(__name__)
_ASK_AGAIN = ("overloaded", "server_error")  # provider_trouble kinds a codex request is sent again for

__all__ = ["stream_anthropic", "stream_openai", "stream_openai_codex"]


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
    client = await owner._get_client()
    params = owner.config.query or None
    last_error: Exception | None = None
    max_retries = max(1, int(owner._max_retries))
    base_delay = max(0.0, float(owner._base_retry_delay))

    for attempt in range(max_retries):
        lease = await owner.begin_budget_attempt(messages, tools)
        attempt_state = {"started": False}
        try:
            body = owner._build_openai_request(
                messages,
                tools,
                stream=True,
                max_output_tokens=getattr(lease, "output_cap", None),
            )
            async with admitted_stream(
                owner, client, "POST", url, attempt_state=attempt_state, json=body, params=params
            ) as resp:
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
                        # The park keeps these words, so the next message is told
                        # what the provider said rather than what the park says.
                        detail = f"HTTP 429 rate limited.{wait_note} {error_body.decode(errors='replace')[:240]}"
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
                    error_code, safe_headers = quota_error_fields(error_body, resp.headers)
                    raise LLMError(
                        f"HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                        status=resp.status_code,
                        error_code=error_code,
                        response_headers=safe_headers,
                    )

                tool_calls: dict[int, ToolCallAccumulator] = {}
                tool_call_idx_by_id: dict[str, int] = {}
                legacy_tool_idx = -1
                # A model without native tool calling writes the call into its
                # content. While a request carried tools, content that opens like
                # JSON is held rather than streamed; at the end it is either the
                # one call it turned out to be (emitted as tool-call events, so
                # the loop's fence, policy and execution see a real call) or
                # text released whole. Prose is never held, and a request that
                # offered no tools is never touched.
                offered_names: set[str] = set()
                for spec in tools or []:
                    fn = spec.get("function") if isinstance(spec, dict) else None
                    fn_name = str((fn or {}).get("name") or "") if isinstance(fn, dict) else ""
                    if fn_name:
                        offered_names.add(fn_name)
                        offered_names.add(owner._openai_tool_name_map.get(fn_name, fn_name))
                held_text = ""
                holding = bool(offered_names)
                held_flushed = False

                def _release_held() -> list[StreamEvent]:
                    nonlocal held_text, holding
                    holding = False
                    if not held_text:
                        return []
                    text, held_text = held_text, ""
                    return [StreamEvent(type="token", data={"text": text})]

                def _held_as_call() -> list[StreamEvent]:
                    nonlocal held_text, holding
                    holding = False
                    call = embedded_tool_call(held_text, offered_names) if not tool_calls else None
                    if call is None:
                        return _release_held()
                    name, arguments = call
                    held_text = ""
                    idx = _next_tool_idx()
                    tc_id = f"call_content_{idx}"
                    tool_calls[idx] = ToolCallAccumulator(id=tc_id, name=name, arguments=arguments, finished=True)
                    return [
                        StreamEvent(type="tool_call_start", data={"id": tc_id, "name": name, "index": idx}),
                        StreamEvent(type="tool_call_delta", data={"id": tc_id, "delta": arguments}),
                        StreamEvent(type="tool_call_end", data={"id": tc_id, "name": name, "arguments": arguments}),
                    ]

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
                # The exact model the provider says answered, carried on `done`
                # so a Build turn can record it (build_model_receipt.py).
                reported_model = ""

                async for line in resp.aiter_lines():
                    pending_events: list[StreamEvent] = []
                    if not line.startswith("data:"):
                        continue
                    # Some OpenAI-compatible providers emit "data:<json>" (no space)
                    # while others emit "data: <json>"; accept both.
                    data_str = line[5:].lstrip()
                    if data_str.strip() == "[DONE]":
                        if not held_flushed:
                            held_flushed = True
                            for ev in _held_as_call():
                                yield ev
                        # Emit end events for any unfinished tool calls
                        await _emit_pending_tool_ends()
                        for ev in pending_events:
                            yield ev
                        yield StreamEvent(type="done", data={"model": reported_model} if reported_model else {})
                        done_emitted = True
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("model"):
                        reported_model = str(chunk["model"])

                    # Extract usage if present
                    if "usage" in chunk and chunk["usage"]:
                        details = chunk["usage"].get("prompt_tokens_details")
                        cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
                        usage = TokenUsage(
                            prompt_tokens=chunk["usage"].get("prompt_tokens", 0),
                            completion_tokens=chunk["usage"].get("completion_tokens", 0),
                            total_tokens=chunk["usage"].get("total_tokens", 0),
                            cached_prompt_tokens=int(cached or 0) if isinstance(cached, (int, float)) else 0,
                        )
                        owner.session_usage.add(usage)
                        yield StreamEvent(type="usage", data={"usage": usage})

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # Text content
                    content = delta.get("content")
                    if content and holding:
                        held_text += content
                        probe = held_text.lstrip()
                        looks_like_json = not probe or probe[0] in "{`"
                        if not looks_like_json or len(held_text) > 12_000:
                            for ev in _release_held():
                                yield ev
                    elif content:
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

                        args_delta = coerce_args_fragment(func_obj.get("arguments", ""))
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

                        legacy_args = coerce_args_fragment(legacy_fc.get("arguments", ""))
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
                        if not held_flushed:
                            held_flushed = True
                            pending_events[0:0] = _held_as_call()
                        await _emit_pending_tool_ends()

                    for ev in pending_events:
                        yield ev

                # EOF is not proof of completion. A truncated provider stream must
                # never be promoted to a successful turn.
                if not done_emitted:
                    raise LLMError(
                        "OpenAI-compatible stream ended before the [DONE] confirmation.",
                        status=503,
                        retryable=True,
                    )
                return

        except httpx.HTTPStatusError as e:
            if e.response.status_code in RETRYABLE_STATUS and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                log.warning("HTTP error %d, retrying in %.1fs", e.response.status_code, delay)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise LLMError(str(e), status=e.response.status_code)
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                if isinstance(e, httpx.ConnectError):
                    from thomas.core.ollama_autostart import maybe_autostart_ollama

                    if maybe_autostart_ollama(getattr(owner.config, "base_url", None)):
                        delay = max(delay, 3.0)  # give the backend a moment to bind
                log.warning("Connection error, retrying in %.1fs: %s", delay, e)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise LLMError(f"Connection failed after {max_retries} attempts: {e}")
        finally:
            await finish_admitted_attempt(owner, lease, attempt_state)

    raise last_error or LLMError("Request failed after retries")


async def stream_openai_codex(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    turn_user_content: Any = None,
) -> AsyncIterator[StreamEvent]:
    """Stream through ChatGPT's native Codex Responses endpoint."""
    base = str(owner.config.base_url or OPENAI_CODEX_BASE_URL).rstrip("/")
    url = base + "/responses"
    profile = getattr(owner.config, "name", "") or "chatgpt"
    access_token = str(getattr(owner.config, "api_key", "") or "").strip()
    # Only a client that brought its own token (a Build child) keeps a recovered one in its config. A shared config
    # carries none and reads the store on every call: a token written into it outlived sign-outs and account switches.
    brought_token = bool(access_token)
    if access_token:
        access_token = await current_access_token(profile, access_token)
    else:
        access_token = await resolve_access_token(profile)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    client = await owner._get_client()
    last_error: Exception | None = None
    max_retries = max(1, int(owner._max_retries))
    base_delay = max(0.0, float(owner._base_retry_delay))

    auth_retry_used = False
    different_stored_token_retried = False
    live_token_used = False
    live_token_available_next_call = False
    live_token_checked_after_stored_retry = False
    for attempt in range(max_retries + 1):
        stream_event_emitted = False
        done_emitted = False
        lease = await owner.begin_budget_attempt(messages, tools)
        attempt_state = {"started": False}
        try:
            output_cap = int(getattr(lease, "output_cap", owner.config.max_tokens) or 0)
            if lease is not None and output_cap < max(1, int(owner.config.max_tokens or 1)):
                await owner.abort_budget_attempt(lease)
                lease = None
                raise LLMError(
                    "ChatGPT/Codex cannot safely enforce the reduced output budget for this request.",
                    status=429,
                )
            body = _build_openai_codex_request(
                owner,
                messages,
                tools,
                turn_user_content=turn_user_content,
            )
            # The ChatGPT backend keeps one session's calls together by this header; with only the body's key, 37% of
            # requests that merely grew at the end were served from cache (2026-11-06).
            if body.get("prompt_cache_key"):
                headers["session_id"] = str(body["prompt_cache_key"])
            async with admitted_stream(
                owner, client, "POST", url, attempt_state=attempt_state, json=body, headers=headers
            ) as resp:
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
                        # Kept by the park: your plan's limit outlives it by a day
                        # and a half, and the next message must still name it.
                        detail = (
                            f"ChatGPT/Codex HTTP 429 rate limited.{wait_note} "
                            f"{error_body.decode(errors='replace')[:240]}"
                        )
                        owner._mark_rate_limited(owner.config, retry_after_s, detail)
                        raise LLMError(
                            detail,
                            status=429,
                            retryable=True,
                            error_code=error_code,
                            response_headers=safe_headers,
                        )
                    if resp.status_code in RETRYABLE_STATUS and attempt < max_retries - 1:
                        last_error = LLMError(
                            f"ChatGPT/Codex HTTP {resp.status_code}: {error_body.decode(errors='replace')[:200]}",
                            status=resp.status_code,
                            retryable=True,
                        )
                        delay = base_delay * (2**attempt)
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    error_code, safe_headers = quota_error_fields(error_body, resp.headers)
                    if resp.status_code == 401:
                        if not auth_retry_used or different_stored_token_retried:
                            # A second rejected stored copy still needs checking against
                            # the live login, but must not get a second request retry.
                            previously_retried = auth_retry_used
                            auth_retry_used = True
                            replacement, live_token_checked = await recover_rejected_token(profile, access_token)
                            if previously_retried:
                                live_token_checked_after_stored_retry = live_token_checked
                                if replacement:
                                    if brought_token:
                                        owner.config.api_key = replacement
                                    live_token_available_next_call = live_token_checked
                            elif replacement:
                                live_token_used = live_token_checked
                                different_stored_token_retried = not live_token_checked
                                access_token = replacement
                                # Keep the token for the next model call in this run.
                                if brought_token:
                                    owner.config.api_key = replacement
                                headers["Authorization"] = f"Bearer {access_token}"
                                continue
                            else:
                                live_token_used = live_token_checked
                        reason = (
                            "revoked or invalidated"
                            if error_code == "token_revoked" or b"invalidated oauth token" in error_body.lower()
                            else "expired"
                            if error_code in {"token_expired", "expired_token"} or b"expired" in error_body.lower()
                            else "rejected"
                        )
                        source = "The live Codex login" if live_token_used else "The stored token"
                        guidance = (
                            " Run `codex login` to sign in again."
                            if live_token_used
                            else " A retry with a different stored token was also rejected."
                            if different_stored_token_retried
                            else " No retry with a different access token was made."
                        )
                        next_call_note = (
                            " The live Codex login was imported for the next call; it was not retried here."
                            if live_token_available_next_call
                            else " The live Codex login still contains the rejected stored token."
                            if live_token_checked_after_stored_retry
                            else ""
                        )
                        raise LLMError(
                            f"ChatGPT/Codex HTTP 401: {source} was {reason} by the server.{guidance}{next_call_note}",
                            status=401,
                            error_code=error_code,
                        )
                    raise LLMError(
                        f"ChatGPT/Codex HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                        status=resp.status_code,
                        error_code=error_code,
                        response_headers=safe_headers,
                    )

                tool_calls: dict[str, ToolCallAccumulator] = {}
                # Calls carry an item id ("fc_") and a call_id ("call_"); argument deltas name only the item id.
                # Key every call by call_id (what function_call_output names) via item_id -> call_id, or deltas
                # spawn a mis-keyed call: the next turn fails "No tool call found for function call output".
                item_to_call: dict[str, str] = {}
                reasoning_items: list[dict[str, Any]] = []  # replayed on the next step (llm_streaming_codex)
                # `response.model` from response.created/completed: the exact model
                # the provider says answered, carried on `done` for the Build turn.
                reported_model = ""

                def _done() -> StreamEvent:
                    return StreamEvent(type="done", data={"model": reported_model} if reported_model else {})

                event_name = ""
                data_lines: list[str] = []

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
                    nonlocal done_emitted, reported_model
                    events: list[StreamEvent] = []
                    data_str = payload.strip()
                    if not data_str or data_str == "[DONE]":
                        events.extend(await _emit_pending_tool_ends())
                        events.append(_done())
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
                    response_obj = chunk.get("response")
                    if isinstance(response_obj, dict) and response_obj.get("model"):
                        reported_model = str(response_obj["model"])
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
                            item_id = str(item.get("id") or "").strip()
                            call_id = str(item.get("call_id") or item_id or "").strip()
                            if item_id and call_id:
                                item_to_call[item_id] = call_id
                            raw_name = str(item.get("name") or "").strip()
                            name = owner._openai_tool_name_map.get(raw_name, raw_name)
                            if call_id and call_id not in tool_calls:
                                tool_calls[call_id] = ToolCallAccumulator(id=call_id, name=name)
                                events.append(StreamEvent(type="tool_call_start", data={"id": call_id, "name": name}))
                    elif event_type == "response.function_call_arguments.delta":
                        raw_ref = str(chunk.get("call_id") or chunk.get("item_id") or "").strip()
                        call_id = item_to_call.get(raw_ref, raw_ref)
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
                        reasoning_items.extend(_replayable_reasoning(item))
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
                    elif event_type == "response.completed":
                        _remember_reasoning(owner, reasoning_items, list(tool_calls))
                        events.extend(await _emit_pending_tool_ends())
                        events.append(_done())
                        done_emitted = True
                    elif event_type == "response.incomplete":
                        response = chunk.get("response")
                        details = response.get("incomplete_details") if isinstance(response, dict) else None
                        reason = details.get("reason") if isinstance(details, dict) else None
                        raise LLMError(
                            f"ChatGPT/Codex response was incomplete ({reason or 'unknown reason'}). Retry this turn.",
                            status=503,
                            retryable=True,
                        )
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
                                stream_event_emitted = True
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
                        stream_event_emitted = True
                        yield ev

                if not done_emitted:
                    last_error = LLMError(
                        "ChatGPT/Codex disconnected before confirming the response completed. Retry this turn.",
                        status=503,
                        retryable=True,
                    )
                    if not stream_event_emitted and attempt < max_retries - 1:
                        log.warning(
                            "ChatGPT/Codex stream ended before a terminal event; retrying request %d/%d",
                            attempt + 2,
                            max_retries,
                        )
                        delay = base_delay * (2**attempt)
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    raise last_error
                if not stream_event_emitted:
                    # The response completed and carried nothing. Returning here hands the caller an empty stream that
                    # is indistinguishable from a successful one, and every layer above then invents its own
                    # explanation: the Canvas worker calls it "empty output", retries, and finally reports "Canvas
                    # generation failed before a verified result was produced" -- while the diagnostics show only "0
                    # events, 0 tokens". Someone asking for a graph is told the canvas failed, with nothing anywhere
                    # saying the model returned an empty completion.
                    raise LLMError(
                        "ChatGPT/Codex completed the response without returning any content. "
                        "This usually means the request was rejected upstream (most often "
                        "expired or missing credentials) rather than that the model had "
                        "nothing to say.",
                        status=502,
                        retryable=True,
                    )
                return

        except LLMError as e:  # nothing reached the caller yet: an overloaded model is asked again (2026-10-26)
            trouble = provider_trouble.classify(str(e), e.status)
            if stream_event_emitted or attempt >= max_retries - 1 or getattr(trouble, "kind", "") not in _ASK_AGAIN:
                raise
            last_error = e
            await asyncio.sleep(max(base_delay * (2**attempt), 15.0 * (attempt + 1)))
        except httpx.HTTPStatusError as e:
            if e.response.status_code in RETRYABLE_STATUS and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise LLMError(str(e), status=e.response.status_code)
        except httpx.TransportError as e:
            last_error = e
            if done_emitted:
                return
            if not stream_event_emitted and attempt < max_retries - 1:
                log.warning(
                    "ChatGPT/Codex stream failed before usable output (%s); retrying request %d/%d",
                    type(e).__name__,
                    attempt + 2,
                    max_retries,
                )
                delay = base_delay * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            phase = "after partial output" if stream_event_emitted else "before any usable output"
            raise LLMError(
                f"ChatGPT/Codex stream disconnected {phase}. Retry this turn.",
                status=503,
                retryable=True,
            ) from e
        finally:
            await finish_admitted_attempt(owner, lease, attempt_state)

    raise last_error or LLMError("ChatGPT/Codex request failed after retries")
