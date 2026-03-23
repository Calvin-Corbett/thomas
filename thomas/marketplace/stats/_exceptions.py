"""Exception classes for the statistics module."""


class StatsError(Exception):
    """Base exception for statistics module."""

    pass


class InsufficientDataError(StatsError):
    """Raised when there is insufficient data to perform a statistical operation."""

    pass


class ConvergenceError(StatsError):
    """Raised when an iterative algorithm fails to converge."""

    pass
