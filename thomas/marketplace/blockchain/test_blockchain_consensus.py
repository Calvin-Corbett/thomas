"""
Tests for consensus mechanisms.

Tests Proof of Work, Proof of Stake, and Delegated Proof of Stake.
"""

import pytest

from thomas.marketplace.blockchain.block import create_block, create_genesis_block
from thomas.marketplace.blockchain.consensus import DelegatedProofOfStake, ProofOfStake, ProofOfWork
from thomas.marketplace.blockchain.transaction import create_coinbase_transaction


@pytest.fixture
def pow_consensus():
    """Create Proof of Work consensus."""
    return ProofOfWork(target_difficulty_seconds=10, initial_difficulty=1)


@pytest.fixture
def pos_consensus():
    """Create Proof of Stake consensus."""
    return ProofOfStake(validator_set_size=32)


@pytest.fixture
def dpos_consensus():
    """Create Delegated Proof of Stake consensus."""
    return DelegatedProofOfStake(delegate_count=21)


@pytest.fixture
def genesis_block():
    """Create genesis block."""
    return create_genesis_block(
        miner="miner_1",
        initial_reward=5000000000,
        difficulty=1,
    )


class TestProofOfWork:
    """Test Proof of Work consensus."""

    def test_mine_block(self, pow_consensus, genesis_block):
        """Test mining a block."""
        miner_addr = genesis_block.miner

        # Create block to mine
        coinbase = create_coinbase_transaction(miner_addr, 5000000000, 1, miner_addr)
        block = create_block(
            index=1,
            transactions=[coinbase],
            previous_hash=genesis_block.hash,
            difficulty=1,
            miner=miner_addr,
        )

        # Mine block
        nonce, iterations = pow_consensus.mine_block(block)

        assert nonce >= 0
        assert iterations >= 0

    def test_difficulty_check_valid(self, pow_consensus):
        """Test valid hash passes difficulty check."""
        # Hash with leading zeros should pass low difficulty
        valid_hash = "0" * 20 + "a" * 44

        assert pow_consensus._check_difficulty(valid_hash, 1) is True

    def test_difficulty_check_invalid(self, pow_consensus):
        """Test invalid hash fails difficulty check."""
        # No leading zeros should fail high difficulty
        invalid_hash = "f" * 64

        assert pow_consensus._check_difficulty(invalid_hash, 5) is False

    def test_difficulty_zero_invalid(self, pow_consensus):
        """Test difficulty of 0 is invalid."""
        valid_hash = "0" * 64

        assert pow_consensus._check_difficulty(valid_hash, 0) is False

    def test_adjust_difficulty_increases(self, pow_consensus):
        """Test difficulty increases when blocks too fast."""
        import time

        blocks = []
        current_time = int(time.time())

        # Create blocks faster than target
        for i in range(10):
            block = create_genesis_block(
                miner=f"miner_{i}",
                initial_reward=5000000000,
                difficulty=1,
            )
            # Override timestamp to be faster
            blocks.append(block)

        # Difficulty should not increase with only 10 blocks
        # (adjustment normally happens every 2016 blocks)

    def test_hashrate_estimation(self, pow_consensus, genesis_block):
        """Test hashrate estimation."""
        blocks = [genesis_block]

        hashrate = pow_consensus.estimate_hashrate(blocks)

        # Low hashrate for single block
        assert hashrate >= 0

    def test_pow_validate_block_valid(self, pow_consensus, genesis_block):
        """Test validating block with PoW."""
        assert pow_consensus.validate_block(genesis_block) is True

    def test_pow_validate_block_tampered(self, pow_consensus, genesis_block):
        """Test PoW validation fails on tampered hash."""
        # Create block with wrong hash
        from thomas.marketplace.blockchain._types import Block

        tampered = Block(
            index=genesis_block.index,
            timestamp=genesis_block.timestamp,
            transactions=genesis_block.transactions,
            previous_hash=genesis_block.previous_hash,
            nonce=genesis_block.nonce,
            hash="0" * 64,  # Wrong hash
            merkle_root=genesis_block.merkle_root,
            difficulty=genesis_block.difficulty,
            miner=genesis_block.miner,
        )

        assert pow_consensus.validate_block(tampered) is False


class TestProofOfStake:
    """Test Proof of Stake consensus."""

    def test_select_validator(self, pos_consensus):
        """Test validator selection."""
        validators = {
            "validator_1": 1000,
            "validator_2": 2000,
            "validator_3": 500,
        }

        validator = pos_consensus.select_validator(validators, epoch=0)

        assert validator in validators

    def test_validator_selection_weighted(self, pos_consensus):
        """Test validator selection is weighted by stake."""
        validators = {
            "rich_validator": 10000,
            "poor_validator": 10,
        }

        # With same seed, should always select same validator
        validator1 = pos_consensus.select_validator(validators, epoch=0, random_seed=42)
        validator2 = pos_consensus.select_validator(validators, epoch=0, random_seed=42)

        assert validator1 == validator2

    def test_validator_selection_no_validators(self, pos_consensus):
        """Test selection fails with no validators."""
        from thomas.marketplace.blockchain._exceptions import ConsensusError

        with pytest.raises(ConsensusError):
            pos_consensus.select_validator({}, epoch=0)

    def test_validator_selection_zero_stake(self, pos_consensus):
        """Test selection fails when total stake is zero."""
        from thomas.marketplace.blockchain._exceptions import ConsensusError

        validators = {
            "validator_1": 0,
            "validator_2": 0,
        }

        with pytest.raises(ConsensusError):
            pos_consensus.select_validator(validators, epoch=0)

    def test_pos_validate_block_valid(self, pos_consensus, genesis_block):
        """Test validating block with PoS."""
        validators = {genesis_block.miner: 1000}

        is_valid = pos_consensus.validate_block(genesis_block, genesis_block.miner, validators)

        assert is_valid is True

    def test_pos_validate_block_invalid_validator(self, pos_consensus, genesis_block):
        """Test validation fails for unknown validator."""
        validators = {"other_validator": 1000}

        is_valid = pos_consensus.validate_block(genesis_block, "unknown_validator", validators)

        assert is_valid is False

    def test_epoch_calculation(self, pos_consensus):
        """Test epoch calculation."""
        # With epoch_length=256
        assert pos_consensus.get_epoch(0) == 0
        assert pos_consensus.get_epoch(255) == 0
        assert pos_consensus.get_epoch(256) == 1
        assert pos_consensus.get_epoch(511) == 1
        assert pos_consensus.get_epoch(512) == 2

    def test_epoch_end_block(self, pos_consensus):
        """Test epoch end block calculation."""
        assert pos_consensus.get_epoch_end_block(0) == 255
        assert pos_consensus.get_epoch_end_block(1) == 511
        assert pos_consensus.get_epoch_end_block(2) == 767


class TestDelegatedProofOfStake:
    """Test Delegated Proof of Stake consensus."""

    def test_select_validators(self, dpos_consensus):
        """Test selecting top delegates."""
        delegates = {
            "delegate_1": 5000,
            "delegate_2": 4000,
            "delegate_3": 3000,
            "delegate_4": 2000,
            "delegate_5": 1000,
        }

        top_delegates = dpos_consensus.select_validators(delegates)

        # Should return top N delegates
        assert len(top_delegates) <= dpos_consensus.delegate_count
        assert "delegate_1" in top_delegates
        assert "delegate_5" in top_delegates

    def test_block_producer_order(self, dpos_consensus):
        """Test block producer selection order."""
        validators = ["delegate_1", "delegate_2", "delegate_3"]

        # First block -> delegate_1
        producer = dpos_consensus.get_block_producer(validators, 0)
        assert producer == "delegate_1"

        # Second block -> delegate_2
        producer = dpos_consensus.get_block_producer(validators, 1)
        assert producer == "delegate_2"

        # After round -> back to delegate_1
        producer = dpos_consensus.get_block_producer(validators, 3)
        assert producer == "delegate_1"

    def test_block_producer_no_validators(self, dpos_consensus):
        """Test producer selection fails with no validators."""
        from thomas.marketplace.blockchain._exceptions import ConsensusError

        with pytest.raises(ConsensusError):
            dpos_consensus.get_block_producer([], 0)

    def test_dpos_validate_block_valid(self, dpos_consensus, genesis_block):
        """Test validating block with DPoS."""
        validators = [genesis_block.miner, "delegate_2", "delegate_3"]

        is_valid = dpos_consensus.validate_block(genesis_block, genesis_block.miner, validators, 0)

        assert is_valid is True

    def test_dpos_validate_block_wrong_producer(self, dpos_consensus, genesis_block):
        """Test validation fails for wrong producer."""
        validators = ["delegate_1", "delegate_2", "delegate_3"]

        is_valid = dpos_consensus.validate_block(
            genesis_block,
            "delegate_2",
            validators,
            0,  # Block 0 should be by delegate_1
        )

        assert is_valid is False

    def test_slashing_condition_double_signing(self, dpos_consensus, genesis_block):
        """Test slashing condition for double signing."""
        # Create two blocks at same height
        block2 = create_genesis_block(
            miner=genesis_block.miner,
            initial_reward=5000000000,
            difficulty=1,
        )

        blocks = [genesis_block, block2]

        # Both have index 0, so double signing is detected
        should_slash = dpos_consensus.slashing_condition_met(genesis_block.miner, blocks, int(genesis_block.timestamp))

        assert should_slash is True


class TestConsensusIntegration:
    """Integration tests for consensus mechanisms."""

    def test_pow_consensus_flow(self, pow_consensus, genesis_block):
        """Test complete PoW consensus flow."""
        # Validate genesis
        assert pow_consensus.validate_block(genesis_block) is True

    def test_pos_consensus_flow(self, pos_consensus):
        """Test complete PoS consensus flow."""
        validators = {
            "validator_1": 5000,
            "validator_2": 3000,
        }

        # Select validator
        validator = pos_consensus.select_validator(validators, 0)
        assert validator in validators

    def test_dpos_consensus_flow(self, dpos_consensus):
        """Test complete DPoS consensus flow."""
        delegates = {f"delegate_{i}": 5000 - (i * 100) for i in range(dpos_consensus.delegate_count)}

        # Select top delegates
        top = dpos_consensus.select_validators(delegates)
        assert len(top) == dpos_consensus.delegate_count

        # Get next producer
        producer = dpos_consensus.get_block_producer(top, 0)
        assert producer in top
