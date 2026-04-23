"""Base specialist agent class.

All specialists inherit from ``BaseSpecialist`` and override
``_execute_impl()``.  The base class handles:
    - Capability token validation
    - Contract input validation
    - Tool execution with permission checking
    - Event emission (thinking, tool_start, tool_result, text, done)
    - Timeout enforcement
    - Error handling and recovery
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from thomas.marketplace.orchestrator.protocol import (
    CapabilityToken,
    DelegationContract,
    HealthReport,
)

log = logging.getLogger(__name__)


class BaseSpecialist:
    """Base class for all Thomas specialist agents.

    Subclasses MUST override:
        - ``specialist_id`` property
        - ``description`` property
        - ``capabilities`` property
        - ``_execute_impl()`` async generator

    The base class handles token validation, timeout enforcement,
    and event wrapping.

    Parameters
    ----------
    config:
        Thomas AppConfig.
    llm:
        LLM client for this specialist's reasoning.
    tools:
        Thomas ToolRegistry (optional — not all specialists need tools).
    """

    def __init__(
        self,
        config: Any,
        llm: Any,
        tools: Any = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.tools = tools
        self._execution_count: int = 0
        self._last_execution_ms: int = 0
        self._error_count: int = 0

    # ── identity (override in subclasses) ────────────────────────

    @property
    def specialist_id(self) -> str:
        raise NotImplementedError

    @property
    def description(self) -> str:
        raise NotImplementedError

    @property
    def capabilities(self) -> set[str]:
        raise NotImplementedError

    # ── main execute (DO NOT override) ───────────────────────────

    async def execute(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a delegated task.  Validates token + contract first.

        DO NOT override this method.  Override ``_execute_impl`` instead.
        """
        start = time.monotonic()

        # Validate capability token
        if not token.is_valid():
            yield {"type": "error", "error": "Capability token expired"}
            return

        if token.specialist_id != self.specialist_id:
            yield {
                "type": "error",
                "error": f"Token issued for '{token.specialist_id}', " f"not '{self.specialist_id}'",
            }
            return

        try:
            # Execute with timeout.
            timeout_seconds = float(contract.timeout_seconds) if contract.timeout_seconds is not None else None
            event_stream = self._collect_events(
                contract,
                token,
                prompt,
                conversation_context,
                memory_context,
            )
            if timeout_seconds is None or timeout_seconds <= 0.0:
                async for event in event_stream:
                    yield event
            else:
                deadline = time.monotonic() + timeout_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        raise asyncio.TimeoutError()
                    try:
                        event = await asyncio.wait_for(event_stream.__anext__(), timeout=remaining)
                    except StopAsyncIteration:
                        break
                    yield event

            self._execution_count += 1
            self._last_execution_ms = int((time.monotonic() - start) * 1000)

        except asyncio.TimeoutError:
            self._error_count += 1
            yield {
                "type": "error",
                "error": f"Specialist '{self.specialist_id}' timed out " f"after {contract.timeout_seconds}s",
            }

        except Exception as exc:
            self._error_count += 1
            log.error("Specialist %s failed: %s", self.specialist_id, exc)
            yield {"type": "error", "error": str(exc)}

    async def _collect_events(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Wrapper to make the async generator compatible with wait_for."""
        try:
            events_or_coro = self._execute_impl(
                contract,
                token,
                prompt,
                conversation_context,
                memory_context,
            )
        except Exception as exc:
            log.error("Specialist %s _execute_impl invocation failed: %s", self.specialist_id, exc)
            yield {"type": "error", "error": str(exc)}
            return

        if asyncio.iscoroutine(events_or_coro):
            # Defensive path: some integrations may accidentally implement
            # _execute_impl as a coroutine (single awaited payload) instead of
            # an async generator. Normalize to event stream semantics.
            try:
                result = await events_or_coro
            except Exception as exc:
                log.error(
                    "Specialist %s _execute_impl coroutine failed: %s",
                    self.specialist_id,
                    exc,
                )
                yield {"type": "error", "error": str(exc)}
                return

            if isinstance(result, dict):
                if result:
                    yield result
                return
            if isinstance(result, (list, tuple)):
                for event in result:
                    if isinstance(event, dict):
                        yield event
                return

            if result is None:
                return

            yield {
                "type": "error",
                "error": (
                    f"Specialist '{self.specialist_id}' returned unsupported "
                    f"event payload type {type(result).__name__}"
                ),
            }
            return

        if not hasattr(events_or_coro, "__aiter__"):
            yield {
                "type": "error",
                "error": (
                    f"Specialist '{self.specialist_id}' returned non-iterable event stream "
                    f"{type(events_or_coro).__name__}"
                ),
            }
            return

        async for event in events_or_coro:
            yield event

    # ── override this ────────────────────────────────────────────

    async def _execute_impl(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Implement specialist logic here.

        Must yield event dicts with at least a ``type`` field:
            - ``thinking``: reasoning text
            - ``tool_start``: beginning tool execution
            - ``tool_result``: tool execution result
            - ``text``: response text chunk
            - ``done``: execution complete
        """
        raise NotImplementedError(f"Specialist '{self.specialist_id}' must implement _execute_impl()")

    # ── tool execution helper ────────────────────────────────────

    async def _run_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        token: CapabilityToken,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a tool with permission checking.

        Validates the capability token permits this tool before running.
        Yields tool_start, tool_result events.
        """
        # Permission check
        if not token.permits_tool(tool_name):
            yield {
                "type": "tool_result",
                "name": tool_name,
                "ok": False,
                "result": f"Permission denied: token does not permit '{tool_name}'",
                "ms": 0,
            }
            return

        yield {
            "type": "tool_start",
            "name": tool_name,
            "id": tool_name,
            "args": args,
        }

        start = time.monotonic()
        try:
            if self.tools and hasattr(self.tools, "execute"):
                result = await self.tools.execute(tool_name, args)
                elapsed = int((time.monotonic() - start) * 1000)
                yield {
                    "type": "tool_result",
                    "name": tool_name,
                    "id": tool_name,
                    "ok": True,
                    "result": str(result)[:2000],
                    "ms": elapsed,
                }
            elif self.tools and hasattr(self.tools, "call"):
                result = await self.tools.call(tool_name, **args)
                elapsed = int((time.monotonic() - start) * 1000)
                yield {
                    "type": "tool_result",
                    "name": tool_name,
                    "id": tool_name,
                    "ok": True,
                    "result": str(result)[:2000],
                    "ms": elapsed,
                }
            else:
                yield {
                    "type": "tool_result",
                    "name": tool_name,
                    "id": tool_name,
                    "ok": False,
                    "result": "No tool registry available",
                    "ms": 0,
                }
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            yield {
                "type": "tool_result",
                "name": tool_name,
                "id": tool_name,
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }

    # ── LLM helper ───────────────────────────────────────────────

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 2_000,
    ) -> str:
        """Call this specialist's LLM.

        Note: max_tokens is accepted for caller convenience but Thomas's
        LLMClient reads the limit from model config, not per-call args.
        """
        try:
            if hasattr(self.llm, "chat"):
                response = await self.llm.chat(messages=messages)
                # LLMClient.chat() returns a dict with "text" key
                if isinstance(response, dict):
                    return str(response.get("text", ""))
                if hasattr(response, "content"):
                    return str(response.content)
                return str(response)
            elif hasattr(self.llm, "complete"):
                prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
                response = await self.llm.complete(prompt=prompt_text)
                return str(response)
            return ""
        except Exception as exc:
            log.error("Specialist %s LLM call failed: %s", self.specialist_id, exc)
            raise

    # ── health ───────────────────────────────────────────────────

    async def check_health(self) -> HealthReport:
        return HealthReport(
            specialist_id=self.specialist_id,
            healthy=self._error_count < 10,
            message=f"OK ({self._execution_count} runs, {self._error_count} errors)",
            last_execution_ms=self._last_execution_ms,
            total_executions=self._execution_count,
            error_count=self._error_count,
        )
