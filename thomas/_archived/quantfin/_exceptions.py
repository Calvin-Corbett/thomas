"""Exception classes for quantitative finance module."""


class QuantFinException(Exception):
    """Base exception for all quantitative finance errors."""

    pass


class PricingError(QuantFinException):
    """Raised when option pricing calculation fails."""

    pass


class PortfolioError(QuantFinException):
    """Raised when portfolio operation fails."""

    pass


class RiskError(QuantFinException):
    """Raised when risk calculation fails."""

    pass


class OrderError(QuantFinException):
    """Raised when order operation fails."""

    pass


class TimeSeriesError(QuantFinException):
    """Raised when time series operation fails."""

    pass


class VolatilityError(QuantFinException):
    """Raised when volatility calculation fails."""

    pass


class OptimizationError(QuantFinException):
    """Raised when optimization fails."""

    pass
