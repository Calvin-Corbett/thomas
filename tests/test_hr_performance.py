"""Tests for performance management system."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.hr_platform._exceptions import PerformanceReviewError
from thomas.marketplace.hr_platform._types import CompetencyLevel, Employee, ReviewCycle
from thomas.marketplace.hr_platform.performance import PerformanceManager, ReviewCycleManager


class TestPerformanceManager:
    """Test performance management functionality."""

    @pytest.fixture
    def manager(self) -> PerformanceManager:
        """Create performance manager."""
        return PerformanceManager()

    @pytest.fixture
    def employee(self) -> Employee:
        """Create test employee."""
        return Employee(
            id="emp1",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            phone="555-1234",
            ssn="123-45-6789",
            date_of_birth=date(1990, 1, 15),
            gender="M",
            position_id="pos1",
            department_id="dept1",
            salary=Decimal("100000"),
        )

    def test_create_goal(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test creating SMART goal."""
        goal = manager.create_goal(
            employee.id,
            "Increase test coverage",
            "Improve code quality by increasing test coverage",
            date(2026, 12, 31),
            Decimal("25"),
            "90% coverage",
        )

        assert goal.employee_id == employee.id
        assert goal.is_smart()

    def test_invalid_goal_not_smart(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test error for non-SMART goal."""
        with pytest.raises(PerformanceReviewError):
            manager.create_goal(
                employee.id,
                "",  # Missing title
                "Do better",
                date(2026, 12, 31),
                Decimal("25"),
                "Get better",
            )

    def test_update_goal_progress(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test updating goal progress."""
        goal = manager.create_goal(
            employee.id,
            "Increase test coverage",
            "Improve code quality",
            date(2026, 12, 31),
            Decimal("25"),
            "90% coverage",
        )

        updated = manager.update_goal_progress(goal.id, Decimal("50"))

        assert updated.current_progress == Decimal("50")

    def test_complete_goal(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test completing goal."""
        goal = manager.create_goal(
            employee.id,
            "Increase test coverage",
            "Improve code quality",
            date(2026, 12, 31),
            Decimal("25"),
            "90% coverage",
        )

        completed = manager.complete_goal(goal.id)

        assert completed.status == "completed"
        assert completed.current_progress == Decimal("100")

    def test_get_employee_goals(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test retrieving employee goals."""
        goal1 = manager.create_goal(
            employee.id,
            "Goal 1",
            "Description 1",
            date(2026, 12, 31),
            Decimal("25"),
            "Target 1",
        )

        goal2 = manager.create_goal(
            employee.id,
            "Goal 2",
            "Description 2",
            date(2026, 12, 31),
            Decimal("25"),
            "Target 2",
        )

        goals = manager.get_employee_goals(employee.id)

        assert len(goals) == 2

    def test_filter_goals_by_status(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test filtering goals by status."""
        goal1 = manager.create_goal(
            employee.id,
            "Goal 1",
            "Description 1",
            date(2026, 12, 31),
            Decimal("25"),
            "Target 1",
        )

        manager.complete_goal(goal1.id)

        active = manager.get_employee_goals(employee.id, "active")
        completed = manager.get_employee_goals(employee.id, "completed")

        assert len(active) == 0
        assert len(completed) == 1

    def test_create_competency(self, manager: PerformanceManager) -> None:
        """Test creating competency."""
        comp = manager.create_competency(
            "Python Programming",
            "Proficiency in Python language",
            "technical",
        )

        assert comp.name == "Python Programming"
        assert comp.category == "technical"

    def test_create_performance_review(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test creating performance review."""
        review = manager.create_performance_review(
            employee.id,
            "mgr1",
            Decimal("4.0"),
            "Strong performer, good team player",
            ReviewCycle.ANNUAL,
        )

        assert review.employee_id == employee.id
        assert review.rating == Decimal("4.0")
        assert review.is_valid_rating()

    def test_invalid_review_rating(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test error for invalid rating."""
        with pytest.raises(PerformanceReviewError):
            manager.create_performance_review(
                employee.id,
                "mgr1",
                Decimal("6.0"),  # Invalid: > 5
                "Comment",
                ReviewCycle.ANNUAL,
            )

    def test_add_goal_to_review(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test linking goal to review."""
        goal = manager.create_goal(
            employee.id,
            "Goal 1",
            "Description",
            date(2026, 12, 31),
            Decimal("25"),
            "Target",
        )

        review = manager.create_performance_review(
            employee.id,
            "mgr1",
            Decimal("4.0"),
            "Good",
            ReviewCycle.ANNUAL,
        )

        updated = manager.add_goal_to_review(review.id, goal.id)

        assert goal.id in updated.goals

    def test_add_competency_assessment(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test adding competency assessment."""
        comp = manager.create_competency(
            "Python",
            "Python programming",
            "technical",
        )

        review = manager.create_performance_review(
            employee.id,
            "mgr1",
            Decimal("4.0"),
            "Good",
            ReviewCycle.ANNUAL,
        )

        updated = manager.add_competency_assessment(
            review.id,
            comp.id,
            CompetencyLevel.PROFICIENT,
        )

        assert len(updated.competencies) == 1

    def test_add_360_feedback(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test recording 360 feedback."""
        feedback = manager.add_360_feedback(
            employee.id,
            "peer",
            "Great collaborator",
            "peer1",
        )

        assert feedback["type"] == "peer"
        assert "Great" in feedback["text"]

    def test_get_360_feedback(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test retrieving 360 feedback."""
        manager.add_360_feedback(employee.id, "peer", "Good team player", "peer1")
        manager.add_360_feedback(employee.id, "manager", "Meets expectations", "mgr1")

        feedback = manager.get_360_feedback(employee.id)

        assert len(feedback) == 2

    def test_aggregate_360_feedback(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test aggregating 360 feedback by source."""
        manager.add_360_feedback(employee.id, "peer", "Good", "peer1")
        manager.add_360_feedback(employee.id, "peer", "Excellent", "peer2")
        manager.add_360_feedback(employee.id, "manager", "Meets goals", "mgr1")

        aggregated = manager.aggregate_360_feedback(employee.id)

        assert len(aggregated["peer"]) == 2
        assert len(aggregated["manager"]) == 1

    def test_calibrate_ratings(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test performance rating calibration."""
        emp1 = employee
        emp2 = Employee(
            id="emp2",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            phone="555-5678",
            ssn="987-65-4321",
            date_of_birth=date(1992, 6, 20),
            gender="F",
            position_id="pos1",
            department_id="dept1",
            salary=Decimal("100000"),
        )

        rev1 = manager.create_performance_review(emp1.id, "mgr1", Decimal("5.0"), "Excellent", ReviewCycle.ANNUAL)

        rev2 = manager.create_performance_review(emp2.id, "mgr1", Decimal("3.0"), "Good", ReviewCycle.ANNUAL)

        calibrated = manager.calibrate_ratings([emp1.id, emp2.id])

        assert emp1.id in calibrated
        assert emp2.id in calibrated

    def test_create_pip(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test creating Performance Improvement Plan."""
        pip = manager.create_pip(
            employee.id,
            "mgr1",
            ["Missed deadlines", "Quality issues"],
            ["Meet all deadlines", "Improve code quality"],
            12,
        )

        assert pip["employee_id"] == employee.id
        assert pip["status"] == "active"

    def test_close_pip(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test closing PIP."""
        pip = manager.create_pip(
            employee.id,
            "mgr1",
            ["Issue"],
            ["Goal"],
        )

        closed = manager.close_pip(pip["id"], True, "Employee improved significantly")

        assert closed["status"] == "completed"
        assert closed["successful"]

    def test_succession_plan(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test succession planning."""
        emp1 = employee
        emp2 = Employee(
            id="emp2",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            phone="555-5678",
            ssn="987-65-4321",
            date_of_birth=date(1992, 6, 20),
            gender="F",
            position_id="pos1",
            department_id="dept1",
            salary=Decimal("100000"),
            hire_date=date(2015, 1, 1),  # 9 years tenure
        )

        manager.create_performance_review(emp1.id, "mgr1", Decimal("4.5"), "Strong", ReviewCycle.ANNUAL)

        manager.create_performance_review(emp2.id, "mgr1", Decimal("3.0"), "Good", ReviewCycle.ANNUAL)

        succession = manager.succession_plan("pos1", [emp1, emp2])

        assert len(succession) == 2
        # Should be sorted by score (which favors higher rating and tenure)
        assert succession[0][1] >= succession[1][1]

    def test_get_employee_reviews(self, manager: PerformanceManager, employee: Employee) -> None:
        """Test retrieving employee review history."""
        manager.create_performance_review(employee.id, "mgr1", Decimal("4.0"), "Good", ReviewCycle.ANNUAL)

        manager.create_performance_review(
            employee.id, "mgr1", Decimal("3.5"), "Meets expectations", ReviewCycle.QUARTERLY
        )

        reviews = manager.get_employee_reviews(employee.id)

        assert len(reviews) == 2

    def test_review_cycle_manager(self) -> None:
        """Test review cycle management."""
        cycle_mgr = ReviewCycleManager()

        cycle = cycle_mgr.create_review_cycle(
            2024,
            ReviewCycle.ANNUAL,
            date(2024, 1, 1),
            date(2026, 12, 31),
            date(2024, 12, 15),
        )

        assert cycle["type"] == "annual"

    def test_invalid_goal_id(self, manager: PerformanceManager) -> None:
        """Test error for invalid goal ID."""
        with pytest.raises(PerformanceReviewError):
            manager.update_goal_progress("invalid", Decimal("50"))

    def test_invalid_review_id(self, manager: PerformanceManager) -> None:
        """Test error for invalid review ID."""
        with pytest.raises(PerformanceReviewError):
            manager.add_goal_to_review("invalid", "goal1")
