"""Shared LLM stream primitives used across providers."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Collection
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
    # Prompt tokens the provider served from its cache (a subset of
    # prompt_tokens). Every transport reported it; until 2026-09-05 the
    # count dissolved here and the reply receipt could not show it.
    cached_prompt_tokens: int = 0

    def add(self, other: TokenUsage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.cached_prompt_tokens += getattr(other, "cached_prompt_tokens", 0) or 0


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


_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def embedded_tool_call(text: str, tool_names: Collection[str]) -> tuple[str, str] | None:
    """The one tool call a model wrote into its text, as ``(name, arguments_json)``.

    Models without native tool calling answer with the call itself, often in a
    ```json fence: ``{"name": "recall", "arguments": {...}}``, or the OpenAI
    shape ``{"function": {"name": ..., "arguments": ...}}``. The whole text
    must be that one object and the name must be a tool that was offered;
    anything else (prose, other JSON, a call plus commentary, an unknown
    tool) is None and stays text.
    """

    raw = str(text or "").strip()
    fenced = _FENCE_RE.match(raw)
    if fenced:
        raw = fenced.group(1).strip()
    if not raw.startswith("{") or not raw.endswith("}"):
        return None
    try:
        call = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(call, dict):
        return None
    function = call.get("function")
    if isinstance(function, dict):
        call = function
    name = call.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    offered = {str(item) for item in tool_names}
    if name not in offered:
        lowered = {item.lower(): item for item in offered}
        if name.lower() not in lowered:
            return None
        name = lowered[name.lower()]
    arguments = call.get("arguments", call.get("parameters", {}))
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except (ValueError, TypeError):
            return None
    if not isinstance(arguments, dict):
        return None
    return name, json.dumps(arguments, ensure_ascii=False)
