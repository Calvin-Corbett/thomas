"""
Custom exceptions for the CRM module.
"""


class CRMException(Exception):
    """Base exception for CRM module."""

    pass


class ContactNotFoundError(CRMException):
    """Raised when a contact is not found."""

    pass


class CompanyNotFoundError(CRMException):
    """Raised when a company is not found."""

    pass


class DealNotFoundError(CRMException):
    """Raised when a deal is not found."""

    pass


class PipelineNotFoundError(CRMException):
    """Raised when a pipeline is not found."""

    pass


class InvalidStageError(CRMException):
    """Raised when an invalid stage is provided."""

    pass


class DuplicateContactError(CRMException):
    """Raised when a duplicate contact is detected."""

    pass


class WorkflowError(CRMException):
    """Raised when a workflow operation fails."""

    pass


class IntegrationError(CRMException):
    """Raised when an integration operation fails."""

    pass
