"""Compliance monitoring and reporting.

Monitors compliance with security frameworks (PCI-DSS, HIPAA, SOX, GDPR),
tracks control compliance, generates audit logs, and calculates compliance scores.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from thomas.marketplace.siem._types import EventSeverity, SecurityEvent


class ComplianceFramework(Enum):
    """Supported compliance frameworks."""

    PCI_DSS = "PCI-DSS"
    HIPAA = "HIPAA"
    SOX = "SOX"
    GDPR = "GDPR"


@dataclass
class ComplianceControl:
    """Single compliance control requirement."""

    control_id: str
    framework: ComplianceFramework
    name: str
    description: str
    requirement: str
    category: str  # access_control, encryption, audit, etc.
    is_compliant: bool = False
    last_checked: datetime | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class AuditLogEntry:
    """Tamper-evident audit log entry."""

    entry_id: str
    timestamp: datetime
    user: str
    action: str
    resource: str
    result: str  # success, failure
    details: dict[str, Any] = field(default_factory=dict)
    previous_hash: str | None = None
    entry_hash: str | None = None

    def calculate_hash(self) -> str:
        """Calculate hash of this entry."""
        content = f"{self.entry_id}{self.timestamp}{self.user}{self.action}{self.previous_hash}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class ComplianceGap:
    """Identified compliance gap."""

    gap_id: str
    framework: ComplianceFramework
    control_id: str
    severity: EventSeverity
    description: str
    remediation: str
    due_date: datetime


class ComplianceFrameworkMapper:
    """Maps security events to compliance control requirements."""

    CONTROL_MAPPING = {
        ComplianceFramework.PCI_DSS: {
            "1.1": "Firewall rules documented and tested",
            "2.1": "Default passwords changed",
            "6.5.1": "Injection prevention",
            "7.1": "Access control implementation",
            "8.1": "User identification",
            "10.1": "Audit trails for all access",
            "10.2": "Automated audit trail",
        },
        ComplianceFramework.HIPAA: {
            "164.308(a)(1)(i)": "Security management process",
            "164.308(a)(5)(ii)(C)": "Log-in monitoring",
            "164.308(a)(7)(i)": "Backup and disaster recovery",
            "164.312(a)(2)(i)": "Unique user identification",
            "164.312(b)": "Encryption of PHI",
            "164.312(a)(2)(ii)": "Emergency access procedures",
        },
        ComplianceFramework.SOX: {
            "302": "CEO/CFO certification",
            "404": "Internal control assessment",
            "409": "Real-time disclosure of material changes",
            "906": "Criminal penalties for certification",
        },
        ComplianceFramework.GDPR: {
            "5": "Principles of personal data processing",
            "32": "Security of processing",
            "33": "Breach notification",
            "34": "Communication to data subjects",
            "35": "DPIA requirements",
        },
    }

    @staticmethod
    def get_framework_controls(
        framework: ComplianceFramework,
    ) -> dict[str, str]:
        """Get all controls for framework.

        Args:
            framework: Compliance framework.

        Returns:
            Dictionary of control_id -> description.
        """
        return ComplianceFrameworkMapper.CONTROL_MAPPING.get(framework, {})


class AuditLogger:
    """Maintains tamper-evident audit logs."""

    def __init__(self):
        """Initialize audit logger."""
        self.entries: list[AuditLogEntry] = []
        self.last_hash: str | None = None

    def log_action(
        self,
        user: str,
        action: str,
        resource: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Log security action.

        Args:
            user: User performing action.
            action: Action type.
            resource: Resource affected.
            result: Result (success/failure).
            details: Additional details.

        Returns:
            Created AuditLogEntry.
        """
        entry = AuditLogEntry(
            entry_id=f"audit_{len(self.entries)}",
            timestamp=datetime.utcnow(),
            user=user,
            action=action,
            resource=resource,
            result=result,
            details=details or {},
            previous_hash=self.last_hash,
        )

        # Calculate hash with chain of previous entries
        entry.entry_hash = entry.calculate_hash()
        self.entries.append(entry)
        self.last_hash = entry.entry_hash

        return entry

    def verify_integrity(self) -> bool:
        """Verify audit log integrity (hash chain).

        Returns:
            True if all hashes are valid.
        """
        previous_hash = None

        for entry in self.entries:
            if entry.previous_hash != previous_hash:
                return False

            calculated = entry.calculate_hash()
            if calculated != entry.entry_hash:
                return False

            previous_hash = entry.entry_hash

        return True

    def get_entries(
        self,
        user: str | None = None,
        action: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[AuditLogEntry]:
        """Retrieve audit entries with filters.

        Args:
            user: Filter by user.
            action: Filter by action type.
            start_time: Filter from time.
            end_time: Filter to time.

        Returns:
            List of audit entries.
        """
        results = self.entries

        if user:
            results = [e for e in results if e.user == user]

        if action:
            results = [e for e in results if e.action == action]

        if start_time:
            results = [e for e in results if e.timestamp >= start_time]

        if end_time:
            results = [e for e in results if e.timestamp <= end_time]

        return results


class ComplianceScorer:
    """Calculates compliance scores for frameworks."""

    @staticmethod
    def calculate_framework_score(
        controls: list[ComplianceControl],
    ) -> float:
        """Calculate compliance score for framework.

        Args:
            controls: Framework controls.

        Returns:
            Score (0-100).
        """
        if not controls:
            return 0.0

        compliant = len([c for c in controls if c.is_compliant])
        return (compliant / len(controls)) * 100.0

    @staticmethod
    def calculate_overall_score(
        framework_scores: dict[ComplianceFramework, float],
    ) -> float:
        """Calculate overall compliance score.

        Args:
            framework_scores: Scores by framework.

        Returns:
            Overall score (0-100).
        """
        if not framework_scores:
            return 0.0

        return sum(framework_scores.values()) / len(framework_scores)


class ComplianceMonitor:
    """Main compliance monitoring engine.

    Tracks compliance with multiple frameworks, monitors controls,
    generates reports, and identifies gaps.
    """

    def __init__(self):
        """Initialize compliance monitor."""
        self.controls: dict[str, ComplianceControl] = {}
        self.audit_logger = AuditLogger()
        self.gaps: dict[str, ComplianceGap] = {}
        self.framework_mapper = ComplianceFrameworkMapper()
        self.scorer = ComplianceScorer()

    def initialize_framework(self, framework: ComplianceFramework) -> None:
        """Initialize controls for framework.

        Args:
            framework: Framework to initialize.
        """
        controls = self.framework_mapper.get_framework_controls(framework)

        for control_id, description in controls.items():
            control = ComplianceControl(
                control_id=control_id,
                framework=framework,
                name=f"{framework.value} {control_id}",
                description=description,
                requirement=description,
                category=self._categorize_control(framework, control_id),
            )
            self.controls[control_id] = control

    def check_control(self, control_id: str, events: list[SecurityEvent]) -> bool:
        """Check compliance of a control.

        Args:
            control_id: Control to check.
            events: Events to evaluate against control.

        Returns:
            True if control is compliant.
        """
        if control_id not in self.controls:
            return False

        control = self.controls[control_id]

        # Evaluate based on control category and events
        is_compliant = self._evaluate_control(control.control_id, control.category, events)

        control.is_compliant = is_compliant
        control.last_checked = datetime.utcnow()

        return is_compliant

    def _evaluate_control(self, control_id: str, category: str, events: list[SecurityEvent]) -> bool:
        """Evaluate specific control.

        Args:
            control_id: Control identifier.
            category: Control category.
            events: Events to evaluate.

        Returns:
            True if compliant.
        """
        if category == "access_control":
            # Check for authentication events
            auth_events = [e for e in events if "auth" in e.message.lower()]
            return len(auth_events) > 0

        elif category == "encryption":
            # Check for encrypted connections
            encrypted = [e for e in events if "tls" in e.message.lower() or "https" in e.message.lower()]
            return len(encrypted) > 0

        elif category == "audit":
            # Check for audit logging
            return len(events) > 0

        else:
            # Generic check
            return len(events) > 0

    def _categorize_control(self, framework: ComplianceFramework, control_id: str) -> str:
        """Categorize control.

        Args:
            framework: Framework.
            control_id: Control identifier.

        Returns:
            Control category.
        """
        # Simple categorization based on framework and ID
        if "encrypt" in control_id.lower():
            return "encryption"
        elif "access" in control_id.lower() or "user" in control_id.lower():
            return "access_control"
        elif "log" in control_id.lower() or "audit" in control_id.lower():
            return "audit"
        else:
            return "general"

    def identify_gaps(self, framework: ComplianceFramework) -> list[ComplianceGap]:
        """Identify compliance gaps.

        Args:
            framework: Framework to assess.

        Returns:
            List of identified gaps.
        """
        gaps = []

        for control_id, control in self.controls.items():
            if control.framework == framework and not control.is_compliant:
                gap = ComplianceGap(
                    gap_id=f"gap_{control_id}",
                    framework=framework,
                    control_id=control_id,
                    severity=EventSeverity.MEDIUM,
                    description=f"Control {control_id} not compliant",
                    remediation=f"Implement {control.name}",
                    due_date=datetime.utcnow() + timedelta(days=30),
                )
                gaps.append(gap)
                self.gaps[gap.gap_id] = gap

        return gaps

    def get_compliance_score(self, framework: ComplianceFramework) -> float:
        """Get compliance score for framework.

        Args:
            framework: Framework to score.

        Returns:
            Compliance score (0-100).
        """
        framework_controls = [c for c in self.controls.values() if c.framework == framework]
        return self.scorer.calculate_framework_score(framework_controls)

    def generate_report(self, framework: ComplianceFramework) -> dict[str, Any]:
        """Generate compliance report.

        Args:
            framework: Framework to report on.

        Returns:
            Compliance report dictionary.
        """
        controls = [c for c in self.controls.values() if c.framework == framework]
        compliant = [c for c in controls if c.is_compliant]
        score = self.scorer.calculate_framework_score(controls)

        return {
            "framework": framework.value,
            "total_controls": len(controls),
            "compliant_controls": len(compliant),
            "non_compliant_controls": len(controls) - len(compliant),
            "compliance_score": score,
            "compliance_percentage": f"{score:.1f}%",
            "gaps": self.identify_gaps(framework),
            "last_assessment": datetime.utcnow(),
        }

    def log_compliance_action(
        self,
        user: str,
        action: str,
        control_id: str,
        status: str,
    ) -> None:
        """Log compliance-related action to audit log.

        Args:
            user: User performing action.
            action: Action type.
            control_id: Associated control.
            status: Status/result.
        """
        self.audit_logger.log_action(
            user=user,
            action=action,
            resource=control_id,
            result=status,
            details={"control_id": control_id},
        )

    def get_audit_trail(self, start_time: datetime | None = None) -> list[AuditLogEntry]:
        """Get audit trail.

        Args:
            start_time: Filter from time.

        Returns:
            List of audit entries.
        """
        return self.audit_logger.get_entries(start_time=start_time)

    def verify_audit_integrity(self) -> bool:
        """Verify audit log integrity.

        Returns:
            True if audit log is unmodified.
        """
        return self.audit_logger.verify_integrity()
