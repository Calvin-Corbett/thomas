"""Log formatters for various output formats."""

import json
import re
from datetime import datetime
from typing import Any

from thomas.logging_framework._exceptions import FormatterError
from thomas.logging_framework._types import LogFormatter, LogLevel, LogRecord


class BaseFormatter(LogFormatter):
    """Base formatter with common utilities."""

    def format_timestamp(self, dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Format datetime object.

        Args:
            dt: Datetime to format
            fmt: Format string

        Returns:
            Formatted datetime string
        """
        return dt.strftime(fmt)

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted duration string
        """
        if seconds < 0.001:
            return f"{seconds * 1000000:.1f}µs"
        elif seconds < 1:
            return f"{seconds * 1000:.2f}ms"
        elif seconds < 60:
            return f"{seconds:.2f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"

    def format_size(self, size_bytes: int) -> str:
        """Format size in human-readable form.

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted size string
        """
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}PB"


class JSONFormatter(BaseFormatter):
    """Formatter that outputs structured JSON."""

    def __init__(
        self,
        include_fields: bool = True,
        include_caller: bool = True,
        include_context: bool = True,
        pretty_print: bool = False,
    ) -> None:
        """Initialize JSON formatter.

        Args:
            include_fields: Include structured fields
            include_caller: Include caller information
            include_context: Include context data
            pretty_print: Format JSON with indentation
        """
        self.include_fields = include_fields
        self.include_caller = include_caller
        self.include_context = include_context
        self.pretty_print = pretty_print

    def format(self, record: LogRecord) -> str:
        """Format record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON formatted log string
        """
        try:
            output: dict[str, Any] = {
                "timestamp": self.format_timestamp(record.timestamp),
                "level": record.level.name,
                "logger": record.logger_name,
                "message": record.message,
            }

            if self.include_caller and record.caller_frame:
                output["caller"] = {
                    "file": record.caller_frame,
                    "line": record.caller_line,
                    "function": record.caller_function,
                }

            if self.include_fields and record.fields:
                output["fields"] = {k: v.value for k, v in record.fields.items()}

            if record.thread_name:
                output["thread"] = record.thread_name

            if record.process_id:
                output["process"] = record.process_id

            if self.include_context and record.context_data:
                output["context"] = record.context_data

            if record.trace_context:
                output["trace"] = {
                    "trace_id": record.trace_context.trace_id,
                    "span_id": record.trace_context.span_id,
                }

            if record.correlation_id:
                output["correlation"] = {
                    "request_id": record.correlation_id.request_id,
                }

            if record.exc_info:
                output["exception"] = self.format_exception(record.exc_info)

            indent = 2 if self.pretty_print else None
            return json.dumps(output, indent=indent, default=str)
        except Exception as e:
            raise FormatterError(f"JSON formatting failed: {e}", "JSONFormatter")


class TextFormatter(BaseFormatter):
    """Formatter with configurable text pattern."""

    # Default format: timestamp [level] logger: message
    DEFAULT_FORMAT = "%(timestamp)s [%(level)s] %(logger)s: %(message)s"

    def __init__(self, fmt: str = DEFAULT_FORMAT) -> None:
        """Initialize text formatter.

        Args:
            fmt: Format string with %{name} placeholders
        """
        self.fmt = fmt
        self._pattern = self._compile_pattern(fmt)

    @staticmethod
    def _compile_pattern(fmt: str) -> str:
        """Compile format string to regex pattern.

        Args:
            fmt: Format string with %(name)s placeholders

        Returns:
            Compiled pattern
        """
        return fmt

    def format(self, record: LogRecord) -> str:
        """Format record as text.

        Args:
            record: Log record to format

        Returns:
            Formatted log string
        """
        try:
            timestamp = self.format_timestamp(record.timestamp)
            message = record.message

            # Add exception info if present
            if record.exc_info:
                message += "\n" + self.format_exception(record.exc_info)

            # Build substitution dictionary
            subs: dict[str, Any] = {
                "timestamp": timestamp,
                "level": record.level.name,
                "levelno": record.level.value,
                "logger": record.logger_name,
                "message": message,
                "thread": record.thread_name,
                "threadid": record.thread_id,
                "process": record.process_id,
                "file": record.caller_frame,
                "line": record.caller_line,
                "function": record.caller_function,
            }

            # Add structured fields
            for name, field in record.fields.items():
                subs[f"field_{name}"] = field.value

            # Substitute values using % formatting
            output = self.fmt % subs
            return output
        except KeyError as e:
            raise FormatterError(f"Unknown placeholder: {e}", "TextFormatter")
        except Exception as e:
            raise FormatterError(f"Text formatting failed: {e}", "TextFormatter")


class LogfmtFormatter(BaseFormatter):
    """Formatter that outputs logfmt (key=value) format."""

    def format(self, record: LogRecord) -> str:
        """Format record as logfmt.

        Args:
            record: Log record to format

        Returns:
            Logfmt formatted log string
        """
        try:
            parts: list[str] = []

            # Core fields
            parts.append(f"timestamp={self._quote_value(record.timestamp.isoformat())}")
            parts.append(f"level={record.level.name}")
            parts.append(f"logger={self._quote_value(record.logger_name)}")
            parts.append(f"message={self._quote_value(record.message)}")

            # Caller info
            if record.caller_frame:
                parts.append(f"file={self._quote_value(record.caller_frame)}")
                if record.caller_line:
                    parts.append(f"line={record.caller_line}")
                if record.caller_function:
                    parts.append(f"func={self._quote_value(record.caller_function)}")

            # Structured fields
            for name, field in record.fields.items():
                parts.append(f"{name}={self._quote_value(str(field.value))}")

            # Thread and process
            if record.thread_name:
                parts.append(f"thread={self._quote_value(record.thread_name)}")
            parts.append(f"pid={record.process_id}")

            # Trace context
            if record.trace_context:
                parts.append(f"trace_id={self._quote_value(record.trace_context.trace_id)}")

            # Exception
            if record.exc_info:
                exc_str = self.format_exception(record.exc_info)
                parts.append(f"exception={self._quote_value(exc_str)}")

            return " ".join(parts)
        except Exception as e:
            raise FormatterError(f"Logfmt formatting failed: {e}", "LogfmtFormatter")

    @staticmethod
    def _quote_value(value: str) -> str:
        """Quote a value if it contains spaces or special characters.

        Args:
            value: Value to quote

        Returns:
            Quoted value
        """
        if re.search(r'[\s="\']', value):
            return f'"{value.replace(chr(34), chr(92) + chr(34))}"'
        return value


class CEFFormatter(BaseFormatter):
    """Formatter for Common Event Format (security event format)."""

    def format(self, record: LogRecord) -> str:
        """Format record as CEF.

        Args:
            record: Log record to format

        Returns:
            CEF formatted log string
        """
        try:
            # CEF Header: CEF:0|Vendor|Product|Version|EventId|EventName|Severity|...
            vendor = "Thomas"
            product = "LoggingFramework"
            version = "1.0"
            event_id = f"{record.logger_name}_{record.level.name}"
            event_name = record.message[:50]  # Truncate for CEF
            severity = self._map_level_to_cef_severity(record.level)

            cef_header = f"CEF:0|{vendor}|{product}|{version}|{event_id}|{event_name}|{severity}"

            # Extensions (key=value pairs)
            extensions: list[str] = [
                f"requestClientApplication={record.logger_name}",
                f"deviceProcessId={record.process_id}",
                f"deviceThreadId={record.thread_id}",
                f"rt={int(record.timestamp.timestamp() * 1000)}",
            ]

            if record.caller_function:
                extensions.append("cs1Label=function")
                extensions.append(f"cs1={record.caller_function}")

            for name, field in record.fields.items():
                extensions.append(f"{name}={self._escape_cef_value(str(field.value))}")

            return f"{cef_header}|{' '.join(extensions)}"
        except Exception as e:
            raise FormatterError(f"CEF formatting failed: {e}", "CEFFormatter")

    @staticmethod
    def _map_level_to_cef_severity(level: LogLevel) -> int:
        """Map LogLevel to CEF severity (0-10).

        Args:
            level: Log level

        Returns:
            CEF severity value
        """
        mapping = {
            LogLevel.DEBUG: 1,
            LogLevel.INFO: 2,
            LogLevel.WARNING: 5,
            LogLevel.ERROR: 7,
            LogLevel.CRITICAL: 10,
        }
        return mapping.get(level, 5)

    @staticmethod
    def _escape_cef_value(value: str) -> str:
        """Escape special characters in CEF value.

        Args:
            value: Value to escape

        Returns:
            Escaped value
        """
        return value.replace("\\", "\\\\").replace("=", "\\=")


class ColorizedFormatter(BaseFormatter):
    """Formatter with ANSI color codes for console output."""

    # ANSI color codes
    COLORS = {
        LogLevel.DEBUG: "\033[36m",  # Cyan
        LogLevel.INFO: "\033[32m",  # Green
        LogLevel.WARNING: "\033[33m",  # Yellow
        LogLevel.ERROR: "\033[31m",  # Red
        LogLevel.CRITICAL: "\033[41m\033[37m",  # Red background, white text
    }
    RESET = "\033[0m"

    def __init__(self, use_color: bool = True) -> None:
        """Initialize colorized formatter.

        Args:
            use_color: Enable color output
        """
        self.use_color = use_color

    def format(self, record: LogRecord) -> str:
        """Format record with color codes.

        Args:
            record: Log record to format

        Returns:
            Colored formatted log string
        """
        try:
            timestamp = self.format_timestamp(record.timestamp, "%H:%M:%S")
            message = record.message

            if record.exc_info:
                message += "\n" + self.format_exception(record.exc_info)

            level_str = record.level.name
            if self.use_color and record.level in self.COLORS:
                level_str = f"{self.COLORS[record.level]}{level_str}{self.RESET}"

            output = f"{timestamp} [{level_str}] {record.logger_name}: {message}"

            if record.fields:
                fields_str = " ".join(f"{k}={v.value}" for k, v in record.fields.items())
                output += f" {fields_str}"

            return output
        except Exception as e:
            raise FormatterError(f"Color formatting failed: {e}", "ColorizedFormatter")


class MultilineFormatter(BaseFormatter):
    """Formatter that properly handles multiline content like stack traces."""

    def __init__(self, indent: str = "  ") -> None:
        """Initialize multiline formatter.

        Args:
            indent: Indentation for continuation lines
        """
        self.indent = indent
        self.base_formatter = TextFormatter()

    def format(self, record: LogRecord) -> str:
        """Format record with multiline handling.

        Args:
            record: Log record to format

        Returns:
            Formatted log string with proper indentation
        """
        try:
            # Format the base message
            base_output = self.base_formatter.format(record)

            # Handle multiline content
            lines = base_output.split("\n")
            if len(lines) > 1:
                # Indent continuation lines
                indented_lines = [lines[0]]
                indented_lines.extend(f"{self.indent}{line}" for line in lines[1:])
                return "\n".join(indented_lines)

            return base_output
        except Exception as e:
            raise FormatterError(f"Multiline formatting failed: {e}", "MultilineFormatter")
