"""Async multi-provider LLM client with streaming support.

Supports OpenAI-compatible endpoints (Ollama, vLLM, LM Studio, OpenAI)
and Anthropic's native API. Handles retries, error classification,
token tracking, and tool call parsing from streamed responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from thomas.core.config import ModelConfig

log = logging.getLogger(__name__)

# Retryable HTTP status codes
_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_FAILOVER_COOLDOWN_UNTIL: Dict[str, float] = {}


class LLMError(Exception):
    """LLM request failed after retries."""

    def __init__(self, message: str, status: int = 0, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class TokenUsage:
    """Token accounting for a single request or session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: TokenUsage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens


@dataclass
class StreamEvent:
    """A single event from a streaming LLM response."""

    type: str  # "token", "tool_call_start", "tool_call_delta", "tool_call_end", "done", "error", "usage"
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallAccumulator:
    """Accumulates streamed tool call chunks into complete calls."""

    id: str
    name: str = ""
    arguments: str = ""
    finished: bool = False


class LLMClient:
    """Async LLM client with streaming, retries, and multi-provider support."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        fallback_configs: Optional[List[ModelConfig]] = None,
        failover_enabled: bool = False,
        failover_cooldown_s: int = 300,
        failover_on_auth_error: bool = False,
    ):
        self.config = config
        self._primary_config = config
        self.session_usage = TokenUsage()
        self._client: Optional[httpx.AsyncClient] = None
        self._codex_provider: Optional[Any] = None  # lazy CodexProvider
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled) and len(self._fallback_configs) > 0
        self._failover_cooldown_s = max(0, int(failover_cooldown_s))
        self._failover_on_auth_error = bool(failover_on_auth_error)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if self.config.extra_headers:
                headers.update(self.config.extra_headers)

            if self.config.api_key:
                if self.config.provider == "anthropic":
                    headers["x-api-key"] = self.config.api_key
                    headers.setdefault("anthropic-version", "2023-06-01")
                else:
                    header_name = self.config.api_key_header or "Authorization"
                    prefix = self.config.api_key_prefix or ""
                    headers[header_name] = f"{prefix}{self.config.api_key}"

            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=self.config.timeout_s,
                    write=10.0,
                    pool=10.0,
                ),
            )
        return self._client

    async def close(self) -> None:
        if self._codex_provider is not None:
            await self._codex_provider.close()
            self._codex_provider = None
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _switch_config(self, cfg: ModelConfig) -> None:
        """Switch active model config and reset provider clients if needed."""
        if self.config is cfg:
            return
        if (
            self.config.name != cfg.name
            or self.config.provider != cfg.provider
            or self.config.base_url != cfg.base_url
            or self.config.model != cfg.model
            or self.config.api_key != cfg.api_key
        ):
            await self.close()
        self.config = cfg

    @staticmethod
    def _cooldown_key(cfg: ModelConfig) -> str:
        return str(cfg.name or cfg.model or "unknown")

    def _mark_cooldown(self, cfg: ModelConfig) -> None:
        if self._failover_cooldown_s <= 0:
            return
        key = self._cooldown_key(cfg)
        _FAILOVER_COOLDOWN_UNTIL[key] = time.monotonic() + float(self._failover_cooldown_s)

    def _cooldown_remaining(self, cfg: ModelConfig) -> float:
        key = self._cooldown_key(cfg)
        until = float(_FAILOVER_COOLDOWN_UNTIL.get(key, 0.0) or 0.0)
        rem = until - time.monotonic()
        return rem if rem > 0 else 0.0

    def _build_openai_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": stream,
        }
        if self.config.top_p < 1.0:
            body["top_p"] = self.config.top_p
        if tools:
            body["tools"] = tools
        return body

    def _build_anthropic_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> Dict[str, Any]:
        # Convert OpenAI message format to Anthropic format
        system_text = ""
        anthropic_messages: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                system_text += msg.get("content", "") + "\n"

            elif role == "assistant":
                # Convert assistant messages with tool_calls to Anthropic content blocks
                content_blocks: List[Dict[str, Any]] = []
                text = msg.get("content", "")
                if text:
                    content_blocks.append({"type": "text", "text": text})
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if args_str else {}
                    except json.JSONDecodeError:
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": args,
                    })
                if content_blocks:
                    anthropic_messages.append({"role": "assistant", "content": content_blocks})
                elif text:
                    anthropic_messages.append({"role": "assistant", "content": text})

            elif role == "tool":
                # Convert tool result to Anthropic tool_result content block
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                }
                # Anthropic requires tool_result blocks in a "user" message
                # Group consecutive tool results together
                if (anthropic_messages
                        and anthropic_messages[-1]["role"] == "user"
                        and isinstance(anthropic_messages[-1]["content"], list)
                        and anthropic_messages[-1]["content"]
                        and anthropic_messages[-1]["content"][0].get("type") == "tool_result"):
                    anthropic_messages[-1]["content"].append(tool_result)
                else:
                    anthropic_messages.append({"role": "user", "content": [tool_result]})

            elif role == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    blocks: List[Dict[str, Any]] = []
                    for part in content:
                        if isinstance(part, dict):
                            ptype = part.get("type")
                            if ptype == "text":
                                blocks.append({"type": "text", "text": str(part.get("text", ""))})
                            elif ptype == "image_url":
                                img = part.get("image_url", {})
                                url = img.get("url") if isinstance(img, dict) else str(img)
                                if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                                    meta, b64 = url.split(";base64,", 1)
                                    media_type = meta[5:] or "image/png"
                                    blocks.append(
                                        {
                                            "type": "image",
                                            "source": {
                                                "type": "base64",
                                                "media_type": media_type,
                                                "data": b64,
                                            },
                                        }
                                    )
                        elif isinstance(part, str):
                            blocks.append({"type": "text", "text": part})
                    anthropic_messages.append({"role": "user", "content": blocks})
                else:
                    anthropic_messages.append({"role": "user", "content": content})

        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": stream,
        }
        if system_text:
            body["system"] = system_text.strip()
        if tools:
            # Convert OpenAI tool format to Anthropic tool format
            anthropic_tools = []
            for t in tools:
                func = t.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })
            body["tools"] = anthropic_tools
        return body

    @staticmethod
    def _extract_anthropic_usage(event_data: Dict[str, Any]) -> Dict[str, int]:
        """Extract Anthropic usage fields from top-level and nested message objects."""
        raw_usage: Dict[str, Any] = {}

        top_usage = event_data.get("usage")
        if isinstance(top_usage, dict):
            raw_usage.update(top_usage)

        message_obj = event_data.get("message")
        if isinstance(message_obj, dict):
            msg_usage = message_obj.get("usage")
            if isinstance(msg_usage, dict):
                for k, v in msg_usage.items():
                    raw_usage.setdefault(k, v)

        out: Dict[str, int] = {}
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

    async def _get_codex_provider(self) -> Any:
        if self._codex_provider is None:
            from thomas.codex.provider import CodexProvider
            self._codex_provider = CodexProvider(self.config)
        return self._codex_provider

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion, yielding events as they arrive."""
        if not self._failover_enabled:
            async for event in self._stream_current_provider(messages, tools):
                yield event
            return

        primary_cfg = self._primary_config
        candidates = [primary_cfg] + [cfg for cfg in self._fallback_configs]
        last_error: Optional[Exception] = None

        for idx, cfg in enumerate(candidates):
            if idx > 0:
                rem = self._cooldown_remaining(cfg)
                if rem > 0:
                    log.info(
                        "Skipping failover profile '%s' due cooldown (%.0fs remaining).",
                        cfg.name,
                        rem,
                    )
                    continue

            await self._switch_config(cfg)

            try:
                async for event in self._stream_current_provider(messages, tools):
                    yield event
                return
            except LLMError as e:
                last_error = e
                auth_error = e.status in (401, 403)
                if auth_error and not self._failover_on_auth_error:
                    raise
                self._mark_cooldown(cfg)
                if idx < len(candidates) - 1:
                    log.warning(
                        "LLM profile '%s' failed (%s). Trying failover profile.",
                        cfg.name,
                        e,
                    )
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException, OSError) as e:
                last_error = e
                self._mark_cooldown(cfg)
                if idx < len(candidates) - 1:
                    log.warning(
                        "LLM profile '%s' connection failed (%s). Trying failover profile.",
                        cfg.name,
                        type(e).__name__,
                    )
                    continue
                raise

        if last_error is not None:
            if isinstance(last_error, Exception):
                raise last_error
        raise LLMError("No available model profiles after failover checks.")

    async def _stream_current_provider(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        if self.config.provider == "codex":
            provider = await self._get_codex_provider()
            async for event in provider.stream_chat(messages, tools):
                yield event
        elif self.config.provider == "anthropic":
            async for event in self._stream_anthropic(messages, tools):
                yield event
        else:
            async for event in self._stream_openai(messages, tools):
                yield event

    async def _stream_openai(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        base = self.config.base_url.rstrip("/")
        path = self.config.chat_path or "/chat/completions"
        if not path.startswith("/"):
            path = "/" + path
        url = base + path
        body = self._build_openai_request(messages, tools, stream=True)

        client = await self._get_client()
        params = self.config.query or None
        last_error: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES):
            try:
                async with client.stream("POST", url, json=body, params=params) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        if resp.status_code in _RETRYABLE:
                            last_error = LLMError(
                                f"HTTP {resp.status_code}: {error_body.decode(errors='replace')[:200]}",
                                status=resp.status_code,
                                retryable=True,
                            )
                            delay = _BASE_DELAY * (2**attempt)
                            log.warning(
                                "LLM request failed (attempt %d/%d), retrying in %.1fs: %s",
                                attempt + 1, _MAX_RETRIES, delay, last_error,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise LLMError(
                            f"HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                            status=resp.status_code,
                        )

                    tool_calls: Dict[int, ToolCallAccumulator] = {}
                    # Avoid returning from inside the streaming iterator; letting the
                    # `async for` unwind cleanly prevents noisy asyncio/httpx shutdown
                    # errors on some platforms.
                    done_emitted = False

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            # Emit end events for any unfinished tool calls
                            for tc in tool_calls.values():
                                if not tc.finished:
                                    tc.finished = True
                                    yield StreamEvent(
                                        type="tool_call_end",
                                        data={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                                    )
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
                            self.session_usage.add(usage)
                            yield StreamEvent(type="usage", data={"usage": usage})

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        # Text content
                        content = delta.get("content")
                        if content:
                            yield StreamEvent(type="token", data={"text": content})

                        # Tool calls
                        for tc_delta in delta.get("tool_calls", []):
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls:
                                tc_id = tc_delta.get("id", f"call_{idx}")
                                tc_name = tc_delta.get("function", {}).get("name", "")
                                tool_calls[idx] = ToolCallAccumulator(id=tc_id, name=tc_name)
                                yield StreamEvent(
                                    type="tool_call_start",
                                    data={"id": tc_id, "name": tc_name, "index": idx},
                                )

                            args_delta = tc_delta.get("function", {}).get("arguments", "")
                            if args_delta:
                                tool_calls[idx].arguments += args_delta
                                yield StreamEvent(
                                    type="tool_call_delta",
                                    data={"id": tool_calls[idx].id, "delta": args_delta},
                                )

                            # Update name if it wasn't in the first chunk
                            name_delta = tc_delta.get("function", {}).get("name", "")
                            if name_delta and not tool_calls[idx].name:
                                tool_calls[idx].name = name_delta

                        # Finish reason
                        finish = choices[0].get("finish_reason")
                        if finish == "tool_calls" or finish == "stop":
                            for tc in tool_calls.values():
                                if not tc.finished:
                                    tc.finished = True
                                    yield StreamEvent(
                                        type="tool_call_end",
                                        data={
                                            "id": tc.id,
                                            "name": tc.name,
                                            "arguments": tc.arguments,
                                        },
                                    )

                    # Stream completed without [DONE].
                    if not done_emitted:
                        yield StreamEvent(type="done")
                    return

            except httpx.HTTPStatusError as e:
                if e.response.status_code in _RETRYABLE and attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2**attempt)
                    log.warning("HTTP error %d, retrying in %.1fs", e.response.status_code, delay)
                    await asyncio.sleep(delay)
                    continue
                raise LLMError(str(e), status=e.response.status_code)
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2**attempt)
                    log.warning("Connection error, retrying in %.1fs: %s", delay, e)
                    await asyncio.sleep(delay)
                    continue
                raise LLMError(f"Connection failed after {_MAX_RETRIES} attempts: {e}")

        raise last_error or LLMError("Request failed after retries")

    async def _stream_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self.config.base_url.rstrip('/')}/messages"
        body = self._build_anthropic_request(messages, tools, stream=True)

        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES):
            try:
                async with client.stream("POST", url, json=body) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        if resp.status_code in _RETRYABLE:
                            last_error = LLMError(
                                f"Anthropic HTTP {resp.status_code}: "
                                f"{error_body.decode(errors='replace')[:200]}",
                                status=resp.status_code,
                                retryable=True,
                            )
                            delay = _BASE_DELAY * (2**attempt)
                            log.warning(
                                "Anthropic request failed (attempt %d/%d), retrying in %.1fs: %s",
                                attempt + 1, _MAX_RETRIES, delay, last_error,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise LLMError(
                            f"Anthropic HTTP {resp.status_code}: "
                            f"{error_body.decode(errors='replace')[:500]}",
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
                        usage_fields = self._extract_anthropic_usage(event_data)
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
                                current_tool_name = block.get("name", "")
                                current_tool_args = ""
                                yield StreamEvent(
                                    type="tool_call_start",
                                    data={"id": current_tool_id, "name": current_tool_name},
                                )

                        elif event_type == "content_block_delta":
                            delta = event_data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield StreamEvent(type="token", data={"text": delta.get("text", "")})
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

                        elif event_type == "message_stop":
                            if not usage_emitted and (prompt_tokens or completion_tokens):
                                tu = TokenUsage(
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens,
                                    total_tokens=prompt_tokens + completion_tokens,
                                )
                                self.session_usage.add(tu)
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
                        self.session_usage.add(tu)
                        yield StreamEvent(type="usage", data={"usage": tu})
                    yield StreamEvent(type="done")
                    return

            except httpx.ConnectError as e:
                last_error = e
                delay = _BASE_DELAY * (2**attempt)
                log.warning(
                    "Anthropic connection failed (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)

        raise LLMError(
            f"Anthropic request failed after {_MAX_RETRIES} attempts: {last_error}",
            retryable=False,
        )

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Non-streaming chat completion. Returns full response.

        Returns dict with keys:
        - text: str (assistant's text response)
        - tool_calls: list of {id, name, arguments} dicts
        - usage: TokenUsage
        """
        text_parts: list[str] = []
        tool_calls: list[Dict[str, Any]] = []
        usage = TokenUsage()

        async for event in self.stream_chat(messages, tools):
            if event.type == "token":
                text_parts.append(event.data["text"])
            elif event.type == "tool_call_end":
                tool_calls.append({
                    "id": event.data["id"],
                    "name": event.data["name"],
                    "arguments": event.data["arguments"],
                })
            elif event.type == "usage":
                usage = event.data["usage"]

        return {
            "text": "".join(text_parts),
            "tool_calls": tool_calls,
            "usage": usage,
        }
