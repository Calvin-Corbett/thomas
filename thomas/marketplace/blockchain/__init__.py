"""
Thomas Blockchain Module - Complete blockchain implementation from scratch.

A production-ready blockchain engine supporting multiple consensus mechanisms,
smart contracts, and wallet functionality.
"""

from thomas.marketplace.blockchain._exceptions import (
    BlockchainError,
    ConsensusError,
    DoubleSpendError,
    InsufficientFundsError,
    InvalidBlockError,
    InvalidTransactionError,
    MerkleError,
)
from thomas.marketplace.blockchain._types import (
    Block,
    BlockHeader,
    ChainConfig,
    ConsensusType,
    MempoolEntry,
    Transaction,
    WalletInfo,
)
from thomas.marketplace.blockchain.block import (
    compute_block_hash,
    create_block,
    create_genesis_block,
    validate_block,
)
from thomas.marketplace.blockchain.chain import Blockchain
from thomas.marketplace.blockchain.consensus import (
    DelegatedProofOfStake,
    ProofOfStake,
    ProofOfWork,
)
from thomas.marketplace.blockchain.crypto import (
    KeyPair,
    derive_address,
    generate_deterministic_keypair,
    generate_keypair,
    sign_message,
    verify_signature,
)
from thomas.marketplace.blockchain.mempool import Mempool
from thomas.marketplace.blockchain.merkle import (
    MerkleTree,
    build_merkle_tree,
    verify_merkle_proof,
)
from thomas.marketplace.blockchain.network import MessageType, Network, NetworkMessage
from thomas.marketplace.blockchain.smart_contracts import ContractEngine, SmartContract
from thomas.marketplace.blockchain.transaction import (
    create_coinbase_transaction,
    create_transaction,
    transaction_hash,
    verify_transaction,
)
from thomas.marketplace.blockchain.wallet import Wallet

__all__ = [
    # Types
    "Transaction",
    "Block",
    "BlockHeader",
    "ConsensusType",
    "ChainConfig",
    "WalletInfo",
    "MempoolEntry",
    # Exceptions
    "BlockchainError",
    "InvalidBlockError",
    "InvalidTransactionError",
    "InsufficientFundsError",
    "DoubleSpendError",
    "ConsensusError",
    "MerkleError",
    # Crypto
    "KeyPair",
    "sign_message",
    "verify_signature",
    "generate_keypair",
    "derive_address",
    "generate_deterministic_keypair",
    # Merkle
    "MerkleTree",
    "build_merkle_tree",
    "verify_merkle_proof",
    # Transaction
    "create_transaction",
    "create_coinbase_transaction",
    "verify_transaction",
    "transaction_hash",
    # Block
    "create_block",
    "create_genesis_block",
    "validate_block",
    "compute_block_hash",
    # Chain
    "Blockchain",
    # Consensus
    "ProofOfWork",
    "ProofOfStake",
    "DelegatedProofOfStake",
    # Mempool
    "Mempool",
    # Network
    "Network",
    "NetworkMessage",
    "MessageType",
    # Wallet
    "Wallet",
    # Smart Contracts
    "SmartContract",
    "ContractEngine",
]

__version__ = "1.0.0"
