"""
Tests for merkle tree implementation.

Tests tree construction, proof generation, and proof verification.
"""

import hashlib

import pytest

from thomas.blockchain.merkle import (
    MerkleTree,
    PartialMerkleTree,
    build_merkle_tree,
    verify_merkle_proof,
)


def _make_hashes(count: int) -> list[str]:
    """Generate deterministic test hashes."""
    return [hashlib.sha256(f"tx_{i}".encode()).hexdigest() for i in range(count)]


class TestMerkleTreeConstruction:
    """Test merkle tree construction."""

    def test_build_tree_single_hash(self) -> None:
        """Test building tree with single transaction."""
        hashes = _make_hashes(1)
        tree = MerkleTree(hashes)

        # Root should be same as input hash
        assert tree.merkle_root == hashes[0]

    def test_build_tree_two_hashes(self) -> None:
        """Test building tree with two transactions."""
        hashes = _make_hashes(2)
        tree = MerkleTree(hashes)

        # Root should be hash of both
        assert tree.merkle_root != hashes[0]
        assert tree.merkle_root != hashes[1]
        assert len(tree.merkle_root) == 64

    def test_build_tree_odd_number(self) -> None:
        """Test building tree with odd number of transactions."""
        hashes = _make_hashes(3)
        tree = MerkleTree(hashes)

        # Tree should handle odd numbers
        assert tree.merkle_root is not None
        assert len(tree.merkle_root) == 64

    def test_build_tree_many_hashes(self) -> None:
        """Test building tree with many transactions."""
        hashes = _make_hashes(100)
        tree = MerkleTree(hashes)

        assert tree.merkle_root is not None
        # Tree levels should be log2(100) ≈ 7
        assert len(tree.tree) >= 6

    def test_merkle_root_deterministic(self) -> None:
        """Test that merkle root is deterministic."""
        hashes = _make_hashes(10)
        tree1 = MerkleTree(hashes)
        tree2 = MerkleTree(hashes)

        assert tree1.merkle_root == tree2.merkle_root

    def test_different_order_different_root(self) -> None:
        """Test that different transaction order produces different root."""
        hashes = _make_hashes(5)
        tree1 = MerkleTree(hashes)
        tree2 = MerkleTree(list(reversed(hashes)))

        assert tree1.merkle_root != tree2.merkle_root

    def test_tree_constructor_rejects_empty(self) -> None:
        """Test that empty hash list is rejected."""
        with pytest.raises(ValueError):
            MerkleTree([])


class TestMerkleProof:
    """Test merkle proof generation and verification."""

    def test_get_proof_single_leaf(self) -> None:
        """Test proof for single transaction."""
        hashes = _make_hashes(1)
        tree = MerkleTree(hashes)

        proof = tree.get_proof(0)

        # Single leaf has no proof (empty list)
        assert len(proof) == 0

    def test_get_proof_multiple_leaves(self) -> None:
        """Test proof generation for multiple transactions."""
        hashes = _make_hashes(4)
        tree = MerkleTree(hashes)

        # Get proof for each transaction
        for i in range(4):
            proof = tree.get_proof(i)
            # Proof should be non-empty for all but root
            assert isinstance(proof, list)

    def test_verify_proof_valid(self) -> None:
        """Test verifying valid merkle proof."""
        hashes = _make_hashes(8)
        tree = MerkleTree(hashes)

        for i in range(8):
            proof = tree.get_proof(i)
            is_valid = verify_merkle_proof(hashes[i], proof, tree.merkle_root)
            assert is_valid

    def test_verify_proof_invalid_hash(self) -> None:
        """Test rejecting proof for wrong transaction hash."""
        hashes = _make_hashes(8)
        tree = MerkleTree(hashes)

        proof = tree.get_proof(0)

        # Try with different hash
        wrong_hash = hashlib.sha256(b"wrong").hexdigest()
        is_valid = verify_merkle_proof(wrong_hash, proof, tree.merkle_root)

        assert not is_valid

    def test_verify_proof_wrong_root(self) -> None:
        """Test rejecting proof for wrong merkle root."""
        hashes = _make_hashes(8)
        tree = MerkleTree(hashes)

        proof = tree.get_proof(0)

        # Wrong root
        wrong_root = hashlib.sha256(b"wrong_root").hexdigest()
        is_valid = verify_merkle_proof(hashes[0], proof, wrong_root)

        assert not is_valid

    def test_verify_proof_tampered(self) -> None:
        """Test rejecting tampered proof."""
        hashes = _make_hashes(16)
        tree = MerkleTree(hashes)

        proof = tree.get_proof(5)

        # Tamper with proof
        if proof:
            tampered_hash, direction = proof[0]
            tampered = [("0" * 64, direction)] + proof[1:]
            is_valid = verify_merkle_proof(hashes[5], tampered, tree.merkle_root)
            assert not is_valid

    def test_proof_path_length(self) -> None:
        """Test proof path lengths are logarithmic."""
        # 8 transactions: proof depth should be 3
        hashes = _make_hashes(8)
        tree = MerkleTree(hashes)

        for i in range(8):
            proof = tree.get_proof(i)
            assert len(proof) <= 3  # log2(8) = 3

        # 1024 transactions: proof depth should be 10
        hashes = _make_hashes(1024)
        tree = MerkleTree(hashes)

        for i in range(1024):
            proof = tree.get_proof(i)
            assert len(proof) <= 11  # log2(1024) + 1


class TestMerkleHelper:
    """Test helper functions."""

    def test_build_merkle_tree_function(self) -> None:
        """Test standalone build_merkle_tree function."""
        hashes = _make_hashes(10)
        tree = build_merkle_tree(hashes)

        assert isinstance(tree, MerkleTree)
        assert tree.merkle_root is not None

    def test_verify_merkle_proof_function(self) -> None:
        """Test standalone verify_merkle_proof function."""
        hashes = _make_hashes(16)
        tree = MerkleTree(hashes)

        for i in range(16):
            proof = tree.get_proof(i)
            is_valid = verify_merkle_proof(hashes[i], proof, tree.merkle_root)
            assert is_valid


class TestPartialMerkleTree:
    """Test partial merkle tree for SPV."""

    def test_create_partial_tree(self) -> None:
        """Test creating partial merkle tree."""
        hashes = _make_hashes(16)
        full_tree = MerkleTree(hashes)

        # Create partial tree for subset of transactions
        matched = [0, 5, 10, 15]
        partial = PartialMerkleTree(full_tree, matched)

        assert partial.full_tree.root == full_tree.root

    def test_verify_transaction_in_partial_tree(self) -> None:
        """Test verifying transaction in partial tree."""
        hashes = _make_hashes(32)
        full_tree = MerkleTree(hashes)

        # Include transactions 0, 5, 10
        matched = [0, 5, 10]
        partial = PartialMerkleTree(full_tree, matched)

        # These should verify
        for idx in matched:
            assert partial.verify_transaction(hashes[idx], idx)

    def test_partial_tree_rejects_unmatched(self) -> None:
        """Test that partial tree rejects unmatched transactions."""
        hashes = _make_hashes(16)
        full_tree = MerkleTree(hashes)

        matched = [0, 5]
        partial = PartialMerkleTree(full_tree, matched)

        # Transaction not in matched set should fail
        assert not partial.verify_transaction(hashes[3], 3)


class TestMerkleVisualization:
    """Test tree visualization."""

    def test_visualize(self) -> None:
        """Test tree visualization function."""
        hashes = _make_hashes(4)
        tree = MerkleTree(hashes)

        viz = tree.visualize()

        assert isinstance(viz, str)
        assert "Level" in viz
        assert "..." in viz  # Truncated hashes


class TestMerkleEdgeCases:
    """Test edge cases."""

    def test_large_tree(self) -> None:
        """Test building large merkle tree."""
        hashes = _make_hashes(10000)
        tree = MerkleTree(hashes)

        # Should complete without errors
        assert tree.merkle_root is not None

        # Verify a few transactions
        for idx in [0, 5000, 9999]:
            proof = tree.get_proof(idx)
            is_valid = verify_merkle_proof(hashes[idx], proof, tree.merkle_root)
            assert is_valid

    def test_power_of_two_sizes(self) -> None:
        """Test various power-of-two sizes."""
        for power in range(1, 10):
            count = 2**power
            hashes = _make_hashes(count)
            tree = MerkleTree(hashes)

            # Verify each transaction
            for i in range(min(count, 10)):  # Test first 10
                proof = tree.get_proof(i)
                is_valid = verify_merkle_proof(hashes[i], proof, tree.merkle_root)
                assert is_valid

    def test_non_power_of_two_sizes(self) -> None:
        """Test non-power-of-two sizes."""
        for count in [3, 5, 7, 11, 13, 17]:
            hashes = _make_hashes(count)
            tree = MerkleTree(hashes)

            # Verify all transactions
            for i in range(count):
                proof = tree.get_proof(i)
                is_valid = verify_merkle_proof(hashes[i], proof, tree.merkle_root)
                assert is_valid
