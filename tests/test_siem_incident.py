"""Tests for SIEM incident management module."""

from datetime import datetime, timedelta

import pytest

from thomas.siem._types import (
    Alert,
    EventCategory,
    EventSeverity,
    Incident,
    SecurityEvent,
)
from thomas.siem.incident import (
    ImpactAssessor,
    IncidentClassifier,
    IncidentGrouper,
    IncidentManager,
)


class TestIncidentClassifier:
    """Tests for incident severity classification."""

    def test_classifier_assigns_critical_severity(self):
        """Test classification assigns critical severity."""
        alerts = [
            Alert(
                severity=EventSeverity.CRITICAL,
                events=[
                    SecurityEvent(
                        category=EventCategory.DATA_EXFILTRATION,
                        severity=EventSeverity.CRITICAL,
                    )
                ],
            )
        ]

        severity, score = IncidentClassifier.calculate_severity(alerts)

        assert severity == EventSeverity.CRITICAL

    def test_classifier_calculates_score(self):
        """Test classifier calculates numerical score."""
        alerts = [
            Alert(
                severity=EventSeverity.HIGH,
                events=[
                    SecurityEvent(
                        category=EventCategory.MALWARE,
                        severity=EventSeverity.HIGH,
                    )
                ],
            )
        ]

        severity, score = IncidentClassifier.calculate_severity(alerts)

        assert score > 0
        assert severity == EventSeverity.HIGH

    def test_classifier_boosts_for_high_impact_categories(self):
        """Test classifier boosts score for high-impact categories."""
        alerts_normal = [
            Alert(
                severity=EventSeverity.MEDIUM,
                events=[
                    SecurityEvent(
                        category=EventCategory.NETWORK,
                        severity=EventSeverity.MEDIUM,
                    )
                ],
            )
        ]

        alerts_high_impact = [
            Alert(
                severity=EventSeverity.MEDIUM,
                events=[
                    SecurityEvent(
                        category=EventCategory.C2_COMMUNICATION,
                        severity=EventSeverity.MEDIUM,
                    )
                ],
            )
        ]

        _, score_normal = IncidentClassifier.calculate_severity(alerts_normal)
        _, score_impact = IncidentClassifier.calculate_severity(alerts_high_impact)

        assert score_impact > score_normal

    def test_classifier_handles_empty_alerts(self):
        """Test classifier handles empty alert list."""
        severity, score = IncidentClassifier.calculate_severity([])

        assert severity == EventSeverity.LOW
        assert score == 1.0


class TestIncidentGrouper:
    """Tests for alert grouping into incidents."""

    def test_grouper_groups_related_alerts(self):
        """Test grouper identifies related alerts."""
        grouper = IncidentGrouper(time_window=300)

        now = datetime.utcnow()
        alerts = [
            Alert(
                created_at=now,
                events=[
                    SecurityEvent(
                        src_ip="192.168.1.1",
                        dst_ip="10.0.0.1",
                    )
                ],
            ),
            Alert(
                created_at=now + timedelta(seconds=30),
                events=[
                    SecurityEvent(
                        src_ip="192.168.1.1",
                        category=EventCategory.MALWARE,
                    )
                ],
            ),
        ]

        groups = grouper.group_alerts(alerts)

        assert len(groups) == 1

    def test_grouper_separates_unrelated_alerts(self):
        """Test grouper separates unrelated alerts."""
        grouper = IncidentGrouper(time_window=300)

        now = datetime.utcnow()
        alerts = [
            Alert(
                created_at=now,
                events=[SecurityEvent(src_ip="192.168.1.1")],
            ),
            Alert(
                created_at=now + timedelta(seconds=400),
                events=[SecurityEvent(src_ip="192.168.1.2")],
            ),
        ]

        groups = grouper.group_alerts(alerts)

        assert len(groups) == 2

    def test_grouper_respects_event_limit(self):
        """Test grouper respects max events per incident."""
        grouper = IncidentGrouper(max_events_per_incident=2)

        now = datetime.utcnow()
        alerts = [
            Alert(
                created_at=now + timedelta(seconds=i),
                events=[SecurityEvent(src_ip="192.168.1.1")],
            )
            for i in range(5)
        ]

        groups = grouper.group_alerts(alerts)

        assert len(groups) > 1


class TestImpactAssessor:
    """Tests for incident impact assessment."""

    def test_assessor_calculates_assets_affected(self):
        """Test impact assessment counts affected assets."""
        assessor = ImpactAssessor()

        incident = Incident(
            alerts=[],
            events=[],
        )

        impact = assessor.assess_impact(incident)

        assert "assets_affected" in impact

    def test_assessor_calculates_business_impact(self):
        """Test business impact classification."""
        assessor = ImpactAssessor()

        # High impact: many assets and users
        impact = assessor._calculate_business_impact(
            assets=15,
            users=20,
        )

        assert impact == "critical"

    def test_assessor_calculates_low_impact(self):
        """Test low impact classification."""
        assessor = ImpactAssessor()

        impact = assessor._calculate_business_impact(
            assets=1,
            users=1,
        )

        assert impact == "low"


class TestIncidentManager:
    """Tests for main incident management."""

    def test_manager_creates_incident_from_alerts(self):
        """Test creating incident from alerts."""
        manager = IncidentManager()

        alerts = [
            Alert(
                severity=EventSeverity.HIGH,
                events=[
                    SecurityEvent(
                        category=EventCategory.MALWARE,
                    )
                ],
            )
        ]

        incident = manager.create_incident_from_alerts(alerts)

        assert incident is not None
        assert incident.severity >= EventSeverity.HIGH

    def test_manager_updates_incident_status(self):
        """Test updating incident status."""
        manager = IncidentManager()

        incident = manager.create_incident(
            title="Test",
            description="Test incident",
            severity=EventSeverity.MEDIUM,
            alerts=[],
            events=[],
        )

        success = manager.update_incident_status(
            str(incident.incident_id),
            "investigating",
        )

        assert success is True

    def test_manager_closes_incident(self):
        """Test closing incident."""
        manager = IncidentManager()

        incident = manager.create_incident(
            title="Test",
            description="Test",
            severity=EventSeverity.LOW,
            alerts=[],
            events=[],
        )

        success = manager.close_incident(str(incident.incident_id))

        assert success is True

    def test_manager_creates_investigation(self):
        """Test creating investigation."""
        manager = IncidentManager()

        incident = manager.create_incident(
            title="Test",
            description="Test",
            severity=EventSeverity.MEDIUM,
            alerts=[],
            events=[],
        )

        investigation = manager.create_investigation(
            str(incident.incident_id),
            "John Analyst",
        )

        assert investigation.investigator == "John Analyst"

    def test_manager_calculates_sla_status(self):
        """Test SLA status calculation."""
        manager = IncidentManager()

        incident = manager.create_incident(
            title="Test",
            description="Test",
            severity=EventSeverity.CRITICAL,
            alerts=[],
            events=[],
        )

        sla = manager.get_incident_sla_status(str(incident.incident_id))

        assert sla is not None
        assert "sla_time" in sla
        assert "remaining_time" in sla

    def test_manager_retrieves_incidents_by_status(self):
        """Test retrieving incidents by status."""
        manager = IncidentManager()

        incident = manager.create_incident(
            title="Test",
            description="Test",
            severity=EventSeverity.MEDIUM,
            alerts=[],
            events=[],
        )

        incidents = manager.get_incidents(status="new")

        assert len(incidents) > 0

    def test_manager_retrieves_incidents_by_severity(self):
        """Test retrieving incidents by severity."""
        manager = IncidentManager()

        manager.create_incident(
            title="Low",
            description="Low severity",
            severity=EventSeverity.LOW,
            alerts=[],
            events=[],
        )

        manager.create_incident(
            title="High",
            description="High severity",
            severity=EventSeverity.HIGH,
            alerts=[],
            events=[],
        )

        high_incidents = manager.get_incidents(severity=EventSeverity.HIGH)

        assert len(high_incidents) >= 1

    def test_manager_calculates_statistics(self):
        """Test statistics calculation."""
        manager = IncidentManager()

        manager.create_incident(
            title="Test1",
            description="Test",
            severity=EventSeverity.HIGH,
            alerts=[],
            events=[],
        )

        stats = manager.get_statistics()

        assert stats["total_incidents"] > 0
        assert "by_severity" in stats

    def test_manager_gets_impact_assessment(self):
        """Test getting impact assessment."""
        manager = IncidentManager()

        incident = manager.create_incident(
            title="Test",
            description="Test",
            severity=EventSeverity.HIGH,
            alerts=[],
            events=[],
        )

        impact = manager.get_incident_impact(str(incident.incident_id))

        assert impact is not None
        assert "assets_affected" in impact

    def test_manager_invalid_incident_id(self):
        """Test handling invalid incident ID."""
        manager = IncidentManager()

        success = manager.update_incident_status("invalid_id", "closed")

        assert success is False

    def test_manager_rejects_empty_alerts(self):
        """Test manager rejects incident creation without alerts."""
        manager = IncidentManager()

        from thomas.siem._exceptions import IncidentCreationException

        with pytest.raises(IncidentCreationException):
            manager.create_incident_from_alerts([])
