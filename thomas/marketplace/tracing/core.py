"""Distributed tracing with spans, traces, context propagation, and sampling.

Provides distributed tracing infrastructure with span management,
trace context propagation, and trace export.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SpanKind(Enum):
    """Span kind."""

    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanStatus(Enum):
    """Span status."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


@dataclass
class SpanEvent:
    """Span event."""

    name: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpanLink:
    """Link to another span."""

    trace_id: str
    span_id: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """Distributed trace span."""

    trace_id: str
    span_id: str
    name: str
    kind: SpanKind = SpanKind.INTERNAL
    parent_span_id: str | None = None
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime | None = None
    duration_ms: float = 0.0
    status: SpanStatus = SpanStatus.UNSET
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    links: list[SpanLink] = field(default_factory=list)

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add event to span."""
        event = SpanEvent(name=name, attributes=attributes or {})
        self.events.append(event)

    def add_link(self, trace_id: str, span_id: str) -> None:
        """Add link to another span."""
        link = SpanLink(trace_id=trace_id, span_id=span_id)
        self.links.append(link)

    def end(self) -> None:
        """End span."""
        self.end_time = datetime.utcnow()
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        """Convert span to dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "kind": self.kind.value,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "attributes": self.attributes,
            "events": [
                {"name": e.name, "timestamp": e.timestamp.isoformat(), "attributes": e.attributes} for e in self.events
            ],
            "links": [{"trace_id": l.trace_id, "span_id": l.span_id, "attributes": l.attributes} for l in self.links],
        }


@dataclass
class Trace:
    """Distributed trace."""

    trace_id: str
    root_span_id: str
    spans: list[Span] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None

    def add_span(self, span: Span) -> None:
        """Add span to trace."""
        self.spans.append(span)

    def get_span(self, span_id: str) -> Span | None:
        """Get span by ID."""
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def end(self) -> None:
        """End trace."""
        self.ended_at = datetime.utcnow()

    def get_duration_ms(self) -> float:
        """Get total trace duration."""
        if not self.spans:
            return 0.0

        start = min(s.start_time for s in self.spans)
        end = max(s.end_time for s in self.spans if s.end_time)
        return (end - start).total_seconds() * 1000


class TraceContext:
    """Trace context for propagation."""

    def __init__(self, trace_id: str, span_id: str, parent_span_id: str | None = None):
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.baggage: dict[str, str] = {}

    def to_headers(self) -> dict[str, str]:
        """Convert to HTTP headers."""
        return {"traceparent": f"00-{self.trace_id}-{self.span_id}-01", "tracestate": ""}

    @staticmethod
    def from_headers(headers: dict[str, str]) -> Optional["TraceContext"]:
        """Parse from HTTP headers."""
        traceparent = headers.get("traceparent")
        if not traceparent:
            return None

        parts = traceparent.split("-")
        if len(parts) >= 3:
            trace_id = parts[1]
            span_id = parts[2]
            return TraceContext(trace_id=trace_id, span_id=span_id)

        return None


class Tracer:
    """Tracer for creating spans."""

    def __init__(self, service_name: str = "default"):
        self.service_name = service_name
        self.traces: dict[str, Trace] = {}
        self.active_spans: dict[str, Span] = {}

    def start_trace(self, name: str) -> Trace:
        """Start new trace."""
        trace_id = str(uuid.uuid4()).replace("-", "")
        root_span_id = str(uuid.uuid4()).replace("-", "")

        root_span = Span(trace_id=trace_id, span_id=root_span_id, name=name, kind=SpanKind.INTERNAL)

        trace = Trace(trace_id=trace_id, root_span_id=root_span_id)
        trace.add_span(root_span)
        self.traces[trace_id] = trace
        self.active_spans[root_span_id] = root_span

        return trace

    def start_span(
        self, trace_id: str, name: str, parent_span_id: str | None = None, kind: SpanKind = SpanKind.INTERNAL
    ) -> Span | None:
        """Start new span."""
        trace = self.traces.get(trace_id)
        if not trace:
            return None

        span_id = str(uuid.uuid4()).replace("-", "")
        span = Span(trace_id=trace_id, span_id=span_id, name=name, kind=kind, parent_span_id=parent_span_id)

        trace.add_span(span)
        self.active_spans[span_id] = span
        return span

    def end_span(self, span_id: str) -> bool:
        """End span."""
        span = self.active_spans.get(span_id)
        if span:
            span.end()
            return True
        return False

    def get_trace(self, trace_id: str) -> Trace | None:
        """Get trace by ID."""
        return self.traces.get(trace_id)

    def export_traces(self) -> list[dict[str, Any]]:
        """Export traces."""
        return [
            {
                "trace_id": trace.trace_id,
                "duration_ms": trace.get_duration_ms(),
                "spans": len(trace.spans),
                "spans_data": [s.to_dict() for s in trace.spans],
            }
            for trace in self.traces.values()
        ]


class SamplingStrategy:
    """Trace sampling strategy."""

    def should_sample(self, trace_id: str) -> bool:
        """Determine if trace should be sampled."""
        return True


class FixedRateSampler(SamplingStrategy):
    """Fixed rate sampling."""

    def __init__(self, rate: float = 0.1):
        self.rate = min(1.0, max(0.0, rate))

    def should_sample(self, trace_id: str) -> bool:
        """Sample based on fixed rate."""
        # Simple hash-based sampling
        hash_val = int(trace_id[:8], 16)
        return (hash_val % 100) < (self.rate * 100)


class TracingCollector:
    """Collects and manages traces."""

    def __init__(self, max_traces: int = 1000):
        self.max_traces = max_traces
        self.traces: dict[str, Trace] = {}
        self.sampler = FixedRateSampler(rate=0.1)

    def add_trace(self, trace: Trace) -> bool:
        """Add trace to collector."""
        if not self.sampler.should_sample(trace.trace_id):
            return False

        if len(self.traces) >= self.max_traces:
            # Remove oldest trace
            oldest_id = min(self.traces.keys(), key=lambda k: self.traces[k].created_at)
            del self.traces[oldest_id]

        self.traces[trace.trace_id] = trace
        return True

    def get_traces(self, limit: int = 100) -> list[Trace]:
        """Get recent traces."""
        sorted_traces = sorted(self.traces.values(), key=lambda t: t.created_at, reverse=True)
        return sorted_traces[:limit]

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics."""
        if not self.traces:
            return {"total": 0, "avg_duration_ms": 0.0}

        durations = [t.get_duration_ms() for t in self.traces.values()]
        return {
            "total_traces": len(self.traces),
            "avg_duration_ms": sum(durations) / len(durations) if durations else 0.0,
            "min_duration_ms": min(durations) if durations else 0.0,
            "max_duration_ms": max(durations) if durations else 0.0,
        }
