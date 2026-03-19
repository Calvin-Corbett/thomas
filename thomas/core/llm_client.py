"""LLMClient: Async multi-provider LLM client with streaming support.

Provides the base LLMClient class with configuration management, streaming,
retries, error classification, token tracking, and tool call parsing.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from thomas.core.config import ModelConfig
from thomas.core.llm_shared import LLMError, StreamEvent, TokenUsage
from thomas.core.llm_streaming import stream_anthropic, stream_openai

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_DEFAULT_RATE_LIMIT_COOLDOWN_S = 20.0
_MAX_RETRY_AFTER_S = 300.0
_AUTH_FAILURE_BASE_S = 18_000.0  # 5 hours (billing/auth failures)
_SERVER_FAILURE_BASE_S = 300.0  # 5 minutes (general server errors)
_MAX_BACKOFF_S = 86_400.0  # 24 hours cap
_RATE_LIMIT_BACKOFF_CAP_S = 600.0  # 10 minutes cap for rate limits


@dataclass
class _ProviderCooldown:
    """Tracks per-provider cooldown with exponential backoff."""

    until: float = 0.0
    failure_count: int = 0
    failure_type: str = ""  # "rate_limit" | "auth" | "server" | "connect"

    def mark(self, failure_type: str, base_s: float = _SERVER_FAILURE_BASE_S) -> None:
        self.failure_type = failure_type
        self.failure_count += 1
        wait = base_s * (2 ** min(self.failure_count - 1, 7))
        wait = min(wait, _MAX_BACKOFF_S)
        if failure_type == "rate_limit":
            wait = min(wait, _RATE_LIMIT_BACKOFF_CAP_S)
        self.until = time.monotonic() + wait

    def remaining(self) -> float:
        rem = self.until - time.monotonic()
        return rem if rem > 0 else 0.0

    def is_active(self) -> bool:
        return self.remaining() > 0

    def clear(self) -> None:
        self.until = 0.0
        self.failure_count = 0
        self.failure_type = ""


_PROVIDER_COOLDOWNS: dict[str, _ProviderCooldown] = {}


async def _coerce_async_iterator(value: Any, *, source: str) -> AsyncIterator[Any]:
    if hasattr(value, "__aiter__"):
        return value
    if inspect.isawaitable(value):
        resolved = await value
        if hasattr(resolved, "__aiter__"):
            return resolved
        raise TypeError(f"{source} returned {type(resolved)!r} after await, not an async iterator.")
    raise TypeError(f"{source} returned unsupported type {type(value)!r}; expected async iterator.")


def _get_cooldown(key: str) -> _ProviderCooldown:
    if key not in _PROVIDER_COOLDOWNS:
        _PROVIDER_COOLDOWNS[key] = _ProviderCooldown()
    return _PROVIDER_COOLDOWNS[key]


class LLMClient:
    """Async LLM client with streaming, retries, and multi-provider support."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        fallback_configs: list[ModelConfig] | None = None,
        failover_enabled: bool = False,
        failover_cooldown_s: int = 300,
        failover_on_auth_error: bool = False,
        max_retries: int = _MAX_RETRIES,
        base_retry_delay_s: float = _BASE_DELAY,
        request_overrides: dict[str, Any] | None = None,
    ):
        self.config = config
        self._primary_config = config
        self.session_usage = TokenUsage()
        self._client: httpx.AsyncClient | None = None
        self._anthropic_tool_name_map: dict[str, str] = {}  # sanitized→original
        self._openai_tool_name_map: dict[str, str] = {}  # sanitized→original
        self._codex_provider: Any | None = None  # lazy CodexProvider
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled) and len(self._fallback_configs) > 0
        self._failover_cooldown_s = max(0, int(failover_cooldown_s))
        self._failover_on_auth_error = bool(failover_on_auth_error)
        self._max_retries = max(1, int(max_retries))
        self._base_retry_delay = max(0.0, float(base_retry_delay_s))
        self._session_pinned_key: str | None = None  # set on first success
        self._request_overrides = dict(request_overrides or {})
        self._attempt_trace: list[dict[str, Any]] = []

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
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

    def _mark_cooldown(self, cfg: ModelConfig, failure_type: str = "server") -> None:
        if self._failover_cooldown_s <= 0:
            return
        key = self._cooldown_key(cfg)
        cd = _get_cooldown(key)
        base = _AUTH_FAILURE_BASE_S if failure_type == "auth" else float(self._failover_cooldown_s)
        cd.mark(failure_type, base_s=base)

    def _clear_cooldown(self, cfg: ModelConfig) -> None:
        key = self._cooldown_key(cfg)
        cd = _get_cooldown(key)
        cd.clear()
        # Also clear session pin tracking on explicit clear.
        if hasattr(self, "_session_pinned_key") and self._session_pinned_key == key:
            pass  # keep pin; it succeeded

    def _cooldown_remaining(self, cfg: ModelConfig) -> float:
        key = self._cooldown_key(cfg)
        return _get_cooldown(key).remaining()

    @staticmethod
    def _retry_after_seconds(headers: Any) -> float | None:
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
                return min(seconds, _MAX_RETRY_AFTER_S)
        except ValueError:
            pass

        try:
            dt = parsedate_to_datetime(raw)
            now = time.time()
            delta = max(0.0, float(dt.timestamp() - now))
            return min(delta, _MAX_RETRY_AFTER_S)
        except (ValueError, TypeError):
            return None

    def _mark_rate_limited(self, cfg: ModelConfig, retry_after_s: float | None) -> None:
        key = self._cooldown_key(cfg)
        cd = _get_cooldown(key)
        if retry_after_s is not None and retry_after_s > 0:
            # Use server-provided Retry-After directly (capped).
            cd.until = time.monotonic() + min(float(retry_after_s), _MAX_RETRY_AFTER_S)
            cd.failure_type = "rate_limit"
            cd.failure_count = max(cd.failure_count, 1)
        else:
            cd.mark("rate_limit", base_s=float(_DEFAULT_RATE_LIMIT_COOLDOWN_S))

    def _rate_limit_remaining(self, cfg: ModelConfig) -> float:
        key = self._cooldown_key(cfg)
        cd = _get_cooldown(key)
        if cd.failure_type == "rate_limit":
            return cd.remaining()
        return 0.0

    @staticmethod
    def _cfg_snapshot(cfg: ModelConfig) -> dict[str, Any]:
        return {
            "profile": str(cfg.name or ""),
            "provider": str(cfg.provider or ""),
            "model": str(cfg.model or ""),
            "base_url": str(cfg.base_url or ""),
        }

    def runtime_trace(self) -> dict[str, Any]:
        """Runtime model trace for the most recent stream_chat() call."""
        primary = self._cfg_snapshot(self._primary_config)
        active = self._cfg_snapshot(self.config)
        attempts = [dict(a) for a in self._attempt_trace]
        failover_used = any(
            str(a.get("status") or "") == "success" and str(a.get("profile") or "") != str(primary.get("profile") or "")
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
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return safe[:128]

    def _build_openai_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> dict[str, Any]:
        # Reset per-request tool name map
        self._openai_tool_name_map = {}

        body: dict[str, Any] = {
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
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> dict[str, Any]:
        # Reset per-request state
        self._anthropic_tool_name_map = {}

        # Convert OpenAI message format to Anthropic format
        system_text = ""
        anthropic_messages: list[dict[str, Any]] = []
        pending_tool_use_ids: set[str] = set()
        current_tool_result_anchor: str | None = None

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                system_text += msg.get("content", "") + "\n"

            elif role == "assistant":
                # Convert assistant messages with tool_calls to Anthropic content blocks
                content_blocks: list[dict[str, Any]] = []
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
                        log.warning("Malformed tool arguments for %s: %s", func.get("name", "?"), args_str[:200])
                        args = {}
                    tc_id = str(tc.get("id", "")).strip()
                    if not tc_id:
                        continue
                    assistant_tool_use_ids.add(tc_id)
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc_id,
                            "name": func.get("name", "").replace(".", "_"),
                            "input": args,
                        }
                    )
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
                if (
                    anthropic_messages
                    and anthropic_messages[-1]["role"] == "user"
                    and isinstance(anthropic_messages[-1]["content"], list)
                    and anthropic_messages[-1]["content"]
                    and anthropic_messages[-1]["content"][0].get("type") == "tool_result"
                    and current_tool_result_anchor == "assistant_tool_use"
                ):
                    anthropic_messages[-1]["content"].append(tool_result)
                else:
                    anthropic_messages.append({"role": "user", "content": [tool_result]})
                    current_tool_result_anchor = "assistant_tool_use"
                pending_tool_use_ids.discard(tool_use_id)

            elif role == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    blocks: list[dict[str, Any]] = []
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

        body: dict[str, Any] = {
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
            name_map: dict[str, str] = {}
            for t in tools:
                func = t.get("function", {})
                original_name = func.get("name", "")
                safe_name = original_name.replace(".", "_")
                name_map[safe_name] = original_name
                anthropic_tools.append(
                    {
                        "name": safe_name,
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {}),
                    }
                )
            body["tools"] = anthropic_tools
            body["tool_choice"] = {"type": "auto"}
            self._anthropic_tool_name_map = name_map
        return body

    @staticmethod
    def _extract_anthropic_usage(event_data: dict[str, Any]) -> dict[str, int]:
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

    async def _get_codex_provider(self) -> Any:
        if self._codex_provider is None:
            from thomas.codex.provider import CodexProvider

            self._codex_provider = CodexProvider(self.config)
        return self._codex_provider

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
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
                    f"Rate-limit cooldown active for profile '{self.config.name}' " f"({int(rem)}s remaining).",
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
            except asyncio.CancelledError:
                raise
            except LLMError as e:
                attempt["status"] = "error"
                attempt["error"] = f"{type(e).__name__}: {e}"
                raise
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException, OSError, NotImplementedError) as e:
                attempt["status"] = "error"
                attempt["error"] = f"{type(e).__name__}: {e}"
                raise

        primary_cfg = self._primary_config
        candidates = [primary_cfg] + [cfg for cfg in self._fallback_configs]

        # Session pinning: if a provider succeeded before in this session,
        # move it to the front of candidates (if not in cooldown).
        if self._session_pinned_key:
            pinned_cd = _get_cooldown(self._session_pinned_key)
            if not pinned_cd.is_active():
                pinned_idx = next(
                    (i for i, c in enumerate(candidates) if self._cooldown_key(c) == self._session_pinned_key),
                    -1,
                )
                if pinned_idx > 0:
                    candidates.insert(0, candidates.pop(pinned_idx))

        last_error: Exception | None = None

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
                    f"Rate-limit cooldown active for profile '{cfg.name}' " f"({int(rate_limited_for)}s remaining).",
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
                # On success, clear backoff and pin provider for this session.
                self._clear_cooldown(cfg)
                # Only pin when cooldowns are enabled; otherwise always
                # start from primary on the next turn.
                if self._failover_cooldown_s > 0:
                    self._session_pinned_key = self._cooldown_key(cfg)
                return
            except LLMError as e:
                last_error = e
                attempt["status"] = "error"
                attempt["error"] = f"LLMError({int(getattr(e, 'status', 0) or 0)}): {e}"
                attempt["retryable"] = bool(getattr(e, "retryable", False))
                auth_error = e.status in (401, 403)
                if auth_error and not self._failover_on_auth_error:
                    raise
                failure_type = "auth" if auth_error else "server"
                self._mark_cooldown(cfg, failure_type=failure_type)
                if idx < len(candidates) - 1:
                    log.warning(
                        "LLM profile '%s' failed (%s, type=%s). Trying failover profile.",
                        cfg.name,
                        e,
                        failure_type,
                    )
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException, OSError, NotImplementedError) as e:
                last_error = e
                attempt["status"] = "error"
                attempt["error"] = f"{type(e).__name__}: {e}"
                self._mark_cooldown(cfg, failure_type="connect")
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
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if self.config.provider == "codex":
            provider = await self._get_codex_provider()
            stream_obj = await _coerce_async_iterator(
                provider.stream_chat(messages, tools),
                source="provider.stream_chat",
            )
            async for event in stream_obj:
                yield event
        elif self.config.provider == "anthropic":
            stream_obj = await _coerce_async_iterator(
                self._stream_anthropic(messages, tools),
                source="stream_anthropic",
            )
            async for event in stream_obj:
                yield event
        else:
            stream_obj = await _coerce_async_iterator(
                self._stream_openai(messages, tools),
                source="stream_openai",
            )
            async for event in stream_obj:
                yield event

    async def _stream_openai(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        stream_obj = await _coerce_async_iterator(
            stream_openai(self, messages, tools),
            source="stream_openai",
        )
        async for event in stream_obj:
            yield event

    async def _stream_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        stream_obj = await _coerce_async_iterator(
            stream_anthropic(self, messages, tools),
            source="stream_anthropic",
        )
        async for event in stream_obj:
            yield event

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat completion. Returns full response.

        Returns dict with keys:
        - text: str (assistant's text response)
        - tool_calls: list of {id, name, arguments} dicts
        - usage: TokenUsage
        """
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage = TokenUsage()

        async for event in self.stream_chat(messages, tools):
            if event.type == "token":
                text_parts.append(event.data["text"])
            elif event.type == "tool_call_end":
                tool_calls.append(
                    {
                        "id": event.data["id"],
                        "name": event.data["name"],
                        "arguments": event.data["arguments"],
                    }
                )
            elif event.type == "usage":
                usage = event.data["usage"]

        return {
            "text": "".join(text_parts),
            "tool_calls": tool_calls,
            "usage": usage,
        }
