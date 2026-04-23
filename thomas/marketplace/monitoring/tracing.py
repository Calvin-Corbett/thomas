"""
Distributed tracing system.

Span model, trace context propagation using W3C Trace Context format,
trace assembly, critical path analysis, and service dependency graphs.
"""

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Span:
    """A span in a distributed trace."""

    trace_id: str
    span_id: str
    operation: str
    start_time: float
    end_time: float | None = None
    parent_span_id: str | None = None
    service: str = ""
    status: str = "ok"  # ok, error, unset
    tags: dict[str, str] = field(default_factory=dict)
    logs: list[dict[str, any]] = field(default_factory=list)

    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    def finish(self) -> None:
        """Mark span as finished."""
        self.end_time = time.time()

    def set_tag(self, key: str, value: str) -> None:
        """Set a tag on the span."""
        self.tags[key] = value

    def log_event(self, message: str, timestamp: float | None = None) -> None:
        """Log an event on the span."""
        self.logs.append(
            {
                "message": message,
                "timestamp": timestamp or time.time(),
            }
        )


@dataclass
class Trace:
    """A complete distributed trace."""

    trace_id: str
    spans: list[Span] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    def add_span(self, span: Span) -> None:
        """Add a span to the trace."""
        self.spans.append(span)

    def duration_ms(self) -> float:
        """Get total trace duration in milliseconds."""
        if not self.spans:
            return 0.0

        min_start = min(s.start_time for s in self.spans)
        max_end = max((s.end_time or s.start_time) for s in self.spans)

        return (max_end - min_start) * 1000


@dataclass
class CriticalPath:
    """The critical path through a trace."""

    spans: list[Span]
    duration_ms: float
    bottleneck_span: Span | None = None


class TraceContext:
    """W3C Trace Context for distributed tracing."""

    def __init__(
        self,
        trace_id: str,
        parent_id: str | None = None,
        trace_flags: str = "01",
    ) -> None:
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.trace_flags = trace_flags

    @staticmethod
    def from_headers(headers: dict[str, str]) -> Optional["TraceContext"]:
        """Create context from W3C Trace Context headers."""
        traceparent = headers.get("traceparent", "")
        if not traceparent:
            return None

        parts = traceparent.split("-")
        if len(parts) != 4:
            return None

        version, trace_id, parent_id, trace_flags = parts

        if version != "00":
            return None

        return TraceContext(
            trace_id=trace_id,
            parent_id=parent_id,
            trace_flags=trace_flags,
        )

    def to_headers(self) -> dict[str, str]:
        """Convert to W3C Trace Context headers."""
        # Generate new span ID
        span_id = uuid.uuid4().hex[:16]

        traceparent = f"00-{self.trace_id}-{span_id}-{self.trace_flags}"

        return {
            "traceparent": traceparent,
            "tracestate": "",
        }


class TracingCollector:
    """Collects and manages distributed traces."""

    def __init__(self) -> None:
        self._traces: dict[str, Trace] = {}
        self._span_index: dict[str, Span] = {}
        self._service_index: dict[str, list[Span]] = defaultdict(list)
        self._lock = __import__("threading").Lock()
        self._max_traces = 10000

    def start_span(
        self,
        trace_id: str,
        operation: str,
        service: str = "",
        parent_span_id: str | None = None,
    ) -> Span:
        """Start a new span."""
        span_id = uuid.uuid4().hex[:16]
        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            operation=operation,
            start_time=time.time(),
            parent_span_id=parent_span_id,
            service=service,
        )

        with self._lock:
            # Create trace if doesn't exist
            if trace_id not in self._traces:
                if len(self._traces) >= self._max_traces:
                    # Remove oldest trace
                    oldest = min(
                        self._traces.values(),
                        key=lambda t: t.start_time,
                    )
                    del self._traces[oldest.trace_id]

                self._traces[trace_id] = Trace(trace_id=trace_id)

            self._traces[trace_id].add_span(span)
            self._span_index[span_id] = span
            self._service_index[service].append(span)

        return span

    def finish_span(self, span: Span) -> None:
        """Finish a span."""
        span.finish()

    def record_span(self, span: Span) -> None:
        """Record a span that was created elsewhere."""
        with self._lock:
            if span.trace_id not in self._traces:
                self._traces[span.trace_id] = Trace(trace_id=span.trace_id)

            self._traces[span.trace_id].add_span(span)
            self._span_index[span.span_id] = span
            self._service_index[span.service].append(span)

    def get_trace(self, trace_id: str) -> Trace | None:
        """Get a trace by ID."""
        with self._lock:
            return self._traces.get(trace_id)

    def get_traces(self, service: str | None = None) -> list[Trace]:
        """Get traces, optionally filtered by service."""
        with self._lock:
            if service:
                trace_ids = {span.trace_id for span in self._service_index.get(service, [])}
                return [self._traces[tid] for tid in trace_ids if tid in self._traces]
            return list(self._traces.values())

    def get_critical_path(self, trace: Trace) -> CriticalPath:
        """Analyze critical path through trace."""
        if not trace.spans:
            return CriticalPath(spans=[], duration_ms=0.0)

        # Build span tree
        span_tree: dict[str | None, list[Span]] = defaultdict(list)
        for span in trace.spans:
            span_tree[span.parent_span_id].append(span)

        # Find critical path (longest path through DAG)
        critical_spans = []
        max_duration = 0.0

        def dfs(parent_id: str | None, current_duration: float) -> None:
            nonlocal max_duration, critical_spans

            children = span_tree.get(parent_id, [])
            if not children:
                if current_duration > max_duration:
                    max_duration = current_duration
                return

            for child in children:
                child_duration = child.duration_ms() / 1000
                dfs(child.span_id, current_duration + child_duration)

        dfs(None, 0.0)

        # Find bottleneck (slowest span)
        bottleneck = None
        if trace.spans:
            bottleneck = max(trace.spans, key=lambda s: s.duration_ms())

        return CriticalPath(
            spans=critical_spans,
            duration_ms=max_duration * 1000,
            bottleneck_span=bottleneck,
        )

    def get_service_dependencies(self, trace: Trace) -> dict[str, list[str]]:
        """Extract service dependency graph from trace."""
        dependencies: dict[str, list[str]] = defaultdict(list)

        # Build span parent map
        span_map = {s.span_id: s for s in trace.spans}

        for span in trace.spans:
            if span.parent_span_id and span.parent_span_id in span_map:
                parent = span_map[span.parent_span_id]
                if parent.service and span.service:
                    if span.service not in dependencies[parent.service]:
                        dependencies[parent.service].append(span.service)

        return dict(dependencies)

    def get_latency_breakdown(self, trace: Trace) -> dict[str, float]:
        """Get latency breakdown by service."""
        breakdown: dict[str, float] = defaultdict(float)

        for span in trace.spans:
            service = span.service or "unknown"
            breakdown[service] += span.duration_ms()

        return dict(breakdown)

    def find_errors(self, trace: Trace) -> list[Span]:
        """Find all error spans in trace."""
        return [s for s in trace.spans if s.status == "error"]

    def find_slow_spans(self, trace: Trace, threshold_ms: float = 100.0) -> list[Span]:
        """Find spans slower than threshold."""
        return [s for s in trace.spans if s.duration_ms() > threshold_ms]

    def export_trace(self, trace: Trace) -> dict[str, any]:
        """Export trace as dictionary."""
        return {
            "trace_id": trace.trace_id,
            "duration_ms": trace.duration_ms(),
            "spans": [
                {
                    "span_id": s.span_id,
                    "operation": s.operation,
                    "service": s.service,
                    "duration_ms": s.duration_ms(),
                    "start_time": s.start_time,
                    "status": s.status,
                    "parent_span_id": s.parent_span_id,
                    "tags": s.tags,
                    "logs": s.logs,
                }
                for s in trace.spans
            ],
        }

    def get_stats(self) -> dict[str, any]:
        """Get tracing statistics."""
        with self._lock:
            traces = list(self._traces.values())
            all_spans = []
            for trace in traces:
                all_spans.extend(trace.spans)

            avg_spans_per_trace = len(all_spans) / len(traces) if traces else 0
            avg_duration = sum(t.duration_ms() for t in traces) / len(traces) if traces else 0

            return {
                "trace_count": len(self._traces),
                "span_count": len(all_spans),
                "avg_spans_per_trace": avg_spans_per_trace,
                "avg_duration_ms": avg_duration,
                "services": list(self._service_index.keys()),
            }
