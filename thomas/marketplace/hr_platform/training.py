"""Learning management system with training, certifications, and skill development."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from thomas.marketplace.hr_platform._exceptions import HRException
from thomas.marketplace.hr_platform._types import Training


class SkillGapAnalysis:
    """Analyzes skill gaps for employees."""

    def __init__(self, required_skills: dict[str, int], actual_skills: dict[str, int]) -> None:
        """Initialize skill gap analysis.

        Args:
            required_skills: Skill -> required proficiency level (1-5)
            actual_skills: Skill -> actual proficiency level (1-5)
        """
        self.required_skills = required_skills
        self.actual_skills = actual_skills

    def gap_analysis(self) -> dict[str, int]:
        """Calculate skill gaps.

        Returns:
            Dictionary of skill -> gap (negative means above requirement)
        """
        gaps: dict[str, int] = {}

        for skill, required_level in self.required_skills.items():
            actual_level = self.actual_skills.get(skill, 0)
            gaps[skill] = required_level - actual_level

        return gaps

    def training_priority(self) -> list[tuple[str, int]]:
        """Get ranked list of skills to train on.

        Returns:
            Sorted list of (skill, gap_size) tuples
        """
        gaps = self.gap_analysis()
        priority = [(skill, gap) for skill, gap in gaps.items() if gap > 0]
        priority.sort(key=lambda x: x[1], reverse=True)
        return priority


class CourseCatalog:
    """Maintains course offerings."""

    def __init__(self) -> None:
        """Initialize course catalog."""
        self.courses: dict[str, dict] = {}

    def add_course(
        self,
        name: str,
        provider: str,
        duration_hours: int,
        cost: Decimal,
        description: str,
        skills_taught: list[str],
    ) -> dict:
        """Add a course to catalog.

        Args:
            name: Course name
            provider: Training provider
            duration_hours: Course duration
            cost: Cost per student
            description: Course description
            skills_taught: Skills covered

        Returns:
            Course record dictionary
        """
        course_id = str(uuid.uuid4())
        course = {
            "id": course_id,
            "name": name,
            "provider": provider,
            "duration_hours": duration_hours,
            "cost": cost,
            "description": description,
            "skills_taught": skills_taught,
            "created_at": datetime.now(),
        }
        self.courses[course_id] = course
        return course

    def find_courses_by_skill(self, skill: str) -> list[dict]:
        """Find courses that teach a specific skill.

        Args:
            skill: Skill name

        Returns:
            List of relevant courses
        """
        return [c for c in self.courses.values() if skill.lower() in [s.lower() for s in c["skills_taught"]]]


class TrainingManager:
    """Manages employee training and development."""

    def __init__(self) -> None:
        """Initialize training manager."""
        self.trainings: dict[str, Training] = {}
        self.enrollments: dict[str, list[str]] = {}  # course_id -> employee_ids
        self.catalog = CourseCatalog()

    def enroll_employee(
        self,
        employee_id: str,
        course_name: str,
        provider: str,
        cost: Decimal = Decimal("0"),
        course_type: str = "development",
    ) -> Training:
        """Enroll employee in training.

        Args:
            employee_id: ID of employee
            course_name: Name of course
            provider: Training provider
            cost: Cost of course
            course_type: Type (development, compliance, certification)

        Returns:
            The created Training record
        """
        training = Training(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            course_name=course_name,
            provider=provider,
            cost=cost,
            course_type=course_type,
            status="enrolled",
        )

        self.trainings[training.id] = training
        return training

    def start_training(self, training_id: str) -> Training:
        """Mark training as in progress.

        Args:
            training_id: ID of training record

        Returns:
            Updated Training

        Raises:
            HRException: If training not found
        """
        if training_id not in self.trainings:
            raise HRException(f"Training {training_id} not found")

        training = self.trainings[training_id]
        training.status = "in_progress"
        return training

    def complete_training(
        self,
        training_id: str,
        completion_date: date | None = None,
        expiry_date: date | None = None,
    ) -> Training:
        """Mark training as completed.

        Args:
            training_id: ID of training record
            completion_date: Date completed (defaults to today)
            expiry_date: Date certification expires (if applicable)

        Returns:
            Updated Training

        Raises:
            HRException: If training not found
        """
        if training_id not in self.trainings:
            raise HRException(f"Training {training_id} not found")

        training = self.trainings[training_id]
        if completion_date is None:
            completion_date = date.today()

        training.completion_date = completion_date
        training.expiry_date = expiry_date
        training.status = "completed"
        return training

    def record_kirkpatrick_evaluation(
        self,
        training_id: str,
        level1: int | None = None,
        level2: int | None = None,
        level3: int | None = None,
        level4: int | None = None,
    ) -> Training:
        """Record Kirkpatrick model evaluation scores.

        Args:
            training_id: ID of training record
            level1: Reaction (1-5 rating)
            level2: Learning (test score 0-100)
            level3: Behavior (application score 0-100)
            level4: Business impact (ROI 0-100)

        Returns:
            Updated Training

        Raises:
            HRException: If training not found
        """
        if training_id not in self.trainings:
            raise HRException(f"Training {training_id} not found")

        training = self.trainings[training_id]
        training.kirkpatrick_level1 = level1
        training.kirkpatrick_level2 = level2
        training.kirkpatrick_level3 = level3
        training.kirkpatrick_level4 = level4
        return training

    def get_employee_trainings(self, employee_id: str, status: str | None = None) -> list[Training]:
        """Get trainings for an employee.

        Args:
            employee_id: ID of employee
            status: Optional status filter

        Returns:
            List of trainings
        """
        trainings = [t for t in self.trainings.values() if t.employee_id == employee_id]
        if status:
            trainings = [t for t in trainings if t.status == status]
        return trainings

    def get_valid_certifications(self, employee_id: str) -> list[Training]:
        """Get valid (non-expired) certifications for employee.

        Args:
            employee_id: ID of employee

        Returns:
            List of current certifications
        """
        trainings = self.get_employee_trainings(employee_id, "completed")
        return [t for t in trainings if t.is_current()]

    def analyze_skill_gaps(
        self,
        employee_id: str,
        position_requirements: dict[str, int],
    ) -> SkillGapAnalysis:
        """Analyze skill gaps for employee in position.

        Args:
            employee_id: ID of employee
            position_requirements: Skill -> required level

        Returns:
            SkillGapAnalysis object
        """
        trainings = self.get_valid_certifications(employee_id)
        actual_skills: dict[str, int] = {}

        for training in trainings:
            if training.course_type == "certification":
                actual_skills[training.course_name] = 3  # Assume competent

        return SkillGapAnalysis(position_requirements, actual_skills)

    def recommend_training_path(
        self,
        employee_id: str,
        target_role_requirements: dict[str, int],
    ) -> list[dict]:
        """Generate recommended training path for role progression.

        Args:
            employee_id: ID of employee
            target_role_requirements: Required skills for target role

        Returns:
            List of recommended courses
        """
        gap_analysis = self.analyze_skill_gaps(employee_id, target_role_requirements)
        priority = gap_analysis.training_priority()

        recommendations = []
        for skill, gap_size in priority[:5]:  # Top 5 skills
            courses = self.catalog.find_courses_by_skill(skill)
            if courses:
                recommendations.append(courses[0])

        return recommendations

    def calculate_training_budget_utilization(
        self,
        department_budget: Decimal,
        department_employee_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, any]:
        """Calculate training budget utilization for department.

        Args:
            department_budget: Annual training budget
            department_employee_ids: IDs of employees in department
            start_date: Period start
            end_date: Period end

        Returns:
            Budget utilization metrics
        """
        total_cost = Decimal("0")
        training_count = 0

        for emp_id in department_employee_ids:
            trainings = self.get_employee_trainings(emp_id)
            for training in trainings:
                if training.completion_date and start_date <= training.completion_date <= end_date:
                    total_cost += training.cost
                    training_count += 1

        remaining = department_budget - total_cost
        utilization_percent = (
            total_cost / department_budget * Decimal("100") if department_budget > 0 else Decimal("0")
        ).quantize(Decimal("0.01"))

        return {
            "budget": department_budget,
            "spent": total_cost,
            "remaining": remaining,
            "utilization_percent": utilization_percent,
            "training_count": training_count,
            "avg_cost_per_training": (total_cost / Decimal(str(max(1, training_count)))).quantize(Decimal("0.01")),
        }

    def get_certification_expiry_report(self, warning_days: int = 60) -> list[tuple[Training, int]]:
        """Get certifications expiring soon.

        Args:
            warning_days: Days before expiry to flag

        Returns:
            List of (Training, days_until_expiry) tuples
        """
        expiring: list[tuple[Training, int]] = []
        today = date.today()
        cutoff = today + timedelta(days=warning_days)

        for training in self.trainings.values():
            if training.expiry_date and today <= training.expiry_date <= cutoff:
                days_until = (training.expiry_date - today).days
                expiring.append((training, days_until))

        expiring.sort(key=lambda x: x[1])
        return expiring

    def get_training_effectiveness(self, course_name: str) -> dict[str, any]:
        """Calculate effectiveness metrics for a course.

        Args:
            course_name: Name of course

        Returns:
            Effectiveness metrics dictionary
        """
        trainings = [t for t in self.trainings.values() if t.course_name == course_name and t.status == "completed"]

        if not trainings:
            return {"course": course_name, "samples": 0}

        level1_scores = [t.kirkpatrick_level1 for t in trainings if t.kirkpatrick_level1]
        level2_scores = [t.kirkpatrick_level2 for t in trainings if t.kirkpatrick_level2]
        level3_scores = [t.kirkpatrick_level3 for t in trainings if t.kirkpatrick_level3]
        level4_scores = [t.kirkpatrick_level4 for t in trainings if t.kirkpatrick_level4]

        return {
            "course": course_name,
            "total_completions": len(trainings),
            "level1_satisfaction": (sum(level1_scores) / len(level1_scores) if level1_scores else None),
            "level2_learning": (sum(level2_scores) / len(level2_scores) if level2_scores else None),
            "level3_application": (sum(level3_scores) / len(level3_scores) if level3_scores else None),
            "level4_impact": (sum(level4_scores) / len(level4_scores) if level4_scores else None),
        }
