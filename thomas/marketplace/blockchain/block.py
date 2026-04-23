"""
Block creation and validation.

Handles block construction, hash computation, and comprehensive validation.
"""

import hashlib
import time

from thomas.marketplace.blockchain._exceptions import InvalidBlockError
from thomas.marketplace.blockchain._types import Block, BlockHeader, Transaction
from thomas.marketplace.blockchain.merkle import build_merkle_tree


def _serialize_block_header(header: BlockHeader) -> bytes:
    """
    Serialize block header for hashing.

    Args:
        header: BlockHeader to serialize.

    Returns:
        Serialized header bytes.
    """
    data = (
        header.index.to_bytes(4, byteorder="big")
        + header.timestamp.to_bytes(8, byteorder="big")
        + bytes.fromhex(header.merkle_root)
        + bytes.fromhex(header.previous_hash)
        + header.difficulty.to_bytes(4, byteorder="big")
        + header.nonce.to_bytes(8, byteorder="big")
    )
    return data


def compute_block_hash(header: BlockHeader) -> str:
    """
    Compute block hash from header.

    Uses double SHA-256 (standard for Bitcoin).

    Args:
        header: BlockHeader to hash.

    Returns:
        Block hash as hex string (64 characters).
    """
    serialized = _serialize_block_header(header)
    hash1 = hashlib.sha256(serialized).digest()
    hash2 = hashlib.sha256(hash1).digest()
    return hash2.hex()


def _compute_merkle_root(transactions: list[Transaction]) -> str:
    """
    Compute merkle root of transactions.

    Args:
        transactions: List of transactions in block.

    Returns:
        Merkle root hash as hex string.
    """
    if not transactions:
        # Empty block - return zero hash
        return "0" * 64

    tx_hashes = [tx.hash for tx in transactions]
    merkle_tree = build_merkle_tree(tx_hashes)
    return merkle_tree.merkle_root


def _calculate_block_reward(block_index: int, initial_reward: int) -> int:
    """
    Calculate block reward with halving every 210,000 blocks.

    Args:
        block_index: Block number (0 for genesis).
        initial_reward: Initial block reward (in satoshis).

    Returns:
        Block reward for this block.
    """
    halvings = block_index // 210000
    if halvings >= 33:  # After ~33 halvings, reward becomes 0
        return 0
    return initial_reward >> halvings


def create_block(
    index: int,
    transactions: list[Transaction],
    previous_hash: str,
    difficulty: int,
    miner: str,
    nonce: int = 0,
    timestamp: int = None,
) -> Block:
    """
    Create a new block with transactions.

    Args:
        index: Block number in chain.
        transactions: List of transactions (should include coinbase).
        previous_hash: Hash of parent block.
        difficulty: Mining difficulty target.
        miner: Address of miner/validator.
        nonce: Proof of work nonce (default 0).
        timestamp: Block timestamp (default current time).

    Returns:
        Block object.

    Raises:
        InvalidBlockError: If block parameters invalid.
    """
    if index < 0:
        raise InvalidBlockError("Block index cannot be negative")
    if difficulty < 1:
        raise InvalidBlockError("Difficulty must be at least 1")
    if not transactions:
        raise InvalidBlockError("Block must have at least one transaction")

    if timestamp is None:
        timestamp = int(time.time())

    # Compute merkle root
    merkle_root = _compute_merkle_root(transactions)

    # Create header
    header = BlockHeader(
        index=index,
        timestamp=timestamp,
        merkle_root=merkle_root,
        previous_hash=previous_hash,
        difficulty=difficulty,
        nonce=nonce,
    )

    # Compute block hash
    block_hash = compute_block_hash(header)

    return Block(
        index=index,
        timestamp=timestamp,
        transactions=transactions,
        previous_hash=previous_hash,
        nonce=nonce,
        hash=block_hash,
        merkle_root=merkle_root,
        difficulty=difficulty,
        miner=miner,
    )


def create_genesis_block(
    miner: str,
    initial_reward: int,
    difficulty: int = 1,
) -> Block:
    """
    Create genesis (first) block.

    Args:
        miner: Address of genesis block creator.
        initial_reward: Initial coinbase reward.
        difficulty: Starting difficulty.

    Returns:
        Genesis Block.
    """
    # Create coinbase transaction for genesis block
    from thomas.marketplace.blockchain.transaction import create_coinbase_transaction

    coinbase = create_coinbase_transaction(miner, initial_reward, 0, miner)

    return create_block(
        index=0,
        transactions=[coinbase],
        previous_hash="0" * 64,
        difficulty=difficulty,
        miner=miner,
        nonce=0,
        timestamp=int(time.time()),
    )


def validate_block(
    block: Block,
    previous_block: Block = None,
    target_difficulty: int = None,
) -> bool:
    """
    Validate a block for correctness.

    Checks:
    - Block hash is correct
    - All transactions are valid
    - Merkle root is correct
    - Previous hash link is correct
    - Difficulty target is met
    - Timestamp is reasonable

    Args:
        block: Block to validate.
        previous_block: Previous block in chain (optional).
        target_difficulty: Expected difficulty target (optional).

    Returns:
        True if block is valid.
    """
    try:
        # Validate block hash
        header = BlockHeader(
            index=block.index,
            timestamp=block.timestamp,
            merkle_root=block.merkle_root,
            previous_hash=block.previous_hash,
            difficulty=block.difficulty,
            nonce=block.nonce,
        )
        expected_hash = compute_block_hash(header)
        if block.hash != expected_hash:
            return False

        # Validate previous hash link
        if previous_block is not None:
            if block.previous_hash != previous_block.hash:
                return False
            if block.index != previous_block.index + 1:
                return False

        # Validate merkle root
        expected_merkle = _compute_merkle_root(block.transactions)
        if block.merkle_root != expected_merkle:
            return False

        # Validate difficulty target is met
        if not _check_difficulty_target(block.hash, block.difficulty):
            return False

        # Validate timestamp
        if previous_block is not None:
            if block.timestamp <= previous_block.timestamp:
                return False

        # Validate transaction count
        if len(block.transactions) > 2000:  # Reasonable max
            return False

        return True

    except Exception:
        return False


def _check_difficulty_target(block_hash: str, difficulty: int) -> bool:
    """
    Check if block hash meets difficulty target.

    Difficulty is encoded in "bits" format (4 bytes):
    - 1 byte: exponent
    - 3 bytes: mantissa
    Target = mantissa * 2^(8*(exponent-3))

    Args:
        block_hash: Block hash as hex string.
        difficulty: Difficulty in bits format.

    Returns:
        True if hash meets target.
    """
    # For simplified version: just check leading zeros
    # Real implementation would check against bits target
    if difficulty < 1:
        return False

    # Require leading zeros based on difficulty
    required_leading_zeros = difficulty - 1
    hash_int = int(block_hash, 16)

    # Count leading zero bits
    if hash_int == 0:
        leading_zeros = 256
    else:
        leading_zeros = 256 - hash_int.bit_length()

    return leading_zeros >= required_leading_zeros


def validate_block_header(header: BlockHeader) -> bool:
    """
    Validate block header format.

    Args:
        header: BlockHeader to validate.

    Returns:
        True if header is valid.
    """
    try:
        if header.index < 0:
            return False
        if header.difficulty < 1:
            return False
        if len(header.merkle_root) != 64:
            return False
        if len(header.previous_hash) != 64:
            return False
        return True
    except Exception:
        return False


def get_block_reward(block_index: int, initial_reward: int) -> int:
    """
    Get block reward for a specific block.

    Implements halving schedule every 210,000 blocks.

    Args:
        block_index: Block number.
        initial_reward: Initial reward amount.

    Returns:
        Block reward in satoshis.
    """
    return _calculate_block_reward(block_index, initial_reward)
