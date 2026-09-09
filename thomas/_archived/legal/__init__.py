"""Thomas Legal Practice Management System.

A comprehensive legal practice and case management platform with support for
case management, contract handling, billing, discovery, compliance, and analytics.
"""

from thomas.legal._exceptions import (
    ConflictDetectedError,
    DeadlineCalculationError,
    DocumentNotFoundError,
    InsufficientFundsError,
    InvalidCaseStateError,
    InvalidContractStateError,
    LegalHoldError,
    PrivilegeClaimError,
)
from thomas.legal._types import (
    Attorney,
    BillingStatus,
    Case,
    CaseOutcome,
    CaseStatus,
    CaseType,
    Clause,
    Client,
    Conflict,
    Contract,
    ContractStatus,
    Court,
    Document,
    DocumentType,
    Filing,
    Invoice,
    Jurisdiction,
    Statute,
    TimeEntry,
    Trust,
)

__all__ = [
    "Attorney",
    "BillingStatus",
    "Case",
    "CaseOutcome",
    "CaseStatus",
    "CaseType",
    "Clause",
    "Client",
    "Conflict",
    "Contract",
    "ContractStatus",
    "Court",
    "Document",
    "DocumentType",
    "Filing",
    "Invoice",
    "Jurisdiction",
    "Statute",
    "TimeEntry",
    "Trust",
    "ConflictDetectedError",
    "DeadlineCalculationError",
    "DocumentNotFoundError",
    "InsufficientFundsError",
    "InvalidCaseStateError",
    "InvalidContractStateError",
    "LegalHoldError",
    "PrivilegeClaimError",
]

__version__ = "0.1.0"
