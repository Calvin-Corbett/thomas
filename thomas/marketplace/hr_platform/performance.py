"""Performance management system with reviews, goals, and 360 feedback."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from thomas.marketplace.hr_platform._exceptions import PerformanceReviewError
from thomas.marketplace.hr_platform._types import (
    Competency,
    CompetencyLevel,
    Employee,
    Goal,
    Performance,
    ReviewCycle,
)


class ReviewCycleManager:
    """Manages performance review cycles and scheduling."""

    def __init__(self) -> None:
        """Initialize review cycle manager."""
        self.cycles: dict[str, dict] = {}

    def create_review_cycle(
        self,
        year: int,
        cycle_type: ReviewCycle,
        start_date: date,
        end_date: date,
        review_deadline: date,
    ) -> dict:
        """Create a new review cycle.

        Args:
            year: Calendar year
            cycle_type: Type of cycle (quarterly, semi-annual, annual)
            start_date: Period start date
            end_date: Period end date
            review_deadline: Deadline for submission

        Returns:
            Review cycle dictionary
        """
        cycle_id = str(uuid.uuid4())
        cycle = {
            "id": cycle_id,
            "year": year,
            "type": cycle_type.value,
            "start_date": start_date,
            "end_date": end_date,
            "review_deadline": review_deadline,
            "created_at": datetime.now(),
        }
        self.cycles[cycle_id] = cycle
        return cycle

    def get_active_cycle(self) -> dict | None:
        """Get currently active review cycle.

        Returns:
            Active cycle dictionary or None
        """
        today = date.today()
        for cycle in self.cycles.values():
            if cycle["start_date"] <= today <= cycle["end_date"]:
                return cycle
        return None


class PerformanceManager:
    """Manages performance reviews, goals, and competencies."""

    def __init__(self) -> None:
        """Initialize performance manager."""
        self.reviews: dict[str, Performance] = {}
        self.goals: dict[str, Goal] = {}
        self.competencies: dict[str, Competency] = {}
        self.feedback: dict[str, list[dict]] = {}  # employee_id -> 360 feedback
        self.pips: dict[str, dict] = {}  # Performance Improvement Plans
        self.cycle_manager = ReviewCycleManager()

    def create_goal(
        self,
        employee_id: str,
        title: str,
        description: str,
        due_date: date,
        weight: Decimal,
        target_value: str,
    ) -> Goal:
        """Create a SMART goal for employee.

        Args:
            employee_id: ID of employee
            title: Goal title
            description: Detailed description
            due_date: Target completion date
            weight: Weight in overall performance (0-100%)
            target_value: Target metric or outcome

        Returns:
            The created Goal

        Raises:
            PerformanceReviewError: If goal not SMART
        """
        goal = Goal(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            title=title,
            description=description,
            due_date=due_date,
            weight=weight,
            target_value=target_value,
        )

        if not goal.is_smart():
            raise PerformanceReviewError("Goal does not meet SMART criteria")

        self.goals[goal.id] = goal
        return goal

    def update_goal_progress(self, goal_id: str, progress: Decimal) -> Goal:
        """Update goal progress.

        Args:
            goal_id: ID of goal
            progress: Progress percentage (0-100)

        Returns:
            Updated Goal

        Raises:
            PerformanceReviewError: If goal not found
        """
        if goal_id not in self.goals:
            raise PerformanceReviewError(f"Goal {goal_id} not found")

        goal = self.goals[goal_id]
        goal.current_progress = min(progress, Decimal("100"))
        return goal

    def complete_goal(self, goal_id: str) -> Goal:
        """Mark goal as completed.

        Args:
            goal_id: ID of goal

        Returns:
            Updated Goal

        Raises:
            PerformanceReviewError: If goal not found
        """
        if goal_id not in self.goals:
            raise PerformanceReviewError(f"Goal {goal_id} not found")

        goal = self.goals[goal_id]
        goal.status = "completed"
        goal.current_progress = Decimal("100")
        return goal

    def get_employee_goals(self, employee_id: str, status: str | None = None) -> list[Goal]:
        """Get all goals for an employee.

        Args:
            employee_id: ID of employee
            status: Optional status filter

        Returns:
            List of goals
        """
        goals = [g for g in self.goals.values() if g.employee_id == employee_id]
        if status:
            goals = [g for g in goals if g.status == status]
        return goals

    def create_competency(
        self,
        name: str,
        description: str,
        category: str,
    ) -> Competency:
        """Create a competency definition.

        Args:
            name: Competency name
            description: Description
            category: Category (technical, behavioral, domain)

        Returns:
            The created Competency
        """
        comp = Competency(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            category=category,
        )
        self.competencies[comp.id] = comp
        return comp

    def create_performance_review(
        self,
        employee_id: str,
        reviewer_id: str,
        rating: Decimal,
        overall_comments: str,
        review_cycle: ReviewCycle,
    ) -> Performance:
        """Create a performance review.

        Args:
            employee_id: ID of employee being reviewed
            reviewer_id: ID of reviewer
            rating: Performance rating (1-5)
            overall_comments: Reviewer comments
            review_cycle: Review cycle type

        Returns:
            The created Performance review

        Raises:
            PerformanceReviewError: If rating invalid
        """
        if not (Decimal("1") <= rating <= Decimal("5")):
            raise PerformanceReviewError("Rating must be between 1 and 5")

        review = Performance(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            reviewer_id=reviewer_id,
            rating=rating,
            overall_comments=overall_comments,
            review_cycle=review_cycle,
        )

        if not review.is_valid_rating():
            raise PerformanceReviewError("Invalid performance rating")

        self.reviews[review.id] = review
        return review

    def add_goal_to_review(self, review_id: str, goal_id: str) -> Performance:
        """Link a goal to a performance review.

        Args:
            review_id: ID of review
            goal_id: ID of goal

        Returns:
            Updated Performance review

        Raises:
            PerformanceReviewError: If review not found
        """
        if review_id not in self.reviews:
            raise PerformanceReviewError(f"Review {review_id} not found")

        review = self.reviews[review_id]
        if goal_id not in review.goals:
            review.goals.append(goal_id)

        return review

    def add_competency_assessment(
        self,
        review_id: str,
        competency_id: str,
        level: CompetencyLevel,
    ) -> Performance:
        """Add competency assessment to review.

        Args:
            review_id: ID of review
            competency_id: ID of competency
            level: Proficiency level

        Returns:
            Updated Performance review

        Raises:
            PerformanceReviewError: If review not found
        """
        if review_id not in self.reviews:
            raise PerformanceReviewError(f"Review {review_id} not found")

        review = self.reviews[review_id]
        comp_name = self.competencies.get(competency_id, {}).name or competency_id
        review.competencies.append((comp_name, level))

        return review

    def add_360_feedback(
        self,
        employee_id: str,
        feedback_type: str,
        feedback_text: str,
        submitter_id: str,
    ) -> dict:
        """Submit 360-degree feedback for employee.

        Args:
            employee_id: ID of employee receiving feedback
            feedback_type: Type (peer, manager, direct_report)
            feedback_text: Feedback content
            submitter_id: ID of feedback submitter

        Returns:
            Feedback record dictionary
        """
        if employee_id not in self.feedback:
            self.feedback[employee_id] = []

        feedback_item = {
            "id": str(uuid.uuid4()),
            "type": feedback_type,
            "text": feedback_text,
            "submitter_id": submitter_id,
            "submitted_at": datetime.now(),
        }

        self.feedback[employee_id].append(feedback_item)
        return feedback_item

    def get_360_feedback(self, employee_id: str) -> list[dict]:
        """Get all 360 feedback for an employee.

        Args:
            employee_id: ID of employee

        Returns:
            List of feedback items
        """
        return self.feedback.get(employee_id, [])

    def aggregate_360_feedback(self, employee_id: str) -> dict[str, list[str]]:
        """Aggregate 360 feedback by source type.

        Args:
            employee_id: ID of employee

        Returns:
            Dictionary of feedback_type -> list of feedback
        """
        feedback = self.get_360_feedback(employee_id)
        aggregated: dict[str, list[str]] = {}

        for item in feedback:
            ftype = item["type"]
            if ftype not in aggregated:
                aggregated[ftype] = []
            aggregated[ftype].append(item["text"])

        return aggregated

    def calibrate_ratings(self, employee_ids: list[str]) -> dict[str, tuple[Decimal, Decimal]]:
        """Calibrate performance ratings to enforce bell curve.

        Uses normal distribution: 10% exceeds, 20% exceeds, 20% meets+, etc.

        Args:
            employee_ids: IDs of employees to calibrate

        Returns:
            Dictionary of employee_id -> (original_rating, calibrated_rating)
        """
        reviews = [r for r in self.reviews.values() if r.employee_id in employee_ids]

        if not reviews:
            return {}

        # Sort by original rating
        reviews.sort(key=lambda r: r.rating)

        # Calculate calibrated ratings (bell curve)
        distribution = [5, 5, 4, 4, 3, 3, 2, 2, 1, 1]  # 10 buckets
        calibrated: dict[str, tuple[Decimal, Decimal]] = {}

        for idx, review in enumerate(reviews):
            bucket = min(idx // max(1, len(reviews) // 10), 9)
            new_rating = Decimal(str(distribution[bucket]))
            calibrated[review.employee_id] = (review.rating, new_rating)
            review.rating = new_rating

        return calibrated

    def create_pip(
        self,
        employee_id: str,
        manager_id: str,
        performance_issues: list[str],
        goals: list[str],
        duration_weeks: int = 12,
    ) -> dict:
        """Create a Performance Improvement Plan.

        Args:
            employee_id: ID of employee on PIP
            manager_id: ID of manager
            performance_issues: List of issues to address
            goals: Goals to achieve
            duration_weeks: Duration of PIP (typically 12)

        Returns:
            PIP record dictionary
        """
        pip_id = str(uuid.uuid4())
        pip = {
            "id": pip_id,
            "employee_id": employee_id,
            "manager_id": manager_id,
            "issues": performance_issues,
            "goals": goals,
            "duration_weeks": duration_weeks,
            "start_date": date.today(),
            "end_date": date.today() + timedelta(weeks=duration_weeks),
            "status": "active",
            "created_at": datetime.now(),
        }
        self.pips[pip_id] = pip
        return pip

    def close_pip(self, pip_id: str, successful: bool, comments: str = "") -> dict:
        """Close a Performance Improvement Plan.

        Args:
            pip_id: ID of PIP
            successful: Whether employee met PIP goals
            comments: Closing comments

        Returns:
            Updated PIP record

        Raises:
            PerformanceReviewError: If PIP not found
        """
        if pip_id not in self.pips:
            raise PerformanceReviewError(f"PIP {pip_id} not found")

        pip = self.pips[pip_id]
        pip["status"] = "completed"
        pip["successful"] = successful
        pip["closing_comments"] = comments
        pip["closed_at"] = datetime.now()

        return pip

    def succession_plan(self, position_id: str, department_employees: list[Employee]) -> list[tuple[Employee, Decimal]]:
        """Generate succession plan for a position.

        Args:
            position_id: ID of position
            department_employees: Employees to consider

        Returns:
            Ranked list of (Employee, readiness_score) tuples
        """
        candidates: list[tuple[Employee, Decimal]] = []

        for emp in department_employees:
            # Readiness based on reviews and tenure
            recent_reviews = [r for r in self.reviews.values() if r.employee_id == emp.id]

            if not recent_reviews:
                score = Decimal("0")
            else:
                avg_rating = sum(r.rating for r in recent_reviews) / len(recent_reviews)
                tenure_score = min(
                    Decimal(str(emp.years_of_service())) / Decimal("5"),
                    Decimal("1"),
                )
                score = (avg_rating / Decimal("5")) * Decimal("50") + (tenure_score * Decimal("50"))

            candidates.append((emp, score.quantize(Decimal("0.01"))))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def get_employee_reviews(self, employee_id: str) -> list[Performance]:
        """Get all performance reviews for an employee.

        Args:
            employee_id: ID of employee

        Returns:
            List of reviews sorted by date
        """
        reviews = [r for r in self.reviews.values() if r.employee_id == employee_id]
        reviews.sort(key=lambda r: r.created_at)
        return reviews
