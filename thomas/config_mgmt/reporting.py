"""
Configuration management reporting and analytics.

Generates compliance reports, execution summaries, audit trails,
and configuration analytics.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ReportFormat(Enum):
    """Supported report output formats."""

    JSON = "json"
    YAML = "yaml"
    HTML = "html"
    CSV = "csv"
    TEXT = "text"


@dataclass
class ExecutionReport:
    """Report of a playbook execution."""

    execution_id: str
    playbook_name: str
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    skipped_tasks: int
    duration_ms: float
    success_rate: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    host_count: int = 0
    changed_resources: int = 0
    failed_resources: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "execution_id": self.execution_id,
            "playbook_name": self.playbook_name,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "skipped_tasks": self.skipped_tasks,
            "duration_ms": self.duration_ms,
            "success_rate": self.success_rate,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_human_readable(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Execution Report: {self.playbook_name}",
            f"ID: {self.execution_id}",
            f"Timestamp: {self.timestamp.isoformat()}",
            "",
            f"Total Tasks: {self.total_tasks}",
            f"Successful: {self.successful_tasks}",
            f"Failed: {self.failed_tasks}",
            f"Skipped: {self.skipped_tasks}",
            f"Success Rate: {self.success_rate:.1f}%",
            f"Duration: {self.duration_ms:.2f}ms",
        ]
        return "\n".join(lines)


@dataclass
class ComplianceReport:
    """Configuration compliance report."""

    report_id: str
    total_resources: int
    compliant_resources: int
    non_compliant_resources: int
    compliance_percentage: float
    drift_details: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    recommendations: list[str] = field(default_factory=list)

    @property
    def resource_type_breakdown(self) -> dict[str, int]:
        """Get breakdown by resource type."""
        breakdown: dict[str, int] = {}
        for drift in self.drift_details:
            res_type = drift.get("resource_type", "unknown")
            breakdown[res_type] = breakdown.get(res_type, 0) + 1
        return breakdown

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "report_id": self.report_id,
            "total_resources": self.total_resources,
            "compliant_resources": self.compliant_resources,
            "non_compliant_resources": self.non_compliant_resources,
            "compliance_percentage": self.compliance_percentage,
            "drift_count": len(self.drift_details),
            "timestamp": self.timestamp.isoformat(),
        }

    def to_human_readable(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "Configuration Compliance Report",
            f"ID: {self.report_id}",
            f"Timestamp: {self.timestamp.isoformat()}",
            "",
            f"Total Resources: {self.total_resources}",
            f"Compliant: {self.compliant_resources}",
            f"Non-Compliant: {self.non_compliant_resources}",
            f"Compliance Rate: {self.compliance_percentage:.1f}%",
        ]

        if self.recommendations:
            lines.append("")
            lines.append("Recommendations:")
            for rec in self.recommendations:
                lines.append(f"  - {rec}")

        return "\n".join(lines)


@dataclass
class AuditLog:
    """Audit log entry for configuration changes."""

    entry_id: str
    timestamp: datetime
    action: str
    resource_id: str
    resource_type: str
    change_summary: str
    initiated_by: str
    ip_address: str | None = None
    status: str = "success"  # success, failure, pending
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "initiated_by": self.initiated_by,
            "status": self.status,
        }


class Reporter:
    """Generates configuration management reports."""

    def __init__(self) -> None:
        """Initialize reporter."""
        self.audit_logs: list[AuditLog] = []
        self.execution_reports: list[ExecutionReport] = []
        self.compliance_reports: list[ComplianceReport] = []

    def log_audit_event(self, log: AuditLog) -> None:
        """Log an audit event."""
        self.audit_logs.append(log)

    def generate_execution_report(self, execution_data: dict[str, Any]) -> ExecutionReport:
        """Generate execution report from execution data."""
        report = ExecutionReport(
            execution_id=execution_data.get("execution_id", ""),
            playbook_name=execution_data.get("playbook_name", ""),
            total_tasks=execution_data.get("total_tasks", 0),
            successful_tasks=execution_data.get("successful_tasks", 0),
            failed_tasks=execution_data.get("failed_tasks", 0),
            skipped_tasks=execution_data.get("skipped_tasks", 0),
            duration_ms=execution_data.get("duration_ms", 0.0),
            success_rate=execution_data.get("success_rate", 0.0),
            host_count=execution_data.get("host_count", 0),
            changed_resources=execution_data.get("changed_resources", 0),
            failed_resources=execution_data.get("failed_resources", 0),
        )

        self.execution_reports.append(report)
        return report

    def generate_compliance_report(self, compliance_data: dict[str, Any]) -> ComplianceReport:
        """Generate compliance report from compliance data."""
        total = compliance_data.get("total_resources", 0)
        compliant = compliance_data.get("compliant_resources", 0)
        non_compliant = compliance_data.get("non_compliant_resources", 0)

        compliance_pct = (compliant / total * 100) if total > 0 else 0.0

        report = ComplianceReport(
            report_id=compliance_data.get("report_id", ""),
            total_resources=total,
            compliant_resources=compliant,
            non_compliant_resources=non_compliant,
            compliance_percentage=compliance_pct,
            drift_details=compliance_data.get("drift_summary", []),
        )

        # Generate recommendations
        if non_compliant > 0:
            report.recommendations.append(f"Address {non_compliant} non-compliant resource(s)")
            if non_compliant / total > 0.2:
                report.recommendations.append("Compliance is below 80%; priority remediation recommended")

        self.compliance_reports.append(report)
        return report

    def get_audit_trail(
        self, resource_id: str | None = None, start_time: datetime | None = None, end_time: datetime | None = None
    ) -> list[AuditLog]:
        """Get audit trail with optional filtering."""
        logs = self.audit_logs

        if resource_id:
            logs = [l for l in logs if l.resource_id == resource_id]

        if start_time:
            logs = [l for l in logs if l.timestamp >= start_time]

        if end_time:
            logs = [l for l in logs if l.timestamp <= end_time]

        return sorted(logs, key=lambda l: l.timestamp, reverse=True)

    def get_execution_summary(self) -> dict[str, Any]:
        """Get summary of all executions."""
        if not self.execution_reports:
            return {}

        total_executions = len(self.execution_reports)
        successful = sum(1 for r in self.execution_reports if r.failed_tasks == 0)
        total_tasks = sum(r.total_tasks for r in self.execution_reports)
        total_successes = sum(r.successful_tasks for r in self.execution_reports)
        total_failures = sum(r.failed_tasks for r in self.execution_reports)

        avg_success_rate = (total_successes / total_tasks * 100) if total_tasks > 0 else 0.0

        return {
            "total_executions": total_executions,
            "successful_executions": successful,
            "failed_executions": total_executions - successful,
            "total_tasks_executed": total_tasks,
            "successful_tasks": total_successes,
            "failed_tasks": total_failures,
            "average_success_rate": avg_success_rate,
        }

    def get_compliance_summary(self) -> dict[str, Any]:
        """Get summary of all compliance reports."""
        if not self.compliance_reports:
            return {}

        total_resources = sum(r.total_resources for r in self.compliance_reports)
        compliant_resources = sum(r.compliant_resources for r in self.compliance_reports)
        non_compliant = sum(r.non_compliant_resources for r in self.compliance_reports)

        overall_compliance = (compliant_resources / total_resources * 100) if total_resources > 0 else 0.0

        return {
            "total_resources_assessed": total_resources,
            "compliant_resources": compliant_resources,
            "non_compliant_resources": non_compliant,
            "overall_compliance_rate": overall_compliance,
            "reports_generated": len(self.compliance_reports),
        }

    def export_report(self, report: Any, format_type: ReportFormat) -> str:
        """Export report in specified format."""
        if format_type == ReportFormat.JSON:
            return json.dumps(report.to_dict(), indent=2)
        elif format_type == ReportFormat.TEXT:
            return report.to_human_readable()
        elif format_type == ReportFormat.YAML:
            import yaml

            return yaml.dump(report.to_dict(), default_flow_style=False)
        elif format_type == ReportFormat.CSV:
            # Basic CSV export for dict-like reports
            report_dict = report.to_dict()
            headers = ",".join(report_dict.keys())
            values = ",".join(str(v) for v in report_dict.values())
            return f"{headers}\n{values}"
        else:
            return str(report)
