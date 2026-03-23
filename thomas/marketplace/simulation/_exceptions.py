"""
Simulation exception hierarchy.

Provides custom exceptions for various simulation failure modes.
"""


class SimulationError(Exception):
    """Base exception for simulation errors."""

    pass


class EventError(SimulationError):
    """Raised when event scheduling or processing fails."""

    pass


class AgentError(SimulationError):
    """Raised when agent lifecycle or behavior fails."""

    pass


class ResourceError(SimulationError):
    """Raised when resource constraints are violated."""

    pass


class ScheduleError(SimulationError):
    """Raised when agent scheduling fails."""

    pass


class DistributionError(SimulationError):
    """Raised when distribution sampling fails."""

    pass


class EnvironmentError(SimulationError):
    """Raised when environment operations fail."""

    pass


class MetricsError(SimulationError):
    """Raised when metrics collection fails."""

    pass
