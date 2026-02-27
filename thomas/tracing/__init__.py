"""Distributed tracing with spans, traces, context propagation, and sampling.

Provides distributed trace creation, span management, context
propagation, and trace sampling strategies.
"""

from .core import (
    FixedRateSampler,
    SamplingStrategy,
    Span,
    SpanEvent,
    SpanKind,
    SpanLink,
    SpanStatus,
    Trace,
    TraceContext,
    Tracer,
    TracingCollector,
)

__all__ = [
    "SpanKind",
    "SpanStatus",
    "SpanEvent",
    "SpanLink",
    "Span",
    "Trace",
    "TraceContext",
    "Tracer",
    "SamplingStrategy",
    "FixedRateSampler",
    "TracingCollector",
]

__version__ = "1.0.0"
