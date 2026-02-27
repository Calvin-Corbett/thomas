"""Exception definitions for the e-commerce system."""


class EcommerceError(Exception):
    """Base exception for e-commerce errors."""

    pass


class OutOfStockError(EcommerceError):
    """Raised when product is out of stock."""

    def __init__(self, product_id: str, requested: int, available: int):
        """Initialize OutOfStockError.

        Args:
            product_id: ID of the out-of-stock product
            requested: Requested quantity
            available: Available quantity
        """
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(f"Product {product_id}: requested {requested} but only {available} available")


class InvalidCouponError(EcommerceError):
    """Raised when coupon is invalid."""

    def __init__(self, code: str, reason: str = "Invalid coupon"):
        """Initialize InvalidCouponError.

        Args:
            code: Coupon code
            reason: Reason the coupon is invalid
        """
        self.code = code
        self.reason = reason
        super().__init__(f"Coupon {code}: {reason}")


class PricingError(EcommerceError):
    """Raised when pricing calculation fails."""

    def __init__(self, message: str):
        """Initialize PricingError.

        Args:
            message: Error message
        """
        super().__init__(message)


class OrderError(EcommerceError):
    """Raised when order operation fails."""

    def __init__(self, message: str):
        """Initialize OrderError.

        Args:
            message: Error message
        """
        super().__init__(message)


class PaymentError(EcommerceError):
    """Raised when payment operation fails."""

    def __init__(self, message: str):
        """Initialize PaymentError.

        Args:
            message: Error message
        """
        super().__init__(message)


class InventoryError(EcommerceError):
    """Raised when inventory operation fails."""

    def __init__(self, message: str):
        """Initialize InventoryError.

        Args:
            message: Error message
        """
        super().__init__(message)
