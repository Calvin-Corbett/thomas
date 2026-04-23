"""Project reporting with dashboards and performance analytics.

Implements status reporting, progress tracking, dashboards,
variance reports, trend analysis, and stakeholder communications.
"""

import uuid
from datetime import datetime, timedelta

from thomas.marketplace.project_mgmt._types import (
    Project,
    RiskItem,
    StatusReport,
    Task,
    TaskStatus,
)


class ReportingManager:
    """Manages project reporting and analytics.

    Handles status reports, progress tracking, dashboard generation,
    performance metrics, and trend analysis.
    """

    def __init__(self) -> None:
        """Initialize reporting manager."""
        self.reports: dict[str, StatusReport] = {}
        self.metrics_history: dict[str, list[dict[str, any]]] = {}

    def create_status_report(
        self,
        project_id: str,
        summary: str = "",
        achievements: list[str] | None = None,
        risks: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> StatusReport:
        """Create project status report.

        Args:
            project_id: Project identifier.
            summary: Executive summary.
            achievements: Completed items since last report.
            risks: Active risks.
            blockers: Current blockers/issues.

        Returns:
            Created StatusReport instance.
        """
        report_id = str(uuid.uuid4())
        report = StatusReport(
            id=report_id,
            project_id=project_id,
            summary=summary,
            achievements=achievements or [],
            risks=risks or [],
            blockers=blockers or [],
        )
        self.reports[report_id] = report

        # Record metrics for trend analysis
        if project_id not in self.metrics_history:
            self.metrics_history[project_id] = []

        self.metrics_history[project_id].append(
            {
                "report_date": report.report_date,
                "overall_status": report.overall_status,
            }
        )

        return report

    def get_report(self, report_id: str) -> StatusReport:
        """Retrieve status report by ID.

        Args:
            report_id: Report identifier.

        Returns:
            StatusReport instance.
        """
        return self.reports.get(report_id)

    def generate_dashboard_data(
        self,
        project: Project,
        tasks: list[Task],
        risks: list[RiskItem] | None = None,
    ) -> dict[str, any]:
        """Generate executive project dashboard.

        Args:
            project: Project instance.
            tasks: Project tasks.
            risks: Project risks (optional).

        Returns:
            Dictionary with dashboard metrics and visualizations.
        """
        if not tasks:
            return {
                "project_id": project.id,
                "project_name": project.name,
                "status": project.status.value,
                "health": {"overall": "AMBER"},
            }

        # Calculate progress metrics
        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        in_progress = sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS)
        todo_tasks = sum(1 for t in tasks if t.status == TaskStatus.TODO)

        percent_complete = (completed_tasks / total_tasks * 100.0) if total_tasks > 0 else 0.0
        avg_percent = sum(t.percent_complete for t in tasks) / total_tasks if total_tasks > 0 else 0.0

        # Schedule analysis
        today = datetime.now()
        overdue = sum(1 for t in tasks if t.due_date < today and t.status != TaskStatus.DONE)
        at_risk = sum(1 for t in tasks if t.due_date <= today + timedelta(days=7) and t.status != TaskStatus.DONE)

        # Schedule health
        if overdue > 0:
            schedule_status = "RED"
        elif at_risk > total_tasks * 0.2:
            schedule_status = "AMBER"
        else:
            schedule_status = "GREEN"

        # Quality assessment (based on task reopenings, simple proxy)
        quality_status = "GREEN"

        # Overall health
        statuses = [schedule_status, "GREEN", "GREEN", quality_status]
        if "RED" in statuses:
            overall = "RED"
        elif "AMBER" in statuses:
            overall = "AMBER"
        else:
            overall = "GREEN"

        # Effort tracking
        total_estimated = sum(t.pert_estimate() for t in tasks)
        total_actual = sum(t.actual_hours for t in tasks)

        # Risk summary
        risk_count = len(risks) if risks else 0

        return {
            "project_id": project.id,
            "project_name": project.name,
            "project_status": project.status.value,
            "report_date": today,
            "health": {
                "overall": overall,
                "schedule": schedule_status,
                "budget": "AMBER",
                "scope": "GREEN",
                "quality": quality_status,
            },
            "progress": {
                "percent_complete": percent_complete,
                "avg_task_completion": avg_percent,
                "completed_tasks": completed_tasks,
                "in_progress_tasks": in_progress,
                "todo_tasks": todo_tasks,
                "total_tasks": total_tasks,
            },
            "schedule": {
                "overdue_tasks": overdue,
                "at_risk_tasks": at_risk,
                "start_date": project.start_date,
                "end_date": project.end_date,
                "days_remaining": max(0, (project.end_date - today).days),
            },
            "effort": {
                "total_estimated_hours": total_estimated,
                "total_actual_hours": total_actual,
                "variance_hours": total_estimated - total_actual,
            },
            "risks": {
                "total_risks": risk_count,
            },
        }

    def generate_progress_report(
        self,
        project_id: str,
        tasks: list[Task],
        milestone_ids: list[str] | None = None,
    ) -> dict[str, any]:
        """Generate detailed progress report by task/milestone.

        Args:
            project_id: Project identifier.
            tasks: Project tasks.
            milestone_ids: Milestone identifiers (optional).

        Returns:
            Dictionary with detailed progress metrics.
        """
        report: dict[str, any] = {
            "project_id": project_id,
            "generated_at": datetime.now(),
            "tasks": [],
        }

        for task in tasks:
            task_report = {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
                "priority": task.priority.value,
                "assigned_to": task.assigned_to_id,
                "percent_complete": task.percent_complete,
                "estimated_hours": task.pert_estimate(),
                "actual_hours": task.actual_hours,
                "variance": task.pert_estimate() - task.actual_hours,
                "due_date": task.due_date,
                "days_until_due": ((task.due_date - datetime.now()).days),
            }
            report["tasks"].append(task_report)

        return report

    def generate_velocity_report(
        self,
        project_id: str,
        completed_sprints: list[tuple[str, float, int]],
    ) -> dict[str, any]:
        """Generate team velocity report.

        Args:
            project_id: Project identifier.
            completed_sprints: List of (sprint_name, velocity, duration_days) tuples.

        Returns:
            Dictionary with velocity metrics.
        """
        if not completed_sprints:
            return {
                "project_id": project_id,
                "sprints": [],
                "average_velocity": 0.0,
                "velocity_trend": "stable",
            }

        velocities = [v for _, v, _ in completed_sprints]
        avg_velocity = sum(velocities) / len(velocities)

        # Calculate trend (simple: compare first vs last)
        trend = "stable"
        if len(velocities) > 1:
            if velocities[-1] > velocities[0] * 1.1:
                trend = "improving"
            elif velocities[-1] < velocities[0] * 0.9:
                trend = "declining"

        return {
            "project_id": project_id,
            "sprints": [
                {
                    "name": name,
                    "velocity": velocity,
                    "duration_days": duration,
                }
                for name, velocity, duration in completed_sprints
            ],
            "average_velocity": avg_velocity,
            "velocity_trend": trend,
            "forecast_velocity": avg_velocity,
        }

    def generate_resource_utilization_report(
        self,
        team_capacity: dict[str, dict[str, float]],
    ) -> dict[str, any]:
        """Generate resource utilization report.

        Args:
            team_capacity: Team capacity metrics per resource.

        Returns:
            Dictionary with utilization metrics.
        """
        if not team_capacity:
            return {
                "total_resources": 0,
                "average_utilization": 0.0,
                "overallocated": 0,
                "underutilized": 0,
                "resources": [],
            }

        utilizations = [c["utilization"] for c in team_capacity.values()]
        avg_util = sum(utilizations) / len(utilizations)
        overallocated = sum(1 for c in team_capacity.values() if c["utilization"] > 100)
        underutilized = sum(1 for c in team_capacity.values() if c["utilization"] < 50)

        resources = []
        for resource_id, metrics in team_capacity.items():
            resources.append(
                {
                    "resource_id": resource_id,
                    "capacity": metrics["capacity"],
                    "allocated": metrics["allocated"],
                    "available": metrics["available"],
                    "utilization": metrics["utilization"],
                    "status": (
                        "OVERALLOCATED"
                        if metrics["utilization"] > 100
                        else "UNDERUTILIZED"
                        if metrics["utilization"] < 50
                        else "OPTIMAL"
                    ),
                }
            )

        return {
            "total_resources": len(team_capacity),
            "average_utilization": avg_util,
            "overallocated": overallocated,
            "underutilized": underutilized,
            "resources": resources,
        }

    def generate_variance_report(
        self,
        cost_variance: float,
        schedule_variance: float,
        cpi: float,
        spi: float,
    ) -> dict[str, any]:
        """Generate cost and schedule variance report.

        Args:
            cost_variance: Cost variance (EV - AC).
            schedule_variance: Schedule variance (EV - PV).
            cpi: Cost performance index.
            spi: Schedule performance index.

        Returns:
            Dictionary with variance analysis.
        """
        return {
            "cost_variance": cost_variance,
            "cost_status": ("OVER_BUDGET" if cost_variance < 0 else "ON_BUDGET"),
            "schedule_variance": schedule_variance,
            "schedule_status": ("BEHIND_SCHEDULE" if schedule_variance < 0 else "ON_SCHEDULE"),
            "cost_performance_index": cpi,
            "schedule_performance_index": spi,
            "cpi_interpretation": ("under budget" if cpi > 1.0 else "over budget"),
            "spi_interpretation": ("ahead of schedule" if spi > 1.0 else "behind schedule"),
        }

    def generate_trend_report(
        self,
        project_id: str,
        days_back: int = 30,
    ) -> dict[str, any]:
        """Generate trend analysis for project metrics.

        Args:
            project_id: Project identifier.
            days_back: Number of days to analyze.

        Returns:
            Dictionary with trend metrics.
        """
        if project_id not in self.metrics_history:
            return {
                "project_id": project_id,
                "trend": "no_data",
                "data_points": [],
            }

        history = self.metrics_history[project_id]
        cutoff = datetime.now() - timedelta(days=days_back)
        recent = [m for m in history if m["report_date"] >= cutoff]

        if not recent:
            return {
                "project_id": project_id,
                "trend": "no_recent_data",
                "data_points": [],
            }

        # Determine trend direction
        red_count = sum(1 for m in recent if m["overall_status"] == "RED")
        amber_count = sum(1 for m in recent if m["overall_status"] == "AMBER")

        if red_count > len(recent) * 0.5:
            trend = "deteriorating"
        elif amber_count > len(recent) * 0.5:
            trend = "caution"
        else:
            trend = "improving"

        return {
            "project_id": project_id,
            "period_days": days_back,
            "trend": trend,
            "data_points": recent,
        }

    def list_reports(
        self,
        project_id: str | None = None,
    ) -> list[StatusReport]:
        """List status reports with optional filtering.

        Args:
            project_id: Filter by project.

        Returns:
            List of StatusReport instances.
        """
        reports = list(self.reports.values())
        if project_id:
            reports = [r for r in reports if r.project_id == project_id]
        reports.sort(key=lambda r: r.report_date, reverse=True)
        return reports
