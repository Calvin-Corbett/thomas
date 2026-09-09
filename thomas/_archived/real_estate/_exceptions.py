"""Custom exceptions for real estate platform."""


class RealEstateException(Exception):
    """Base exception for real estate operations."""

    pass


class ValidationError(RealEstateException):
    """Raised when validation of data fails."""

    pass


class InvalidPropertyError(RealEstateException):
    """Raised when property data is invalid or missing."""

    pass


class InvalidListingError(RealEstateException):
    """Raised when listing data is invalid."""

    pass


class InvalidTransactionError(RealEstateException):
    """Raised when transaction data is invalid."""

    pass


class InsufficientDataError(RealEstateException):
    """Raised when insufficient data is available for analysis."""

    pass


class PropertyNotFoundError(RealEstateException):
    """Raised when property cannot be found."""

    pass


class ListingNotFoundError(RealEstateException):
    """Raised when listing cannot be found."""

    pass


class TransactionNotFoundError(RealEstateException):
    """Raised when transaction cannot be found."""

    pass


class ContingencyError(RealEstateException):
    """Raised when contingency deadline has passed or conditions not met."""

    pass
