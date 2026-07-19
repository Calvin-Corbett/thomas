"""Canonical Work domain: durable app definitions and Mission delegation metadata."""

from .store import WorkStore
from .validation import (
    WorkConflictError,
    WorkCorruptStateError,
    WorkDependencyUnavailableError,
    WorkError,
    WorkNotFoundError,
    WorkValidationError,
)

__all__ = [
    "WorkConflictError",
    "WorkCorruptStateError",
    "WorkDependencyUnavailableError",
    "WorkError",
    "WorkNotFoundError",
    "WorkStore",
    "WorkValidationError",
]
