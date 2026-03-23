"""Log collection and normalization engine.

Collects logs from multiple sources (syslog, Windows Event Log, CEF, JSON),
normalizes to common schema, enriches with contextual data, and monitors
source health.
"""

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.siem._exceptions import (
    EnrichmentException,
    ParsingException,
)
from thomas.marketplace.siem._types import (
    Asset,
    EventCategory,
    EventSeverity,
    SecurityEvent,
)


@dataclass
class SourceHealth:
    """Health metrics for a log source.

    Attributes:
        source_name: Name of the log source.
        last_event_time: Timestamp of last received event.
        event_count: Total events received from this source.
        error_count: Total parse errors.
        latency_ms: Average latency in milliseconds.
        is_healthy: Current health status.
    """

    source_name: str
    last_event_time: datetime | None = None
    event_count: int = 0
    error_count: int = 0
    latency_ms: float = 0.0
    is_healthy: bool = True

    def check_health(self, timeout_seconds: int = 300) -> bool:
        """Check if source is still healthy based on timeout."""
        if self.last_event_time is None:
            self.is_healthy = False
            return False

        time_since_last = datetime.utcnow() - self.last_event_time
        if time_since_last > timedelta(seconds=timeout_seconds):
            self.is_healthy = False
            return False

        self.is_healthy = True
        return True


class SyslogParser:
    """RFC 5424 syslog parser with structured data support."""

    # RFC 5424 regex pattern
    SYSLOG_PATTERN = re.compile(
        r"^<(\d+)>(\d+)\s+"
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+"
        r"([^\s]+)\s+"
        r"([^\s\[]+)"
        r"(?:\[(\d+)\])?"
        r"(?:\s+(-\s+|(.+)))?",
        re.DOTALL,
    )

    @staticmethod
    def parse(raw_log: str, source: str = "syslog") -> SecurityEvent:
        """Parse RFC 5424 syslog entry.

        Args:
            raw_log: Raw syslog message.
            source: Log source identifier.

        Returns:
            Normalized SecurityEvent.

        Raises:
            ParsingException: If parsing fails.
        """
        match = SyslogParser.SYSLOG_PATTERN.match(raw_log)
        if not match:
            raise ParsingException(f"Invalid syslog format: {raw_log}")

        priority = int(match.group(1))
        severity = EventSeverity.INFO
        if priority >= 24:
            severity = EventSeverity.CRITICAL
        elif priority >= 20:
            severity = EventSeverity.HIGH
        elif priority >= 16:
            severity = EventSeverity.MEDIUM
        elif priority >= 12:
            severity = EventSeverity.LOW

        try:
            timestamp = datetime.fromisoformat(match.group(3).replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.utcnow()

        hostname = match.group(4)
        process = match.group(5)
        pid = match.group(6)
        message = match.group(8) or ""

        event = SecurityEvent(
            timestamp=timestamp,
            source=source,
            severity=severity,
            host=hostname,
            message=message,
            raw_data=raw_log,
            category=EventCategory.NETWORK,
        )

        event.metadata = {
            "process": process,
            "pid": pid,
            "priority": priority,
        }

        return event


class WindowsEventLogParser:
    """Windows Event Log XML parser."""

    @staticmethod
    def parse(xml_entry: str, source: str = "windows_events") -> SecurityEvent:
        """Parse Windows Event Log XML entry.

        Args:
            xml_entry: Raw XML event entry.
            source: Log source identifier.

        Returns:
            Normalized SecurityEvent.

        Raises:
            ParsingException: If parsing fails.
        """
        event = SecurityEvent(source=source, category=EventCategory.ENDPOINT)

        # Extract event ID
        event_id_match = re.search(r"<EventID>(\d+)</EventID>", xml_entry)
        if event_id_match:
            event_code = int(event_id_match.group(1))
            event.metadata["event_code"] = event_code
            # Map Windows event codes to severity
            if event_code in [4625, 4771, 4768]:  # Failed auth
                event.severity = EventSeverity.MEDIUM
                event.category = EventCategory.AUTHENTICATION
            elif event_code == 4720:  # New user
                event.severity = EventSeverity.LOW
                event.category = EventCategory.AUTHORIZATION

        # Extract timestamp
        time_match = re.search(r"<System><EventID>.*?<TimeCreated SystemTime='([^']+)'", xml_entry, re.DOTALL)
        if not time_match:
            time_match = re.search(r"SystemTime='([^']+)'", xml_entry)
        if time_match:
            try:
                event.timestamp = datetime.fromisoformat(time_match.group(1).replace("Z", "+00:00"))
            except ValueError:
                pass

        # Extract computer name
        computer_match = re.search(r"<Computer>([^<]+)</Computer>", xml_entry)
        if computer_match:
            event.host = computer_match.group(1)

        # Extract user
        user_match = re.search(r"<Data Name='TargetUserName'>([^<]+)</Data>", xml_entry)
        if user_match:
            event.user = user_match.group(1)

        event.message = xml_entry[:200]
        event.raw_data = xml_entry

        return event


class CEFParser:
    """Common Event Format (CEF) parser."""

    @staticmethod
    def parse(cef_message: str, source: str = "cef") -> SecurityEvent:
        """Parse CEF format log entry.

        Args:
            cef_message: Raw CEF message.
            source: Log source identifier.

        Returns:
            Normalized SecurityEvent.

        Raises:
            ParsingException: If parsing fails.
        """
        if not cef_message.startswith("CEF:"):
            raise ParsingException(f"Invalid CEF format: {cef_message}")

        event = SecurityEvent(source=source)

        # Parse CEF header: CEF:Version|Device Vendor|Device Product|Device Version|...
        parts = cef_message.split("|", 7)
        if len(parts) < 7:
            raise ParsingException(f"Incomplete CEF header: {cef_message}")

        event.metadata = {
            "vendor": parts[1],
            "product": parts[2],
            "version": parts[3],
            "event_type": parts[4],
            "event_name": parts[5],
            "severity": int(parts[6]) if parts[6].isdigit() else 5,
        }

        # Map CEF severity to EventSeverity
        cef_severity = event.metadata["severity"]
        if cef_severity >= 8:
            event.severity = EventSeverity.CRITICAL
        elif cef_severity >= 6:
            event.severity = EventSeverity.HIGH
        elif cef_severity >= 4:
            event.severity = EventSeverity.MEDIUM
        elif cef_severity >= 2:
            event.severity = EventSeverity.LOW
        else:
            event.severity = EventSeverity.INFO

        # Parse extensions (key=value pairs)
        if len(parts) > 7:
            extensions = parts[7]
            for kv_pair in re.finditer(r"(\w+)=([^\s=]+(?:\s+(?![\w]+=))*)", extensions):
                key, value = kv_pair.groups()
                if key == "src":
                    event.src_ip = value
                elif key == "dst":
                    event.dst_ip = value
                elif key == "spt":
                    try:
                        event.src_port = int(value)
                    except ValueError:
                        pass
                elif key == "dpt":
                    try:
                        event.dst_port = int(value)
                    except ValueError:
                        pass
                elif key == "proto":
                    event.protocol = value
                elif key == "cs1":
                    event.user = value
                else:
                    event.metadata[key] = value

        event.message = cef_message[:500]
        event.raw_data = cef_message

        return event


class JSONLogParser:
    """JSON log format parser."""

    @staticmethod
    def parse(json_str: str, source: str = "json_log") -> SecurityEvent:
        """Parse JSON log entry.

        Args:
            json_str: Raw JSON log string.
            source: Log source identifier.

        Returns:
            Normalized SecurityEvent.

        Raises:
            ParsingException: If parsing fails.
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ParsingException(f"Invalid JSON: {e}")

        event = SecurityEvent(source=source)

        # Try to extract common fields
        if isinstance(data, dict):
            if "timestamp" in data:
                try:
                    event.timestamp = datetime.fromisoformat(str(data["timestamp"]))
                except ValueError:
                    pass

            if "severity" in data:
                severity_str = str(data["severity"]).upper()
                try:
                    event.severity = EventSeverity[severity_str]
                except KeyError:
                    pass

            if "host" in data:
                event.host = str(data["host"])

            if "src_ip" in data or "source_ip" in data:
                event.src_ip = str(data.get("src_ip") or data.get("source_ip"))

            if "dst_ip" in data or "dest_ip" in data:
                event.dst_ip = str(data.get("dst_ip") or data.get("dest_ip"))

            if "user" in data or "username" in data:
                event.user = str(data.get("user") or data.get("username"))

            if "message" in data:
                event.message = str(data["message"])

            if "category" in data:
                try:
                    event.category = EventCategory[str(data["category"]).upper()]
                except KeyError:
                    pass

            event.metadata = {
                k: v
                for k, v in data.items()
                if k
                not in [
                    "timestamp",
                    "severity",
                    "host",
                    "src_ip",
                    "source_ip",
                    "dst_ip",
                    "dest_ip",
                    "user",
                    "username",
                    "message",
                    "category",
                ]
            }

        event.raw_data = json_str

        return event


class EventEnricher:
    """Enriches events with contextual data."""

    def __init__(self, assets: dict[str, Asset] | None = None):
        """Initialize enricher.

        Args:
            assets: Dictionary of known assets by hostname/IP.
        """
        self.assets = assets or {}
        self.geo_cache: dict[str, dict[str, str]] = {}

    def enrich(self, event: SecurityEvent) -> None:
        """Enrich event with contextual data.

        Args:
            event: Event to enrich.

        Raises:
            EnrichmentException: If enrichment fails.
        """
        self._add_asset_info(event)
        self._add_geo_info(event)
        self._add_protocol_info(event)

    def _add_asset_info(self, event: SecurityEvent) -> None:
        """Add asset information to event."""
        for identifier in [event.host, event.src_ip, event.dst_ip]:
            if identifier and identifier in self.assets:
                asset = self.assets[identifier]
                event.enrichment["asset"] = {
                    "hostname": asset.hostname,
                    "criticality": asset.criticality,
                    "owner": asset.owner,
                    "type": asset.asset_type,
                }
                break

    def _add_geo_info(self, event: SecurityEvent) -> None:
        """Add geolocation information to event."""
        for ip in [event.src_ip, event.dst_ip]:
            if ip and self._is_valid_ip(ip):
                if ip not in self.geo_cache:
                    # Simulate geolocation lookup
                    self.geo_cache[ip] = self._lookup_geo(ip)
                event.enrichment[f"geo_{ip}"] = self.geo_cache[ip]

    def _add_protocol_info(self, event: SecurityEvent) -> None:
        """Add protocol-specific information."""
        if event.protocol:
            event.enrichment["protocol_info"] = {
                "name": event.protocol.upper(),
                "is_encrypted": event.protocol.upper() in ["HTTPS", "TLS", "SSH"],
            }

    @staticmethod
    def _is_valid_ip(ip_str: str) -> bool:
        """Check if string is valid IP address."""
        try:
            ipaddress.ip_address(ip_str)
            return True
        except ValueError:
            return False

    @staticmethod
    def _lookup_geo(ip: str) -> dict[str, str]:
        """Simulate geolocation lookup for IP."""
        # In production, this would call a real geolocation API
        if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
            return {"location": "Internal", "country": "XX"}
        return {"location": "Unknown", "country": "XX"}


class LogCollector:
    """Main log collection and normalization engine.

    Manages collection from multiple sources, parsing, normalization,
    enrichment, and source health monitoring.
    """

    def __init__(self, assets: dict[str, Asset] | None = None):
        """Initialize log collector.

        Args:
            assets: Dictionary of known assets for enrichment.
        """
        self.enricher = EventEnricher(assets)
        self.source_health: dict[str, SourceHealth] = {}
        self.collected_events: list[SecurityEvent] = []
        self.metrics: dict[str, int] = {
            "total_events": 0,
            "total_errors": 0,
            "events_per_second": 0,
        }

    def collect_syslog(self, raw_log: str) -> SecurityEvent | None:
        """Collect and normalize syslog entry.

        Args:
            raw_log: Raw syslog message.

        Returns:
            Normalized SecurityEvent or None if parsing fails.
        """
        try:
            event = SyslogParser.parse(raw_log)
            self._post_process(event)
            return event
        except ParsingException:
            self._record_error("syslog")
            return None

    def collect_windows_event(self, xml_entry: str) -> SecurityEvent | None:
        """Collect and normalize Windows Event Log entry.

        Args:
            xml_entry: Raw XML event entry.

        Returns:
            Normalized SecurityEvent or None if parsing fails.
        """
        try:
            event = WindowsEventLogParser.parse(xml_entry)
            self._post_process(event)
            return event
        except ParsingException:
            self._record_error("windows_events")
            return None

    def collect_cef(self, cef_message: str) -> SecurityEvent | None:
        """Collect and normalize CEF log entry.

        Args:
            cef_message: Raw CEF formatted message.

        Returns:
            Normalized SecurityEvent or None if parsing fails.
        """
        try:
            event = CEFParser.parse(cef_message)
            self._post_process(event)
            return event
        except ParsingException:
            self._record_error("cef")
            return None

    def collect_json(self, json_str: str) -> SecurityEvent | None:
        """Collect and normalize JSON log entry.

        Args:
            json_str: Raw JSON formatted log.

        Returns:
            Normalized SecurityEvent or None if parsing fails.
        """
        try:
            event = JSONLogParser.parse(json_str)
            self._post_process(event)
            return event
        except ParsingException:
            self._record_error("json_log")
            return None

    def _post_process(self, event: SecurityEvent) -> None:
        """Post-process event: enrich and update metrics."""
        try:
            self.enricher.enrich(event)
        except EnrichmentException:
            pass  # Continue even if enrichment fails

        self.collected_events.append(event)
        self.metrics["total_events"] += 1

        # Update source health
        if event.source not in self.source_health:
            self.source_health[event.source] = SourceHealth(event.source)

        health = self.source_health[event.source]
        health.last_event_time = datetime.utcnow()
        health.event_count += 1

    def _record_error(self, source: str) -> None:
        """Record parsing error for a source."""
        if source not in self.source_health:
            self.source_health[source] = SourceHealth(source)

        health = self.source_health[source]
        health.error_count += 1
        self.metrics["total_errors"] += 1

    def get_source_health(self, source: str | None = None) -> dict[str, SourceHealth]:
        """Get health status of log sources.

        Args:
            source: Specific source to check, or None for all.

        Returns:
            Dictionary of source health metrics.
        """
        if source:
            if source in self.source_health:
                self.source_health[source].check_health()
                return {source: self.source_health[source]}
            return {}

        for health in self.source_health.values():
            health.check_health()

        return self.source_health

    def get_events(
        self,
        source: str | None = None,
        severity: EventSeverity | None = None,
        category: EventCategory | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[SecurityEvent]:
        """Retrieve collected events with optional filtering.

        Args:
            source: Filter by log source.
            severity: Filter by severity or higher.
            category: Filter by event category.
            start_time: Filter events after this time.
            end_time: Filter events before this time.

        Returns:
            List of matching SecurityEvents.
        """
        results = self.collected_events

        if source:
            results = [e for e in results if e.source == source]

        if severity:
            results = [e for e in results if e.severity >= severity]

        if category:
            results = [e for e in results if e.category == category]

        if start_time:
            results = [e for e in results if e.timestamp >= start_time]

        if end_time:
            results = [e for e in results if e.timestamp <= end_time]

        return results

    def update_metrics(self) -> dict[str, Any]:
        """Calculate and return current collection metrics.

        Returns:
            Dictionary of metrics including events per second.
        """
        if len(self.collected_events) > 1:
            time_span = self.collected_events[-1].timestamp - self.collected_events[0].timestamp
            if time_span.total_seconds() > 0:
                self.metrics["events_per_second"] = int(len(self.collected_events) / time_span.total_seconds())

        return self.metrics.copy()

    def clear_events(self) -> None:
        """Clear collected events (for testing/reset)."""
        self.collected_events.clear()
