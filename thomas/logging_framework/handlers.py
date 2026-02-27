"""Log handlers for various output destinations."""

import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TextIO

from thomas.logging_framework._exceptions import HandlerError
from thomas.logging_framework._types import (
    LogFormatter,
    LogHandler,
    LogLevel,
    LogRecord,
    RetentionPolicy,
    RotationPolicy,
)
from thomas.logging_framework.formatters import TextFormatter


class ConsoleHandler(LogHandler):
    """Handler that writes logs to stdout/stderr."""

    def __init__(
        self,
        level: LogLevel = LogLevel.DEBUG,
        formatter: LogFormatter | None = None,
        use_stderr: bool = False,
    ) -> None:
        """Initialize console handler.

        Args:
            level: Minimum log level
            formatter: Log formatter
            use_stderr: Write to stderr instead of stdout
        """
        super().__init__(level, formatter or TextFormatter())
        self.use_stderr = use_stderr

    def emit(self, record: LogRecord) -> None:
        """Emit log record to console.

        Args:
            record: Log record to emit
        """
        try:
            output = self.formatter.format(record)
            stream = sys.stderr if self.use_stderr else sys.stdout
            stream.write(output + "\n")
            stream.flush()
        except Exception:
            self.handle_error(record)


class FileHandler(LogHandler):
    """Handler that writes logs to a file with optional rotation."""

    def __init__(
        self,
        filename: str,
        level: LogLevel = LogLevel.DEBUG,
        formatter: LogFormatter | None = None,
        rotation_policy: RotationPolicy | None = None,
        retention_policy: RetentionPolicy | None = None,
        encoding: str = "utf-8",
    ) -> None:
        """Initialize file handler.

        Args:
            filename: Path to log file
            level: Minimum log level
            formatter: Log formatter
            rotation_policy: File rotation policy
            retention_policy: Log retention policy
            encoding: File encoding
        """
        super().__init__(level, formatter or TextFormatter())
        self.filename = filename
        self.rotation_policy = rotation_policy
        self.retention_policy = retention_policy
        self.encoding = encoding
        self._file: TextIO | None = None
        self._lock = threading.RLock()
        self._last_rotation = datetime.now()
        self._rotation_count = 0
        self._file_size = 0
        self._ensure_open()

    def _ensure_open(self) -> None:
        """Ensure file is open for writing."""
        with self._lock:
            if self._file is None:
                try:
                    self._file = open(self.filename, "a", encoding=self.encoding)
                    self._file_size = os.path.getsize(self.filename)
                except Exception as e:
                    raise HandlerError(f"Cannot open file {self.filename}: {e}", "FileHandler")

    def _rotate_file(self) -> None:
        """Perform file rotation based on policy."""
        if not self.rotation_policy:
            return

        with self._lock:
            if self._file:
                self._file.close()
                self._file = None

            # Rename current file
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{self.filename}.{timestamp}.{self._rotation_count}"
                os.rename(self.filename, backup_name)
                self._rotation_count += 1

                # Cleanup old backups if needed
                if self.rotation_policy.max_count:
                    self._cleanup_old_backups()

                self._file_size = 0
                self._last_rotation = datetime.now()
                self._ensure_open()
            except Exception as e:
                raise HandlerError(f"File rotation failed: {e}", "FileHandler")

    def _cleanup_old_backups(self) -> None:
        """Clean up old backup files based on retention policy."""
        if not self.rotation_policy or not self.rotation_policy.max_count:
            return

        try:
            base_path = Path(self.filename)
            parent = base_path.parent
            pattern = f"{base_path.name}.*"

            backups = sorted(parent.glob(pattern))
            if len(backups) > self.rotation_policy.max_count:
                for old_file in backups[: len(backups) - self.rotation_policy.max_count]:
                    old_file.unlink()
        except (OSError, FileNotFoundError):
            pass  # Ignore cleanup errors

    def emit(self, record: LogRecord) -> None:
        """Emit log record to file.

        Args:
            record: Log record to emit
        """
        try:
            with self._lock:
                # Check rotation
                if self.rotation_policy:
                    if self.rotation_policy.should_rotate(self._file_size, self._last_rotation):
                        self._rotate_file()

                # Write record
                output = self.formatter.format(record)
                self._ensure_open()
                if self._file:
                    self._file.write(output + "\n")
                    self._file.flush()
                    self._file_size += len(output) + 1
        except (OSError, FileNotFoundError):
            self.handle_error(record)

    def close(self) -> None:
        """Close the file handler."""
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None


class AsyncHandler(LogHandler):
    """Handler that buffers logs and flushes asynchronously."""

    def __init__(
        self,
        target_handler: LogHandler,
        buffer_size: int = 100,
        flush_interval: float = 1.0,
        level: LogLevel = LogLevel.DEBUG,
    ) -> None:
        """Initialize async handler.

        Args:
            target_handler: Handler to flush buffered records to
            buffer_size: Maximum buffer size before auto-flush
            flush_interval: Seconds between auto-flushes
            level: Minimum log level
        """
        super().__init__(level, target_handler.formatter)
        self.target_handler = target_handler
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self._buffer: deque = deque(maxlen=buffer_size)
        self._lock = threading.RLock()
        self._flush_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_flush_thread()

    def _start_flush_thread(self) -> None:
        """Start background flush thread."""
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background thread loop for periodic flushing."""
        while not self._stop_event.is_set():
            time.sleep(self.flush_interval)
            if self._buffer:
                self.flush()

    def emit(self, record: LogRecord) -> None:
        """Buffer a log record.

        Args:
            record: Log record to buffer
        """
        with self._lock:
            self._buffer.append(record)
            if len(self._buffer) >= self.buffer_size:
                self.flush()

    def flush(self) -> None:
        """Flush all buffered records."""
        with self._lock:
            while self._buffer:
                record = self._buffer.popleft()
                try:
                    self.target_handler.handle(record)
                except Exception:  # REVIEWED: broad catch
                    pass

    def close(self) -> None:
        """Close the async handler."""
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
        self.flush()
        if hasattr(self.target_handler, "close"):
            self.target_handler.close()


class SyslogHandler(LogHandler):
    """Handler that sends logs to syslog (RFC 5424)."""

    def __init__(
        self,
        address: str = "/dev/log",
        facility: int = 16,  # Local0
        level: LogLevel = LogLevel.DEBUG,
        formatter: LogFormatter | None = None,
    ) -> None:
        """Initialize syslog handler.

        Args:
            address: Syslog socket address
            facility: Syslog facility code
            level: Minimum log level
            formatter: Log formatter
        """
        super().__init__(level, formatter or TextFormatter())
        self.address = address
        self.facility = facility
        self._socket = None
        self._connect()

    def _connect(self) -> None:
        """Connect to syslog socket."""
        try:
            import socket

            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._socket.connect(self.address)
        except Exception as e:
            raise HandlerError(f"Cannot connect to syslog: {e}", "SyslogHandler")

    def emit(self, record: LogRecord) -> None:
        """Emit log record to syslog.

        Args:
            record: Log record to emit
        """
        try:
            # RFC 5424 format: <PRI>VERSION TIMESTAMP HOSTNAME TAG[PID]: MSG
            priority = self.facility * 8 + record.level.value // 10
            timestamp = record.timestamp.isoformat()
            hostname = os.uname().nodename
            tag = record.logger_name
            message = self.formatter.format(record)

            syslog_msg = f"<{priority}>{timestamp} {hostname} {tag}[{record.process_id}]: {message}\n"

            if self._socket:
                self._socket.send(syslog_msg.encode("utf-8"))
        except (ConnectionError, TimeoutError):
            self.handle_error(record)

    def close(self) -> None:
        """Close the syslog handler."""
        if self._socket:
            self._socket.close()
            self._socket = None


class MemoryHandler(LogHandler):
    """Handler that stores recent logs in a ring buffer."""

    def __init__(
        self,
        capacity: int = 1000,
        level: LogLevel = LogLevel.DEBUG,
        formatter: LogFormatter | None = None,
    ) -> None:
        """Initialize memory handler.

        Args:
            capacity: Maximum number of logs to store
            level: Minimum log level
            formatter: Log formatter
        """
        super().__init__(level, formatter or TextFormatter())
        self.capacity = capacity
        self._buffer: deque = deque(maxlen=capacity)
        self._lock = threading.RLock()

    def emit(self, record: LogRecord) -> None:
        """Store log record in memory.

        Args:
            record: Log record to store
        """
        with self._lock:
            self._buffer.append(record)

    def get_records(self) -> list[LogRecord]:
        """Get all stored records.

        Returns:
            List of stored log records
        """
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Clear all stored records."""
        with self._lock:
            self._buffer.clear()


class NullHandler(LogHandler):
    """Handler that discards all log records."""

    def emit(self, record: LogRecord) -> None:
        """Discard log record.

        Args:
            record: Log record to discard
        """
        pass


class MultiHandler(LogHandler):
    """Handler that fans out to multiple target handlers."""

    def __init__(
        self,
        handlers: list[LogHandler] | None = None,
        level: LogLevel = LogLevel.DEBUG,
    ) -> None:
        """Initialize multi handler.

        Args:
            handlers: List of target handlers
            level: Minimum log level
        """
        super().__init__(level)
        self.handlers = handlers or []

    def add_handler(self, handler: LogHandler) -> None:
        """Add a target handler.

        Args:
            handler: Handler to add
        """
        if handler not in self.handlers:
            self.handlers.append(handler)

    def remove_handler(self, handler: LogHandler) -> None:
        """Remove a target handler.

        Args:
            handler: Handler to remove
        """
        if handler in self.handlers:
            self.handlers.remove(handler)

    def emit(self, record: LogRecord) -> None:
        """Emit record to all target handlers.

        Args:
            record: Log record to emit
        """
        for handler in self.handlers:
            try:
                handler.handle(record)
            except Exception:  # REVIEWED: broad catch
                pass


class RotatingFileHandler(FileHandler):
    """Convenience handler for file rotation."""

    def __init__(
        self,
        filename: str,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB default
        backup_count: int = 5,
        level: LogLevel = LogLevel.DEBUG,
        formatter: LogFormatter | None = None,
    ) -> None:
        """Initialize rotating file handler.

        Args:
            filename: Path to log file
            max_bytes: Maximum file size in bytes before rotation
            backup_count: Number of backup files to keep
            level: Minimum log level
            formatter: Log formatter
        """
        rotation_policy = RotationPolicy(
            rotation_type="size",
            max_size=max_bytes,
            max_count=backup_count,
        )
        super().__init__(
            filename=filename,
            level=level,
            formatter=formatter,
            rotation_policy=rotation_policy,
        )


class TimedRotatingFileHandler(FileHandler):
    """Convenience handler for time-based file rotation."""

    def __init__(
        self,
        filename: str,
        when: str = "midnight",
        interval: int = 1,
        backup_count: int = 7,
        level: LogLevel = LogLevel.DEBUG,
        formatter: LogFormatter | None = None,
    ) -> None:
        """Initialize timed rotating file handler.

        Args:
            filename: Path to log file
            when: When to rotate ("midnight", "hourly")
            interval: Interval between rotations
            backup_count: Number of backup files to keep
            level: Minimum log level
            formatter: Log formatter
        """
        time_interval = "daily" if when == "midnight" else when
        rotation_policy = RotationPolicy(
            rotation_type="time",
            time_interval=time_interval,
            max_count=backup_count,
        )
        super().__init__(
            filename=filename,
            level=level,
            formatter=formatter,
            rotation_policy=rotation_policy,
        )
