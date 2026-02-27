"""Exception types for project management module."""


class ProjectManagementException(Exception):
    """Base exception for project management module."""

    pass


class ProjectNotFoundError(ProjectManagementException):
    """Raised when project cannot be found."""

    pass


class TaskNotFoundError(ProjectManagementException):
    """Raised when task cannot be found."""

    pass


class ResourceNotFoundError(ProjectManagementException):
    """Raised when resource cannot be found."""

    pass


class InvalidStatusTransitionError(ProjectManagementException):
    """Raised when status transition is not allowed."""

    pass


class ResourceOverallocationError(ProjectManagementException):
    """Raised when resource is overallocated."""

    pass


class CircularDependencyError(ProjectManagementException):
    """Raised when circular task dependency is detected."""

    pass


class InvalidTaskHierarchyError(ProjectManagementException):
    """Raised when task hierarchy violates WBS rules."""

    pass


class BudgetExceededError(ProjectManagementException):
    """Raised when budget is exceeded."""

    pass


class InvalidDateRangeError(ProjectManagementException):
    """Raised when date range is invalid."""

    pass


class SprintNotFoundError(ProjectManagementException):
    """Raised when sprint cannot be found."""

    pass


class MilestoneNotFoundError(ProjectManagementException):
    """Raised when milestone cannot be found."""

    pass


class RiskNotFoundError(ProjectManagementException):
    """Raised when risk item cannot be found."""

    pass


class InvalidPriorityError(ProjectManagementException):
    """Raised when priority value is invalid."""

    pass


class SkillMatchError(ProjectManagementException):
    """Raised when resource lacks required skills."""

    pass
