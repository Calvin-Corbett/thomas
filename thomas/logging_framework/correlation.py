"""Log correlation across services and requests."""

import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from thomas.logging_framework._types import LogRecord


class CorrelationStore:
    """Stores and retrieves correlations between logs."""

    def __init__(self) -> None:
        """Initialize correlation store."""
        self.logs_by_trace: dict[str, list[LogRecord]] = defaultdict(list)
        self.logs_by_request: dict[str, list[LogRecord]] = defaultdict(list)
        self.logs_by_session: dict[str, list[LogRecord]] = defaultdict(list)
        self.temporal_groups: dict[str, list[LogRecord]] = defaultdict(list)
        self._lock = threading.RLock()
        self.retention_seconds = 3600  # 1 hour

    def add_record(self, record: LogRecord) -> None:
        """Add a record to correlation tracking.

        Args:
            record: Log record to add
        """
        with self._lock:
            # Track by trace ID
            if record.trace_context:
                self.logs_by_trace[record.trace_context.trace_id].append(record)

            # Track by request ID
            if record.correlation_id:
                self.logs_by_request[record.correlation_id.request_id].append(record)
                if record.correlation_id.session_id:
                    self.logs_by_session[record.correlation_id.session_id].append(record)

            self._cleanup_old_records()

    def get_logs_by_trace(self, trace_id: str) -> list[LogRecord]:
        """Get all logs for a trace.

        Args:
            trace_id: Trace ID to look up

        Returns:
            List of correlated logs
        """
        with self._lock:
            return self.logs_by_trace.get(trace_id, [])

    def get_logs_by_request(self, request_id: str) -> list[LogRecord]:
        """Get all logs for a request.

        Args:
            request_id: Request ID to look up

        Returns:
            List of correlated logs
        """
        with self._lock:
            return self.logs_by_request.get(request_id, [])

    def get_logs_by_session(self, session_id: str) -> list[LogRecord]:
        """Get all logs for a session.

        Args:
            session_id: Session ID to look up

        Returns:
            List of correlated logs
        """
        with self._lock:
            return self.logs_by_session.get(session_id, [])

    def _cleanup_old_records(self) -> None:
        """Remove records older than retention period."""
        cutoff = datetime.now() - timedelta(seconds=self.retention_seconds)

        for logs in [
            self.logs_by_trace.values(),
            self.logs_by_request.values(),
            self.logs_by_session.values(),
        ]:
            for log_list in logs:
                # Keep only recent records
                while log_list and log_list[0].timestamp < cutoff:
                    log_list.pop(0)


class TraceChainBuilder:
    """Builds causal chains of events from correlated logs."""

    def __init__(self) -> None:
        """Initialize trace chain builder."""
        self.chains: dict[str, list[LogRecord]] = {}
        self._lock = threading.RLock()

    def build_chain(self, records: list[LogRecord]) -> list[LogRecord]:
        """Build ordered causal chain from records.

        Args:
            records: Correlated log records

        Returns:
            Records ordered by timestamp with causality relationships
        """
        if not records:
            return []

        # Sort by timestamp
        sorted_records = sorted(records, key=lambda r: r.timestamp)

        # Build chain with parent-child relationships using span IDs
        chain = []
        span_map = {}

        for record in sorted_records:
            if record.trace_context:
                span_map[record.trace_context.span_id] = record

            chain.append(record)

        return chain

    def get_critical_path(self, records: list[LogRecord]) -> list[LogRecord]:
        """Get critical path (longest sequence of dependent operations).

        Args:
            records: Correlated log records

        Returns:
            Records on critical path
        """
        if not records:
            return []

        chain = self.build_chain(records)

        # For now, return the entire chain as the critical path
        # In a real implementation, would use span duration data
        return chain


class CrossServiceCorrelator:
    """Correlates logs across multiple services."""

    def __init__(self) -> None:
        """Initialize cross-service correlator."""
        self.service_logs: dict[str, list[LogRecord]] = defaultdict(list)
        self._lock = threading.RLock()

    def add_record(self, service_name: str, record: LogRecord) -> None:
        """Add a record from a service.

        Args:
            service_name: Name of service that logged
            record: Log record
        """
        with self._lock:
            self.service_logs[service_name].append(record)

    def correlate_by_trace(self, trace_id: str) -> dict[str, list[LogRecord]]:
        """Get logs for a trace grouped by service.

        Args:
            trace_id: Trace ID to find

        Returns:
            Dict mapping service names to their logs
        """
        result = {}
        with self._lock:
            for service_name, logs in self.service_logs.items():
                service_trace_logs = [r for r in logs if r.trace_context and r.trace_context.trace_id == trace_id]
                if service_trace_logs:
                    result[service_name] = service_trace_logs

        return result

    def find_service_dependencies(
        self,
        records: list[LogRecord],
    ) -> dict[str, set[str]]:
        """Find service dependencies from correlated logs.

        Args:
            records: Correlated log records

        Returns:
            Dict mapping service A -> services called by A
        """
        dependencies: dict[str, set[str]] = defaultdict(set)

        # Extract service names from logger names (e.g., "service.api" -> "service")
        for record in records:
            parts = record.logger_name.split(".")
            if len(parts) > 0:
                service = parts[0]
                # Look for calls to other services in message
                # (simplified - real implementation would use structured fields)
                for other_record in records:
                    if other_record.timestamp > record.timestamp:
                        other_parts = other_record.logger_name.split(".")
                        if other_parts and other_parts[0] != service:
                            dependencies[service].add(other_parts[0])

        return {k: v for k, v in dependencies.items() if v}


class CorrelationTimeline:
    """Creates a timeline of correlated events."""

    def __init__(self) -> None:
        """Initialize correlation timeline."""
        self.events: list[tuple[datetime, str, Any]] = []
        self._lock = threading.RLock()

    def add_event(self, record: LogRecord) -> None:
        """Add an event from a log record.

        Args:
            record: Log record representing an event
        """
        with self._lock:
            self.events.append(
                (
                    record.timestamp,
                    f"{record.logger_name}:{record.level.name}",
                    record.message,
                )
            )

    def get_timeline(self) -> list[dict[str, Any]]:
        """Get timeline of events.

        Returns:
            Ordered list of timeline events
        """
        with self._lock:
            return [
                {
                    "timestamp": ts.isoformat(),
                    "event": event_type,
                    "message": message,
                }
                for ts, event_type, message in sorted(self.events, key=lambda x: x[0])
            ]

    def get_time_delta(self, record1: LogRecord, record2: LogRecord) -> float:
        """Get time delta between two records.

        Args:
            record1: First record
            record2: Second record

        Returns:
            Time delta in seconds
        """
        return (record2.timestamp - record1.timestamp).total_seconds()


class AutoCorrelator:
    """Automatically finds related logs by temporal proximity and field overlap."""

    def __init__(self, time_window_seconds: int = 10) -> None:
        """Initialize auto-correlator.

        Args:
            time_window_seconds: Time window for finding related logs
        """
        self.time_window = timedelta(seconds=time_window_seconds)
        self._lock = threading.RLock()

    def find_related_logs(
        self,
        record: LogRecord,
        candidate_records: list[LogRecord],
    ) -> list[LogRecord]:
        """Find logs related to a given record.

        Args:
            record: Reference log record
            candidate_records: Candidate logs to search

        Returns:
            List of related logs
        """
        related = []

        for candidate in candidate_records:
            if candidate == record:
                continue

            # Check temporal proximity
            time_delta = abs((candidate.timestamp - record.timestamp).total_seconds())
            if time_delta > self.time_window.total_seconds():
                continue

            # Check field overlap
            overlap = self._calculate_field_overlap(record, candidate)
            if overlap > 0:
                related.append(candidate)

        return related

    @staticmethod
    def _calculate_field_overlap(record1: LogRecord, record2: LogRecord) -> int:
        """Calculate how many fields match between two records.

        Args:
            record1: First record
            record2: Second record

        Returns:
            Count of overlapping field values
        """
        overlap = 0

        # Check common fields
        for field_name in record1.fields:
            if field_name in record2.fields:
                if record1.fields[field_name].value == record2.fields[field_name].value:
                    overlap += 1

        # Check same logger
        if record1.logger_name == record2.logger_name:
            overlap += 1

        # Check same thread
        if record1.thread_id == record2.thread_id:
            overlap += 1

        return overlap


class CorrelationVisualizer:
    """Generates visualizations of correlated events."""

    @staticmethod
    def generate_sequence_diagram(
        records: list[LogRecord],
    ) -> str:
        """Generate ASCII sequence diagram of correlation.

        Args:
            records: Correlated log records

        Returns:
            ASCII art sequence diagram
        """
        if not records:
            return ""

        # Group by logger
        by_logger = defaultdict(list)
        for record in records:
            parts = record.logger_name.split(".")
            service = parts[0] if parts else "unknown"
            by_logger[service].append(record)

        # Sort records by time
        sorted_records = sorted(records, key=lambda r: r.timestamp)

        # Create simple ASCII representation
        lines = ["Sequence Diagram:"]
        lines.append("-" * 50)

        for i, record in enumerate(sorted_records):
            parts = record.logger_name.split(".")
            service = parts[0] if parts else "unknown"
            lines.append(f"{i + 1}. [{service}] {record.message[:40]}")

        return "\n".join(lines)

    @staticmethod
    def generate_dependency_graph(
        service_correlations: dict[str, set[str]],
    ) -> str:
        """Generate ASCII dependency graph.

        Args:
            service_correlations: Service dependency mapping

        Returns:
            ASCII art dependency graph
        """
        lines = ["Service Dependencies:"]
        lines.append("-" * 30)

        for service, deps in sorted(service_correlations.items()):
            lines.append(f"{service}")
            for dep in sorted(deps):
                lines.append(f"  -> {dep}")

        return "\n".join(lines)
