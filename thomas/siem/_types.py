"""Core type definitions for SIEM module.

Defines all fundamental data structures for security events, alerts, rules,
threat intelligence, incidents, and forensics data.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4


class EventSeverity(Enum):
    """Security event severity levels."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    def __lt__(self, other: "EventSeverity") -> bool:
        return self.value < other.value

    def __le__(self, other: "EventSeverity") -> bool:
        return self.value <= other.value

    def __gt__(self, other: "EventSeverity") -> bool:
        return self.value > other.value

    def __ge__(self, other: "EventSeverity") -> bool:
        return self.value >= other.value


class EventCategory(Enum):
    """Security event categories."""

    AUTHENTICATION = auto()
    AUTHORIZATION = auto()
    MALWARE = auto()
    INTRUSION = auto()
    DATA_EXFILTRATION = auto()
    LATERAL_MOVEMENT = auto()
    PRIVILEGE_ESCALATION = auto()
    PERSISTENCE = auto()
    C2_COMMUNICATION = auto()
    VULNERABILITY = auto()
    CONFIGURATION = auto()
    POLICY = auto()
    SUSPICIOUS_PROCESS = auto()
    FILE_SYSTEM = auto()
    NETWORK = auto()
    ENDPOINT = auto()
    APPLICATION = auto()
    DATABASE = auto()
    FIREWALL = auto()
    WAF = auto()


class MITREAttackTechnique(Enum):
    """MITRE ATT&CK Framework technique identifiers."""

    T1078 = "Valid Accounts"
    T1110 = "Brute Force"
    T1021 = "Remote Services"
    T1570 = "Lateral Tool Transfer"
    T1059 = "Command and Scripting Interpreter"
    T1071 = "Application Layer Protocol"
    T1041 = "Exfiltration Over C2 Channel"
    T1020 = "Automated Exfiltration"
    T1557 = "Man-in-the-Middle"
    T1566 = "Phishing"
    T1192 = "Spearphishing Link"
    T1199 = "Trusted Relationship"
    T1091 = "Replication Through Removable Media"


class KillChainPhase(Enum):
    """Lockheed Martin Cyber Kill Chain phases."""

    RECONNAISSANCE = 1
    WEAPONIZATION = 2
    DELIVERY = 3
    EXPLOITATION = 4
    INSTALLATION = 5
    COMMAND_AND_CONTROL = 6
    ACTIONS_ON_OBJECTIVES = 7


@dataclass
class SecurityEvent:
    """Normalized security event from any log source.

    Attributes:
        event_id: Unique identifier for this event.
        timestamp: When the event occurred.
        source: Log source (e.g., 'syslog', 'windows_events', 'firewall').
        category: Security event category classification.
        severity: Event severity level.
        host: Hostname or asset generating the event.
        user: Associated username if applicable.
        src_ip: Source IP address.
        dst_ip: Destination IP address.
        src_port: Source port number.
        dst_port: Destination port number.
        protocol: Network protocol (e.g., 'TCP', 'UDP').
        message: Raw event message/description.
        raw_data: Original unparsed log entry.
        metadata: Additional structured fields specific to event type.
        enrichment: Data added during enrichment (geolocation, asset info).
    """

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""
    category: EventCategory = EventCategory.NETWORK
    severity: EventSeverity = EventSeverity.INFO
    host: str = ""
    user: str = ""
    src_ip: str | None = None
    dst_ip: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    protocol: str = ""
    message: str = ""
    raw_data: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    enrichment: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.event_id)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary representation."""
        return {
            "event_id": str(self.event_id),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "category": self.category.name,
            "severity": self.severity.name,
            "host": self.host,
            "user": self.user,
            "src_ip": self.src_ip,
            "dst_ip": self.dst_ip,
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "protocol": self.protocol,
            "message": self.message,
            "metadata": self.metadata,
            "enrichment": self.enrichment,
        }


@dataclass
class IOC:
    """Indicator of Compromise (IOC).

    Attributes:
        ioc_id: Unique identifier.
        ioc_type: Type of indicator (ip, domain, hash, url).
        value: The actual indicator value.
        source: Source of the intelligence.
        confidence: Confidence score (0-100).
        created_at: When this IOC was added.
        expires_at: When this IOC expires and should be removed.
        tags: Tags for categorization.
    """

    ioc_id: UUID = field(default_factory=uuid4)
    ioc_type: str = ""  # ip, domain, hash, url
    value: str = ""
    source: str = ""
    confidence: int = 50  # 0-100
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    tags: set[str] = field(default_factory=set)

    def is_expired(self) -> bool:
        """Check if this IOC has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


@dataclass
class Indicator:
    """Indicator for threat detection and intelligence matching.

    Attributes:
        indicator_id: Unique identifier.
        pattern: Pattern to match (e.g., YARA rule pattern).
        pattern_type: Type of pattern (yara, regex, etc.).
        severity: Associated severity level.
        confidence: Confidence in this indicator.
        created_at: When indicator was created.
        last_updated: Last update time.
    """

    indicator_id: UUID = field(default_factory=uuid4)
    pattern: str = ""
    pattern_type: str = "yara"
    severity: EventSeverity = EventSeverity.MEDIUM
    confidence: int = 75
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Rule:
    """Detection or correlation rule.

    Attributes:
        rule_id: Unique identifier.
        name: Human-readable rule name.
        description: Detailed description.
        rule_type: Type of rule (detection, correlation, threshold).
        condition: Rule condition/logic.
        severity: Alert severity if rule triggers.
        enabled: Whether rule is active.
        created_at: Creation timestamp.
        last_updated: Last modification time.
        metadata: Additional rule configuration.
    """

    rule_id: UUID = field(default_factory=uuid4)
    name: str = ""
    description: str = ""
    rule_type: str = "detection"  # detection, correlation, threshold
    condition: str = ""
    severity: EventSeverity = EventSeverity.MEDIUM
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.rule_id)


@dataclass
class Alert:
    """Security alert from rule trigger or correlation.

    Attributes:
        alert_id: Unique identifier.
        rule_id: Triggering rule identifier.
        severity: Alert severity level.
        title: Alert title.
        description: Detailed description.
        events: SecurityEvents that triggered this alert.
        created_at: When alert was generated.
        status: Current alert status.
        assigned_to: User responsible for investigation.
    """

    alert_id: UUID = field(default_factory=uuid4)
    rule_id: UUID = field(default_factory=uuid4)
    severity: EventSeverity = EventSeverity.MEDIUM
    title: str = ""
    description: str = ""
    events: list[SecurityEvent] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "new"  # new, triaged, investigating, resolved, closed
    assigned_to: str | None = None

    def __hash__(self) -> int:
        return hash(self.alert_id)


@dataclass
class ThreatIntel:
    """Threat intelligence record.

    Attributes:
        intel_id: Unique identifier.
        iocs: List of associated IOCs.
        mitre_techniques: MITRE ATT&CK techniques used.
        kill_chain_phases: Cyber kill chain phases.
        description: Threat description.
        first_seen: When threat was first observed.
        last_seen: Last observation time.
        confidence: Confidence in threat assessment.
    """

    intel_id: UUID = field(default_factory=uuid4)
    iocs: list[IOC] = field(default_factory=list)
    mitre_techniques: list[MITREAttackTechnique] = field(default_factory=list)
    kill_chain_phases: list[KillChainPhase] = field(default_factory=list)
    description: str = ""
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    confidence: int = 50


@dataclass
class Asset:
    """IT asset tracked by SIEM.

    Attributes:
        asset_id: Unique identifier.
        hostname: Asset hostname.
        ip_addresses: Associated IP addresses.
        asset_type: Type (server, workstation, network_device).
        owner: Asset owner/responsible party.
        criticality: Business criticality level.
        vulnerabilities: Known vulnerabilities on this asset.
        last_seen: Last activity timestamp.
    """

    asset_id: UUID = field(default_factory=uuid4)
    hostname: str = ""
    ip_addresses: set[str] = field(default_factory=set)
    asset_type: str = ""  # server, workstation, network_device
    owner: str = ""
    criticality: int = 1  # 1=low, 5=critical
    vulnerabilities: list["Vulnerability"] = field(default_factory=list)
    last_seen: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Vulnerability:
    """Security vulnerability.

    Attributes:
        vuln_id: Unique identifier or CVE.
        cve: CVE identifier if applicable.
        title: Vulnerability title.
        description: Detailed description.
        severity: CVSS severity level.
        cvss_score: CVSS v3 score (0-10).
        affected_assets: Assets with this vulnerability.
        discovered_at: When vulnerability was discovered.
    """

    vuln_id: UUID = field(default_factory=uuid4)
    cve: str = ""
    title: str = ""
    description: str = ""
    severity: EventSeverity = EventSeverity.MEDIUM
    cvss_score: float = 5.0
    affected_assets: list[UUID] = field(default_factory=list)
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Investigation:
    """Investigation into an incident.

    Attributes:
        investigation_id: Unique identifier.
        incident_id: Associated incident.
        investigator: Lead investigator name.
        status: Investigation status.
        findings: Investigation findings.
        evidence_ids: Associated evidence.
        started_at: Investigation start time.
        completed_at: Completion time if finished.
    """

    investigation_id: UUID = field(default_factory=uuid4)
    incident_id: UUID = field(default_factory=uuid4)
    investigator: str = ""
    status: str = "open"  # open, in_progress, completed
    findings: str = ""
    evidence_ids: list[UUID] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


@dataclass
class Timeline:
    """Timeline of events for forensic analysis.

    Attributes:
        timeline_id: Unique identifier.
        events: Sorted list of events by timestamp.
        artifacts: Associated artifacts/evidence.
        created_at: Timeline creation time.
    """

    timeline_id: UUID = field(default_factory=uuid4)
    events: list[SecurityEvent] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_event(self, event: SecurityEvent) -> None:
        """Add event to timeline maintaining chronological order."""
        self.events.append(event)
        self.events.sort(key=lambda e: e.timestamp)

    def get_events_in_range(self, start: datetime, end: datetime) -> list[SecurityEvent]:
        """Get events within time range."""
        return [e for e in self.events if start <= e.timestamp <= end]


@dataclass
class NetworkFlow:
    """Network traffic flow record.

    Attributes:
        flow_id: Unique identifier.
        src_ip: Source IP address.
        dst_ip: Destination IP address.
        src_port: Source port.
        dst_port: Destination port.
        protocol: Network protocol.
        start_time: Flow start timestamp.
        end_time: Flow end timestamp.
        packets: Total packets in flow.
        bytes_in: Bytes received.
        bytes_out: Bytes sent.
    """

    flow_id: UUID = field(default_factory=uuid4)
    src_ip: str = ""
    dst_ip: str = ""
    src_port: int = 0
    dst_port: int = 0
    protocol: str = ""
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime = field(default_factory=datetime.utcnow)
    packets: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


@dataclass
class Incident:
    """Security incident.

    Attributes:
        incident_id: Unique identifier.
        title: Incident title.
        description: Detailed description.
        severity: Incident severity level.
        status: Current status in lifecycle.
        created_at: When incident was created.
        closed_at: When incident was closed.
        impact: Impact description.
        assigned_to: Analyst responsible.
        alerts: Related alerts.
        events: Related events.
        mitigations: Applied mitigations.
    """

    incident_id: UUID = field(default_factory=uuid4)
    title: str = ""
    description: str = ""
    severity: EventSeverity = EventSeverity.MEDIUM
    status: str = "new"  # new, triaged, investigating, contained, remediated, closed
    created_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    impact: str = ""
    assigned_to: str | None = None
    alerts: list[UUID] = field(default_factory=list)
    events: list[UUID] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)

    def calculate_sla_time(self) -> timedelta | None:
        """Calculate SLA time based on severity and current status."""
        if self.closed_at is None:
            end_time = datetime.utcnow()
        else:
            end_time = self.closed_at
        return end_time - self.created_at

    def __hash__(self) -> int:
        return hash(self.incident_id)
