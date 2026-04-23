"""Custom exceptions for autonomous vehicle module."""


class AVException(Exception):
    """Base exception for autonomous vehicle module."""

    pass


class PerceptionException(AVException):
    """Exception raised in perception pipeline."""

    pass


class LocalizationException(AVException):
    """Exception raised in localization system."""

    pass


class PlanningException(AVException):
    """Exception raised in planning system."""

    pass


class ControlException(AVException):
    """Exception raised in control system."""

    pass


class SafetyException(AVException):
    """Exception raised in safety systems."""

    pass


class SensorDropoutException(PerceptionException):
    """Exception raised when critical sensor drops out."""

    pass


class LaneDetectionFailureException(PerceptionException):
    """Exception raised when lane detection fails."""

    pass


class LocalizationDriftException(LocalizationException):
    """Exception raised when localization drift exceeds threshold."""

    pass


class NoPathFoundException(PlanningException):
    """Exception raised when path planner cannot find a path."""

    pass


class ActuatorLimitException(ControlException):
    """Exception raised when actuator limits are exceeded."""

    pass


class RSSSafetyViolationException(SafetyException):
    """Exception raised when RSS safety distance is violated."""

    pass


class ODDViolationException(SafetyException):
    """Exception raised when vehicle exits operational design domain."""

    pass
