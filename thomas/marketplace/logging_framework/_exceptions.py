"""Exception definitions for the logging framework."""


class LoggingError(Exception):
    """Base exception for all logging framework errors."""

    def __init__(self, message: str, error_code: str = "UNKNOWN") -> None:
        """Initialize logging error.

        Args:
            message: Error message
            error_code: Unique error code
        """
        super().__init__(message)
        self.error_code = error_code
        self.message = message

    def __str__(self) -> str:
        """String representation."""
        return f"[{self.error_code}] {self.message}"


class HandlerError(LoggingError):
    """Exception related to log handler operations."""

    def __init__(self, message: str, handler_name: str = "unknown") -> None:
        """Initialize handler error.

        Args:
            message: Error message
            handler_name: Name of the handler that failed
        """
        super().__init__(message, "HANDLER_ERROR")
        self.handler_name = handler_name


class FilterError(LoggingError):
    """Exception related to log filter operations."""

    def __init__(self, message: str, filter_name: str = "unknown") -> None:
        """Initialize filter error.

        Args:
            message: Error message
            filter_name: Name of the filter that failed
        """
        super().__init__(message, "FILTER_ERROR")
        self.filter_name = filter_name


class FormatterError(LoggingError):
    """Exception related to log formatting operations."""

    def __init__(self, message: str, formatter_name: str = "unknown") -> None:
        """Initialize formatter error.

        Args:
            message: Error message
            formatter_name: Name of the formatter that failed
        """
        super().__init__(message, "FORMATTER_ERROR")
        self.formatter_name = formatter_name


class SearchError(LoggingError):
    """Exception related to log search operations."""

    def __init__(self, message: str, query: str = "unknown") -> None:
        """Initialize search error.

        Args:
            message: Error message
            query: The query that failed
        """
        super().__init__(message, "SEARCH_ERROR")
        self.query = query


class AggregationError(LoggingError):
    """Exception related to log aggregation operations."""

    def __init__(self, message: str) -> None:
        """Initialize aggregation error.

        Args:
            message: Error message
        """
        super().__init__(message, "AGGREGATION_ERROR")


class ComplianceError(LoggingError):
    """Exception related to compliance operations."""

    def __init__(self, message: str, compliance_rule: str = "unknown") -> None:
        """Initialize compliance error.

        Args:
            message: Error message
            compliance_rule: Compliance rule that failed
        """
        super().__init__(message, "COMPLIANCE_ERROR")
        self.compliance_rule = compliance_rule


class CorrelationError(LoggingError):
    """Exception related to log correlation operations."""

    def __init__(self, message: str) -> None:
        """Initialize correlation error.

        Args:
            message: Error message
        """
        super().__init__(message, "CORRELATION_ERROR")


class ConfigurationError(LoggingError):
    """Exception related to logging configuration."""

    def __init__(self, message: str, config_key: str = "unknown") -> None:
        """Initialize configuration error.

        Args:
            message: Error message
            config_key: Configuration key that was invalid
        """
        super().__init__(message, "CONFIG_ERROR")
        self.config_key = config_key
