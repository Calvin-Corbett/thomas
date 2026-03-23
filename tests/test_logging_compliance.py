"""Tests for compliance and regulatory features."""

import unittest
from datetime import datetime, timedelta

from thomas.marketplace.logging_framework.compliance import (
    AuditLogger,
    ComplianceReporter,
    GDPRCompliance,
    LegalHold,
    PIIDetector,
    RetentionEnforcer,
)
from thomas.marketplace.logging_framework.handlers import MemoryHandler
from thomas.marketplace.logging_framework.logger import Logger


class TestRetentionEnforcer(unittest.TestCase):
    """Test cases for RetentionEnforcer."""

    def test_retention_policy(self) -> None:
        """Test retention policy enforcement."""
        enforcer = RetentionEnforcer(retention_days=30)

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Recent message")
        record = handler.get_records()[0]

        # Recent record should not be deleted
        self.assertFalse(enforcer.should_delete(record))

    def test_retention_expiry(self) -> None:
        """Test records older than retention are expired."""
        enforcer = RetentionEnforcer(retention_days=1)

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")
        record = handler.get_records()[0]

        # Manually set timestamp to old date
        record.timestamp = datetime.now() - timedelta(days=40)

        self.assertTrue(enforcer.should_delete(record))

    def test_apply_retention(self) -> None:
        """Test applying retention policy to record list."""
        enforcer = RetentionEnforcer(retention_days=1)

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        for i in range(5):
            logger.info(f"Message {i}")

        records = handler.get_records()
        # Age one record
        records[0].timestamp = datetime.now() - timedelta(days=40)

        filtered = enforcer.apply_retention(records)

        self.assertEqual(len(filtered), 4)
        self.assertNotIn(records[0], filtered)


class TestAuditLogger(unittest.TestCase):
    """Test cases for AuditLogger."""

    def test_audit_log_event(self) -> None:
        """Test logging audit event."""
        audit = AuditLogger()

        hash1 = audit.log_event("user_login", "User john logged in")
        self.assertIsNotNone(hash1)
        self.assertEqual(len(hash1), 64)  # SHA256 hex

    def test_audit_trail_chain(self) -> None:
        """Test hash chain in audit trail."""
        audit = AuditLogger()

        hash1 = audit.log_event("event1", "First event")
        hash2 = audit.log_event("event2", "Second event")

        trail = audit.get_audit_trail()
        self.assertEqual(len(trail), 2)
        self.assertEqual(trail[1]["previous_hash"], hash1)

    def test_audit_integrity_verification(self) -> None:
        """Test verifying audit trail integrity."""
        audit = AuditLogger()

        audit.log_event("event1", "First")
        audit.log_event("event2", "Second")

        self.assertTrue(audit.verify_integrity())

    def test_audit_tampering_detection(self) -> None:
        """Test detecting tampering in audit trail."""
        audit = AuditLogger()

        audit.log_event("event1", "First")
        audit.log_event("event2", "Second")

        # Tamper with trail
        audit.audit_trail[0]["description"] = "Modified"

        self.assertFalse(audit.verify_integrity())


class TestPIIDetector(unittest.TestCase):
    """Test cases for PIIDetector."""

    def test_detect_email(self) -> None:
        """Test detecting email addresses."""
        detector = PIIDetector()

        text = "Contact john@example.com for support"
        pii = detector.detect_pii(text)

        self.assertIn("email", pii)
        self.assertIn("john@example.com", pii["email"])

    def test_detect_phone(self) -> None:
        """Test detecting phone numbers."""
        detector = PIIDetector()

        text = "Call 555-123-4567 for help"
        pii = detector.detect_pii(text)

        self.assertIn("phone", pii)

    def test_detect_ssn(self) -> None:
        """Test detecting social security numbers."""
        detector = PIIDetector()

        text = "SSN: 123-45-6789"
        pii = detector.detect_pii(text)

        self.assertIn("ssn", pii)

    def test_detect_credit_card(self) -> None:
        """Test detecting credit card numbers."""
        detector = PIIDetector()

        text = "Card: 4532-1234-5678-9010"
        pii = detector.detect_pii(text)

        self.assertIn("credit_card", pii)

    def test_detect_pii_in_record(self) -> None:
        """Test detecting PII in log record."""
        detector = PIIDetector()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("User john@example.com logged in")
        record = handler.get_records()[0]

        pii = detector.detect_in_record(record)

        self.assertIn("email", pii)

    def test_mask_pii(self) -> None:
        """Test masking PII in text."""
        detector = PIIDetector()

        text = "Email: john@example.com Phone: 555-123-4567"
        masked = detector.mask_pii(text)

        self.assertNotIn("john@example.com", masked)
        self.assertNotIn("555-123-4567", masked)
        self.assertIn("****", masked)


class TestGDPRCompliance(unittest.TestCase):
    """Test cases for GDPR compliance."""

    def test_find_subject_logs(self) -> None:
        """Test finding logs for a data subject."""
        gdpr = GDPRCompliance()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("User john.doe@example.com logged in")
        logger.info("User jane@example.com logged in")
        logger.info("System backup completed")

        records = handler.get_records()
        subject_logs = gdpr.find_subject_logs(records, "john.doe")

        self.assertEqual(len(subject_logs), 1)
        self.assertIn("john.doe", subject_logs[0].message)

    def test_data_export_json(self) -> None:
        """Test exporting data in JSON format."""
        gdpr = GDPRCompliance()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test log 1")
        logger.info("Test log 2")

        records = handler.get_records()
        export = gdpr.generate_data_export(records, format="json")

        self.assertIn("Test log 1", export)
        self.assertIn("Test log 2", export)
        import json

        data = json.loads(export)
        self.assertEqual(len(data), 2)

    def test_data_export_csv(self) -> None:
        """Test exporting data in CSV format."""
        gdpr = GDPRCompliance()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test log 1")
        logger.info("Test log 2")

        records = handler.get_records()
        export = gdpr.generate_data_export(records, format="csv")

        self.assertIn("Test log 1", export)
        self.assertIn("Test log 2", export)
        self.assertIn("timestamp", export)


class TestComplianceReporter(unittest.TestCase):
    """Test cases for ComplianceReporter."""

    def test_summary_report(self) -> None:
        """Test generating summary report."""
        reporter = ComplianceReporter()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")

        records = handler.get_records()
        report = reporter.generate_report(records, report_type="summary")

        self.assertEqual(report["total_records"], 3)
        self.assertIn("level_distribution", report)
        self.assertIn("logger_distribution", report)

    def test_detailed_report(self) -> None:
        """Test generating detailed report."""
        reporter = ComplianceReporter()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("User john@example.com logged in")

        records = handler.get_records()
        report = reporter.generate_report(records, report_type="detailed")

        self.assertIn("pii_detected", report)

    def test_report_time_range(self) -> None:
        """Test report includes time range."""
        reporter = ComplianceReporter()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")

        records = handler.get_records()
        report = reporter.generate_report(records)

        self.assertIn("time_range", report)
        self.assertIn("start", report["time_range"])
        self.assertIn("end", report["time_range"])


class TestLegalHold(unittest.TestCase):
    """Test cases for LegalHold."""

    def test_add_legal_hold(self) -> None:
        """Test adding a legal hold."""
        hold = LegalHold()

        start = datetime.now()
        end = datetime.now() + timedelta(days=365)

        hold.add_hold("hold-001", start, end)

        active_holds = hold.get_active_holds()
        self.assertIn("hold-001", active_holds)

    def test_is_under_hold(self) -> None:
        """Test checking if record is under hold."""
        hold = LegalHold()

        start = datetime.now() - timedelta(days=1)
        end = datetime.now() + timedelta(days=1)

        hold.add_hold("hold-001", start, end)

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")
        record = handler.get_records()[0]

        # Record should be under hold
        self.assertTrue(hold.is_under_hold(record))

    def test_record_outside_hold(self) -> None:
        """Test record outside hold period."""
        hold = LegalHold()

        old_start = datetime.now() - timedelta(days=100)
        old_end = datetime.now() - timedelta(days=50)

        hold.add_hold("hold-001", old_start, old_end)

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")
        record = handler.get_records()[0]

        # Record should not be under hold
        self.assertFalse(hold.is_under_hold(record))

    def test_remove_hold(self) -> None:
        """Test removing a legal hold."""
        hold = LegalHold()

        start = datetime.now()
        end = datetime.now() + timedelta(days=365)

        hold.add_hold("hold-001", start, end)
        hold.remove_hold("hold-001")

        active_holds = hold.get_active_holds()
        self.assertNotIn("hold-001", active_holds)


if __name__ == "__main__":
    unittest.main()
