"""Event system for Thomas agent observability.

Provides typed events that flow through the agent loop, enabling
streaming output, logging, and monitoring.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class EventType(Enum):
    """Types of events emitted by the agent system."""

    # LLM streaming events
    TEXT_DELTA = "text_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_ARGS_DELTA = "tool_call_args_delta"
    TOOL_CALL_END = "tool_call_end"

    # Agent lifecycle events
    AGENT_START = "agent_start"
    AGENT_ITERATION = "agent_iteration"
    AGENT_DONE = "agent_done"
    AGENT_ERROR = "agent_error"
    AGENT_END = "agent_end"

    # Tool events
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # Memory events
    MEMORY_QUERY = "memory_query"
    MEMORY_RESULT = "memory_result"

    # Security events
    SECURITY_FLAG = "security_flag"

    # System events
    THINKING = "thinking"
    STATUS = "status"


@dataclass
class AgentEvent:
    """An event emitted during agent execution.

    Attributes:
        type: The event type.
        data: Event-specific payload.
        timestamp: Unix timestamp when the event was created.
        iteration: Which agent loop iteration produced this event.
    """

    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    iteration: int = 0

    @staticmethod
    def text_delta(text: str, **kw: Any) -> AgentEvent:
        return AgentEvent(type=EventType.TEXT_DELTA, data={"text": text}, **kw)

    @staticmethod
    def tool_call_start(
        tool_id: str, tool_name: str, **kw: Any
    ) -> AgentEvent:
        return AgentEvent(
            type=EventType.TOOL_CALL_START,
            data={"tool_id": tool_id, "tool_name": tool_name},
            **kw,
        )

    @staticmethod
    def tool_call_args_delta(
        tool_id: str, delta: str, **kw: Any
    ) -> AgentEvent:
        return AgentEvent(
            type=EventType.TOOL_CALL_ARGS_DELTA,
            data={"tool_id": tool_id, "delta": delta},
            **kw,
        )

    @staticmethod
    def tool_call_end(tool_id: str, **kw: Any) -> AgentEvent:
        return AgentEvent(
            type=EventType.TOOL_CALL_END, data={"tool_id": tool_id}, **kw
        )

    @staticmethod
    def tool_start(
        tool_id: str, tool_name: str, args: Dict[str, Any], **kw: Any
    ) -> AgentEvent:
        return AgentEvent(
            type=EventType.TOOL_START,
            data={"tool_id": tool_id, "tool_name": tool_name, "args": args},
            **kw,
        )

    @staticmethod
    def tool_result(
        tool_id: str,
        tool_name: str,
        result: Any,
        ok: bool,
        duration_ms: float,
        **kw: Any,
    ) -> AgentEvent:
        return AgentEvent(
            type=EventType.TOOL_RESULT,
            data={
                "tool_id": tool_id,
                "tool_name": tool_name,
                "result": result,
                "ok": ok,
                "duration_ms": duration_ms,
            },
            **kw,
        )

    @staticmethod
    def agent_done(
        text: str,
        iterations: int,
        tool_calls: int,
        usage: Optional[Dict[str, Any]] = None,
        token_report: Optional[Dict[str, Any]] = None,
        **kw: Any,
    ) -> AgentEvent:
        data: Dict[str, Any] = {
            "text": text,
            "iterations": iterations,
            "tool_calls": tool_calls,
        }
        if usage is not None:
            data["usage"] = usage
        if token_report is not None:
            data["token_report"] = token_report
        return AgentEvent(
            type=EventType.AGENT_DONE,
            data=data,
            **kw,
        )

    @staticmethod
    def agent_error(error: str, **kw: Any) -> AgentEvent:
        return AgentEvent(
            type=EventType.AGENT_ERROR, data={"error": error}, **kw
        )

    @staticmethod
    def status(message: str, **kw: Any) -> AgentEvent:
        return AgentEvent(
            type=EventType.STATUS, data={"message": message}, **kw
        )
