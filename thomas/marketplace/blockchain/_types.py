"""
Core type definitions for blockchain components.

Defines all core data structures used throughout the blockchain system
with full type annotations and comprehensive documentation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConsensusType(Enum):
    """Supported consensus mechanisms."""

    POW = "proof_of_work"
    POS = "proof_of_stake"
    DPOS = "delegated_proof_of_stake"


@dataclass(frozen=True)
class Transaction:
    """
    Represents a single transaction on the blockchain.

    Attributes:
        sender: Wallet address of the transaction sender.
        recipient: Wallet address of the transaction recipient.
        amount: Amount of cryptocurrency transferred (in satoshis/smallest units).
        fee: Fee paid by sender (in satoshis/smallest units).
        nonce: Transaction sequence number for sender (prevents replay attacks).
        signature: Digital signature (ECDSA) of transaction (hex string).
        hash: Computed SHA-256 hash of the transaction (hex string).
    """

    sender: str
    recipient: str
    amount: int
    fee: int
    nonce: int
    signature: str
    hash: str

    def __post_init__(self) -> None:
        """Validate transaction invariants."""
        if self.amount < 0:
            raise ValueError("Transaction amount cannot be negative")
        if self.fee < 0:
            raise ValueError("Transaction fee cannot be negative")
        if self.nonce < 0:
            raise ValueError("Transaction nonce cannot be negative")
        if not self.sender or not self.recipient:
            raise ValueError("Sender and recipient addresses required")

    def total_value(self) -> int:
        """
        Get total value moved (amount + fee).

        Returns:
            Total value in satoshis.
        """
        return self.amount + self.fee

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize transaction to dictionary.

        Returns:
            Dictionary representation of transaction.
        """
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "fee": self.fee,
            "nonce": self.nonce,
            "signature": self.signature,
            "hash": self.hash,
        }


@dataclass(frozen=True)
class BlockHeader:
    """
    Header of a block containing metadata.

    Attributes:
        index: Block number in the chain (0 for genesis).
        timestamp: Unix timestamp of block creation.
        merkle_root: Root hash of transaction merkle tree (hex string).
        previous_hash: Hash of parent block (hex string).
        difficulty: Current mining difficulty target (bits format).
        nonce: Proof of work nonce or validator info (consensus-dependent).
    """

    index: int
    timestamp: int
    merkle_root: str
    previous_hash: str
    difficulty: int
    nonce: int

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize header to dictionary.

        Returns:
            Dictionary representation of block header.
        """
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "merkle_root": self.merkle_root,
            "previous_hash": self.previous_hash,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
        }


@dataclass(frozen=True)
class Block:
    """
    Represents a single block in the blockchain.

    Attributes:
        index: Block number in the chain (0 for genesis).
        timestamp: Unix timestamp of block creation.
        transactions: List of transactions included in block.
        previous_hash: Hash of parent block (hex string).
        nonce: Proof of work nonce or consensus-specific value.
        hash: Computed SHA-256 hash of block header (hex string).
        merkle_root: Root of transaction merkle tree (hex string).
        difficulty: Mining difficulty target (bits format).
        miner: Address of miner/validator who created block.
    """

    index: int
    timestamp: int
    transactions: list[Transaction]
    previous_hash: str
    nonce: int
    hash: str
    merkle_root: str
    difficulty: int
    miner: str

    def __post_init__(self) -> None:
        """Validate block invariants."""
        if self.index < 0:
            raise ValueError("Block index cannot be negative")
        if self.difficulty < 1:
            raise ValueError("Block difficulty must be at least 1")

    @property
    def transaction_count(self) -> int:
        """Get number of transactions in block."""
        return len(self.transactions)

    @property
    def total_fees(self) -> int:
        """
        Get total transaction fees in block.

        Returns:
            Sum of all transaction fees in satoshis.
        """
        return sum(tx.fee for tx in self.transactions)

    @property
    def is_genesis(self) -> bool:
        """Check if this is the genesis block."""
        return self.index == 0 and self.previous_hash == "0" * 64

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize block to dictionary.

        Returns:
            Dictionary representation of block.
        """
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
            "merkle_root": self.merkle_root,
            "difficulty": self.difficulty,
            "miner": self.miner,
        }


@dataclass
class ChainConfig:
    """
    Configuration for blockchain parameters.

    Attributes:
        consensus_type: Type of consensus mechanism (POW, POS, DPOS).
        difficulty_target_seconds: Target time between blocks (in seconds).
        difficulty_adjustment_interval: Number of blocks between difficulty adjustments.
        block_reward: Initial mining/validator reward (in satoshis).
        max_block_size: Maximum block size in bytes.
        max_transactions_per_block: Maximum transactions per block.
        transaction_pool_max_size: Maximum mempool size in transactions.
        coinbase_maturity: Blocks before coinbase rewards can be spent.
    """

    consensus_type: ConsensusType = ConsensusType.POW
    difficulty_target_seconds: int = 10
    difficulty_adjustment_interval: int = 2016
    block_reward: int = 5000000000  # 50 in 8 decimals
    max_block_size: int = 1000000  # 1 MB
    max_transactions_per_block: int = 2000
    transaction_pool_max_size: int = 10000
    coinbase_maturity: int = 100


@dataclass
class WalletInfo:
    """
    Information about a wallet/account.

    Attributes:
        address: Public wallet address.
        public_key: Public key used for address derivation (hex string).
        balance: Current balance in satoshis.
        nonce: Number of transactions sent from this address.
        transactions: List of transaction hashes involving this address.
    """

    address: str
    public_key: str
    balance: int = 0
    nonce: int = 0
    transactions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize wallet info to dictionary.

        Returns:
            Dictionary representation of wallet info.
        """
        return {
            "address": self.address,
            "public_key": self.public_key,
            "balance": self.balance,
            "nonce": self.nonce,
            "transactions": self.transactions,
        }


@dataclass
class MempoolEntry:
    """
    Entry in the memory pool (transaction pool).

    Attributes:
        transaction: The actual transaction.
        received_at: Unix timestamp when transaction was received.
        priority: Priority for inclusion in next block (fee per byte).
        depends_on: List of transaction hashes this depends on (UTXO inputs).
    """

    transaction: Transaction
    received_at: int
    priority: float
    depends_on: list[str] = field(default_factory=list)

    @property
    def fee_per_byte(self) -> float:
        """
        Calculate fee per byte for priority ordering.

        Returns:
            Fee divided by estimated transaction size in bytes.
        """
        # Rough estimate: 200 bytes base + 40 bytes per input + 40 bytes per output
        estimated_size = 200
        if self.transaction.fee == 0:
            return 0.0
        return self.transaction.fee / estimated_size

    def is_expired(self, current_time: int, expiry_seconds: int = 86400) -> bool:
        """
        Check if transaction has expired from mempool.

        Args:
            current_time: Current Unix timestamp.
            expiry_seconds: Mempool expiry time (default 24 hours).

        Returns:
            True if transaction has expired.
        """
        return current_time - self.received_at > expiry_seconds
