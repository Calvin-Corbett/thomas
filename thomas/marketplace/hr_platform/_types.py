"""Core data types for HR platform.

Defines all primary data structures used throughout the HR management system.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class EmploymentStatus(Enum):
    """Employment status lifecycle states."""

    HIRED = "hired"
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"
    ALUMNI = "alumni"


class LeaveType(Enum):
    """Types of leave employees can request."""

    VACATION = "vacation"
    SICK = "sick"
    PERSONAL = "personal"
    PARENTAL = "parental"
    BEREAVEMENT = "bereavement"
    JURY_DUTY = "jury_duty"
    SABBATICAL = "sabbatical"
    MEDICAL = "medical"


class BenefitType(Enum):
    """Types of benefits offered."""

    HEALTH_INSURANCE = "health_insurance"
    DENTAL_INSURANCE = "dental_insurance"
    VISION_INSURANCE = "vision_insurance"
    LIFE_INSURANCE = "life_insurance"
    RETIREMENT_401K = "retirement_401k"
    FSA = "fsa"
    HSA = "hsa"
    DISABILITY = "disability"


class CompetencyLevel(Enum):
    """Skill competency levels."""

    NOVICE = 1
    BEGINNER = 2
    COMPETENT = 3
    PROFICIENT = 4
    EXPERT = 5


class ReviewCycle(Enum):
    """Performance review cycle types."""

    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"


@dataclass
class Department:
    """Department information."""

    id: str
    name: str
    code: str
    manager_id: str | None = None
    parent_department_id: str | None = None
    budget_annual: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        """Validate department data."""
        if not self.name or not self.code:
            raise ValueError("Department name and code required")


@dataclass
class Position:
    """Job position definition."""

    id: str
    title: str
    department_id: str
    level: str
    salary_min: Decimal
    salary_max: Decimal
    salary_mid: Decimal
    fte: Decimal = Decimal("1.00")
    reports_to_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        """Validate position salary ranges."""
        if not (self.salary_min <= self.salary_mid <= self.salary_max):
            raise ValueError("Salary mid must be between min and max")
        if not Decimal("0") < self.fte <= Decimal("1"):
            raise ValueError("FTE must be between 0 and 1")


@dataclass
class Employee:
    """Employee record with complete profile."""

    id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    ssn: str  # Stored encrypted in production
    date_of_birth: date
    gender: str
    position_id: str
    department_id: str
    status: EmploymentStatus = EmploymentStatus.ACTIVE
    hire_date: date = field(default_factory=date.today)
    termination_date: date | None = None
    manager_id: str | None = None
    salary: Decimal = Decimal("0.00")
    pay_frequency: str = "biweekly"  # biweekly, monthly, hourly
    benefits_enrolled: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def full_name(self) -> str:
        """Return full name."""
        return f"{self.first_name} {self.last_name}"

    def is_active(self) -> bool:
        """Check if employee is currently active."""
        return self.status == EmploymentStatus.ACTIVE

    def years_of_service(self) -> float:
        """Calculate years of service."""
        today = date.today()
        diff = today - self.hire_date
        return diff.days / 365.25

    def age(self) -> int:
        """Calculate employee age."""
        today = date.today()
        return (
            today.year
            - self.date_of_birth.year
            - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        )


@dataclass
class PayrollRecord:
    """Individual payroll calculation record."""

    id: str
    employee_id: str
    pay_period_start: date
    pay_period_end: date
    gross_salary: Decimal
    federal_tax: Decimal
    state_tax: Decimal
    social_security_tax: Decimal
    medicare_tax: Decimal
    pre_tax_deductions: Decimal  # 401k, health insurance
    post_tax_deductions: Decimal  # garnishments
    net_salary: Decimal
    overtime_hours: Decimal = Decimal("0.00")
    overtime_pay: Decimal = Decimal("0.00")
    bonus: Decimal = Decimal("0.00")
    year_to_date: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=datetime.now)

    def total_deductions(self) -> Decimal:
        """Calculate total deductions."""
        taxes = self.federal_tax + self.state_tax + self.social_security_tax + self.medicare_tax
        return taxes + self.pre_tax_deductions + self.post_tax_deductions


@dataclass
class Benefit:
    """Benefit enrollment record."""

    id: str
    employee_id: str
    benefit_type: BenefitType
    plan_name: str
    monthly_cost_employee: Decimal
    monthly_cost_employer: Decimal
    effective_date: date
    termination_date: date | None = None
    dependents: list[str] = field(default_factory=list)
    coverage_level: str = "employee"  # employee, family, employee+spouse
    created_at: datetime = field(default_factory=datetime.now)

    def is_active(self, check_date: date = None) -> bool:
        """Check if benefit is active on given date."""
        if check_date is None:
            check_date = date.today()
        if check_date < self.effective_date:
            return False
        if self.termination_date and check_date > self.termination_date:
            return False
        return True


@dataclass
class LeaveRequest:
    """Employee leave request."""

    id: str
    employee_id: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    days_requested: Decimal
    status: str = "requested"  # requested, approved, rejected, taken, cancelled
    approver_id: str | None = None
    reason: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def duration_days(self) -> int:
        """Calculate duration in days."""
        return (self.end_date - self.start_date).days + 1


@dataclass
class TimeEntry:
    """Time tracking record."""

    id: str
    employee_id: str
    date: date
    clock_in: datetime
    clock_out: datetime | None = None
    break_minutes: int = 0
    billable: bool = True
    project_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def hours_worked(self) -> Decimal:
        """Calculate hours worked."""
        if not self.clock_out:
            return Decimal("0.00")
        minutes = (self.clock_out - self.clock_in).total_seconds() / 60
        minutes -= self.break_minutes
        return Decimal(str(round(minutes / 60, 2)))


@dataclass
class Goal:
    """SMART goal for employee."""

    id: str
    employee_id: str
    title: str
    description: str
    due_date: date
    weight: Decimal  # Percentage contribution to overall performance
    target_value: str  # Quantitative or qualitative target
    current_progress: Decimal = Decimal("0.00")
    status: str = "active"  # active, completed, cancelled
    created_at: datetime = field(default_factory=datetime.now)

    def is_smart(self) -> bool:
        """Validate SMART criteria: Specific, Measurable, Achievable, Relevant, Time-bound."""
        has_title = bool(self.title)
        has_target = bool(self.target_value)
        has_due_date = self.due_date >= date.today()
        return has_title and has_target and has_due_date


@dataclass
class Competency:
    """Skill or competency."""

    id: str
    name: str
    description: str
    category: str  # technical, behavioral, domain
    proficiency_level: CompetencyLevel = CompetencyLevel.NOVICE
    validated: bool = False
    validation_date: date | None = None

    def __post_init__(self) -> None:
        """Validate competency."""
        if not self.name:
            raise ValueError("Competency name required")


@dataclass
class Performance:
    """Performance review record."""

    id: str
    employee_id: str
    reviewer_id: str
    review_cycle: ReviewCycle
    rating: Decimal  # 1-5 scale
    overall_comments: str
    goals: list[str] = field(default_factory=list)
    competencies: list[tuple[str, CompetencyLevel]] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    development_areas: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def is_valid_rating(self) -> bool:
        """Validate performance rating."""
        return Decimal("1.0") <= self.rating <= Decimal("5.0")


@dataclass
class Training:
    """Training course or certification."""

    id: str
    employee_id: str
    course_name: str
    provider: str
    completion_date: date | None = None
    expiry_date: date | None = None
    cost: Decimal = Decimal("0.00")
    course_type: str = "development"  # development, compliance, certification
    status: str = "enrolled"  # enrolled, in_progress, completed, expired
    kirkpatrick_level1: int | None = None  # Reaction (1-5 rating)
    kirkpatrick_level2: int | None = None  # Learning (test score 0-100)
    kirkpatrick_level3: int | None = None  # Behavior application (0-100)
    kirkpatrick_level4: int | None = None  # Business impact (0-100)

    def is_current(self) -> bool:
        """Check if certification is currently valid."""
        if not self.completion_date:
            return False
        if self.expiry_date and date.today() > self.expiry_date:
            return False
        return True


@dataclass
class Candidate:
    """Job candidate for recruitment tracking."""

    id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    position_id: str
    resume_keywords: list[str] = field(default_factory=list)
    source: str = ""  # job_board, referral, linkedin, etc
    status: str = "applied"  # applied, screened, interviewed, offered, hired, rejected
    current_stage: int = 0  # Pipeline stage number
    interview_scores: list[Decimal] = field(default_factory=list)
    offer_extended_date: date | None = None
    hire_date: date | None = None
    rejection_reason: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def full_name(self) -> str:
        """Return full name."""
        return f"{self.first_name} {self.last_name}"

    def match_score(self, required_keywords: list[str]) -> Decimal:
        """Calculate resume match score as percentage."""
        if not required_keywords:
            return Decimal("100.00")
        resume_kw_lower = [kw.lower() for kw in self.resume_keywords]
        matches = sum(1 for kw in required_keywords if kw.lower() in resume_kw_lower)
        return Decimal(str(round((matches / len(required_keywords)) * 100, 2)))


@dataclass
class Interview:
    """Interview record."""

    id: str
    candidate_id: str
    position_id: str
    interviewer_id: str
    interview_date: datetime
    interview_type: str  # phone, video, in_person
    duration_minutes: int
    rating: Decimal  # 1-5 scale
    feedback: str
    scorecard: dict[str, int] = field(default_factory=dict)  # criterion -> score
    recommended: bool = False
    created_at: datetime = field(default_factory=datetime.now)

    def average_score(self) -> Decimal:
        """Calculate average scorecard score."""
        if not self.scorecard:
            return Decimal("0.00")
        total = sum(self.scorecard.values())
        avg = total / len(self.scorecard)
        return Decimal(str(round(avg, 2)))
