"""Compatibility tracing helpers for debug namespace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter
from typing import Any

from . import core

TraceContext = dict[str, Any]


@dataclass
class Span:
    name: str
    start_ns: float | None = None
    end_ns: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


class SpanCollector:
    """Collects spans for lightweight trace inspection."""

    def __init__(self) -> None:
        self._spans: list[Span] = []

    def add(self, span: Span) -> None:
        self._spans.append(span)

    def all(self) -> list[Span]:
        return list(self._spans)


_collector = SpanCollector()


def traced(func: Callable[..., Any]) -> Callable[..., Any]:
    """Synchronous trace decorator."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        span = Span(name=getattr(func, "__name__", "unknown"), start_ns=perf_counter())
        try:
            return func(*args, **kwargs)
        finally:
            span.end_ns = perf_counter()
            _collector.add(span)

    return wrapper


def async_traced(func: Callable[..., Any]) -> Callable[..., Any]:
    """Async trace decorator."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        span = Span(name=getattr(func, "__name__", "unknown"), start_ns=perf_counter())
        try:
            return await func(*args, **kwargs)
        finally:
            span.end_ns = perf_counter()
            _collector.add(span)

    return wrapper


def get_span_collector() -> SpanCollector:
    return _collector


class DebugSession(core.DebugSession):
    """Compatibility shim."""

    pass
