"""LLMClient: Async multi-provider LLM client with streaming support.

Provides the base LLMClient class with configuration management, streaming,
retries, error classification, token tracking, and tool call parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from thomas.core import capture_context
from thomas.core.config import ModelConfig
from thomas.core.llm_budget import LLMBudgetMixin
from thomas.core.llm_park import parked_error, parked_text
from thomas.core.llm_provider_state import (
    _PROVIDER_COOLDOWNS,
    _ProviderCooldown,
    get_cooldown,
)
from thomas.core.llm_shared import LLMError, StreamEvent, TokenUsage, callable_accepts_keyword
from thomas.core.llm_streaming import stream_anthropic, stream_openai, stream_openai_codex
from thomas.core.llm_streaming_anthropic import extract_anthropic_usage
from thomas.core.llm_transport_pool import (
    _coerce_async_iterator,
    close_http_client,
    get_http_client,
    retry_after_seconds,
    stream_anthropic_events,
    stream_current_provider,
    stream_openai_codex_events,
    stream_openai_events,
)
from thomas.core.structured_output import StructuredResult, request_structured

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_DEFAULT_RATE_LIMIT_COOLDOWN_S = 20.0
_MAX_RETRY_AFTER_S = 300.0
_AUTH_FAILURE_BASE_S = 18_000.0  # 5 hours (billing/auth failures)


def _get_cooldown(key: str) -> _ProviderCooldown:
    """Compatibility wrapper over the extracted process-wide registry."""
    return get_cooldown(key, cooldowns=_PROVIDER_COOLDOWNS, cooldown_factory=_ProviderCooldown)


class LLMClient(LLMBudgetMixin):
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
        request_admission: Any = None,
    ):
        self._request_admission = request_admission
        self.config = config
        self._primary_config = config
        self.session_usage = TokenUsage()
        self._client: httpx.AsyncClient | None = None
        self._anthropic_tool_name_map: dict[str, str] = {}  # sanitized→original
        self._openai_tool_name_map: dict[str, str] = {}  # sanitized→original
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled) and len(self._fallback_configs) > 0
        self._failover_cooldown_s = max(0, int(failover_cooldown_s))
        self._failover_on_auth_error = bool(failover_on_auth_error)
        self._max_retries = max(1, int(max_retries))
        self._base_retry_delay = max(0.0, float(base_retry_delay_s))
        self._session_pinned_key: str | None = None  # set on first success
        self._request_overrides = dict(request_overrides or {})
        self._attempt_trace: list[dict[str, Any]] = []
        self._runtime_attempt_trace: list[dict[str, Any]] = []
        # Honesty-spine capture: counted, never fatal. See capture_context.py.
        self.capture_failures: int = 0

    async def _get_client(self) -> httpx.AsyncClient:
        return await get_http_client(self, httpx_module=httpx)

    async def close(self) -> None:
        await close_http_client(self)

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
        return retry_after_seconds(headers, max_retry_after_s=_MAX_RETRY_AFTER_S)

    def _mark_rate_limited(self, cfg: ModelConfig, retry_after_s: float | None, refusal: str = "") -> None:
        key = self._cooldown_key(cfg)
        cd = _get_cooldown(key)
        if retry_after_s is not None and retry_after_s > 0:
            # Use server-provided Retry-After directly (capped).
            cd.until = time.monotonic() + min(float(retry_after_s), _MAX_RETRY_AFTER_S)
            cd.failure_type = "rate_limit"
            cd.failure_count = max(cd.failure_count, 1)
            cd.refusal = refusal
        else:
            cd.mark("rate_limit", base_s=float(_DEFAULT_RATE_LIMIT_COOLDOWN_S), refusal=refusal)

    def _rate_limit_remaining(self, cfg: ModelConfig) -> float:
        key = self._cooldown_key(cfg)
        cd = _get_cooldown(key)
        if cd.failure_type == "rate_limit":
            return cd.remaining()
        return 0.0

    def _parked_text(self, cfg: ModelConfig, remaining: float) -> str:
        """What a turn refused by the park, rather than by the provider, reports (thomas/core/llm_park.py)."""
        return parked_text(cfg.name, remaining, str(_get_cooldown(self._cooldown_key(cfg)).refusal or ""))

    def _parked_error(self, cfg: ModelConfig, remaining: float) -> LLMError:
        """The park's refusal, carrying the quota facts the provider's refusal carried (thomas/core/llm_park.py)."""
        return parked_error(cfg.name, remaining, str(_get_cooldown(self._cooldown_key(cfg)).refusal or ""))

    @staticmethod
    def _cfg_snapshot(cfg: ModelConfig) -> dict[str, Any]:
        return {
            "profile": str(cfg.name or ""),
            "provider": str(cfg.provider or ""),
            "model": str(cfg.model or ""),
            "base_url": str(cfg.base_url or ""),
        }

    def reset_runtime_trace(self) -> None:
        """Start a new turn-level attribution scope."""

        self._runtime_attempt_trace = []

    def runtime_trace(self) -> dict[str, Any]:
        """Runtime model trace aggregated across the current turn scope."""
        primary = self._cfg_snapshot(self._primary_config)
        # An empty turn scope is meaningful: after reset, never fall back to a
        # previous call's trace and falsely attest a model that did not run.
        attempts = [dict(a) for a in self._runtime_attempt_trace]
        active = next(
            (
                {key: attempt.get(key) for key in ("profile", "provider", "model", "base_url")}
                for attempt in reversed(attempts)
                if str(attempt.get("status") or "") == "success"
            ),
            {},
        )
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
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        # Reset per-request tool name map
        self._openai_tool_name_map = {}

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": min(self.config.max_tokens, max_output_tokens)
            if max_output_tokens
            else self.config.max_tokens,
            "stream": stream,
        }
        if stream and str(getattr(self.config, "provider", "") or "").lower() != "azure":
            # OpenAI-compatible streams report usage only when asked; older Azure APIs reject this.
            body["stream_options"] = {"include_usage": True}
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
        max_output_tokens: int | None = None,
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
            "max_tokens": min(self.config.max_tokens, max_output_tokens)
            if max_output_tokens
            else self.config.max_tokens,
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
        return extract_anthropic_usage(event_data)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        turn_user_content: Any = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion, yielding events as they arrive.

        This is the honesty-spine narrow waist: every message list handed to
        a model is captured here, before the underlying provider call, and
        the assembled reply is captured when the stream ends -- whether it
        ends naturally or is closed early by a caller that stops consuming
        partway through (`interrupted=True` in that case). `chat()` is built
        on this method, so it gets capture for free without logging twice.
        See capture_context.py for the capture mechanics and correlation.
        """
        state = capture_context.begin_model_capture(
            messages,
            model=str(getattr(self.config, "model", "") or ""),
            provider=str(getattr(self.config, "provider", "") or ""),
            tools=tools,
        )
        if state.failed:
            self.capture_failures += 1
        interrupted = True
        # Failover can switch providers mid-call (`_switch_config` mutates
        # `self.config`). Track which (provider, model) pairs actually
        # produced token output so the response can honestly flag
        # merged_partial_output instead of presenting multi-provider output
        # as one clean primary response.
        served_configs: set[tuple[str, str]] = set()
        try:
            async for event in self._stream_chat_uncaptured(
                messages,
                tools,
                turn_user_content=turn_user_content,
            ):
                if event.type == "token":
                    served_configs.add(
                        (
                            str(getattr(self.config, "provider", "") or ""),
                            str(getattr(self.config, "model", "") or ""),
                        )
                    )
                capture_context.record_stream_event(state, event)
                yield event
            interrupted = False
        finally:
            # Read at completion time -- whichever attempt was last active,
            # which is not necessarily the config the request was opened
            # with if failover switched providers along the way.
            if capture_context.end_model_capture(
                state,
                interrupted=interrupted,
                served_by_model=str(getattr(self.config, "model", "") or ""),
                served_by_provider=str(getattr(self.config, "provider", "") or ""),
                provider_attempts=max(1, len(self._attempt_trace)),
                merged_partial_output=len(served_configs) > 1,
            ):
                self.capture_failures += 1

    async def _stream_chat_uncaptured(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        turn_user_content: Any = None,
    ) -> AsyncIterator[StreamEvent]:
        """The pre-capture implementation: provider selection, retries, failover."""
        provider_kwargs = (
            {"turn_user_content": turn_user_content}
            if callable_accepts_keyword(self._stream_current_provider, "turn_user_content")
            else {}
        )
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
                self._runtime_attempt_trace.append(attempt)
                raise self._parked_error(self.config, rem)
            attempt = {
                **self._cfg_snapshot(self.config),
                "status": "running",
            }
            self._attempt_trace.append(attempt)
            self._runtime_attempt_trace.append(attempt)
            try:
                async for event in self._stream_current_provider(
                    messages,
                    tools,
                    **provider_kwargs,
                ):
                    yield event
                attempt["status"] = "success"
                # It answered, so nothing the park remembers about it holds. Only
                # the failover loop below cleared the park, and a profile with no
                # fallbacks never enters it -- the ordinary case for one plan picked
                # in the model menu. Harmless while the park was just a timer; not
                # now that a spent allowance is reported until the reset its refusal
                # named (provider_cooldowns.spent_allowances), which for a reset read
                # from words is deliberately an hour late when the zone is unreadable
                # (claude_plan._ZONE_MARGIN_S). Without this the composer's line kept
                # calling your plan out of allowance while it was answering.
                self._clear_cooldown(self.config)
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
            self._runtime_attempt_trace.append(attempt)
            rate_limited_for = self._rate_limit_remaining(cfg)
            if rate_limited_for > 0:
                attempt["status"] = "skipped_rate_limited"
                attempt["cooldown_remaining_s"] = int(rate_limited_for)
                if idx < len(candidates) - 1:
                    continue
                last_error = self._parked_error(cfg, rate_limited_for)
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
                async for event in self._stream_current_provider(
                    messages,
                    tools,
                    **provider_kwargs,
                ):
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
        *,
        turn_user_content: Any = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in stream_current_provider(
            self,
            messages,
            tools,
            turn_user_content=turn_user_content,
            coerce_async_iterator=_coerce_async_iterator,
        ):
            yield event

    async def _stream_openai(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in stream_openai_events(
            self,
            messages,
            tools,
            stream_openai_func=stream_openai,
            coerce_async_iterator=_coerce_async_iterator,
        ):
            yield event

    async def _stream_openai_codex(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        turn_user_content: Any = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in stream_openai_codex_events(
            self,
            messages,
            tools,
            turn_user_content=turn_user_content,
            stream_openai_codex_func=stream_openai_codex,
            coerce_async_iterator=_coerce_async_iterator,
        ):
            yield event

    async def _stream_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in stream_anthropic_events(
            self,
            messages,
            tools,
            stream_anthropic_func=stream_anthropic,
            coerce_async_iterator=_coerce_async_iterator,
        ):
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

    async def chat_structured(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        max_repair_attempts: int = 2,
    ) -> StructuredResult:
        """Non-streaming chat returning JSON validated against a caller schema.

        Delegates to thomas.core.structured_output.request_structured, using
        this client's chat() as the LLM adapter. Validation failures are fed
        back to the model and retried up to ``max_repair_attempts`` times.

        Raises SchemaValidationError for a malformed caller schema and
        StructuredOutputError when the repair loop cannot produce valid output.
        """

        async def _adapter(msgs: list[dict[str, Any]]) -> str:
            result = await self.chat(msgs)
            return str(result.get("text") or "")

        return await request_structured(
            _adapter,
            messages,
            schema,
            max_repair_attempts=max_repair_attempts,
        )
