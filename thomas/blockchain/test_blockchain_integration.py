"""
Integration tests for complete blockchain workflow.

Tests end-to-end flows: wallet → transaction → mempool → mine → chain.
"""

import pytest

from thomas.blockchain._types import ChainConfig, ConsensusType
from thomas.blockchain.block import create_block, create_genesis_block
from thomas.blockchain.chain import Blockchain
from thomas.blockchain.consensus import ProofOfWork
from thomas.blockchain.crypto import (
    derive_address,
    generate_deterministic_keypair,
    generate_keypair,
)
from thomas.blockchain.mempool import Mempool
from thomas.blockchain.network import Network
from thomas.blockchain.transaction import create_coinbase_transaction, create_transaction
from thomas.blockchain.wallet import Wallet


@pytest.fixture
def setup_blockchain():
    """Setup complete blockchain environment."""
    # Create genesis
    genesis = create_genesis_block(
        miner="genesis_miner",
        initial_reward=5000000000,
        difficulty=1,
    )

    # Create chain
    config = ChainConfig(
        consensus_type=ConsensusType.POW,
        difficulty_target_seconds=10,
    )
    chain = Blockchain(genesis, config)

    # Create mempool
    mempool = Mempool(max_size=1000)

    # Create consensus
    consensus = ProofOfWork()

    return {
        "genesis": genesis,
        "chain": chain,
        "mempool": mempool,
        "consensus": consensus,
    }


class TestWalletToTransaction:
    """Test wallet transaction creation."""

    def test_create_transaction_from_wallet(self):
        """Test creating transaction from wallet."""
        # Create wallet
        wallet = Wallet(name="TestWallet")
        addr = wallet.create_address(label="MyAddress")

        # Update balance
        wallet.update_balance(addr, 5000000)

        # Create transaction
        recipient = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )

        tx = wallet.create_transaction(
            sender=addr,
            recipient=recipient,
            amount=1000000,
            fee=10000,
        )

        assert tx is not None
        assert tx.sender == addr
        assert tx.recipient == recipient
        assert tx.amount == 1000000

    def test_wallet_insufficient_balance(self):
        """Test transaction fails with insufficient balance."""
        wallet = Wallet(name="TestWallet")
        addr = wallet.create_address()

        wallet.update_balance(addr, 100000)  # Small balance

        recipient = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )

        with pytest.raises(ValueError):
            wallet.create_transaction(
                sender=addr,
                recipient=recipient,
                amount=200000,  # More than balance
                fee=10000,
            )

    def test_transaction_nonce_increment(self):
        """Test transaction nonce increments."""
        wallet = Wallet(name="TestWallet")
        addr = wallet.create_address()

        wallet.update_balance(addr, 5000000)

        recipient = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )

        # First transaction
        tx1 = wallet.create_transaction(
            sender=addr,
            recipient=recipient,
            amount=100000,
            fee=10000,
        )

        # Update nonce
        wallet.update_nonce(addr, 1)

        # Second transaction
        tx2 = wallet.create_transaction(
            sender=addr,
            recipient=recipient,
            amount=100000,
            fee=10000,
        )

        assert tx1.nonce == 0
        assert tx2.nonce == 1


class TestTransactionToMempool:
    """Test adding transactions to mempool."""

    def test_add_transaction_to_mempool(self, setup_blockchain):
        """Test adding transaction to mempool."""
        mempool = setup_blockchain["mempool"]

        # Create transaction
        from thomas.blockchain.crypto import generate_deterministic_keypair

        keypair = generate_deterministic_keypair("sender")
        sender = derive_address(keypair.public_key_x, keypair.public_key_y)

        keypair2 = generate_deterministic_keypair("recipient")
        recipient = derive_address(keypair2.public_key_x, keypair2.public_key_y)

        tx = create_transaction(
            sender=sender,
            recipient=recipient,
            amount=100000,
            fee=10000,
            nonce=0,
            private_key=keypair.private_key,
        )

        # Add to mempool
        result = mempool.add_transaction(tx)

        assert result is True
        assert mempool.has_transaction(tx.hash)

    def test_mempool_transaction_ordering(self, setup_blockchain):
        """Test mempool orders transactions by priority."""
        mempool = setup_blockchain["mempool"]

        keypair1 = generate_deterministic_keypair("sender1")
        sender1 = derive_address(keypair1.public_key_x, keypair1.public_key_y)

        keypair2 = generate_deterministic_keypair("recipient1")
        recipient1 = derive_address(keypair2.public_key_x, keypair2.public_key_y)

        # Add transactions with different fees
        for fee in [1000, 5000, 2000]:
            tx = create_transaction(
                sender=sender1,
                recipient=recipient1,
                amount=100000,
                fee=fee,
                nonce=0,
                private_key=keypair1.private_key,
            )
            mempool.add_transaction(tx)

        # Get by priority (high fee first)
        txs = mempool.get_transactions_by_priority(2)

        # Higher fee should come first
        assert txs[0].fee >= txs[-1].fee if len(txs) > 1 else True


class TestMempoolToBlock:
    """Test creating blocks from mempool transactions."""

    def test_get_next_batch_for_block(self, setup_blockchain):
        """Test getting transactions for block inclusion."""
        mempool = setup_blockchain["mempool"]

        # Add some transactions
        for i in range(5):
            keypair = generate_deterministic_keypair(f"sender_{i}")
            sender = derive_address(keypair.public_key_x, keypair.public_key_y)

            recipient = derive_address(
                generate_keypair().public_key_x,
                generate_keypair().public_key_y,
            )

            tx = create_transaction(
                sender=sender,
                recipient=recipient,
                amount=100000,
                fee=10000,
                nonce=0,
                private_key=keypair.private_key,
            )

            mempool.add_transaction(tx)

        # Get batch for block
        batch = mempool.get_next_batch(max_count=10)

        assert len(batch) > 0
        assert len(batch) <= 10

    def test_create_block_from_mempool(self, setup_blockchain):
        """Test creating block with mempool transactions."""
        chain = setup_blockchain["chain"]
        mempool = setup_blockchain["mempool"]

        genesis = setup_blockchain["genesis"]

        # Add transaction to mempool
        keypair = generate_deterministic_keypair("sender")
        sender = derive_address(keypair.public_key_x, keypair.public_key_y)

        recipient = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )

        tx = create_transaction(
            sender=sender,
            recipient=recipient,
            amount=100000,
            fee=10000,
            nonce=0,
            private_key=keypair.private_key,
        )

        mempool.add_transaction(tx)

        # Create block
        batch = mempool.get_next_batch()
        coinbase = create_coinbase_transaction("miner", 5000000000, 1, "miner")

        block = create_block(
            index=1,
            transactions=[coinbase] + batch,
            previous_hash=genesis.hash,
            difficulty=1,
            miner="miner",
        )

        assert block.transaction_count >= 1


class TestBlockchainMining:
    """Test mining flow."""

    def test_mine_block(self, setup_blockchain):
        """Test mining a block."""
        consensus = setup_blockchain["consensus"]
        chain = setup_blockchain["chain"]

        genesis = chain.get_block_by_index(0)

        # Create block to mine
        coinbase = create_coinbase_transaction("miner", 5000000000, 1, "miner")

        block = create_block(
            index=1,
            transactions=[coinbase],
            previous_hash=genesis.hash,
            difficulty=1,
            miner="miner",
        )

        # Mine block (simplified, no actual work)
        assert block.hash is not None

    def test_add_mined_block_to_chain(self, setup_blockchain):
        """Test adding mined block to chain."""
        chain = setup_blockchain["chain"]
        genesis = chain.get_block_by_index(0)

        # Create and add block
        coinbase = create_coinbase_transaction("miner", 5000000000, 1, "miner")

        block = create_block(
            index=1,
            transactions=[coinbase],
            previous_hash=genesis.hash,
            difficulty=1,
            miner="miner",
        )

        result = chain.add_block(block)

        assert result is True
        assert chain.get_height() == 2


class TestNetworkPropagation:
    """Test network message propagation."""

    def test_broadcast_block(self):
        """Test broadcasting block over network."""
        # Create network node
        network = Network(node_id="node_1")

        # Add peers
        network.add_peer("node_2", "localhost", 8001)
        network.add_peer("node_3", "localhost", 8002)

        # Create block
        genesis = create_genesis_block("miner", 5000000000, 1)

        # Broadcast
        count = network.broadcast_block(genesis)

        assert count == 2  # Sent to 2 peers

    def test_broadcast_transaction(self):
        """Test broadcasting transaction over network."""
        network = Network(node_id="node_1")

        network.add_peer("node_2", "localhost", 8001)
        network.add_peer("node_3", "localhost", 8002)

        # Create transaction
        keypair = generate_deterministic_keypair("sender")
        sender = derive_address(keypair.public_key_x, keypair.public_key_y)

        recipient = derive_address(
            generate_keypair().public_key_x,
            generate_keypair().public_key_y,
        )

        tx = create_transaction(
            sender=sender,
            recipient=recipient,
            amount=100000,
            fee=10000,
            nonce=0,
            private_key=keypair.private_key,
        )

        # Broadcast
        count = network.broadcast_transaction(tx)

        assert count == 2

    def test_network_partition_recovery(self):
        """Test network partition and recovery."""
        network = Network(node_id="node_1")

        network.add_peer("node_2", "localhost", 8001)

        # Create partition
        network.create_network_partition()
        assert network.is_partitioned() is True

        genesis = create_genesis_block("miner", 5000000000, 1)

        # Messages shouldn't propagate during partition
        count = network.broadcast_block(genesis)
        assert count == 0

        # Heal partition
        network.heal_network_partition()
        assert network.is_partitioned() is False

        # Now messages can propagate
        count = network.broadcast_block(genesis)
        assert count == 1


class TestFullWorkflow:
    """Complete end-to-end workflow tests."""

    def test_complete_transaction_flow(self, setup_blockchain):
        """Test complete transaction workflow."""
        chain = setup_blockchain["chain"]
        mempool = setup_blockchain["mempool"]

        genesis = chain.get_block_by_index(0)
        miner = genesis.miner

        # Update miner balance and nonce
        chain.state[miner].balance = 100000000
        chain.state[miner].nonce = 0

        # Create sender and recipient
        sender_kp = generate_deterministic_keypair("sender")
        sender = derive_address(sender_kp.public_key_x, sender_kp.public_key_y)

        recipient_kp = generate_deterministic_keypair("recipient")
        recipient = derive_address(recipient_kp.public_key_x, recipient_kp.public_key_y)

        # Add balance to sender
        chain.state[sender] = type(
            "obj",
            (object,),
            {
                "address": sender,
                "balance": 50000000,
                "nonce": 0,
                "transactions": [],
            },
        )()

        # Create transaction
        tx = create_transaction(
            sender=sender,
            recipient=recipient,
            amount=1000000,
            fee=100000,
            nonce=0,
            private_key=sender_kp.private_key,
        )

        # Add to mempool
        mempool.add_transaction(tx)

        # Get for block
        batch = mempool.get_next_batch()
        assert len(batch) > 0

        # Create block
        coinbase = create_coinbase_transaction(miner, 5000000000, 1, miner)

        block = create_block(
            index=1,
            transactions=[coinbase] + batch,
            previous_hash=genesis.hash,
            difficulty=1,
            miner=miner,
        )

        # Add to chain
        result = chain.add_block(block)
        assert result is True

        # Verify chain validity
        assert chain.validate_chain() is True

    def test_multiple_blocks_chain(self, setup_blockchain):
        """Test creating multiple blocks and chain validation."""
        chain = setup_blockchain["chain"]

        genesis = chain.get_block_by_index(0)
        miner = genesis.miner

        # Create several blocks
        for i in range(1, 4):
            coinbase = create_coinbase_transaction(miner, 5000000000, i, miner)

            block = create_block(
                index=i,
                transactions=[coinbase],
                previous_hash=chain.get_block_by_index(i - 1).hash,
                difficulty=1,
                miner=miner,
            )

            chain.add_block(block)

        # Verify chain
        assert chain.get_height() == 4
        assert chain.validate_chain() is True
        assert chain.get_balance(miner) > 0
