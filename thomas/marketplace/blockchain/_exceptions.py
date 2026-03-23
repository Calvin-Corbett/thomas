"""
Custom exceptions for blockchain operations.

Defines domain-specific exceptions for various blockchain error conditions.
"""


class BlockchainError(Exception):
    """Base exception for all blockchain-related errors."""

    pass


class InvalidBlockError(BlockchainError):
    """Raised when a block fails validation."""

    pass


class InvalidTransactionError(BlockchainError):
    """Raised when a transaction fails validation."""

    pass


class InsufficientFundsError(BlockchainError):
    """Raised when an address lacks sufficient balance for a transaction."""

    pass


class DoubleSpendError(BlockchainError):
    """Raised when attempting to spend the same output twice."""

    pass


class ConsensusError(BlockchainError):
    """Raised when consensus validation fails."""

    pass


class MerkleError(BlockchainError):
    """Raised when merkle tree operations fail."""

    pass
