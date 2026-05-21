"""Compliance and regulatory logging features."""

import hashlib
import re
import threading
from datetime import datetime
from typing import Any

from thomas.marketplace.logging_framework._exceptions import ComplianceError
from thomas.marketplace.logging_framework._types import LogRecord


class RetentionEnforcer:
    """Enforces log retention policies."""

    def __init__(self, retention_days: int = 30) -> None:
        """Initialize retention enforcer.

        Args:
            retention_days: Days to retain logs
        """
        self.retention_days = retention_days
        self._lock = threading.RLock()

    def should_delete(self, record: LogRecord) -> bool:
        """Determine if a record should be deleted.

        Args:
            record: Log record to evaluate

        Returns:
            True if record is expired
        """
        age = datetime.now() - record.timestamp
        return age.days > self.retention_days

    def apply_retention(self, records: list[LogRecord]) -> list[LogRecord]:
        """Filter records based on retention policy.

        Args:
            records: Log records to filter

        Returns:
            Records that should be kept
        """
        with self._lock:
            return [r for r in records if not self.should_delete(r)]


class AuditLogger:
    """Tamper-evident audit logging with hash chaining."""

    def __init__(self) -> None:
        """Initialize audit logger."""
        self.audit_trail: list[dict[str, Any]] = []
        self.last_hash = "0" * 64
        self._lock = threading.RLock()

    def log_event(
        self,
        event_type: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Log an audit event with hash chain.

        Args:
            event_type: Type of event
            description: Event description
            metadata: Additional metadata

        Returns:
            Hash of this entry
        """
        with self._lock:
            metadata_obj = metadata or {}
            entry = {
                "timestamp": datetime.now().isoformat(),
                "type": event_type,
                "description": description,
                "metadata": metadata_obj,
                "previous_hash": self.last_hash,
            }

            # Calculate hash including previous hash for chain
            metadata_repr = repr(sorted(metadata_obj.items()))
            entry_str = f"{entry['timestamp']}{event_type}{description}{metadata_repr}{self.last_hash}"
            entry_hash = hashlib.sha256(entry_str.encode()).hexdigest()
            entry["hash"] = entry_hash

            self.audit_trail.append(entry)
            self.last_hash = entry_hash

            return entry_hash

    def verify_integrity(self) -> bool:
        """Verify audit trail integrity.

        Returns:
            True if hash chain is intact
        """
        with self._lock:
            if not self.audit_trail:
                return True

            prev_hash = "0" * 64
            for entry in self.audit_trail:
                if entry.get("previous_hash") != prev_hash:
                    return False

                metadata_obj = entry.get("metadata") or {}
                metadata_repr = repr(sorted(metadata_obj.items()))
                entry_str = (
                    f"{entry.get('timestamp')}{entry.get('type')}{entry.get('description')}"
                    f"{metadata_repr}{entry.get('previous_hash')}"
                )
                expected_hash = hashlib.sha256(entry_str.encode()).hexdigest()
                if entry.get("hash") != expected_hash:
                    return False

                prev_hash = entry["hash"]

            if self.last_hash != prev_hash:
                return False

            return True

    def get_audit_trail(self) -> list[dict[str, Any]]:
        """Get complete audit trail.

        Returns:
            Audit trail entries
        """
        with self._lock:
            return [dict(entry) for entry in self.audit_trail]


class PIIDetector:
    """Detects personally identifiable information in logs."""

    PII_PATTERNS = {
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "credit_card": r"\b(?:\d{4}[\s-]?){3}\d{4}\b",
        "phone": r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
        "social_security": r"\b\d{3}-\d{2}-\d{4}\b",
        "passport": r"\b[A-Z]{1,2}\d{6,9}\b",
        "drivers_license": r"\b[A-Z0-9]{5,8}\b",
        "ip_address": r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",
        "ipv6": r"(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}",
        "iban": r"\b[A-Z]{2}\d{2}[A-Z0-9]{1,30}\b",
    }

    def __init__(self) -> None:
        """Initialize PII detector."""
        self.compiled_patterns = {name: re.compile(pattern) for name, pattern in self.PII_PATTERNS.items()}

    def detect_pii(self, text: str) -> dict[str, list[str]]:
        """Detect PII in text.

        Args:
            text: Text to analyze

        Returns:
            Dict mapping PII type to found values
        """
        found_pii = {}

        for pii_type, pattern in self.compiled_patterns.items():
            matches = pattern.findall(text)
            if matches:
                found_pii[pii_type] = matches

        return found_pii

    def detect_in_record(self, record: LogRecord) -> dict[str, list[str]]:
        """Detect PII in a log record.

        Args:
            record: Log record to analyze

        Returns:
            Dict mapping PII type to found values
        """
        pii_found = {}

        # Check message
        message_pii = self.detect_pii(record.message)
        for pii_type, values in message_pii.items():
            if pii_type not in pii_found:
                pii_found[pii_type] = []
            pii_found[pii_type].extend(values)

        # Check structured fields
        for field_name, field in record.fields.items():
            field_pii = self.detect_pii(str(field.value))
            for pii_type, values in field_pii.items():
                if pii_type not in pii_found:
                    pii_found[pii_type] = []
                pii_found[pii_type].extend(values)

        return pii_found

    def mask_pii(self, text: str, keep_first: int = 1) -> str:
        """Mask PII in text.

        Args:
            text: Text containing PII
            keep_first: Keep first N characters

        Returns:
            Text with PII masked
        """
        for pii_type, pattern in self.compiled_patterns.items():
            text = pattern.sub(lambda m: self._mask_value(m.group(), keep_first), text)

        return text

    @staticmethod
    def _mask_value(value: str, keep_first: int = 1) -> str:
        """Mask a value.

        Args:
            value: Value to mask
            keep_first: Keep first N characters

        Returns:
            Masked value
        """
        if len(value) <= keep_first:
            return "*" * len(value)
        return value[:keep_first] + "*" * (len(value) - keep_first)


class GDPRCompliance:
    """GDPR compliance utilities."""

    def __init__(self) -> None:
        """Initialize GDPR compliance."""
        self._lock = threading.RLock()

    def find_subject_logs(
        self,
        records: list[LogRecord],
        subject_identifier: str,
    ) -> list[LogRecord]:
        """Find all logs related to a data subject.

        Args:
            records: Log records to search
            subject_identifier: Email, ID, or name of data subject

        Returns:
            Logs mentioning the subject
        """
        subject_logs = []

        for record in records:
            # Check message
            if subject_identifier.lower() in record.message.lower():
                subject_logs.append(record)
                continue

            # Check fields
            for field in record.fields.values():
                if subject_identifier.lower() in str(field.value).lower():
                    subject_logs.append(record)
                    break

        return subject_logs

    def generate_data_export(
        self,
        records: list[LogRecord],
        format: str = "json",
    ) -> str:
        """Generate GDPR data export for a subject.

        Args:
            records: Records to export
            format: Export format ("json", "csv")

        Returns:
            Exported data as string
        """
        if format == "json":
            import json

            data = [r.to_dict() for r in records]
            return json.dumps(data, indent=2, default=str)
        elif format == "csv":
            import csv
            from io import StringIO

            output = StringIO()
            writer = csv.DictWriter(
                output,
                fieldnames=["timestamp", "level", "logger", "message"],
            )
            writer.writeheader()
            for record in records:
                writer.writerow(
                    {
                        "timestamp": record.timestamp.isoformat(),
                        "level": record.level.name,
                        "logger": record.logger_name,
                        "message": record.message,
                    }
                )
            return output.getvalue()
        else:
            raise ComplianceError(f"Unsupported format: {format}")


class ComplianceReporter:
    """Generates compliance reports."""

    def __init__(self) -> None:
        """Initialize compliance reporter."""
        self._lock = threading.RLock()

    def generate_report(
        self,
        records: list[LogRecord],
        report_type: str = "summary",
    ) -> dict[str, Any]:
        """Generate compliance report.

        Args:
            records: Log records to report on
            report_type: Type of report ("summary", "detailed", "audit")

        Returns:
            Report data
        """
        with self._lock:
            report = {
                "generated": datetime.now().isoformat(),
                "total_records": len(records),
                "time_range": {
                    "start": min(r.timestamp for r in records).isoformat() if records else None,
                    "end": max(r.timestamp for r in records).isoformat() if records else None,
                },
            }

            if report_type in ("summary", "detailed"):
                report["level_distribution"] = self._get_level_distribution(records)
                report["logger_distribution"] = self._get_logger_distribution(records)

            if report_type in ("detailed", "audit"):
                pii_detector = PIIDetector()
                pii_summary = {}
                for record in records:
                    pii = pii_detector.detect_in_record(record)
                    for pii_type, values in pii.items():
                        if pii_type not in pii_summary:
                            pii_summary[pii_type] = len(values)
                        else:
                            pii_summary[pii_type] += len(values)
                report["pii_detected"] = pii_summary

            return report

    @staticmethod
    def _get_level_distribution(records: list[LogRecord]) -> dict[str, int]:
        """Get distribution of records by level.

        Args:
            records: Log records

        Returns:
            Dict mapping level names to counts
        """
        distribution = {}
        for record in records:
            level_name = record.level.name
            distribution[level_name] = distribution.get(level_name, 0) + 1
        return distribution

    @staticmethod
    def _get_logger_distribution(records: list[LogRecord]) -> dict[str, int]:
        """Get distribution of records by logger.

        Args:
            records: Log records

        Returns:
            Dict mapping logger names to counts
        """
        distribution = {}
        for record in records:
            distribution[record.logger_name] = distribution.get(record.logger_name, 0) + 1
        return distribution


class LegalHold:
    """Manages legal holds preventing log deletion."""

    def __init__(self) -> None:
        """Initialize legal hold manager."""
        self.holds: dict[str, tuple[datetime, datetime]] = {}
        self._lock = threading.RLock()

    def add_hold(
        self,
        hold_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Add a legal hold.

        Args:
            hold_id: Unique hold identifier
            start_time: Hold start time
            end_time: Hold end time
        """
        with self._lock:
            self.holds[hold_id] = (start_time, end_time)

    def remove_hold(self, hold_id: str) -> None:
        """Remove a legal hold.

        Args:
            hold_id: Hold identifier to remove
        """
        with self._lock:
            if hold_id in self.holds:
                del self.holds[hold_id]

    def is_under_hold(self, record: LogRecord) -> bool:
        """Check if a record is under legal hold.

        Args:
            record: Log record to check

        Returns:
            True if record is under hold
        """
        with self._lock:
            for start_time, end_time in self.holds.values():
                if start_time <= record.timestamp <= end_time:
                    return True
            return False

    def get_active_holds(self) -> dict[str, tuple[str, str]]:
        """Get active legal holds.

        Returns:
            Dict mapping hold IDs to (start, end) times as ISO strings
        """
        with self._lock:
            return {hold_id: (start.isoformat(), end.isoformat()) for hold_id, (start, end) in self.holds.items()}
