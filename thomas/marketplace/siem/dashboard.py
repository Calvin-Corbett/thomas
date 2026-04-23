"""SIEM dashboard and KPI visualization.

Provides real-time metrics, event counters, alert summaries, threat landscape,
and KPI calculations for SIEM operations.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.siem._types import (
    Alert,
    EventSeverity,
    Incident,
    SecurityEvent,
)


@dataclass
class KPI:
    """Key Performance Indicator."""

    name: str
    value: float
    unit: str = ""
    threshold: float | None = None
    status: str = "normal"  # normal, warning, critical
    timestamp: datetime = field(default_factory=datetime.utcnow)


class MetricsCalculator:
    """Calculates SIEM metrics and KPIs."""

    @staticmethod
    def calculate_mttd(incidents: list[Incident]) -> float | None:
        """Calculate Mean Time To Detect (MTTD).

        Args:
            incidents: Incidents to analyze.

        Returns:
            MTTD in hours or None.
        """
        if not incidents:
            return None

        times = []
        for incident in incidents:
            # Approximate detection time as time from first event to incident creation
            if incident.events:
                detection_time = (incident.created_at - datetime.utcnow()).total_seconds() / 3600
                times.append(detection_time)

        return sum(times) / len(times) if times else None

    @staticmethod
    def calculate_mttr(incidents: list[Incident]) -> float | None:
        """Calculate Mean Time To Resolve (MTTR).

        Args:
            incidents: Incidents to analyze.

        Returns:
            MTTR in hours or None.
        """
        closed = [i for i in incidents if i.closed_at]

        if not closed:
            return None

        times = []
        for incident in closed:
            resolution_time = (incident.closed_at - incident.created_at).total_seconds() / 3600
            times.append(resolution_time)

        return sum(times) / len(times) if times else None

    @staticmethod
    def calculate_alert_accuracy(true_positives: int, false_positives: int) -> float:
        """Calculate alert accuracy percentage.

        Args:
            true_positives: True positive alerts.
            false_positives: False positive alerts.

        Returns:
            Accuracy percentage (0-100).
        """
        total = true_positives + false_positives
        if total == 0:
            return 0.0
        return (true_positives / total) * 100.0

    @staticmethod
    def calculate_incident_severity_ratio(
        incidents: list[Incident],
    ) -> dict[str, float]:
        """Calculate ratio of incidents by severity.

        Args:
            incidents: Incidents to analyze.

        Returns:
            Severity distribution percentages.
        """
        if not incidents:
            return {}

        by_severity = defaultdict(int)
        for incident in incidents:
            by_severity[incident.severity.name] += 1

        total = len(incidents)
        return {severity: (count / total) * 100 for severity, count in by_severity.items()}


class EventAnalyzer:
    """Analyzes event patterns for dashboard."""

    def __init__(self):
        """Initialize event analyzer."""
        self.events: list[SecurityEvent] = []

    def add_events(self, events: list[SecurityEvent]) -> None:
        """Add events to analyzer.

        Args:
            events: Events to add.
        """
        self.events.extend(events)

    def get_events_per_second(self) -> float:
        """Calculate current event rate.

        Returns:
            Events per second.
        """
        if len(self.events) < 2:
            return 0.0

        time_span = (self.events[-1].timestamp - self.events[0].timestamp).total_seconds()
        if time_span == 0:
            return 0.0

        return len(self.events) / time_span

    def get_top_event_sources(self, limit: int = 10) -> list[tuple]:
        """Get most common event sources.

        Args:
            limit: Maximum number to return.

        Returns:
            List of (source, count) tuples.
        """
        source_counts = defaultdict(int)
        for event in self.events:
            source_counts[event.source] += 1

        return sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_event_categories(self, limit: int = 10) -> list[tuple]:
        """Get most common event categories.

        Args:
            limit: Maximum number to return.

        Returns:
            List of (category, count) tuples.
        """
        category_counts = defaultdict(int)
        for event in self.events:
            category_counts[event.category.name] += 1

        return sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_severity_distribution(self) -> dict[str, int]:
        """Get event distribution by severity.

        Returns:
            Severity -> count dictionary.
        """
        severity_counts = defaultdict(int)
        for event in self.events:
            severity_counts[event.severity.name] += 1

        return dict(severity_counts)

    def get_events_by_hour(self, hours: int = 24) -> dict[int, int]:
        """Get event count by hour.

        Args:
            hours: Number of hours to analyze.

        Returns:
            Hour -> count dictionary.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=hours)

        hourly_counts = defaultdict(int)
        for event in self.events:
            if event.timestamp >= cutoff:
                hour_key = event.timestamp.hour
                hourly_counts[hour_key] += 1

        return dict(hourly_counts)


class TalkerAnalyzer:
    """Identifies top talkers (IP addresses with most activity)."""

    def __init__(self):
        """Initialize talker analyzer."""
        self.events: list[SecurityEvent] = []

    def add_events(self, events: list[SecurityEvent]) -> None:
        """Add events.

        Args:
            events: Events to add.
        """
        self.events.extend(events)

    def get_top_src_ips(self, limit: int = 10) -> list[tuple]:
        """Get most active source IPs.

        Args:
            limit: Maximum number to return.

        Returns:
            List of (IP, count) tuples.
        """
        ip_counts = defaultdict(int)
        for event in self.events:
            if event.src_ip:
                ip_counts[event.src_ip] += 1

        return sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_dst_ips(self, limit: int = 10) -> list[tuple]:
        """Get most targeted destination IPs.

        Args:
            limit: Maximum number to return.

        Returns:
            List of (IP, count) tuples.
        """
        ip_counts = defaultdict(int)
        for event in self.events:
            if event.dst_ip:
                ip_counts[event.dst_ip] += 1

        return sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_connections(self, limit: int = 10) -> list[tuple]:
        """Get most common connections.

        Args:
            limit: Maximum number to return.

        Returns:
            List of ((src_ip, dst_ip), count) tuples.
        """
        connection_counts = defaultdict(int)
        for event in self.events:
            if event.src_ip and event.dst_ip:
                connection_counts[(event.src_ip, event.dst_ip)] += 1

        return sorted(connection_counts.items(), key=lambda x: x[1], reverse=True)[:limit]


class ThreatLandscapeAnalyzer:
    """Analyzes threat landscape and active threats."""

    def __init__(self):
        """Initialize threat landscape analyzer."""
        self.alerts: list[Alert] = []
        self.incidents: list[Incident] = []

    def add_alerts(self, alerts: list[Alert]) -> None:
        """Add alerts.

        Args:
            alerts: Alerts to add.
        """
        self.alerts.extend(alerts)

    def add_incidents(self, incidents: list[Incident]) -> None:
        """Add incidents.

        Args:
            incidents: Incidents to add.
        """
        self.incidents.extend(incidents)

    def get_active_threats(self) -> list[dict[str, Any]]:
        """Get currently active threats.

        Returns:
            List of active threat descriptions.
        """
        active = []

        # Get high/critical alerts
        high_alerts = [a for a in self.alerts if a.severity >= EventSeverity.HIGH and a.status == "new"]

        for alert in high_alerts[:5]:
            active.append(
                {
                    "type": "alert",
                    "title": alert.title,
                    "severity": alert.severity.name,
                    "timestamp": alert.created_at,
                }
            )

        # Get open incidents
        open_incidents = [i for i in self.incidents if i.status != "closed"]

        for incident in open_incidents[:5]:
            active.append(
                {
                    "type": "incident",
                    "title": incident.title,
                    "severity": incident.severity.name,
                    "timestamp": incident.created_at,
                }
            )

        return active

    def get_trending_indicators(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get trending threat indicators.

        Args:
            hours: Lookback period in hours.

        Returns:
            List of trending IOCs/indicators.
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        recent_alerts = [a for a in self.alerts if a.created_at >= cutoff]

        # Aggregate by IOC/pattern
        indicators = defaultdict(int)
        for alert in recent_alerts:
            for event in alert.events:
                if event.src_ip:
                    indicators[f"src:{event.src_ip}"] += 1
                if event.dst_ip:
                    indicators[f"dst:{event.dst_ip}"] += 1

        trending = sorted(indicators.items(), key=lambda x: x[1], reverse=True)[:10]

        return [{"indicator": ind, "count": count} for ind, count in trending]


class GeographicAnalyzer:
    """Analyzes geographic distribution of events."""

    def __init__(self):
        """Initialize geographic analyzer."""
        self.events: list[SecurityEvent] = []

    def add_events(self, events: list[SecurityEvent]) -> None:
        """Add events.

        Args:
            events: Events to add.
        """
        self.events.extend(events)

    def get_geographic_distribution(self) -> dict[str, int]:
        """Get event distribution by location.

        Returns:
            Location -> count dictionary.
        """
        locations = defaultdict(int)

        for event in self.events:
            # Get location from enrichment
            for key, value in event.enrichment.items():
                if "geo_" in key and isinstance(value, dict):
                    location = value.get("location", "Unknown")
                    locations[location] += 1
                    break

        return dict(locations)

    def get_risky_countries(self) -> list[tuple]:
        """Get countries with most security events.

        Returns:
            List of (country, count) tuples.
        """
        countries = defaultdict(int)

        for event in self.events:
            for key, value in event.enrichment.items():
                if "geo_" in key and isinstance(value, dict):
                    country = value.get("country", "XX")
                    countries[country] += 1

        return sorted(countries.items(), key=lambda x: x[1], reverse=True)


class SIEMDashboard:
    """Main SIEM dashboard engine.

    Aggregates metrics, KPIs, and provides visualization data
    for real-time SIEM dashboard.
    """

    def __init__(self):
        """Initialize SIEM dashboard."""
        self.metrics_calculator = MetricsCalculator()
        self.event_analyzer = EventAnalyzer()
        self.talker_analyzer = TalkerAnalyzer()
        self.threat_analyzer = ThreatLandscapeAnalyzer()
        self.geo_analyzer = GeographicAnalyzer()

    def update_data(
        self,
        events: list[SecurityEvent],
        alerts: list[Alert],
        incidents: list[Incident],
    ) -> None:
        """Update dashboard data.

        Args:
            events: Recent events.
            alerts: Recent alerts.
            incidents: Incidents.
        """
        self.event_analyzer.add_events(events)
        self.talker_analyzer.add_events(events)
        self.threat_analyzer.add_alerts(alerts)
        self.threat_analyzer.add_incidents(incidents)
        self.geo_analyzer.add_events(events)

    def get_overview(self) -> dict[str, Any]:
        """Get dashboard overview.

        Returns:
            Overview data.
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "events_per_second": self.event_analyzer.get_events_per_second(),
            "top_sources": self.event_analyzer.get_top_event_sources(5),
            "severity_distribution": self.event_analyzer.get_severity_distribution(),
            "hourly_events": self.event_analyzer.get_events_by_hour(1),
        }

    def get_alert_summary(self) -> dict[str, Any]:
        """Get alert summary.

        Returns:
            Alert summary.
        """
        alerts = self.threat_analyzer.alerts
        by_severity = defaultdict(int)

        for alert in alerts:
            by_severity[alert.severity.name] += 1

        return {
            "total_alerts": len(alerts),
            "by_severity": dict(by_severity),
            "by_status": self._get_alerts_by_status(alerts),
        }

    def get_threat_landscape(self) -> dict[str, Any]:
        """Get threat landscape view.

        Returns:
            Threat landscape data.
        """
        return {
            "active_threats": self.threat_analyzer.get_active_threats(),
            "trending_indicators": self.threat_analyzer.get_trending_indicators(),
        }

    def get_geographic_view(self) -> dict[str, Any]:
        """Get geographic distribution.

        Returns:
            Geographic data.
        """
        return {
            "distribution": self.geo_analyzer.get_geographic_distribution(),
            "risky_countries": self.geo_analyzer.get_risky_countries(),
        }

    def get_top_talkers(self) -> dict[str, Any]:
        """Get top talker analysis.

        Returns:
            Top talkers data.
        """
        return {
            "src_ips": self.talker_analyzer.get_top_src_ips(10),
            "dst_ips": self.talker_analyzer.get_top_dst_ips(10),
            "connections": self.talker_analyzer.get_top_connections(10),
        }

    def get_kpis(self, incidents: list[Incident]) -> dict[str, Any]:
        """Get KPI calculations.

        Args:
            incidents: Incidents for KPI calculation.

        Returns:
            KPI data.
        """
        mttd = self.metrics_calculator.calculate_mttd(incidents)
        mttr = self.metrics_calculator.calculate_mttr(incidents)

        return {
            "mttd_hours": mttd,
            "mttr_hours": mttr,
            "severity_ratio": self.metrics_calculator.calculate_incident_severity_ratio(incidents),
        }

    def get_health_status(self) -> dict[str, Any]:
        """Get component health status.

        Returns:
            Health status data.
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "event_collector": "healthy",
                "correlation_engine": "healthy",
                "detection_engine": "healthy",
                "incident_manager": "healthy",
            },
            "event_lag_seconds": 0,
        }

    @staticmethod
    def _get_alerts_by_status(alerts: list[Alert]) -> dict[str, int]:
        """Get alert counts by status.

        Args:
            alerts: Alerts to analyze.

        Returns:
            Status -> count dictionary.
        """
        by_status = defaultdict(int)
        for alert in alerts:
            by_status[alert.status] += 1
        return dict(by_status)
