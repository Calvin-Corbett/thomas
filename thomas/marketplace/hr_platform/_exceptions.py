"""Custom exceptions for HR platform."""


class HRException(Exception):
    """Base exception for HR platform."""

    pass


class EmployeeNotFoundError(HRException):
    """Employee not found in system."""

    def __init__(self, employee_id: str) -> None:
        """Initialize with employee ID."""
        self.employee_id = employee_id
        super().__init__(f"Employee {employee_id} not found")


class PayrollCalculationError(HRException):
    """Error calculating payroll."""

    def __init__(self, message: str) -> None:
        """Initialize with message."""
        super().__init__(f"Payroll calculation error: {message}")


class LeaveBalanceError(HRException):
    """Insufficient leave balance."""

    def __init__(self, message: str) -> None:
        """Initialize with message."""
        super().__init__(f"Leave balance error: {message}")


class BenefitEnrollmentError(HRException):
    """Error enrolling in benefit plan."""

    def __init__(self, message: str) -> None:
        """Initialize with message."""
        super().__init__(f"Benefit enrollment error: {message}")


class RecruitmentError(HRException):
    """Error in recruitment process."""

    def __init__(self, message: str) -> None:
        """Initialize with message."""
        super().__init__(f"Recruitment error: {message}")


class PerformanceReviewError(HRException):
    """Error in performance review."""

    def __init__(self, message: str) -> None:
        """Initialize with message."""
        super().__init__(f"Performance review error: {message}")


class TimeTrackingError(HRException):
    """Error in time tracking."""

    def __init__(self, message: str) -> None:
        """Initialize with message."""
        super().__init__(f"Time tracking error: {message}")
