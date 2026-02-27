"""
Exception classes for the Thomas ERP system.

All ERP exceptions inherit from ERPException for consistent error handling.
"""


class ERPException(Exception):
    """Base exception for all ERP errors."""

    pass


class InvalidAccountError(ERPException):
    """Raised when account operation is invalid."""

    pass


class JournalEntryError(ERPException):
    """Raised when journal entry is invalid or cannot be posted."""

    pass


class InsufficientInventoryError(ERPException):
    """Raised when stock quantity is insufficient."""

    pass


class VendorError(ERPException):
    """Raised when vendor operation fails."""

    pass


class CustomerError(ERPException):
    """Raised when customer operation fails."""

    pass


class InvoiceError(ERPException):
    """Raised when invoice operation is invalid."""

    pass


class POError(ERPException):
    """Raised when purchase order operation fails."""

    pass


class SOError(ERPException):
    """Raised when sales order operation fails."""

    pass


class ManufacturingError(ERPException):
    """Raised when manufacturing operation fails."""

    pass


class TaxError(ERPException):
    """Raised when tax calculation or reporting fails."""

    pass


class ReconciliationError(ERPException):
    """Raised when reconciliation fails."""

    pass


class BalanceSheetError(ERPException):
    """Raised when balance sheet operations fail."""

    pass
