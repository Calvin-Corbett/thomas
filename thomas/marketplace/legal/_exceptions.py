"""Custom exceptions for the legal practice management system."""


class LegalError(Exception):
    """Base exception for legal practice errors."""

    pass


class InvalidCaseStateError(LegalError):
    """Raised when a case operation is invalid for the current case status."""

    pass


class InvalidContractStateError(LegalError):
    """Raised when a contract operation is invalid for the current contract status."""

    pass


class ConflictDetectedError(LegalError):
    """Raised when a conflict of interest is detected."""

    pass


class DocumentNotFoundError(LegalError):
    """Raised when a document cannot be found."""

    pass


class PrivilegeClaimError(LegalError):
    """Raised when attempting to access privileged information without authorization."""

    pass


class DeadlineCalculationError(LegalError):
    """Raised when deadline calculation fails or produces invalid results."""

    pass


class InsufficientFundsError(LegalError):
    """Raised when attempting to withdraw from trust account without sufficient funds."""

    pass


class LegalHoldError(LegalError):
    """Raised when legal hold operations fail."""

    pass
