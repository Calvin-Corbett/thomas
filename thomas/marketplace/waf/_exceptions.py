"""
WAF Exception Classes

Custom exceptions for the WAF module.
"""


class WAFException(Exception):
    """Base exception for WAF module."""

    pass


class RuleParseException(WAFException):
    """Exception raised when parsing WAF rules fails."""

    def __init__(self, message: str, rule_line: str = "", line_number: int = 0) -> None:
        """
        Initialize rule parse exception.

        Args:
            message: Error message
            rule_line: The rule line that failed to parse
            line_number: Line number in rule file
        """
        self.message = message
        self.rule_line = rule_line
        self.line_number = line_number
        super().__init__(f"Rule parse error at line {line_number}: {message}\n" f"Line: {rule_line}")


class ConfigurationException(WAFException):
    """Exception raised for invalid WAF configuration."""

    def __init__(self, message: str, config_key: str = "") -> None:
        """
        Initialize configuration exception.

        Args:
            message: Error message
            config_key: Configuration key that failed
        """
        self.message = message
        self.config_key = config_key
        if config_key:
            super().__init__(f"Configuration error for '{config_key}': {message}")
        else:
            super().__init__(f"Configuration error: {message}")


class RateLimitException(WAFException):
    """Exception raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        ip_address: str = "",
        limit_type: str = "",
        retry_after: int = 0,
    ) -> None:
        """
        Initialize rate limit exception.

        Args:
            message: Error message
            ip_address: IP address that exceeded limit
            limit_type: Type of rate limit (requests_per_second, etc.)
            retry_after: Seconds to wait before retrying
        """
        self.message = message
        self.ip_address = ip_address
        self.limit_type = limit_type
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded: {message} " f"(IP: {ip_address}, Type: {limit_type}, Retry after: {retry_after}s)"
        )
