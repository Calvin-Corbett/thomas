"""HR Management and People Operations Platform.

A comprehensive HR management system supporting employee lifecycle, payroll,
benefits, recruitment, performance management, and analytics.
"""

from thomas.marketplace.hr_platform._exceptions import (
    EmployeeNotFoundError,
    HRException,
    LeaveBalanceError,
    PayrollCalculationError,
)
from thomas.marketplace.hr_platform._types import (
    Benefit,
    BenefitType,
    Candidate,
    Competency,
    Department,
    Employee,
    EmploymentStatus,
    Goal,
    Interview,
    LeaveRequest,
    LeaveType,
    PayrollRecord,
    Performance,
    Position,
    TimeEntry,
    Training,
)

__all__ = [
    "Employee",
    "EmploymentStatus",
    "Department",
    "Position",
    "PayrollRecord",
    "Benefit",
    "BenefitType",
    "LeaveRequest",
    "LeaveType",
    "TimeEntry",
    "Performance",
    "Goal",
    "Competency",
    "Training",
    "Candidate",
    "Interview",
    "HRException",
    "EmployeeNotFoundError",
    "PayrollCalculationError",
    "LeaveBalanceError",
]
