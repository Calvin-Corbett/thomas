"""Container logging infrastructure."""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """Log level enumeration."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass
class LogEntry:
    """Single log entry."""

    timestamp: datetime
    message: str
    level: LogLevel = LogLevel.INFO
    source: str = "stdout"
    container_id: str | None = None


class LogDriver:
    """Container logging driver."""

    def __init__(self, storage_root: str = "/var/lib/containers/logs") -> None:
        """Initialize log driver.

        Args:
            storage_root: Root directory for log storage.
        """
        self.storage_root = storage_root
        self._logs: dict[str, list[LogEntry]] = {}
        self._rotation_size_bytes = 10 * 1024 * 1024  # 10MB
        self._max_files = 3

    def write_log(
        self,
        container_id: str,
        message: str,
        level: LogLevel = LogLevel.INFO,
        source: str = "stdout",
    ) -> None:
        """Write a log entry.

        Args:
            container_id: Container ID.
            message: Log message.
            level: Log level.
            source: Log source (stdout, stderr).
        """
        if container_id not in self._logs:
            self._logs[container_id] = []

        entry = LogEntry(
            timestamp=datetime.utcnow(),
            message=message,
            level=level,
            source=source,
            container_id=container_id,
        )

        self._logs[container_id].append(entry)

    def read_logs(
        self,
        container_id: str,
        tail: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        timestamps: bool = False,
    ) -> list[str]:
        """Read container logs.

        Args:
            container_id: Container ID.
            tail: Return last N lines.
            since: Return logs since timestamp.
            until: Return logs until timestamp.
            timestamps: Include timestamps.

        Returns:
            List of log lines.
        """
        if container_id not in self._logs:
            return []

        entries = self._logs[container_id]

        # Filter by time range
        if since:
            entries = [e for e in entries if e.timestamp >= since]
        if until:
            entries = [e for e in entries if e.timestamp <= until]

        # Format entries
        lines = []
        for entry in entries:
            if timestamps:
                line = f"{entry.timestamp.isoformat()} {entry.message}"
            else:
                line = entry.message
            lines.append(line)

        # Apply tail
        if tail is not None:
            lines = lines[-tail:]

        return lines

    def get_logs_json(
        self,
        container_id: str,
        tail: int | None = None,
    ) -> list[dict]:
        """Get logs in JSON format.

        Args:
            container_id: Container ID.
            tail: Return last N lines.

        Returns:
            List of JSON log objects.
        """
        if container_id not in self._logs:
            return []

        entries = self._logs[container_id]

        if tail is not None:
            entries = entries[-tail:]

        results = []
        for entry in entries:
            results.append(
                {
                    "log": entry.message,
                    "stream": entry.source,
                    "time": entry.timestamp.isoformat(),
                    "level": entry.level.value,
                }
            )

        return results

    def rotate_logs(self, container_id: str) -> None:
        """Rotate container logs.

        Args:
            container_id: Container ID.
        """
        if container_id not in self._logs:
            return

        # Simulate log rotation by limiting history
        if len(self._logs[container_id]) > 10000:
            self._logs[container_id] = self._logs[container_id][-5000:]

    def clear_logs(self, container_id: str) -> None:
        """Clear container logs.

        Args:
            container_id: Container ID.
        """
        if container_id in self._logs:
            self._logs[container_id] = []

    def get_log_size(self, container_id: str) -> int:
        """Get approximate log size.

        Args:
            container_id: Container ID.

        Returns:
            Approximate size in bytes.
        """
        if container_id not in self._logs:
            return 0

        total_size = sum(len(entry.message.encode()) for entry in self._logs[container_id])
        return total_size

    def filter_logs(
        self,
        container_id: str,
        pattern: str,
        case_sensitive: bool = False,
    ) -> list[str]:
        """Filter logs by pattern.

        Args:
            container_id: Container ID.
            pattern: Search pattern.
            case_sensitive: Case sensitive search.

        Returns:
            Matching log lines.
        """
        if container_id not in self._logs:
            return []

        entries = self._logs[container_id]
        results = []

        for entry in entries:
            message = entry.message
            search_pattern = pattern

            if not case_sensitive:
                message = message.lower()
                search_pattern = search_pattern.lower()

            if search_pattern in message:
                results.append(entry.message)

        return results

    def get_logs_by_level(
        self,
        container_id: str,
        level: LogLevel,
    ) -> list[str]:
        """Get logs filtered by level.

        Args:
            container_id: Container ID.
            level: Log level.

        Returns:
            Matching log lines.
        """
        if container_id not in self._logs:
            return []

        entries = self._logs[container_id]
        results = []

        for entry in entries:
            if entry.level == level:
                results.append(entry.message)

        return results

    def export_logs(
        self,
        container_id: str,
        format: str = "json",
    ) -> str:
        """Export logs in specified format.

        Args:
            container_id: Container ID.
            format: Export format (json, text).

        Returns:
            Exported logs string.
        """
        if format == "json":
            logs = self.get_logs_json(container_id)
            return json.dumps(logs, indent=2)
        else:
            logs = self.read_logs(container_id, timestamps=True)
            return "\n".join(logs)

    def stats(self) -> dict:
        """Get logging statistics.

        Returns:
            Statistics dictionary.
        """
        total_entries = sum(len(entries) for entries in self._logs.values())
        total_size = sum(self.get_log_size(cid) for cid in self._logs)

        return {
            "containers": len(self._logs),
            "total_entries": total_entries,
            "total_size_bytes": total_size,
            "average_size_bytes": (total_size // total_entries if total_entries > 0 else 0),
        }
