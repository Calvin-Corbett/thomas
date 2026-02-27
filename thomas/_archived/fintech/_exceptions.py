"""
Exceptions for fintech operations.

Provides domain-specific exceptions for order processing, risk management,
settlement, and compliance violations.
"""


class FintechError(Exception):
    """Base exception for fintech operations."""

    pass


class InsufficientFundsError(FintechError):
    """Raised when account lacks sufficient funds for operation."""

    def __init__(
        self,
        required: float,
        available: float,
        message: str = None,
    ) -> None:
        """
        Initialize insufficient funds error.

        Args:
            required: Required amount
            available: Available amount
            message: Optional custom message
        """
        self.required = required
        self.available = available
        if message is None:
            message = f"Insufficient funds: required {required}, available {available}"
        super().__init__(message)


class OrderError(FintechError):
    """Raised when order operation fails."""

    def __init__(
        self,
        order_id: str,
        reason: str,
        message: str = None,
    ) -> None:
        """
        Initialize order error.

        Args:
            order_id: ID of the affected order
            reason: Reason for the error
            message: Optional custom message
        """
        self.order_id = order_id
        self.reason = reason
        if message is None:
            message = f"Order {order_id} error: {reason}"
        super().__init__(message)


class RiskLimitError(FintechError):
    """Raised when operation violates risk limits."""

    def __init__(
        self,
        limit_type: str,
        current: float,
        limit: float,
        message: str = None,
    ) -> None:
        """
        Initialize risk limit error.

        Args:
            limit_type: Type of limit (e.g., "max_position")
            current: Current value
            limit: Limit value
            message: Optional custom message
        """
        self.limit_type = limit_type
        self.current = current
        self.limit = limit
        if message is None:
            message = f"{limit_type} exceeded: {current} > {limit}"
        super().__init__(message)


class SettlementError(FintechError):
    """Raised when settlement operation fails."""

    def __init__(
        self,
        trade_id: str,
        reason: str,
        message: str = None,
    ) -> None:
        """
        Initialize settlement error.

        Args:
            trade_id: ID of the trade
            reason: Reason for settlement failure
            message: Optional custom message
        """
        self.trade_id = trade_id
        self.reason = reason
        if message is None:
            message = f"Settlement failed for trade {trade_id}: {reason}"
        super().__init__(message)


class ComplianceError(FintechError):
    """Raised when operation violates compliance rules."""

    def __init__(
        self,
        rule: str,
        details: str,
        message: str = None,
    ) -> None:
        """
        Initialize compliance error.

        Args:
            rule: Compliance rule violated
            details: Details about the violation
            message: Optional custom message
        """
        self.rule = rule
        self.details = details
        if message is None:
            message = f"Compliance violation - {rule}: {details}"
        super().__init__(message)
