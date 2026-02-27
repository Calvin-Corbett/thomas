"""Tests for SIEM log collector module."""

from datetime import datetime, timedelta

import pytest

from thomas.siem._exceptions import ParsingException
from thomas.siem._types import Asset, EventCategory, EventSeverity
from thomas.siem.collector import (
    CEFParser,
    EventEnricher,
    JSONLogParser,
    LogCollector,
    SourceHealth,
    SyslogParser,
    WindowsEventLogParser,
)


class TestSyslogParser:
    """Tests for RFC 5424 syslog parser."""

    def test_parse_valid_syslog(self):
        """Test parsing valid syslog entry."""
        raw = "<14>1 2024-01-15T10:30:45.123Z host.example.com sshd[1234] - SSH login attempt"
        event = SyslogParser.parse(raw)

        assert event.host == "host.example.com"
        assert event.message == "SSH login attempt"
        assert event.metadata["process"] == "sshd"
        assert event.metadata["pid"] == "1234"

    def test_parse_invalid_syslog_raises_exception(self):
        """Test invalid syslog raises exception."""
        with pytest.raises(ParsingException):
            SyslogParser.parse("invalid syslog message")

    def test_severity_mapping(self):
        """Test priority to severity mapping."""
        # Critical priority (23)
        event = SyslogParser.parse("<23>1 2024-01-15T10:30:45Z host.example.com test - message")
        assert event.severity == EventSeverity.CRITICAL

        # High priority (20)
        event = SyslogParser.parse("<20>1 2024-01-15T10:30:45Z host.example.com test - message")
        assert event.severity == EventSeverity.HIGH


class TestWindowsEventLogParser:
    """Tests for Windows Event Log parser."""

    def test_parse_windows_event(self):
        """Test parsing Windows event XML."""
        xml = """<System><EventID>4625</EventID>
                 <TimeCreated SystemTime='2024-01-15T10:30:45Z'/>
                 <Computer>WORKSTATION01</Computer></System>
                 <EventData><Data Name='TargetUserName'>admin</Data></EventData>"""

        event = WindowsEventLogParser.parse(xml)

        assert event.host == "WORKSTATION01"
        assert event.user == "admin"
        assert event.category == EventCategory.AUTHENTICATION
        assert event.severity == EventSeverity.MEDIUM

    def test_parse_event_with_missing_fields(self):
        """Test parsing event with missing optional fields."""
        xml = "<System><EventID>1000</EventID></System>"
        event = WindowsEventLogParser.parse(xml)

        assert event.source == "windows_events"
        assert event.metadata["event_code"] == 1000


class TestCEFParser:
    """Tests for CEF format parser."""

    def test_parse_valid_cef(self):
        """Test parsing valid CEF message."""
        cef = "CEF:0|Vendor|Product|1.0|100|Alert Title|5|src=192.168.1.10 dst=10.0.0.1 spt=12345 dpt=80 proto=TCP"
        event = CEFParser.parse(cef)

        assert event.src_ip == "192.168.1.10"
        assert event.dst_ip == "10.0.0.1"
        assert event.protocol == "TCP"
        assert event.severity == EventSeverity.HIGH

    def test_parse_invalid_cef_raises_exception(self):
        """Test invalid CEF raises exception."""
        with pytest.raises(ParsingException):
            CEFParser.parse("Not CEF format")

    def test_cef_severity_mapping(self):
        """Test CEF severity mapping."""
        # Severity 8
        cef = "CEF:0|Test|Test|1.0|1|Title|8|src=1.1.1.1"
        event = CEFParser.parse(cef)
        assert event.severity == EventSeverity.CRITICAL


class TestJSONLogParser:
    """Tests for JSON log parser."""

    def test_parse_valid_json(self):
        """Test parsing valid JSON log."""
        json_str = (
            '{"timestamp": "2024-01-15T10:30:45Z", "severity": "HIGH", "host": "server1", "message": "Test event"}'
        )
        event = JSONLogParser.parse(json_str)

        assert event.host == "server1"
        assert event.severity == EventSeverity.HIGH
        assert event.message == "Test event"

    def test_parse_json_with_ips(self):
        """Test parsing JSON with IP fields."""
        json_str = '{"src_ip": "192.168.1.1", "dst_ip": "10.0.0.1", "source_ip": "192.168.1.2"}'
        event = JSONLogParser.parse(json_str)

        assert event.src_ip == "192.168.1.1"
        assert event.dst_ip == "10.0.0.1"

    def test_parse_invalid_json_raises_exception(self):
        """Test invalid JSON raises exception."""
        with pytest.raises(ParsingException):
            JSONLogParser.parse("{invalid json}")


class TestEventEnricher:
    """Tests for event enrichment."""

    def test_enrich_with_asset_info(self):
        """Test asset information enrichment."""
        asset = Asset(
            hostname="server1",
            criticality=5,
            owner="Security Team",
            asset_type="server",
        )
        enricher = EventEnricher(assets={"server1": asset})

        from thomas.siem._types import SecurityEvent

        event = SecurityEvent(host="server1", message="Test")

        enricher.enrich(event)

        assert "asset" in event.enrichment
        assert event.enrichment["asset"]["owner"] == "Security Team"

    def test_enrich_with_geo_info(self):
        """Test geolocation enrichment."""
        enricher = EventEnricher()

        from thomas.siem._types import SecurityEvent

        event = SecurityEvent(src_ip="8.8.8.8", message="Test")

        enricher.enrich(event)

        assert any("geo_" in key for key in event.enrichment.keys())

    def test_enrich_with_protocol_info(self):
        """Test protocol enrichment."""
        enricher = EventEnricher()

        from thomas.siem._types import SecurityEvent

        event = SecurityEvent(protocol="HTTPS", message="Test")

        enricher.enrich(event)

        assert "protocol_info" in event.enrichment
        assert event.enrichment["protocol_info"]["is_encrypted"] is True


class TestLogCollector:
    """Tests for main log collector."""

    def test_collect_syslog(self):
        """Test collecting syslog entry."""
        collector = LogCollector()
        raw = "<14>1 2024-01-15T10:30:45Z host1 test - message"

        event = collector.collect_syslog(raw)

        assert event is not None
        assert event.host == "host1"
        assert collector.metrics["total_events"] == 1

    def test_collect_multiple_events(self):
        """Test collecting multiple events."""
        collector = LogCollector()

        collector.collect_syslog("<14>1 2024-01-15T10:30:45Z host1 test - msg1")
        collector.collect_syslog("<14>1 2024-01-15T10:30:46Z host2 test - msg2")
        collector.collect_json('{"timestamp": "2024-01-15T10:30:47Z", "message": "msg3"}')

        assert collector.metrics["total_events"] == 3

    def test_source_health_tracking(self):
        """Test source health monitoring."""
        collector = LogCollector()
        collector.collect_syslog("<14>1 2024-01-15T10:30:45Z host1 test - msg")

        health = collector.get_source_health("syslog")
        assert "syslog" in health
        assert health["syslog"].is_healthy is True

    def test_parse_error_tracking(self):
        """Test error tracking for parse failures."""
        collector = LogCollector()

        result = collector.collect_syslog("invalid")
        assert result is None
        assert collector.metrics["total_errors"] == 1

    def test_get_events_filtered(self):
        """Test retrieving events with filters."""
        collector = LogCollector()

        collector.collect_syslog("<26>1 2024-01-15T10:30:45Z host1 test - HIGH msg")
        collector.collect_syslog("<14>1 2024-01-15T10:30:46Z host2 test - LOW msg")

        high_events = collector.get_events(severity=EventSeverity.HIGH)
        assert len(high_events) >= 1

    def test_metrics_calculation(self):
        """Test metrics calculation."""
        collector = LogCollector()

        collector.collect_syslog("<14>1 2024-01-15T10:30:45Z host1 test - msg")
        collector.collect_syslog("<14>1 2024-01-15T10:30:46Z host2 test - msg")

        metrics = collector.update_metrics()

        assert metrics["total_events"] == 2


class TestSourceHealth:
    """Tests for source health tracking."""

    def test_health_check_timeout(self):
        """Test health check detects timeout."""
        health = SourceHealth("test_source")

        # Set last event time to past
        health.last_event_time = datetime.utcnow() - timedelta(seconds=400)
        health.is_healthy = True

        # Check health with 300 second timeout
        is_healthy = health.check_health(timeout_seconds=300)

        assert is_healthy is False
        assert health.is_healthy is False

    def test_health_check_active_source(self):
        """Test health check for active source."""
        health = SourceHealth("test_source")
        health.last_event_time = datetime.utcnow()

        is_healthy = health.check_health(timeout_seconds=300)

        assert is_healthy is True
