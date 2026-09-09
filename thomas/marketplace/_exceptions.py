"""Marketplace platform exceptions."""


class MarketplaceException(Exception):
    """Base exception for marketplace operations."""

    def __init__(self, message: str, code: str = "MARKETPLACE_ERROR") -> None:
        """Initialize marketplace exception."""
        self.message = message
        self.code = code
        super().__init__(message)


class VendorException(MarketplaceException):
    """Vendor operation errors."""

    def __init__(self, message: str, code: str = "VENDOR_ERROR") -> None:
        super().__init__(message, code)


class VendorNotFoundError(VendorException):
    """Vendor does not exist."""

    def __init__(self, vendor_id: str) -> None:
        super().__init__(f"Vendor not found: {vendor_id}", "VENDOR_NOT_FOUND")


class VendorAlreadyExists(VendorException):
    """Vendor registration conflicts."""

    def __init__(self, vendor_id: str) -> None:
        super().__init__(f"Vendor already exists: {vendor_id}", "VENDOR_EXISTS")


class VendorInactive(VendorException):
    """Vendor is not active."""

    def __init__(self, vendor_id: str) -> None:
        super().__init__(f"Vendor is inactive: {vendor_id}", "VENDOR_INACTIVE")


class ListingException(MarketplaceException):
    """Listing operation errors."""

    def __init__(self, message: str, code: str = "LISTING_ERROR") -> None:
        super().__init__(message, code)


class ListingNotFoundError(ListingException):
    """Listing does not exist."""

    def __init__(self, listing_id: str) -> None:
        super().__init__(f"Listing not found: {listing_id}", "LISTING_NOT_FOUND")


class InvalidListingState(ListingException):
    """Invalid listing state transition."""

    def __init__(self, listing_id: str, current_state: str, target_state: str) -> None:
        msg = f"Cannot transition listing {listing_id} from {current_state} to {target_state}"
        super().__init__(msg, "INVALID_LISTING_STATE")


class OrderException(MarketplaceException):
    """Order operation errors."""

    def __init__(self, message: str, code: str = "ORDER_ERROR") -> None:
        super().__init__(message, code)


class OrderNotFoundError(OrderException):
    """Order does not exist."""

    def __init__(self, order_id: str) -> None:
        super().__init__(f"Order not found: {order_id}", "ORDER_NOT_FOUND")


class InvalidOrderState(OrderException):
    """Invalid order state transition."""

    def __init__(self, order_id: str, current_state: str) -> None:
        msg = f"Cannot modify order {order_id} in state {current_state}"
        super().__init__(msg, "INVALID_ORDER_STATE")


class PaymentException(MarketplaceException):
    """Payment processing errors."""

    def __init__(self, message: str, code: str = "PAYMENT_ERROR") -> None:
        super().__init__(message, code)


class PaymentFailed(PaymentException):
    """Payment gateway returned failure."""

    def __init__(self, payment_id: str, reason: str) -> None:
        super().__init__(f"Payment {payment_id} failed: {reason}", "PAYMENT_FAILED")


class InsufficientFunds(PaymentException):
    """Insufficient funds for transaction."""

    def __init__(self) -> None:
        super().__init__("Insufficient funds for transaction", "INSUFFICIENT_FUNDS")


class ReviewException(MarketplaceException):
    """Review operation errors."""

    def __init__(self, message: str, code: str = "REVIEW_ERROR") -> None:
        super().__init__(message, code)


class ReviewNotFoundError(ReviewException):
    """Review does not exist."""

    def __init__(self, review_id: str) -> None:
        super().__init__(f"Review not found: {review_id}", "REVIEW_NOT_FOUND")


class UnverifiedPurchaseReview(ReviewException):
    """Review submitted without verified purchase."""

    def __init__(self) -> None:
        super().__init__("Cannot review without verified purchase", "UNVERIFIED_PURCHASE")


class DisputeException(MarketplaceException):
    """Dispute resolution errors."""

    def __init__(self, message: str, code: str = "DISPUTE_ERROR") -> None:
        super().__init__(message, code)


class DisputeNotFoundError(DisputeException):
    """Dispute does not exist."""

    def __init__(self, dispute_id: str) -> None:
        super().__init__(f"Dispute not found: {dispute_id}", "DISPUTE_NOT_FOUND")


class InvalidDisputeState(DisputeException):
    """Invalid dispute state transition."""

    def __init__(self, dispute_id: str, current_state: str) -> None:
        msg = f"Cannot modify dispute {dispute_id} in state {current_state}"
        super().__init__(msg, "INVALID_DISPUTE_STATE")


class SearchException(MarketplaceException):
    """Search operation errors."""

    def __init__(self, message: str, code: str = "SEARCH_ERROR") -> None:
        super().__init__(message, code)


class InvalidSearchQuery(SearchException):
    """Invalid search parameters."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid search query: {message}", "INVALID_SEARCH_QUERY")
