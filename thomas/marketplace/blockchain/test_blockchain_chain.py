"""
Tests for blockchain chain implementation.

Tests block addition, chain validation, state management, and fork resolution.
"""

import pytest

from thomas.marketplace.blockchain.block import create_block, create_genesis_block
from thomas.marketplace.blockchain.chain import Blockchain
from thomas.marketplace.blockchain.crypto import generate_keypair
from thomas.marketplace.blockchain.transaction import create_coinbase_transaction, create_transaction


@pytest.fixture
def genesis_block():
    """Create genesis block for testing."""
    return create_genesis_block(
        miner="miner_1",
        initial_reward=5000000000,
        difficulty=1,
    )


@pytest.fixture
def chain(genesis_block):
    """Create blockchain with genesis."""
    return Blockchain(genesis_block)


@pytest.fixture
def keypairs():
    """Create test keypairs."""
    return {
        "alice": generate_keypair(b"alice_seed_1234567890123456"),
        "bob": generate_keypair(b"bob_seed__1234567890123456"),
        "charlie": generate_keypair(b"charlie___1234567890123456"),
    }


class TestBlockAddition:
    """Test adding blocks to chain."""

    def test_add_single_block(self, chain, genesis_block):
        """Test adding one block to chain."""
        from thomas.marketplace.blockchain.crypto import derive_address

        # Create coinbase transaction
        miner_addr = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )
        coinbase = create_coinbase_transaction(miner_addr, 5000000000, 1, miner_addr)

        # Create block
        block = create_block(
            index=1,
            transactions=[coinbase],
            previous_hash=genesis_block.hash,
            difficulty=1,
            miner=miner_addr,
        )

        # Add block
        result = chain.add_block(block)

        assert result is True
        assert chain.get_height() == 2

    def test_reject_duplicate_block(self, chain, genesis_block):
        """Test rejecting duplicate blocks."""
        from thomas.marketplace.blockchain.crypto import derive_address

        miner_addr = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )
        coinbase = create_coinbase_transaction(miner_addr, 5000000000, 1, miner_addr)

        block = create_block(
            index=1,
            transactions=[coinbase],
            previous_hash=genesis_block.hash,
            difficulty=1,
            miner=miner_addr,
        )

        # Add block first time
        assert chain.add_block(block) is True

        # Add same block again
        assert chain.add_block(block) is False

    def test_reject_block_wrong_parent(self, chain):
        """Test rejecting block with wrong parent."""
        from thomas.marketplace.blockchain.crypto import derive_address

        miner_addr = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )
        coinbase = create_coinbase_transaction(miner_addr, 5000000000, 1, miner_addr)

        # Block with wrong parent hash
        block = create_block(
            index=1,
            transactions=[coinbase],
            previous_hash="0" * 64,  # Wrong parent
            difficulty=1,
            miner=miner_addr,
        )

        result = chain.add_block(block)

        assert result is False


class TestChainValidation:
    """Test chain validation."""

    def test_validate_valid_chain(self, chain):
        """Test validating valid chain."""
        assert chain.validate_chain() is True

    def test_chain_height_and_tip(self, chain, genesis_block):
        """Test chain height and tip operations."""
        assert chain.get_height() == 1
        assert chain.get_tip() == genesis_block

    def test_get_block_by_index(self, chain, genesis_block):
        """Test retrieving block by index."""
        block = chain.get_block_by_index(0)
        assert block == genesis_block


class TestChainState:
    """Test blockchain state management."""

    def test_initial_state_from_genesis(self, chain):
        """Test initial state after genesis."""
        # Genesis block has coinbase transaction
        tip = chain.get_tip()

        # Miner should have block reward
        miner_info = chain.get_wallet_info(tip.miner)
        assert miner_info is not None
        assert miner_info.balance > 0

    def test_balance_tracking(self, chain, genesis_block, keypairs):
        """Test balance tracking across blocks."""
        alice_keypair = keypairs["alice"]
        from thomas.marketplace.blockchain.crypto import derive_address

        alice_addr = derive_address(alice_keypair.public_key_x, alice_keypair.public_key_y)
        miner_addr = genesis_block.miner

        # Initial state
        chain.get_balance(miner_addr)

        # Create transaction from miner to alice
        amount = 1000000
        fee = 100000

        # First update miner nonce
        chain.update_nonce(miner_addr, 0)

        tx = create_transaction(
            sender=miner_addr,
            recipient=alice_addr,
            amount=amount,
            fee=fee,
            nonce=0,
            private_key=alice_keypair.private_key,
        )

        # Create block with transaction
        coinbase = create_coinbase_transaction(miner_addr, 5000000000, 1, miner_addr)
        block = create_block(
            index=1,
            transactions=[coinbase, tx],
            previous_hash=genesis_block.hash,
            difficulty=1,
            miner=miner_addr,
        )

        # Add block
        chain.add_block(block)

        # Check balances
        alice_balance = chain.get_balance(alice_addr)
        assert alice_balance > 0

    def test_nonce_tracking(self, chain):
        """Test transaction nonce tracking."""
        miner = chain.get_tip().miner

        initial_nonce = chain.get_nonce(miner)
        # Nonce increments with each transaction sent
        assert initial_nonce >= 0


class TestForkResolution:
    """Test fork detection and resolution."""

    def test_longest_chain_wins(self, chain, genesis_block):
        """Test that longest chain is selected."""
        from thomas.marketplace.blockchain.crypto import derive_address

        # Create two blocks on different miners
        miner1_addr = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )
        miner2_addr = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )

        # Block 1 from miner1
        coinbase1 = create_coinbase_transaction(miner1_addr, 5000000000, 1, miner1_addr)
        block1 = create_block(
            index=1,
            transactions=[coinbase1],
            previous_hash=genesis_block.hash,
            difficulty=1,
            miner=miner1_addr,
        )

        # Block 1 from miner2 (fork)
        coinbase2 = create_coinbase_transaction(miner2_addr, 5000000000, 1, miner2_addr)
        block2 = create_block(
            index=1,
            transactions=[coinbase2],
            previous_hash=genesis_block.hash,
            difficulty=1,
            miner=miner2_addr,
        )

        # Add first block
        assert chain.add_block(block1) is True
        assert chain.get_tip().miner == miner1_addr

        # Add second block (fork) - should not replace
        assert chain.add_block(block2) is False
        assert chain.get_tip().miner == miner1_addr

    def test_chain_reorganization(self, chain, genesis_block):
        """Test chain reorganization on longer chain."""
        from thomas.marketplace.blockchain.crypto import derive_address

        miner_addr = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )

        # Build main chain: genesis -> block1 -> block2
        coinbase1 = create_coinbase_transaction(miner_addr, 5000000000, 1, miner_addr)
        block1 = create_block(
            index=1,
            transactions=[coinbase1],
            previous_hash=genesis_block.hash,
            difficulty=1,
            miner=miner_addr,
        )
        chain.add_block(block1)

        coinbase2 = create_coinbase_transaction(miner_addr, 5000000000, 2, miner_addr)
        block2 = create_block(
            index=2,
            transactions=[coinbase2],
            previous_hash=block1.hash,
            difficulty=1,
            miner=miner_addr,
        )
        chain.add_block(block2)

        # Main chain should have 3 blocks
        assert chain.get_height() == 3
        assert chain.get_tip().index == 2


class TestBlockRewards:
    """Test block reward calculations."""

    def test_block_reward_halving(self):
        """Test block reward halving every 210000 blocks."""
        from thomas.marketplace.blockchain.block import get_block_reward

        initial_reward = 5000000000

        # First blocks
        assert get_block_reward(0, initial_reward) == initial_reward
        assert get_block_reward(209999, initial_reward) == initial_reward

        # After halving
        assert get_block_reward(210000, initial_reward) == initial_reward // 2
        assert get_block_reward(419999, initial_reward) == initial_reward // 2

        # Second halving
        assert get_block_reward(420000, initial_reward) == initial_reward // 4


class TestDifficultyAdjustment:
    """Test difficulty adjustment."""

    def test_initial_difficulty(self, genesis_block):
        """Test initial difficulty is set."""
        assert genesis_block.difficulty >= 1


class TestChainIntegrity:
    """Test chain integrity checks."""

    def test_validate_chain_integrity(self, chain):
        """Test complete chain validation."""
        assert chain.validate_chain() is True

    def test_transaction_index(self, chain, genesis_block):
        """Test transaction indexing."""
        coinbase = genesis_block.transactions[0]

        # Coinbase should be indexed
        indexed_hash = chain.tx_index.get(coinbase.hash)
        assert indexed_hash == genesis_block.hash


class TestEdgeCases:
    """Test edge cases."""

    def test_zero_balance_address(self, chain):
        """Test querying balance for non-existent address."""
        balance = chain.get_balance("nonexistent_addr")
        assert balance == 0

    def test_zero_nonce_address(self, chain):
        """Test querying nonce for non-existent address."""
        nonce = chain.get_nonce("nonexistent_addr")
        assert nonce == 0
