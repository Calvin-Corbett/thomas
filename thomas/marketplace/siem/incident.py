"""Incident management system.

Manages incident lifecycle, creation from alerts, severity classification,
impact assessment, evidence collection, and SLA tracking.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from thomas.marketplace.siem._exceptions import (
    IncidentCreationException,
)
from thomas.marketplace.siem._types import (
    Alert,
    EventCategory,
    EventSeverity,
    Incident,
    Investigation,
    SecurityEvent,
)


@dataclass
class PlaybookAction:
    """Single action in an incident response playbook."""

    action_id: str
    action_type: str  # block_ip, disable_user, isolate_host, quarantine_file
    target: str  # IP, user, hostname, file path
    description: str = ""
    auto_approve: bool = False


@dataclass
class PlaybookStep:
    """Step in automated response playbook."""

    step_id: str
    condition: Callable[[Incident], bool]
    actions: list[PlaybookAction] = field(default_factory=list)
    required_approval: bool = False


class IncidentClassifier:
    """Classifies incident severity based on characteristics."""

    # CVSS-inspired scoring
    BASE_SCORES = {
        EventSeverity.CRITICAL: 9.0,
        EventSeverity.HIGH: 7.0,
        EventSeverity.MEDIUM: 5.0,
        EventSeverity.LOW: 3.0,
        EventSeverity.INFO: 0.5,
    }

    # Category impact scores
    CATEGORY_IMPACT = {
        EventCategory.DATA_EXFILTRATION: 1.5,
        EventCategory.C2_COMMUNICATION: 1.3,
        EventCategory.PRIVILEGE_ESCALATION: 1.4,
        EventCategory.LATERAL_MOVEMENT: 1.2,
        EventCategory.MALWARE: 1.4,
        EventCategory.INTRUSION: 1.3,
    }

    @staticmethod
    def calculate_severity(
        alerts: list[Alert],
    ) -> tuple[EventSeverity, float]:
        """Calculate incident severity from alerts.

        Args:
            alerts: Alerts associated with incident.

        Returns:
            (Severity level, numerical score).
        """
        if not alerts:
            return (EventSeverity.LOW, 1.0)

        # Start with highest alert severity
        max_severity = max(a.severity for a in alerts)
        base_score = IncidentClassifier.BASE_SCORES.get(max_severity, 5.0)

        # Boost for high-impact categories
        for alert in alerts:
            for event in alert.events:
                multiplier = IncidentClassifier.CATEGORY_IMPACT.get(event.category, 1.0)
                base_score *= min(1.3, multiplier)

        # Alert count multiplier
        alert_count_multiplier = min(1.5, 1.0 + (len(alerts) / 10.0))
        final_score = base_score * alert_count_multiplier

        # Map score to severity
        if final_score >= 8.5:
            return (EventSeverity.CRITICAL, final_score)
        elif final_score >= 6.5:
            return (EventSeverity.HIGH, final_score)
        elif final_score >= 4.0:
            return (EventSeverity.MEDIUM, final_score)
        else:
            return (EventSeverity.LOW, final_score)


class IncidentGrouper:
    """Groups related alerts into incidents."""

    def __init__(self, time_window: int = 3600, max_events_per_incident: int = 100):
        """Initialize incident grouper.

        Args:
            time_window: Time window for grouping (seconds).
            max_events_per_incident: Max events before creating new incident.
        """
        self.time_window = time_window
        self.max_events_per_incident = max_events_per_incident
        self.alert_groups: list[list[Alert]] = []

    def group_alerts(self, alerts: list[Alert]) -> list[list[Alert]]:
        """Group related alerts.

        Args:
            alerts: Alerts to group.

        Returns:
            List of alert groups.
        """
        if not alerts:
            return []

        groups = []
        sorted_alerts = sorted(alerts, key=lambda a: a.created_at)

        current_group = [sorted_alerts[0]]
        base_time = sorted_alerts[0].created_at

        for alert in sorted_alerts[1:]:
            time_diff = (alert.created_at - base_time).total_seconds()

            # Check if should add to current group
            if (
                time_diff <= self.time_window
                and len(current_group) < self.max_events_per_incident
                and self._is_related(alert, current_group)
            ):
                current_group.append(alert)
            else:
                groups.append(current_group)
                current_group = [alert]
                base_time = alert.created_at

        if current_group:
            groups.append(current_group)

        return groups

    @staticmethod
    def _is_related(alert: Alert, group: list[Alert]) -> bool:
        """Check if alert is related to group.

        Args:
            alert: Alert to check.
            group: Alert group.

        Returns:
            True if alert is related.
        """
        # Related if same source IP, destination, or category
        for group_alert in group:
            for event in alert.events:
                for group_event in group_alert.events:
                    if (
                        (event.src_ip and event.src_ip == group_event.src_ip)
                        or (event.dst_ip and event.dst_ip == group_event.dst_ip)
                        or (event.category == group_event.category)
                    ):
                        return True

        return False


class ImpactAssessor:
    """Assesses impact of security incidents."""

    def __init__(self):
        """Initialize impact assessor."""
        self.affected_assets: dict[str, int] = defaultdict(int)

    def assess_impact(self, incident: Incident) -> dict[str, Any]:
        """Assess incident impact.

        Args:
            incident: Incident to assess.

        Returns:
            Impact assessment dictionary.
        """
        # Get events from alerts
        all_events = []
        for alert_id in incident.alerts:
            all_events.extend([e for a in [incident] for e in a.events if str(a.alert_id) == str(alert_id)])

        assets_affected = len(set(e.host for e in all_events if e.host))
        users_affected = len(set(e.user for e in all_events if e.user))
        data_volume = sum(e.metadata.get("bytes_transferred", 0) for e in all_events)

        severity_score = 1 + (incident.severity.value * 0.25)
        impact_score = severity_score * min(2.0, 1.0 + (assets_affected / 10.0))

        return {
            "assets_affected": assets_affected,
            "users_affected": users_affected,
            "data_volume_bytes": data_volume,
            "impact_score": impact_score,
            "business_impact": self._calculate_business_impact(assets_affected, users_affected),
        }

    @staticmethod
    def _calculate_business_impact(assets: int, users: int) -> str:
        """Calculate business impact level.

        Args:
            assets: Number of affected assets.
            users: Number of affected users.

        Returns:
            Impact level string.
        """
        score = assets * 2 + users
        if score > 20:
            return "critical"
        elif score > 10:
            return "high"
        elif score > 5:
            return "medium"
        else:
            return "low"


class IncidentManager:
    """Main incident management system.

    Manages incident lifecycle, creation from alerts, classification,
    impact assessment, and SLA tracking.
    """

    def __init__(self):
        """Initialize incident manager."""
        self.incidents: dict[str, Incident] = {}
        self.investigations: dict[str, Investigation] = {}
        self.classifier = IncidentClassifier()
        self.grouper = IncidentGrouper()
        self.impact_assessor = ImpactAssessor()
        self.sla_times = {
            EventSeverity.CRITICAL: timedelta(hours=1),
            EventSeverity.HIGH: timedelta(hours=4),
            EventSeverity.MEDIUM: timedelta(hours=8),
            EventSeverity.LOW: timedelta(hours=24),
        }

    def create_incident_from_alerts(self, alerts: list[Alert]) -> Incident:
        """Create incident from alerts.

        Args:
            alerts: Alerts to group into incident.

        Returns:
            Created Incident.

        Raises:
            IncidentCreationException: If creation fails.
        """
        if not alerts:
            raise IncidentCreationException("Cannot create incident without alerts")

        try:
            # Classify severity
            severity, score = self.classifier.calculate_severity(alerts)

            # Collect all events
            all_events = []
            for alert in alerts:
                all_events.extend(alert.events)

            # Create title
            main_category = max(
                set(e.category for e in all_events),
                key=lambda c: sum(1 for e in all_events if e.category == c),
            )
            title = f"Incident: {main_category.name}"

            # Create incident
            incident = Incident(
                title=title,
                severity=severity,
                description=f"Incident created from {len(alerts)} alerts",
                alerts=[a.alert_id for a in alerts],
                events=[e.event_id for e in all_events],
            )

            self.incidents[str(incident.incident_id)] = incident
            return incident

        except Exception as e:
            raise IncidentCreationException(f"Failed to create incident: {e}")

    def create_incident(
        self,
        title: str,
        description: str,
        severity: EventSeverity,
        alerts: list[Alert],
        events: list[SecurityEvent],
    ) -> Incident:
        """Create incident manually.

        Args:
            title: Incident title.
            description: Description.
            severity: Severity level.
            alerts: Associated alerts.
            events: Associated events.

        Returns:
            Created Incident.
        """
        incident = Incident(
            title=title,
            description=description,
            severity=severity,
            alerts=[a.alert_id for a in alerts],
            events=[e.event_id for e in events],
        )

        self.incidents[str(incident.incident_id)] = incident
        return incident

    def update_incident_status(self, incident_id: str, status: str) -> bool:
        """Update incident status.

        Args:
            incident_id: Incident identifier.
            status: New status.

        Returns:
            True if updated, False if not found.
        """
        if incident_id not in self.incidents:
            return False

        incident = self.incidents[incident_id]
        incident.status = status

        if status == "closed":
            incident.closed_at = datetime.utcnow()

        return True

    def create_investigation(self, incident_id: str, investigator: str) -> Investigation:
        """Create investigation for incident.

        Args:
            incident_id: Incident identifier.
            investigator: Investigator name.

        Returns:
            Created Investigation.
        """
        investigation = Investigation(
            incident_id=uuid4().hex,
            investigator=investigator,
        )

        self.investigations[str(investigation.investigation_id)] = investigation
        return investigation

    def get_incident_sla_status(self, incident_id: str) -> dict[str, Any] | None:
        """Get SLA status for incident.

        Args:
            incident_id: Incident identifier.

        Returns:
            SLA status dictionary or None.
        """
        if incident_id not in self.incidents:
            return None

        incident = self.incidents[incident_id]
        sla_time = self.sla_times.get(incident.severity, timedelta(hours=24))

        elapsed = incident.calculate_sla_time()
        remaining = sla_time - elapsed if elapsed else sla_time

        return {
            "severity": incident.severity.name,
            "sla_time": str(sla_time),
            "elapsed_time": str(elapsed),
            "remaining_time": str(remaining),
            "sla_exceeded": elapsed > sla_time if elapsed else False,
        }

    def get_incident(self, incident_id: str) -> Incident | None:
        """Get incident by ID.

        Args:
            incident_id: Incident identifier.

        Returns:
            Incident or None if not found.
        """
        return self.incidents.get(incident_id)

    def get_incidents(
        self,
        status: str | None = None,
        severity: EventSeverity | None = None,
    ) -> list[Incident]:
        """Get incidents with optional filtering.

        Args:
            status: Filter by status.
            severity: Filter by severity or higher.

        Returns:
            List of incidents.
        """
        incidents = list(self.incidents.values())

        if status:
            incidents = [i for i in incidents if i.status == status]

        if severity:
            incidents = [i for i in incidents if i.severity >= severity]

        return incidents

    def get_incident_impact(self, incident_id: str) -> dict[str, Any] | None:
        """Get impact assessment for incident.

        Args:
            incident_id: Incident identifier.

        Returns:
            Impact assessment or None.
        """
        incident = self.get_incident(incident_id)
        if not incident:
            return None

        return self.impact_assessor.assess_impact(incident)

    def close_incident(self, incident_id: str) -> bool:
        """Close incident.

        Args:
            incident_id: Incident identifier.

        Returns:
            True if closed, False if not found.
        """
        return self.update_incident_status(incident_id, "closed")

    def get_statistics(self) -> dict[str, Any]:
        """Get incident statistics.

        Returns:
            Statistics dictionary.
        """
        incidents = list(self.incidents.values())
        closed = [i for i in incidents if i.status == "closed"]
        open_incidents = [i for i in incidents if i.status != "closed"]

        avg_resolution_time = None
        if closed:
            times = [(i.closed_at - i.created_at).total_seconds() for i in closed if i.closed_at]
            if times:
                avg_resolution_time = sum(times) / len(times)

        return {
            "total_incidents": len(incidents),
            "open_incidents": len(open_incidents),
            "closed_incidents": len(closed),
            "avg_resolution_time_seconds": avg_resolution_time,
            "by_severity": {
                severity.name: len([i for i in incidents if i.severity == severity]) for severity in EventSeverity
            },
        }
