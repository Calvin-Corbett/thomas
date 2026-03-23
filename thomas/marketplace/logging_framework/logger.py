"""Core logger implementation with hierarchical logger tree."""

import inspect
import threading
from datetime import datetime
from typing import Any, Optional

from thomas.marketplace.logging_framework._types import (
    CorrelationId,
    LogContext,
    LogFilter,
    LogHandler,
    LogLevel,
    LogRecord,
    StructuredField,
    TraceContext,
)


class Logger:
    """Hierarchical logger with level propagation and structured fields."""

    _lock = threading.RLock()
    _loggers: dict[str, "Logger"] = {}

    def __init__(
        self,
        name: str,
        level: LogLevel = LogLevel.INFO,
        parent: Optional["Logger"] = None,
    ) -> None:
        """Initialize logger.

        Args:
            name: Logger name (dot-separated for hierarchy)
            level: Minimum log level
            parent: Parent logger in hierarchy
        """
        self.name = name
        self.context = LogContext(
            parent_logger=parent,
            level=level,
        )
        self._children: list[Logger] = []
        self._sampling_counts: dict[str, int] = {}
        self._sampling_lock = threading.RLock()

        if parent:
            parent._add_child(self)

    def _add_child(self, child: "Logger") -> None:
        """Register a child logger."""
        with self._lock:
            if child not in self._children:
                self._children.append(child)

    def set_level(self, level: LogLevel) -> None:
        """Set the logger's minimum log level.

        Args:
            level: New log level
        """
        with self.context.lock:
            self.context.level = level

    def get_effective_level(self) -> LogLevel:
        """Get the effective log level (considering parent loggers).

        Args:
            Returns: Effective log level
        """
        with self.context.lock:
            if self.context.level != LogLevel.INFO:
                return self.context.level
            if self.context.parent_logger:
                return self.context.parent_logger.get_effective_level()
            return LogLevel.INFO

    def add_handler(self, handler: LogHandler) -> None:
        """Add a handler to this logger.

        Args:
            handler: Handler to add
        """
        with self.context.lock:
            if handler not in self.context.handlers:
                self.context.handlers.append(handler)

    def remove_handler(self, handler: LogHandler) -> None:
        """Remove a handler from this logger.

        Args:
            handler: Handler to remove
        """
        with self.context.lock:
            if handler in self.context.handlers:
                self.context.handlers.remove(handler)

    def add_filter(self, filter: LogFilter) -> None:
        """Add a filter to this logger.

        Args:
            filter: Filter to add
        """
        with self.context.lock:
            if filter not in self.context.filters:
                self.context.filters.append(filter)

    def remove_filter(self, filter: LogFilter) -> None:
        """Remove a filter from this logger.

        Args:
            filter: Filter to remove
        """
        with self.context.lock:
            if filter in self.context.filters:
                self.context.filters.remove(filter)

    def set_propagate(self, propagate: bool) -> None:
        """Set whether logs propagate to parent logger.

        Args:
            propagate: True to propagate to parent
        """
        with self.context.lock:
            self.context.propagate = propagate

    def add_structured_field(
        self,
        name: str,
        value: Any,
        is_pii: bool = False,
    ) -> None:
        """Add a structured field to logger context.

        Args:
            name: Field name
            value: Field value
            is_pii: Whether field contains personally identifiable information
        """
        self.context.add_field(name, value, is_pii)

    def set_trace_context(self, trace_context: TraceContext) -> None:
        """Set distributed trace context.

        Args:
            trace_context: Trace context for correlation
        """
        with self.context.lock:
            self.context.trace_context = trace_context

    def set_correlation_id(self, correlation_id: CorrelationId) -> None:
        """Set request correlation ID.

        Args:
            correlation_id: Correlation ID for request tracking
        """
        with self.context.lock:
            self.context.correlation_id = correlation_id

    def _get_caller_info(self) -> tuple[str | None, int | None, str | None]:
        """Extract caller information from stack.

        Returns:
            Tuple of (filename, line_number, function_name)
        """
        try:
            frame = inspect.currentframe()
            if frame is None:
                return None, None, None

            # Walk up the stack to find the first caller outside logging framework
            while frame:
                code = frame.f_code
                filename = code.co_filename
                # Skip internal logging framework frames
                if not filename.endswith("logging_framework/logger.py"):
                    return (
                        filename,
                        frame.f_lineno,
                        code.co_name,
                    )
                frame = frame.f_back

            return None, None, None
        except Exception:  # REVIEWED: broad catch
            return None, None, None

    def _create_record(
        self,
        level: LogLevel,
        message: str,
        exc_info: tuple[Any, Any, Any] | None = None,
    ) -> LogRecord:
        """Create a log record.

        Args:
            level: Log level
            message: Log message
            exc_info: Exception info if logging exception

        Returns:
            Populated LogRecord
        """
        caller_file, caller_line, caller_func = self._get_caller_info()

        # Collect structured fields from this logger and parents
        fields: dict[str, StructuredField] = {}
        current = self
        while current:
            for name, value in current.context.get_fields().items():
                if name not in fields:  # Child fields take precedence
                    fields[name] = StructuredField(
                        name=name,
                        value=value.get("value"),
                        is_pii=value.get("is_pii", False),
                    )
            if current.context.parent_logger:
                current = current.context.parent_logger
            else:
                break

        record = LogRecord(
            timestamp=datetime.now(),
            level=level,
            logger_name=self.name,
            message=message,
            fields=fields,
            exc_info=exc_info,
            caller_frame=caller_file,
            caller_line=caller_line,
            caller_function=caller_func,
            trace_context=self.context.trace_context,
            correlation_id=self.context.correlation_id,
        )
        return record

    def _handle_record(self, record: LogRecord) -> None:
        """Process a log record through handlers and filters.

        Args:
            record: Log record to handle
        """
        # Apply logger-level filters
        with self.context.lock:
            for f in self.context.filters:
                if not f.filter(record):
                    return

            # Emit to handlers
            for handler in self.context.handlers:
                handler.handle(record)

        # Propagate to parent logger if enabled
        if self.context.propagate and self.context.parent_logger:
            self.context.parent_logger._handle_record(record)

    def _log(
        self,
        level: LogLevel,
        message: str,
        *args: Any,
        exc_info: bool = False,
        extra_fields: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Internal logging method.

        Args:
            level: Log level
            message: Log message (may contain % formatting placeholders)
            *args: Arguments for message formatting
            exc_info: Include exception info if True
            extra_fields: Additional structured fields
            **kwargs: Additional keyword arguments (ignored for compatibility)
        """
        # Check if this level should be logged
        if level < self.get_effective_level():
            return

        # Lazy message formatting
        try:
            if args:
                formatted_message = message % args
            else:
                formatted_message = message
        except (TypeError, ValueError):
            formatted_message = message

        # Get exception info if requested
        exc_info_tuple = None
        if exc_info:
            import sys

            exc_info_tuple = sys.exc_info()
            if exc_info_tuple == (None, None, None):
                exc_info_tuple = None

        # Create log record
        record = self._create_record(
            level=level,
            message=formatted_message,
            exc_info=exc_info_tuple,
        )

        # Add extra fields to record
        if extra_fields:
            for name, value in extra_fields.items():
                record.fields[name] = StructuredField(
                    name=name,
                    value=value,
                )

        # Handle record (emit to handlers and propagate)
        self._handle_record(record)

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log a debug message.

        Args:
            message: Log message
            *args: Message formatting arguments
            **kwargs: Additional options (exc_info, extra_fields)
        """
        self._log(LogLevel.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log an info message.

        Args:
            message: Log message
            *args: Message formatting arguments
            **kwargs: Additional options (exc_info, extra_fields)
        """
        self._log(LogLevel.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log a warning message.

        Args:
            message: Log message
            *args: Message formatting arguments
            **kwargs: Additional options (exc_info, extra_fields)
        """
        self._log(LogLevel.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log an error message.

        Args:
            message: Log message
            *args: Message formatting arguments
            **kwargs: Additional options (exc_info, extra_fields)
        """
        self._log(LogLevel.ERROR, message, *args, **kwargs)

    def critical(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log a critical message.

        Args:
            message: Log message
            *args: Message formatting arguments
            **kwargs: Additional options (exc_info, extra_fields)
        """
        self._log(LogLevel.CRITICAL, message, *args, **kwargs)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log an exception at ERROR level.

        Args:
            message: Log message
            *args: Message formatting arguments
            **kwargs: Additional options
        """
        self._log(LogLevel.ERROR, message, *args, exc_info=True, **kwargs)


# Global logger registry
_root_logger: Logger | None = None


def _get_root_logger() -> Logger:
    """Get or create the root logger.

    Returns:
        Root logger instance
    """
    global _root_logger
    if _root_logger is None:
        _root_logger = Logger("root")
    return _root_logger


def get_logger(name: str) -> Logger:
    """Get or create a logger by name.

    Loggers are organized in a hierarchical tree using dot-separated names.
    For example, "myapp.database.connection" creates a hierarchy:
    root -> myapp -> myapp.database -> myapp.database.connection

    Args:
        name: Logger name (can be hierarchical with dots)

    Returns:
        Logger instance
    """
    with Logger._lock:
        if name in Logger._loggers:
            return Logger._loggers[name]

        # Get or create parent logger
        root = _get_root_logger()
        if "." not in name:
            parent = root
        else:
            parent_name = name.rsplit(".", 1)[0]
            parent = get_logger(parent_name)

        # Create new logger
        logger = Logger(name, parent=parent)
        Logger._loggers[name] = logger
        return logger


def root_logger() -> Logger:
    """Get the root logger.

    Returns:
        Root logger instance
    """
    return _get_root_logger()
