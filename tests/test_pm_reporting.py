"""Tests for reporting and analytics module."""

from datetime import datetime, timedelta

import pytest

from thomas.project_mgmt._types import Project, Task, TaskStatus
from thomas.project_mgmt.reporting import ReportingManager


class TestReportingManager:
    """Test suite for ReportingManager."""

    @pytest.fixture
    def manager(self) -> ReportingManager:
        """Create reporting manager instance."""
        return ReportingManager()

    @pytest.fixture
    def sample_project(self) -> Project:
        """Create sample project."""
        return Project(
            id="proj-1",
            name="Test Project",
            description="Test project",
            start_date=datetime.now() - timedelta(days=30),
            end_date=datetime.now() + timedelta(days=30),
            owner_id="res-1",
            budget_allocated=10000.0,
        )

    @pytest.fixture
    def sample_tasks(self) -> list:
        """Create sample tasks."""
        return [
            Task(
                id="task-1",
                project_id="proj-1",
                title="Task 1",
                status=TaskStatus.DONE,
                percent_complete=100.0,
            ),
            Task(
                id="task-2",
                project_id="proj-1",
                title="Task 2",
                status=TaskStatus.IN_PROGRESS,
                percent_complete=50.0,
                due_date=datetime.now() + timedelta(days=5),
            ),
            Task(
                id="task-3",
                project_id="proj-1",
                title="Task 3",
                status=TaskStatus.TODO,
                percent_complete=0.0,
                due_date=datetime.now() - timedelta(days=2),  # Overdue
            ),
        ]

    def test_create_status_report(
        self,
        manager: ReportingManager,
    ) -> None:
        """Test status report creation."""
        report = manager.create_status_report(
            project_id="proj-1",
            summary="Project on track",
            achievements=["Feature A complete", "Feature B in progress"],
            risks=["Database scaling concern"],
            blockers=["Waiting for design approval"],
        )

        assert report.id is not None
        assert report.project_id == "proj-1"
        assert len(report.achievements) == 2
        assert len(report.risks) == 1

    def test_get_report(self, manager: ReportingManager) -> None:
        """Test retrieving report."""
        report = manager.create_status_report(
            project_id="proj-1",
            summary="Test",
        )

        retrieved = manager.get_report(report.id)
        assert retrieved.id == report.id

    def test_generate_dashboard_data(
        self,
        manager: ReportingManager,
        sample_project: Project,
        sample_tasks: list,
    ) -> None:
        """Test dashboard data generation."""
        dashboard = manager.generate_dashboard_data(
            sample_project,
            sample_tasks,
        )

        assert dashboard["project_id"] == "proj-1"
        assert "health" in dashboard
        assert "progress" in dashboard
        assert "schedule" in dashboard
        assert "effort" in dashboard

    def test_dashboard_health_indicators(
        self,
        manager: ReportingManager,
        sample_project: Project,
        sample_tasks: list,
    ) -> None:
        """Test health indicators in dashboard."""
        dashboard = manager.generate_dashboard_data(
            sample_project,
            sample_tasks,
        )

        health = dashboard["health"]
        assert health["overall"] in ["RED", "AMBER", "GREEN"]
        assert health["schedule"] in ["RED", "AMBER", "GREEN"]
        assert health["budget"] in ["RED", "AMBER", "GREEN"]

    def test_dashboard_progress_tracking(
        self,
        manager: ReportingManager,
        sample_project: Project,
        sample_tasks: list,
    ) -> None:
        """Test progress tracking in dashboard."""
        dashboard = manager.generate_dashboard_data(
            sample_project,
            sample_tasks,
        )

        progress = dashboard["progress"]
        # 1 completed out of 3
        assert progress["completed_tasks"] == 1
        # 1 in progress
        assert progress["in_progress_tasks"] == 1
        # 1 todo
        assert progress["todo_tasks"] == 1
        # Average completion: (100 + 50 + 0) / 3 = 50%
        assert 40 < progress["avg_task_completion"] < 60

    def test_generate_progress_report(
        self,
        manager: ReportingManager,
        sample_tasks: list,
    ) -> None:
        """Test detailed progress report."""
        report = manager.generate_progress_report(
            project_id="proj-1",
            tasks=sample_tasks,
        )

        assert report["project_id"] == "proj-1"
        assert len(report["tasks"]) == 3
        assert all("title" in t for t in report["tasks"])
        assert all("status" in t for t in report["tasks"])

    def test_generate_velocity_report(self, manager: ReportingManager) -> None:
        """Test velocity report generation."""
        sprints = [
            ("Sprint 1", 20.0, 14),
            ("Sprint 2", 22.0, 14),
            ("Sprint 3", 25.0, 14),
        ]

        report = manager.generate_velocity_report(
            project_id="proj-1",
            completed_sprints=sprints,
        )

        assert report["project_id"] == "proj-1"
        assert len(report["sprints"]) == 3
        # Average velocity
        expected_avg = (20.0 + 22.0 + 25.0) / 3
        assert abs(report["average_velocity"] - expected_avg) < 0.1

    def test_velocity_trend_improving(self, manager: ReportingManager) -> None:
        """Test velocity trend detection (improving)."""
        sprints = [
            ("Sprint 1", 10.0, 14),
            ("Sprint 2", 15.0, 14),
            ("Sprint 3", 20.0, 14),
        ]

        report = manager.generate_velocity_report(
            project_id="proj-1",
            completed_sprints=sprints,
        )

        assert report["velocity_trend"] == "improving"

    def test_velocity_trend_declining(self, manager: ReportingManager) -> None:
        """Test velocity trend detection (declining)."""
        sprints = [
            ("Sprint 1", 20.0, 14),
            ("Sprint 2", 15.0, 14),
            ("Sprint 3", 10.0, 14),
        ]

        report = manager.generate_velocity_report(
            project_id="proj-1",
            completed_sprints=sprints,
        )

        assert report["velocity_trend"] == "declining"

    def test_generate_resource_utilization(
        self,
        manager: ReportingManager,
    ) -> None:
        """Test resource utilization report."""
        team_capacity = {
            "res-1": {
                "capacity": 40.0,
                "allocated": 40.0,
                "available": 0.0,
                "utilization": 100.0,
            },
            "res-2": {
                "capacity": 40.0,
                "allocated": 30.0,
                "available": 10.0,
                "utilization": 75.0,
            },
            "res-3": {
                "capacity": 40.0,
                "allocated": 20.0,
                "available": 20.0,
                "utilization": 50.0,
            },
        }

        report = manager.generate_resource_utilization_report(team_capacity)

        assert report["total_resources"] == 3
        assert report["overallocated"] == 0
        assert report["underutilized"] == 1
        # Average: (100 + 75 + 50) / 3
        assert 70 < report["average_utilization"] < 80

    def test_generate_variance_report(self, manager: ReportingManager) -> None:
        """Test variance report."""
        report = manager.generate_variance_report(
            cost_variance=500.0,
            schedule_variance=-200.0,
            cpi=1.1,
            spi=0.9,
        )

        assert report["cost_variance"] == 500.0
        assert report["cost_status"] == "ON_BUDGET"
        assert report["schedule_status"] == "BEHIND_SCHEDULE"
        assert report["cpi_interpretation"] == "under budget"
        assert report["spi_interpretation"] == "behind schedule"

    def test_generate_trend_report(self, manager: ReportingManager) -> None:
        """Test trend analysis report."""
        # Seed some historical data
        manager.metrics_history["proj-1"] = [
            {
                "report_date": datetime.now() - timedelta(days=10),
                "overall_status": "GREEN",
            },
            {
                "report_date": datetime.now() - timedelta(days=5),
                "overall_status": "AMBER",
            },
            {
                "report_date": datetime.now(),
                "overall_status": "AMBER",
            },
        ]

        trend = manager.generate_trend_report(
            project_id="proj-1",
            days_back=30,
        )

        assert trend["project_id"] == "proj-1"
        assert len(trend["data_points"]) > 0
        assert trend["trend"] in ["improving", "caution", "deteriorating"]

    def test_list_reports(self, manager: ReportingManager) -> None:
        """Test listing reports."""
        r1 = manager.create_status_report(
            project_id="proj-1",
            summary="Report 1",
        )
        r2 = manager.create_status_report(
            project_id="proj-1",
            summary="Report 2",
        )
        r3 = manager.create_status_report(
            project_id="proj-2",
            summary="Report 3",
        )

        # Filter by project
        proj1_reports = manager.list_reports(project_id="proj-1")

        assert len(proj1_reports) == 2
        # Most recent first
        assert proj1_reports[0].id == r2.id

    def test_schedule_health_calculation(
        self,
        manager: ReportingManager,
        sample_project: Project,
        sample_tasks: list,
    ) -> None:
        """Test schedule health calculation."""
        dashboard = manager.generate_dashboard_data(
            sample_project,
            sample_tasks,
        )

        # With overdue task, schedule should be red
        health = dashboard["health"]
        assert health["schedule"] == "RED"

    def test_effort_tracking(
        self,
        manager: ReportingManager,
        sample_project: Project,
    ) -> None:
        """Test effort tracking metrics."""
        tasks = [
            Task(
                id="task-1",
                project_id="proj-1",
                title="Task 1",
                estimated_hours=(4.0, 8.0, 12.0),
                actual_hours=10.0,
            ),
            Task(
                id="task-2",
                project_id="proj-1",
                title="Task 2",
                estimated_hours=(2.0, 4.0, 6.0),
                actual_hours=3.0,
            ),
        ]

        dashboard = manager.generate_dashboard_data(
            sample_project,
            tasks,
        )

        effort = dashboard["effort"]
        assert effort["total_estimated_hours"] > 0
        assert effort["total_actual_hours"] == 13.0
