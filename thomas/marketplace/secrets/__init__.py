"""Secrets management with vault, encryption, rotation, and access control.

Provides encrypted secret storage, rotation policies,
access control, and audit logging.
"""

from .core import (
    AccessLevel,
    AccessPolicy,
    AuditEntry,
    Secret,
    SecretEncryption,
    SecretType,
    SecretVault,
)

__all__ = [
    "SecretType",
    "AccessLevel",
    "Secret",
    "AccessPolicy",
    "AuditEntry",
    "SecretEncryption",
    "SecretVault",
]

__version__ = "1.0.0"
