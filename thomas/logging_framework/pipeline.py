"""Log processing pipeline with enrichment, transformation, and routing."""

import socket
import threading
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from thomas.logging_framework._types import LogFilter, LogRecord, StructuredField


class PipelineStage:
    """Base class for pipeline processing stages."""

    def process(self, record: LogRecord) -> LogRecord | None:
        """Process a log record.

        Args:
            record: Log record to process

        Returns:
            Modified record or None to drop the record
        """
        return record


class EnrichmentProcessor(PipelineStage):
    """Enriches log records with contextual information."""

    def __init__(self) -> None:
        """Initialize enrichment processor."""
        self.add_hostname = True
        self.add_timestamp_millis = True
        self.add_thread_id = True
        self.add_process_id = True
        self.custom_enrichers: dict[str, Callable[[LogRecord], Any]] = {}

    def add_enricher(
        self,
        field_name: str,
        enricher: Callable[[LogRecord], Any],
    ) -> None:
        """Add a custom enrichment function.

        Args:
            field_name: Name of field to add
            enricher: Function that returns field value given a record
        """
        self.custom_enrichers[field_name] = enricher

    def process(self, record: LogRecord) -> LogRecord | None:
        """Enrich a log record with additional information.

        Args:
            record: Log record to enrich

        Returns:
            Enriched log record
        """
        # Add hostname
        if self.add_hostname:
            try:
                hostname = socket.gethostname()
                record.fields["hostname"] = StructuredField(
                    name="hostname",
                    value=hostname,
                )
            except (ConnectionError, TimeoutError):
                pass

        # Add timestamp in milliseconds
        if self.add_timestamp_millis:
            millis = int(record.timestamp.timestamp() * 1000)
            record.fields["timestamp_millis"] = StructuredField(
                name="timestamp_millis",
                value=millis,
            )

        # Add thread info
        if self.add_thread_id:
            record.fields["thread_id"] = StructuredField(
                name="thread_id",
                value=record.thread_id,
            )

        # Add process info
        if self.add_process_id:
            record.fields["process_id"] = StructuredField(
                name="process_id",
                value=record.process_id,
            )

        # Apply custom enrichers
        for field_name, enricher in self.custom_enrichers.items():
            try:
                value = enricher(record)
                record.fields[field_name] = StructuredField(
                    name=field_name,
                    value=value,
                )
            except Exception:  # REVIEWED: broad catch
                pass

        return record


class TransformationProcessor(PipelineStage):
    """Transforms log records (masking, redacting, renaming fields)."""

    def __init__(self) -> None:
        """Initialize transformation processor."""
        self.pii_patterns: dict[str, str] = {
            "ssn": r"\d{3}-\d{2}-\d{4}",
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        }
        self.field_renames: dict[str, str] = {}
        self.field_masks: set[str] = set()
        self.field_redactions: set[str] = set()

    def mask_pii(self, text: str, pattern_name: str) -> str:
        """Mask PII in text using pattern.

        Args:
            text: Text containing PII
            pattern_name: Name of PII pattern

        Returns:
            Text with PII masked
        """
        import re

        pattern = self.pii_patterns.get(pattern_name)
        if not pattern:
            return text
        return re.sub(pattern, "****", text)

    def add_field_mask(self, field_name: str) -> None:
        """Mark a field for masking (partial redaction).

        Args:
            field_name: Field to mask
        """
        self.field_masks.add(field_name)

    def add_field_redaction(self, field_name: str) -> None:
        """Mark a field for full redaction.

        Args:
            field_name: Field to redact completely
        """
        self.field_redactions.add(field_name)

    def rename_field(self, old_name: str, new_name: str) -> None:
        """Rename a field.

        Args:
            old_name: Current field name
            new_name: New field name
        """
        self.field_renames[old_name] = new_name

    def _mask_value(self, value: Any) -> Any:
        """Mask a value showing only first and last character.

        Args:
            value: Value to mask

        Returns:
            Masked value
        """
        s = str(value)
        if len(s) <= 2:
            return "**"
        return f"{s[0]}{'*' * (len(s) - 2)}{s[-1]}"

    def process(self, record: LogRecord) -> LogRecord | None:
        """Transform a log record.

        Args:
            record: Log record to transform

        Returns:
            Transformed log record
        """
        # Apply field renames
        for old_name, new_name in self.field_renames.items():
            if old_name in record.fields:
                field = record.fields.pop(old_name)
                record.fields[new_name] = StructuredField(
                    name=new_name,
                    value=field.value,
                    is_pii=field.is_pii,
                )

        # Apply field redactions
        for field_name in self.field_redactions:
            if field_name in record.fields:
                field = record.fields[field_name]
                field.is_redacted = True
                field.value = "[REDACTED]"

        # Apply field masks
        for field_name in self.field_masks:
            if field_name in record.fields:
                field = record.fields[field_name]
                field.value = self._mask_value(field.value)

        # Mask message if it contains PII
        for pattern_name in self.pii_patterns:
            record.message = self.mask_pii(record.message, pattern_name)

        return record


class _RouteConditionFilter(LogFilter):
    """Handler filter that matches when any registered route condition passes."""

    def __init__(self) -> None:
        self._conditions: list[Callable[[LogRecord], bool]] = []

    def add_condition(self, condition: Callable[[LogRecord], bool]) -> None:
        """Register a route condition for this sink."""
        if condition not in self._conditions:
            self._conditions.append(condition)

    def filter(self, record: LogRecord) -> bool:
        """Allow record when at least one route condition matches."""
        if not self._conditions:
            return True

        for condition in self._conditions:
            try:
                if condition(record):
                    return True
            except Exception:  # REVIEWED: broad catch
                continue
        return False


class Router:
    """Routes log records to different destinations based on conditions."""

    def __init__(self) -> None:
        """Initialize router."""
        self.routes: dict[str, Callable[[LogRecord], bool]] = {}
        self.route_sinks: dict[str, list[Any]] = {}
        self._sink_route_filters: dict[int, _RouteConditionFilter] = {}

    def add_route(
        self,
        route_name: str,
        condition: Callable[[LogRecord], bool],
    ) -> None:
        """Add a routing rule.

        Args:
            route_name: Name for this route
            condition: Callable that returns True if record matches
        """
        self.routes[route_name] = condition
        self.route_sinks[route_name] = []

    def add_sink_to_route(self, route_name: str, sink: Any) -> None:
        """Add a sink to a route.

        Args:
            route_name: Name of route
            sink: Handler/sink to add
        """
        if route_name not in self.route_sinks:
            self.route_sinks[route_name] = []
        self.route_sinks[route_name].append(sink)

        # If the sink is a log handler, attach a route-aware filter so the
        # handler only accepts records matching any of its assigned routes.
        condition = self.routes.get(route_name)
        if condition and hasattr(sink, "add_filter"):
            sink_id = id(sink)
            route_filter = self._sink_route_filters.get(sink_id)
            if route_filter is None:
                route_filter = _RouteConditionFilter()
                self._sink_route_filters[sink_id] = route_filter
                sink.add_filter(route_filter)
            route_filter.add_condition(condition)

    def route(self, record: LogRecord) -> dict[str, list[Any]]:
        """Route a record to matching sinks.

        Args:
            record: Log record to route

        Returns:
            Dict mapping route names to sinks
        """
        matched_sinks = {}
        for route_name, condition in self.routes.items():
            try:
                if condition(record):
                    matched_sinks[route_name] = self.route_sinks[route_name]
            except Exception:  # REVIEWED: broad catch
                pass
        return matched_sinks


class LogPipeline:
    """Pipeline for processing log records through stages."""

    def __init__(self) -> None:
        """Initialize log pipeline."""
        self.stages: list[PipelineStage] = []
        self.enrichment = EnrichmentProcessor()
        self.transformation = TransformationProcessor()
        self.router = Router()
        self._lock = threading.RLock()
        self.enabled = True

    def add_stage(self, stage: PipelineStage) -> None:
        """Add a processing stage to the pipeline.

        Args:
            stage: Pipeline stage to add
        """
        with self._lock:
            self.stages.append(stage)

    def remove_stage(self, stage: PipelineStage) -> None:
        """Remove a processing stage from the pipeline.

        Args:
            stage: Pipeline stage to remove
        """
        with self._lock:
            if stage in self.stages:
                self.stages.remove(stage)

    def process(self, record: LogRecord) -> LogRecord | None:
        """Process a log record through the pipeline.

        Args:
            record: Log record to process

        Returns:
            Processed record or None if dropped
        """
        if not self.enabled:
            return record

        with self._lock:
            # Create a copy to avoid modifying original
            record = deepcopy(record)

            # Run enrichment stage
            record = self.enrichment.process(record)
            if record is None:
                return None

            # Run transformation stage
            record = self.transformation.process(record)
            if record is None:
                return None

            # Run custom stages
            for stage in self.stages:
                record = stage.process(record)
                if record is None:
                    return None

            return record

    def enable(self) -> None:
        """Enable the pipeline."""
        self.enabled = True

    def disable(self) -> None:
        """Disable the pipeline."""
        self.enabled = False


class PipelineConfig:
    """Configuration for log pipeline from dict."""

    @staticmethod
    def from_dict(config: dict[str, Any]) -> LogPipeline:
        """Create pipeline from configuration dictionary.

        Args:
            config: Configuration dict

        Returns:
            Configured LogPipeline

        Example:
            {
                "enrichment": {
                    "add_hostname": True,
                    "add_timestamp_millis": True
                },
                "transformation": {
                    "field_masks": ["password", "token"],
                    "field_redactions": ["ssn"]
                },
                "routes": {
                    "errors": {
                        "condition": "level >= ERROR",
                        "sinks": ["error_handler"]
                    }
                }
            }
        """
        pipeline = LogPipeline()

        # Configure enrichment
        if "enrichment" in config:
            enrichment_cfg = config["enrichment"]
            if "add_hostname" in enrichment_cfg:
                pipeline.enrichment.add_hostname = enrichment_cfg["add_hostname"]
            if "add_timestamp_millis" in enrichment_cfg:
                pipeline.enrichment.add_timestamp_millis = enrichment_cfg["add_timestamp_millis"]

        # Configure transformation
        if "transformation" in config:
            transform_cfg = config["transformation"]
            if "field_masks" in transform_cfg:
                for field in transform_cfg["field_masks"]:
                    pipeline.transformation.add_field_mask(field)
            if "field_redactions" in transform_cfg:
                for field in transform_cfg["field_redactions"]:
                    pipeline.transformation.add_field_redaction(field)

        return pipeline
