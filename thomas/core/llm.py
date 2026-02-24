"""Async multi-provider LLM client with streaming support.

Supports OpenAI-compatible endpoints (Ollama, vLLM, LM Studio, OpenAI)
and Anthropic's native API. Handles retries, error classification,
token tracking, and tool call parsing from streamed responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from email.utils import parsedate_to_datetime
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
_RATE_LIMIT_COOLDOWN_UNTIL: Dict[str, float] = {}
_DEFAULT_RATE_LIMIT_COOLDOWN_S = 20.0
_MAX_RETRY_AFTER_S = 300.0


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
        max_retries: int = _MAX_RETRIES,
        base_retry_delay_s: float = _BASE_DELAY,
        request_overrides: Optional[Dict[str, Any]] = None,
    ):
        self.config = config
        self._primary_config = config
        self.session_usage = TokenUsage()
        self._client: Optional[httpx.AsyncClient] = None
        self._anthropic_tool_name_map: Dict[str, str] = {}  # sanitized→original
        self._openai_tool_name_map: Dict[str, str] = {}  # sanitized→original
        self._codex_provider: Optional[Any] = None  # lazy CodexProvider
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled) and len(self._fallback_configs) > 0
        self._failover_cooldown_s = max(0, int(failover_cooldown_s))
        self._failover_on_auth_error = bool(failover_on_auth_error)
        self._max_retries = max(1, int(max_retries))
        self._base_retry_delay = max(0.0, float(base_retry_delay_s))
        self._request_overrides = dict(request_overrides or {})
        self._attempt_trace: List[Dict[str, Any]] = []

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

    @staticmethod
    def _retry_after_seconds(headers: Any) -> Optional[float]:
        if headers is None:
            return None
        raw = ""
        try:
            raw = str(
                headers.get("retry-after")
                or headers.get("Retry-After")
                or ""
            ).strip()
        except Exception:
            raw = ""
        if not raw:
            return None

        try:
            seconds = float(raw)
            if seconds >= 0:
                return min(seconds, _MAX_RETRY_AFTER_S)
        except Exception:
            pass

        try:
            dt = parsedate_to_datetime(raw)
            now = time.time()
            delta = max(0.0, float(dt.timestamp() - now))
            return min(delta, _MAX_RETRY_AFTER_S)
        except Exception:
            return None

    def _mark_rate_limited(self, cfg: ModelConfig, retry_after_s: Optional[float]) -> None:
        key = self._cooldown_key(cfg)
        base = float(_DEFAULT_RATE_LIMIT_COOLDOWN_S)
        wait = float(retry_after_s) if retry_after_s is not None else base
        wait = max(base, min(wait, _MAX_RETRY_AFTER_S))
        _RATE_LIMIT_COOLDOWN_UNTIL[key] = time.monotonic() + wait

    def _rate_limit_remaining(self, cfg: ModelConfig) -> float:
        key = self._cooldown_key(cfg)
        until = float(_RATE_LIMIT_COOLDOWN_UNTIL.get(key, 0.0) or 0.0)
        rem = until - time.monotonic()
        return rem if rem > 0 else 0.0

    @staticmethod
    def _cfg_snapshot(cfg: ModelConfig) -> Dict[str, Any]:
        return {
            "profile": str(cfg.name or ""),
            "provider": str(cfg.provider or ""),
            "model": str(cfg.model or ""),
            "base_url": str(cfg.base_url or ""),
        }

    def runtime_trace(self) -> Dict[str, Any]:
        """Runtime model trace for the most recent stream_chat() call."""
        primary = self._cfg_snapshot(self._primary_config)
        active = self._cfg_snapshot(self.config)
        attempts = [dict(a) for a in self._attempt_trace]
        failover_used = any(
            str(a.get("status") or "") == "success"
            and str(a.get("profile") or "") != str(primary.get("profile") or "")
            for a in attempts
        )
        return {
            "requested": primary,
            "active": active,
            "failover_enabled": bool(self._failover_enabled),
            "failover_used": bool(failover_used),
            "attempts": attempts,
        }

    @staticmethod
    def _sanitize_tool_name(name: str) -> str:
        """Sanitize a tool name to match ^[a-zA-Z0-9_-]{1,128}$.

        Many providers (Amazon Bedrock, some Azure deployments) reject tool
        names that contain dots or other special characters. Replace dots with
        underscores — the same strategy used for Anthropic.
        """
        safe = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return safe[:128]

    def _build_openai_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> Dict[str, Any]:
        # Reset per-request tool name map
        self._openai_tool_name_map = {}

        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": stream,
        }
        if self.config.top_p < 1.0:
            body["top_p"] = self.config.top_p
        freq_pen = self._request_overrides.get("frequency_penalty")
        if freq_pen is not None:
            body["frequency_penalty"] = float(freq_pen)
        pres_pen = self._request_overrides.get("presence_penalty")
        if pres_pen is not None:
            body["presence_penalty"] = float(pres_pen)
        seed = self._request_overrides.get("seed")
        if seed is not None:
            body["seed"] = int(seed)
        if bool(self._request_overrides.get("json_mode", False)):
            body["response_format"] = {"type": "json_object"}
        stop = self._request_overrides.get("stop")
        if isinstance(stop, list) and stop:
            body["stop"] = [str(x) for x in stop if str(x)]
        elif isinstance(stop, str) and stop.strip():
            body["stop"] = stop.strip()
        if tools:
            sanitized_tools = []
            for t in tools:
                func = t.get("function", {})
                original_name = func.get("name", "")
                safe_name = self._sanitize_tool_name(original_name)
                if safe_name != original_name:
                    self._openai_tool_name_map[safe_name] = original_name
                sanitized_tool = dict(t)
                sanitized_tool["function"] = dict(func)
                sanitized_tool["function"]["name"] = safe_name
                sanitized_tools.append(sanitized_tool)
            body["tools"] = sanitized_tools
        return body

    def _build_anthropic_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> Dict[str, Any]:
        # Reset per-request state
        self._anthropic_tool_name_map = {}

        # Convert OpenAI message format to Anthropic format
        system_text = ""
        anthropic_messages: List[Dict[str, Any]] = []
        pending_tool_use_ids: set[str] = set()
        current_tool_result_anchor: Optional[str] = None

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
                assistant_tool_use_ids: set[str] = set()
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if args_str else {}
                    except json.JSONDecodeError:
                        log.warning("Malformed tool arguments for %s: %s",
                                    func.get("name", "?"), args_str[:200])
                        args = {}
                    tc_id = str(tc.get("id", "")).strip()
                    if not tc_id:
                        continue
                    assistant_tool_use_ids.add(tc_id)
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc_id,
                        "name": func.get("name", "").replace(".", "_"),
                        "input": args,
                    })
                if content_blocks:
                    anthropic_messages.append({"role": "assistant", "content": content_blocks})
                elif text:
                    anthropic_messages.append({"role": "assistant", "content": text})
                pending_tool_use_ids = set(assistant_tool_use_ids)
                current_tool_result_anchor = None

            elif role == "tool":
                tool_use_id = str(msg.get("tool_call_id", "")).strip()
                if not tool_use_id:
                    log.debug("Dropping Anthropic tool_result without tool_call_id.")
                    continue
                if tool_use_id not in pending_tool_use_ids:
                    log.debug(
                        "Dropping orphan/mismatched Anthropic tool_result id=%s (pending=%s)",
                        tool_use_id,
                        sorted(pending_tool_use_ids),
                    )
                    continue

                # Convert tool result to Anthropic tool_result content block
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": msg.get("content", ""),
                }
                # Anthropic requires tool_result blocks in a "user" message
                # Group consecutive tool results together
                if (anthropic_messages
                        and anthropic_messages[-1]["role"] == "user"
                        and isinstance(anthropic_messages[-1]["content"], list)
                        and anthropic_messages[-1]["content"]
                        and anthropic_messages[-1]["content"][0].get("type") == "tool_result"
                        and current_tool_result_anchor == "assistant_tool_use"):
                    anthropic_messages[-1]["content"].append(tool_result)
                else:
                    anthropic_messages.append({"role": "user", "content": [tool_result]})
                    current_tool_result_anchor = "assistant_tool_use"
                pending_tool_use_ids.discard(tool_use_id)

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
                pending_tool_use_ids = set()
                current_tool_result_anchor = None

        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": stream,
        }
        if system_text:
            body["system"] = system_text.strip()
        stop = self._request_overrides.get("stop")
        if isinstance(stop, list) and stop:
            body["stop_sequences"] = [str(x) for x in stop if str(x)]
        elif isinstance(stop, str) and stop.strip():
            body["stop_sequences"] = [stop.strip()]
        if tools:
            # Convert OpenAI tool format to Anthropic tool format.
            # Anthropic tool names must match [a-zA-Z0-9_-]; replace dots.
            anthropic_tools = []
            name_map: Dict[str, str] = {}
            for t in tools:
                func = t.get("function", {})
                original_name = func.get("name", "")
                safe_name = original_name.replace(".", "_")
                name_map[safe_name] = original_name
                anthropic_tools.append({
                    "name": safe_name,
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })
            body["tools"] = anthropic_tools
            body["tool_choice"] = {"type": "auto"}
            self._anthropic_tool_name_map = name_map
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
        self._attempt_trace = []
        if not self._failover_enabled:
            rem = self._rate_limit_remaining(self.config)
            if rem > 0:
                attempt = {
                    **self._cfg_snapshot(self.config),
                    "status": "skipped_rate_limited",
                    "cooldown_remaining_s": int(rem),
                }
                self._attempt_trace.append(attempt)
                raise LLMError(
                    f"Rate-limit cooldown active for profile '{self.config.name}' "
                    f"({int(rem)}s remaining).",
                    status=429,
                    retryable=True,
                )
            attempt = {
                **self._cfg_snapshot(self.config),
                "status": "running",
            }
            self._attempt_trace.append(attempt)
            try:
                async for event in self._stream_current_provider(messages, tools):
                    yield event
                attempt["status"] = "success"
                return
            except Exception as e:
                attempt["status"] = "error"
                attempt["error"] = f"{type(e).__name__}: {e}"
                raise

        primary_cfg = self._primary_config
        candidates = [primary_cfg] + [cfg for cfg in self._fallback_configs]
        last_error: Optional[Exception] = None

        for idx, cfg in enumerate(candidates):
            attempt = {
                **self._cfg_snapshot(cfg),
                "status": "running",
            }
            self._attempt_trace.append(attempt)
            rate_limited_for = self._rate_limit_remaining(cfg)
            if rate_limited_for > 0:
                attempt["status"] = "skipped_rate_limited"
                attempt["cooldown_remaining_s"] = int(rate_limited_for)
                if idx < len(candidates) - 1:
                    continue
                last_error = LLMError(
                    f"Rate-limit cooldown active for profile '{cfg.name}' "
                    f"({int(rate_limited_for)}s remaining).",
                    status=429,
                    retryable=True,
                )
                continue
            if idx > 0:
                rem = self._cooldown_remaining(cfg)
                if rem > 0:
                    log.info(
                        "Skipping failover profile '%s' due cooldown (%.0fs remaining).",
                        cfg.name,
                        rem,
                    )
                    attempt["status"] = "skipped_cooldown"
                    attempt["cooldown_remaining_s"] = int(rem)
                    continue

            await self._switch_config(cfg)

            try:
                async for event in self._stream_current_provider(messages, tools):
                    yield event
                attempt["status"] = "success"
                return
            except LLMError as e:
                last_error = e
                attempt["status"] = "error"
                attempt["error"] = f"LLMError({int(getattr(e, 'status', 0) or 0)}): {e}"
                attempt["retryable"] = bool(getattr(e, "retryable", False))
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
                attempt["status"] = "error"
                attempt["error"] = f"{type(e).__name__}: {e}"
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
        max_retries = max(1, int(self._max_retries))
        base_delay = max(0.0, float(self._base_retry_delay))

        for attempt in range(max_retries):
            try:
                async with client.stream("POST", url, json=body, params=params) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        if resp.status_code == 429:
                            retry_after_s = self._retry_after_seconds(getattr(resp, "headers", None))
                            self._mark_rate_limited(self.config, retry_after_s)
                            wait_note = (
                                f" Retry after about {int(retry_after_s)}s."
                                if retry_after_s is not None and retry_after_s > 0
                                else ""
                            )
                            raise LLMError(
                                f"HTTP 429 rate limited.{wait_note} "
                                f"{error_body.decode(errors='replace')[:240]}",
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
                                attempt + 1, max_retries, delay, last_error,
                            )
                            if delay > 0:
                                await asyncio.sleep(delay)
                            continue
                        raise LLMError(
                            f"HTTP {resp.status_code}: {error_body.decode(errors='replace')[:500]}",
                            status=resp.status_code,
                        )

                    tool_calls: Dict[int, ToolCallAccumulator] = {}
                    legacy_tool_idx = -1

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
                        pending_events: List[StreamEvent] = []
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
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
                            try:
                                idx = int(tc_delta.get("index", 0))
                            except Exception:
                                idx = 0
                            if idx not in tool_calls:
                                tc_id = tc_delta.get("id", f"call_{idx}")
                                raw_name = tc_delta.get("function", {}).get("name", "")
                                # Reverse-map sanitized name back to original dotted name
                                tc_name = self._openai_tool_name_map.get(raw_name, raw_name)
                                tool_calls[idx] = ToolCallAccumulator(id=tc_id, name=tc_name)
                                pending_events.append(StreamEvent(
                                    type="tool_call_start",
                                    data={"id": tc_id, "name": tc_name, "index": idx},
                                ))

                            args_delta = _coerce_args_fragment(
                                tc_delta.get("function", {}).get("arguments", "")
                            )
                            if args_delta:
                                tool_calls[idx].arguments += args_delta
                                pending_events.append(StreamEvent(
                                    type="tool_call_delta",
                                    data={"id": tool_calls[idx].id, "delta": args_delta},
                                ))

                            # Update name if it wasn't in the first chunk (reverse-map too)
                            name_delta = tc_delta.get("function", {}).get("name", "")
                            if name_delta and not tool_calls[idx].name:
                                tool_calls[idx].name = self._openai_tool_name_map.get(name_delta, name_delta)

                        # Legacy OpenAI function-calling stream format:
                        # delta.function_call.{name,arguments}
                        legacy_fc = delta.get("function_call", {})
                        if isinstance(legacy_fc, dict) and legacy_fc:
                            legacy_name = str(legacy_fc.get("name", "") or "")
                            if legacy_tool_idx not in tool_calls:
                                tc_id = "call_legacy_0"
                                tool_calls[legacy_tool_idx] = ToolCallAccumulator(
                                    id=tc_id,
                                    name=legacy_name,
                                )
                                pending_events.append(StreamEvent(
                                    type="tool_call_start",
                                    data={"id": tc_id, "name": legacy_name, "index": legacy_tool_idx},
                                ))

                            if legacy_name and not tool_calls[legacy_tool_idx].name:
                                tool_calls[legacy_tool_idx].name = legacy_name

                            legacy_args = _coerce_args_fragment(legacy_fc.get("arguments", ""))
                            if legacy_args:
                                tool_calls[legacy_tool_idx].arguments += legacy_args
                                pending_events.append(StreamEvent(
                                    type="tool_call_delta",
                                    data={"id": tool_calls[legacy_tool_idx].id, "delta": legacy_args},
                                ))

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

    async def _stream_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self.config.base_url.rstrip('/')}/messages"
        body = self._build_anthropic_request(messages, tools, stream=True)

        # Debug: log tool configuration sent to Anthropic
        tool_names = [t["name"] for t in body.get("tools", [])]
        if tool_names:
            log.debug("Anthropic request: %d tools [%s], tool_choice=%s",
                      len(tool_names), ", ".join(tool_names[:5]),
                      body.get("tool_choice"))
        else:
            log.debug("Anthropic request: NO tools sent")

        client = await self._get_client()
        last_error: Optional[Exception] = None
        max_retries = max(1, int(self._max_retries))
        base_delay = max(0.0, float(self._base_retry_delay))

        for attempt in range(max_retries):
            try:
                async with client.stream("POST", url, json=body) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        if resp.status_code == 429:
                            retry_after_s = self._retry_after_seconds(getattr(resp, "headers", None))
                            self._mark_rate_limited(self.config, retry_after_s)
                            wait_note = (
                                f" Retry after about {int(retry_after_s)}s."
                                if retry_after_s is not None and retry_after_s > 0
                                else ""
                            )
                            raise LLMError(
                                f"Anthropic HTTP 429 rate limited.{wait_note} "
                                f"{error_body.decode(errors='replace')[:240]}",
                                status=429,
                                retryable=True,
                            )
                        if resp.status_code in _RETRYABLE:
                            last_error = LLMError(
                                f"Anthropic HTTP {resp.status_code}: "
                                f"{error_body.decode(errors='replace')[:200]}",
                                status=resp.status_code,
                                retryable=True,
                            )
                            delay = base_delay * (2**attempt)
                            log.warning(
                                "Anthropic request failed (attempt %d/%d), retrying in %.1fs: %s",
                                attempt + 1, max_retries, delay, last_error,
                            )
                            if delay > 0:
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
                        log.debug("Anthropic SSE event: %s", event_type)
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
                                # Reverse-map sanitized name back to original dotted name
                                raw_name = block.get("name", "")
                                current_tool_name = self._anthropic_tool_name_map.get(raw_name, raw_name)
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
                delay = base_delay * (2**attempt)
                log.warning(
                    "Anthropic connection failed (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, max_retries, delay,
                )
                if delay > 0:
                    await asyncio.sleep(delay)

        raise LLMError(
            f"Anthropic request failed after {max_retries} attempts: {last_error}",
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
