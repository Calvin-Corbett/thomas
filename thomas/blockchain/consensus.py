"""
Consensus mechanisms - PoW, PoS, DPoS.

Implements Proof of Work, Proof of Stake, and Delegated Proof of Stake.
"""

import hashlib
from dataclasses import dataclass

from thomas.blockchain._exceptions import ConsensusError
from thomas.blockchain._types import Block


@dataclass
class ProofOfWork:
    """
    Proof of Work consensus mechanism.

    Miners compete to find a nonce that produces a hash below difficulty target.
    """

    target_difficulty_seconds: int = 10
    adjustment_interval: int = 2016
    initial_difficulty: int = 1

    def mine_block(
        self,
        block: Block,
        max_iterations: int = 2**32,
    ) -> tuple[int, int]:
        """
        Mine a block (find valid proof of work).

        Args:
            block: Block to mine.
            max_iterations: Maximum nonce values to try.

        Returns:
            Tuple of (nonce, iterations_tried).

        Raises:
            ConsensusError: If mining fails to find valid nonce.
        """
        from thomas.blockchain.block import BlockHeader, compute_block_hash

        for nonce in range(max_iterations):
            # Update block nonce
            header = BlockHeader(
                index=block.index,
                timestamp=block.timestamp,
                merkle_root=block.merkle_root,
                previous_hash=block.previous_hash,
                difficulty=block.difficulty,
                nonce=nonce,
            )

            block_hash = compute_block_hash(header)

            # Check if hash meets difficulty target
            if self._check_difficulty(block_hash, block.difficulty):
                return nonce, nonce

        raise ConsensusError(f"Failed to mine block after {max_iterations} iterations")

    def _check_difficulty(self, block_hash: str, difficulty: int) -> bool:
        """
        Check if block hash meets difficulty target.

        Args:
            block_hash: Block hash as hex string.
            difficulty: Difficulty bits (number of leading zeros required).

        Returns:
            True if hash meets target.
        """
        if difficulty < 1:
            return False

        required_leading_zeros = difficulty - 1
        hash_int = int(block_hash, 16)

        if hash_int == 0:
            leading_zeros = 256
        else:
            leading_zeros = 256 - hash_int.bit_length()

        return leading_zeros >= required_leading_zeros

    def adjust_difficulty(
        self,
        last_blocks: list[Block],
        target_seconds: int = None,
    ) -> int:
        """
        Adjust difficulty based on block times.

        Targets average block time of target_seconds.

        Args:
            last_blocks: Last N blocks to analyze (usually 2016).
            target_seconds: Target time between blocks.

        Returns:
            New difficulty value.
        """
        target_seconds = target_seconds or self.target_difficulty_seconds

        if len(last_blocks) < 2:
            return self.initial_difficulty

        # Calculate actual time
        actual_time = last_blocks[-1].timestamp - last_blocks[0].timestamp
        expected_time = target_seconds * (len(last_blocks) - 1)

        # Adjust difficulty
        if actual_time == 0:
            actual_time = 1

        old_difficulty = last_blocks[-1].difficulty

        # Clamp adjustment to 4x max change
        if actual_time > expected_time * 4:
            actual_time = expected_time * 4
        elif actual_time < expected_time // 4:
            actual_time = expected_time // 4

        new_difficulty = max(1, (old_difficulty * expected_time) // actual_time)
        return new_difficulty

    def estimate_hashrate(
        self,
        blocks: list[Block],
        target_difficulty_bits: int = 1,
    ) -> float:
        """
        Estimate network hashrate.

        Args:
            blocks: Blocks to analyze.
            target_difficulty_bits: Number of leading zero bits.

        Returns:
            Estimated hashrate (hashes per second).
        """
        if len(blocks) < 2:
            return 0.0

        time_diff = blocks[-1].timestamp - blocks[0].timestamp
        if time_diff == 0:
            return 0.0

        # Rough estimate: 2^difficulty hashes per block
        avg_difficulty = sum(b.difficulty for b in blocks) / len(blocks)
        hashes_per_block = 2.0**avg_difficulty
        blocks_count = len(blocks) - 1

        hashrate = (hashes_per_block * blocks_count) / time_diff
        return hashrate

    def validate_block(self, block: Block) -> bool:
        """
        Validate block against PoW consensus rules.

        Args:
            block: Block to validate.

        Returns:
            True if block meets PoW requirements.
        """
        from thomas.blockchain.block import BlockHeader, compute_block_hash

        header = BlockHeader(
            index=block.index,
            timestamp=block.timestamp,
            merkle_root=block.merkle_root,
            previous_hash=block.previous_hash,
            difficulty=block.difficulty,
            nonce=block.nonce,
        )

        block_hash = compute_block_hash(header)
        return block.hash == block_hash and self._check_difficulty(block_hash, block.difficulty)


@dataclass
class ProofOfStake:
    """
    Proof of Stake consensus mechanism.

    Validators are selected based on stake. Higher stake = higher selection probability.
    """

    validator_set_size: int = 32
    epoch_length: int = 256
    slashing_penalty: int = 1000000  # 0.01 in 8 decimals

    def select_validator(
        self,
        validators: dict[str, int],
        epoch: int,
        random_seed: int = None,
    ) -> str:
        """
        Select validator for next block.

        Selection probability weighted by stake.

        Args:
            validators: Dictionary of address -> stake amount.
            epoch: Current epoch number.
            random_seed: Seed for randomness (default based on epoch).

        Returns:
            Address of selected validator.

        Raises:
            ConsensusError: If no validators available.
        """
        if not validators:
            raise ConsensusError("No validators available")

        if random_seed is None:
            random_seed = epoch

        # Create weighted selection
        total_stake = sum(validators.values())
        if total_stake == 0:
            raise ConsensusError("Total stake is zero")

        # Use deterministic selection based on seed
        seed_hash = hashlib.sha256(str(random_seed).encode()).digest()
        rand_value = int.from_bytes(seed_hash, byteorder="big") % total_stake

        # Find validator
        cumulative = 0
        for address in sorted(validators.keys()):  # Deterministic order
            stake = validators[address]
            cumulative += stake
            if rand_value < cumulative:
                return address

        # Fallback (should not reach)
        return sorted(validators.keys())[0]

    def validate_block(self, block: Block, validator: str, validators: dict[str, int]) -> bool:
        """
        Validate block against PoS consensus rules.

        Args:
            block: Block to validate.
            validator: Address that created the block.
            validators: Dictionary of validators and stakes.

        Returns:
            True if block is valid under PoS.
        """
        # Block is valid if created by a known validator
        return validator in validators and validators[validator] > 0

    def get_epoch(self, block_index: int) -> int:
        """
        Get epoch number for a block.

        Args:
            block_index: Block number.

        Returns:
            Epoch number.
        """
        return block_index // self.epoch_length

    def get_epoch_end_block(self, epoch: int) -> int:
        """
        Get last block number in epoch.

        Args:
            epoch: Epoch number.

        Returns:
            Last block index in epoch.
        """
        return (epoch + 1) * self.epoch_length - 1


@dataclass
class DelegatedProofOfStake:
    """
    Delegated Proof of Stake consensus mechanism.

    Token holders delegate voting power to delegates.
    Top N delegates take turns producing blocks.
    """

    delegate_count: int = 21
    round_length: int = 21  # Blocks per round

    def select_validators(
        self,
        delegates: dict[str, int],
    ) -> list[str]:
        """
        Select top delegates by votes.

        Args:
            delegates: Dictionary of delegate -> vote count.

        Returns:
            List of top N delegates in order.
        """
        sorted_delegates = sorted(delegates.items(), key=lambda x: x[1], reverse=True)[: self.delegate_count]
        return [addr for addr, _ in sorted_delegates]

    def get_block_producer(self, validators: list[str], block_index: int) -> str:
        """
        Get delegate for specific block (round-robin).

        Args:
            validators: Ordered list of validators.
            block_index: Block number.

        Returns:
            Address of block producer for this block.

        Raises:
            ConsensusError: If no validators.
        """
        if not validators:
            raise ConsensusError("No validators available")

        position = block_index % len(validators)
        return validators[position]

    def update_voting_power(
        self,
        votes: dict[str, int],
        voter: str,
        delegate: str,
        amount: int,
    ) -> dict[str, int]:
        """
        Update delegate voting power.

        Args:
            votes: Current vote dictionary.
            voter: Address voting.
            delegate: Delegate receiving vote.
            amount: Vote amount (can be negative for unvote).

        Returns:
            Updated vote dictionary.
        """
        if voter not in votes:
            votes[voter] = {}

        votes[voter][delegate] = votes[voter].get(delegate, 0) + amount

        # Remove if vote is zero
        if votes[voter][delegate] <= 0:
            del votes[voter][delegate]

        return votes

    def validate_block(self, block: Block, validator: str, validators: list[str], block_index: int) -> bool:
        """
        Validate block against DPoS consensus rules.

        Args:
            block: Block to validate.
            validator: Address that created block.
            validators: Ordered list of valid validators.
            block_index: Block number.

        Returns:
            True if block is valid under DPoS.
        """
        try:
            expected_producer = self.get_block_producer(validators, block_index)
            return validator == expected_producer
        except ConsensusError:
            return False

    def slashing_condition_met(self, validator: str, blocks: list[Block], block_timestamp: int) -> bool:
        """
        Check if slashing condition applies (double signing).

        Args:
            validator: Validator address to check.
            blocks: Blocks produced by validator.
            block_timestamp: Timestamp for comparison.

        Returns:
            True if validator should be slashed.
        """
        # Check for blocks with same height (double signing)
        heights: dict[int, int] = {}

        for block in blocks:
            if block.miner == validator:
                if block.index in heights:
                    # Double signing detected
                    return True
                heights[block.index] = block.timestamp

        return False
