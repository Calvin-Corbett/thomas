"""Exceptions for the paper-trading module."""

from __future__ import annotations


class PaperTradingError(Exception):
    """Base class for all paper-trading errors."""


class ConfigError(PaperTradingError):
    """Raised when configuration (credentials, data dir, risk rules) is invalid."""


class CredentialsMissing(ConfigError):
    """Raised when Alpaca paper credentials are not configured."""


class LiveTradingBlocked(PaperTradingError):
    """Raised if anything attempts to point the client at a live (real-money) endpoint.

    This is a hard safety stop: the Phase-1 module is paper-only by construction.
    """


class RiskRejected(PaperTradingError):
    """Raised when a proposed trade violates the configured risk rules."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(self.violations) or "risk rejected")


class ProposalNotFound(PaperTradingError):
    """Raised when a proposal id cannot be located in the store."""


class ApprovalRequired(PaperTradingError):
    """Raised when submission is attempted on a proposal a human has not approved.

    The human approval gate is the core safety property of the module: the model
    may only *propose*; it can never flip a proposal to ``approved``.
    """


class BrokerError(PaperTradingError):
    """Raised when the broker (Alpaca) API returns an error or is unreachable."""
