"""
Cross-cutting concerns middleware for CQRS.

Implements logging, validation, authorization, idempotency,
and metrics collection middleware.
"""

from __future__ import annotations

import time
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ._types import Command, Query


@dataclass
class MetricsSnapshot:
    """Snapshot of metrics data."""

    total_commands: int = 0
    total_queries: int = 0
    total_errors: int = 0
    avg_command_duration_ms: float = 0.0
    avg_query_duration_ms: float = 0.0
    commands_by_type: dict[str, int] = field(default_factory=dict)
    queries_by_type: dict[str, int] = field(default_factory=dict)
    errors_by_type: dict[str, int] = field(default_factory=dict)


class MetricsCollector:
    """
    Collects metrics about command and query execution.

    Tracks timing, counts, and error rates.
    """

    def __init__(self) -> None:
        """Initialize metrics collector."""
        self._command_durations: list[float] = []
        self._query_durations: list[float] = []
        self._commands_by_type: dict[str, int] = {}
        self._queries_by_type: dict[str, int] = {}
        self._errors_by_type: dict[str, int] = {}
        self._total_commands = 0
        self._total_queries = 0
        self._total_errors = 0

    def record_command(self, command_type: str, duration_ms: float) -> None:
        """
        Record command execution.

        Args:
            command_type: Type of command
            duration_ms: Execution time in milliseconds
        """
        self._total_commands += 1
        self._command_durations.append(duration_ms)
        self._commands_by_type[command_type] = self._commands_by_type.get(command_type, 0) + 1

    def record_query(self, query_type: str, duration_ms: float) -> None:
        """
        Record query execution.

        Args:
            query_type: Type of query
            duration_ms: Execution time in milliseconds
        """
        self._total_queries += 1
        self._query_durations.append(duration_ms)
        self._queries_by_type[query_type] = self._queries_by_type.get(query_type, 0) + 1

    def record_error(self, error_type: str) -> None:
        """
        Record error occurrence.

        Args:
            error_type: Type of error
        """
        self._total_errors += 1
        self._errors_by_type[error_type] = self._errors_by_type.get(error_type, 0) + 1

    def snapshot(self) -> MetricsSnapshot:
        """
        Get metrics snapshot.

        Returns:
            Current metrics
        """
        avg_cmd = sum(self._command_durations) / len(self._command_durations) if self._command_durations else 0.0
        avg_qry = sum(self._query_durations) / len(self._query_durations) if self._query_durations else 0.0

        return MetricsSnapshot(
            total_commands=self._total_commands,
            total_queries=self._total_queries,
            total_errors=self._total_errors,
            avg_command_duration_ms=avg_cmd,
            avg_query_duration_ms=avg_qry,
            commands_by_type=self._commands_by_type.copy(),
            queries_by_type=self._queries_by_type.copy(),
            errors_by_type=self._errors_by_type.copy(),
        )

    def reset(self) -> None:
        """Reset all metrics."""
        self._command_durations.clear()
        self._query_durations.clear()
        self._commands_by_type.clear()
        self._queries_by_type.clear()
        self._errors_by_type.clear()
        self._total_commands = 0
        self._total_queries = 0
        self._total_errors = 0


class LoggingMiddleware(ABC):
    """
    Base class for logging middleware.

    Provides structured logging of command/query execution.
    """

    def __init__(self, verbose: bool = False) -> None:
        """
        Initialize logging middleware.

        Args:
            verbose: Enable verbose logging
        """
        self.verbose = verbose
        self._logs: list[str] = []

    def log(self, message: str) -> None:
        """
        Record log message.

        Args:
            message: Message to log
        """
        timestamp = datetime.utcnow().isoformat()
        log_entry = f"[{timestamp}] {message}"
        self._logs.append(log_entry)

    def get_logs(self) -> list[str]:
        """
        Get recorded logs.

        Returns:
            List of log entries
        """
        return self._logs.copy()

    def clear_logs(self) -> None:
        """Clear recorded logs."""
        self._logs.clear()


class AuthorizationPolicy:
    """
    Policy for command/query authorization.

    Defines rules for who can execute what.
    """

    def __init__(self) -> None:
        """Initialize authorization policy."""
        self._rules: dict[str, list[str]] = {}

    def allow(self, resource: str, *principals: str) -> None:
        """
        Allow principals to access resource.

        Args:
            resource: Resource name
            principals: Principals to allow
        """
        if resource not in self._rules:
            self._rules[resource] = []
        self._rules[resource].extend(principals)

    def is_allowed(self, resource: str, principal: str) -> bool:
        """
        Check if principal can access resource.

        Args:
            resource: Resource to check
            principal: Principal to check

        Returns:
            True if allowed
        """
        if resource not in self._rules:
            return False
        return principal in self._rules[resource]


class AuthorizingMiddleware:
    """
    Middleware that enforces authorization.

    Uses policies to control access to commands and queries.
    """

    def __init__(self, policy: AuthorizationPolicy | None = None) -> None:
        """
        Initialize authorizing middleware.

        Args:
            policy: Authorization policy
        """
        self.policy = policy or AuthorizationPolicy()

    def authorize(
        self,
        resource: str,
        principal: str | None,
    ) -> bool:
        """
        Check authorization.

        Args:
            resource: Resource to access
            principal: Principal requesting access

        Returns:
            True if authorized
        """
        if not principal:
            return False
        return self.policy.is_allowed(resource, principal)


class IdempotencyMiddleware:
    """
    Middleware that provides idempotency tracking.

    Prevents duplicate effects from repeated operations.
    """

    def __init__(self) -> None:
        """Initialize idempotency middleware."""
        self._processed: dict[str, Any] = {}

    def mark_processed(self, idempotency_key: str, result: Any) -> None:
        """
        Mark operation as processed.

        Args:
            idempotency_key: Unique key for operation
            result: Result to cache
        """
        self._processed[idempotency_key] = result

    def get_result(self, idempotency_key: str) -> Any | None:
        """
        Get cached result if exists.

        Args:
            idempotency_key: Key to look up

        Returns:
            Cached result or None
        """
        return self._processed.get(idempotency_key)

    def clear(self) -> None:
        """Clear cache."""
        self._processed.clear()


class ValidationMiddleware:
    """
    Middleware that validates commands and queries.

    Ensures objects conform to constraints before execution.
    """

    def __init__(self) -> None:
        """Initialize validation middleware."""
        self._validators: dict[type, Callable] = {}

    def register_validator(
        self,
        obj_type: type,
        validator: Callable[[Any], bool],
    ) -> None:
        """
        Register validator for type.

        Args:
            obj_type: Type to validate
            validator: Validation function
        """
        self._validators[obj_type] = validator

    def validate(self, obj: Any) -> bool:
        """
        Validate object.

        Args:
            obj: Object to validate

        Returns:
            True if valid
        """
        validator = self._validators.get(type(obj))
        if validator:
            return validator(obj)
        return True


class MetricsMiddleware:
    """
    Middleware that collects metrics.

    Tracks execution time, counts, and error rates.
    """

    def __init__(self, collector: MetricsCollector | None = None) -> None:
        """
        Initialize metrics middleware.

        Args:
            collector: Metrics collector
        """
        self.collector = collector or MetricsCollector()

    async def handle_command(
        self,
        command: Command,
        handler: Callable,
    ) -> Any:
        """
        Handle command with metrics.

        Args:
            command: Command to execute
            handler: Command handler

        Returns:
            Handler result
        """
        start = time.time()
        try:
            result = await handler(command)
            duration_ms = (time.time() - start) * 1000
            self.collector.record_command(
                command.__class__.__name__,
                duration_ms,
            )
            return result
        except Exception as e:
            self.collector.record_error(type(e).__name__)
            raise

    async def handle_query(
        self,
        query: Query,
        handler: Callable,
    ) -> Any:
        """
        Handle query with metrics.

        Args:
            query: Query to execute
            handler: Query handler

        Returns:
            Handler result
        """
        start = time.time()
        try:
            result = await handler(query)
            duration_ms = (time.time() - start) * 1000
            self.collector.record_query(
                query.__class__.__name__,
                duration_ms,
            )
            return result
        except Exception as e:
            self.collector.record_error(type(e).__name__)
            raise

    def get_metrics(self) -> MetricsSnapshot:
        """
        Get metrics snapshot.

        Returns:
            Current metrics
        """
        return self.collector.snapshot()
