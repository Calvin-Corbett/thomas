"""Shared LLM stream primitives used across providers."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

# HTTP statuses every provider transport treats as worth another attempt.
# Shared so a change to the retry policy reaches all providers at once.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def callable_accepts_keyword(func: Any, keyword: str) -> bool:
    """Return whether a callable explicitly or variadically accepts a keyword."""
    try:
        return any(
            (
                parameter.name == keyword
                and parameter.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            )
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(func).parameters.values()
        )
    except (TypeError, ValueError):
        return False


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
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallAccumulator:
    """Accumulates streamed tool call chunks into complete calls."""

    id: str
    name: str = ""
    arguments: str = ""
    finished: bool = False
