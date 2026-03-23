"""
Merkle tree implementation for transaction verification.

Provides merkle tree construction, proof generation, and verification
for efficient SPV (Simplified Payment Verification).
"""

import hashlib
from typing import Any


def _merkle_hash(left: str, right: str) -> str:
    """
    Compute merkle parent hash.

    Args:
        left: Left child hash (hex string).
        right: Right child hash (hex string).

    Returns:
        Parent hash (hex string).
    """
    combined = bytes.fromhex(left) + bytes.fromhex(right)
    return hashlib.sha256(combined).hexdigest()


class MerkleTree:
    """
    Merkle tree for transaction hashes.

    Supports proof generation and verification for SPV clients.
    """

    def __init__(self, transaction_hashes: list[str]) -> None:
        """
        Build merkle tree from transaction hashes.

        Args:
            transaction_hashes: List of transaction hashes (hex strings).

        Raises:
            ValueError: If no transactions provided.
        """
        if not transaction_hashes:
            raise ValueError("At least one transaction hash required")

        self.transaction_hashes = transaction_hashes
        self.tree: list[list[str]] = []
        self.root: str = ""
        self._build_tree()

    def _build_tree(self) -> None:
        """Build the merkle tree bottom-up."""
        # Start with transaction hashes as leaves
        current_level = self.transaction_hashes.copy()
        self.tree = [current_level.copy()]

        while len(current_level) > 1:
            next_level = []

            # Process pairs
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                # If odd number of hashes, duplicate the last one
                right = current_level[i + 1] if i + 1 < len(current_level) else left

                parent = _merkle_hash(left, right)
                next_level.append(parent)

            self.tree.append(next_level)
            current_level = next_level

        # Root is the last hash computed
        self.root = current_level[0] if current_level else ""

    @property
    def merkle_root(self) -> str:
        """
        Get the merkle root hash.

        Returns:
            Root hash (hex string).
        """
        return self.root

    def get_proof(self, transaction_index: int) -> list[tuple[str, str]]:
        """
        Generate merkle proof for a transaction.

        Proof is a list of (hash, direction) tuples showing the path
        from leaf to root.

        Args:
            transaction_index: Index of transaction in leaf list.

        Returns:
            List of (sibling_hash, direction) tuples.
            Direction is "left" or "right" indicating sibling position.

        Raises:
            ValueError: If index out of range.
        """
        if transaction_index >= len(self.transaction_hashes):
            raise ValueError("Transaction index out of range")

        proof: list[tuple[str, str]] = []
        index = transaction_index
        level = 0

        while level < len(self.tree) - 1:
            level_hashes = self.tree[level]

            # Determine if index is on left or right
            if index % 2 == 0:
                # Index is on left, sibling is on right
                sibling_index = index + 1
                direction = "right"
            else:
                # Index is on right, sibling is on left
                sibling_index = index - 1
                direction = "left"

            # Get sibling hash
            if sibling_index < len(level_hashes):
                sibling_hash = level_hashes[sibling_index]
                proof.append((sibling_hash, direction))

            # Move up to next level
            index = index // 2
            level += 1

        return proof

    def verify_proof(self, transaction_hash: str, proof: list[tuple[str, str]], root: str) -> bool:
        """
        Verify a merkle proof for a transaction.

        Args:
            transaction_hash: Hash of the transaction to verify.
            proof: Merkle proof (from get_proof).
            root: Expected merkle root.

        Returns:
            True if proof is valid and leads to expected root.
        """
        current = transaction_hash

        for sibling, direction in proof:
            if direction == "left":
                current = _merkle_hash(sibling, current)
            else:
                current = _merkle_hash(current, sibling)

        return current == root

    def visualize(self) -> str:
        """
        Generate ASCII visualization of merkle tree.

        Returns:
            String representation of tree structure.
        """
        lines = []
        for level_idx, level in enumerate(self.tree):
            indent = "  " * level_idx
            lines.append(f"Level {level_idx}:")
            for hash_val in level:
                lines.append(f"{indent}  {hash_val[:16]}...")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize merkle tree to dictionary.

        Returns:
            Dictionary representation of tree.
        """
        return {
            "root": self.root,
            "transaction_count": len(self.transaction_hashes),
            "tree_depth": len(self.tree),
        }


def build_merkle_tree(transaction_hashes: list[str]) -> MerkleTree:
    """
    Build a merkle tree from transaction hashes.

    Args:
        transaction_hashes: List of transaction hashes (hex strings).

    Returns:
        MerkleTree instance.

    Raises:
        ValueError: If no transactions provided.
    """
    return MerkleTree(transaction_hashes)


def verify_merkle_proof(transaction_hash: str, proof: list[tuple[str, str]], root: str) -> bool:
    """
    Verify a merkle proof (standalone function).

    Args:
        transaction_hash: Hash of transaction.
        proof: Merkle proof from get_proof.
        root: Expected merkle root.

    Returns:
        True if proof is valid.
    """
    current = transaction_hash

    for sibling, direction in proof:
        if direction == "left":
            current = _merkle_hash(sibling, current)
        else:
            current = _merkle_hash(current, sibling)

    return current == root


class PartialMerkleTree:
    """
    Partial merkle tree for SPV client verification.

    Allows verification of transactions without downloading full block.
    """

    def __init__(self, full_tree: MerkleTree, matched_indices: list[int]) -> None:
        """
        Create partial merkle tree.

        Args:
            full_tree: Full merkle tree.
            matched_indices: Indices of transactions to verify.
        """
        self.full_tree = full_tree
        self.matched_indices = set(matched_indices)
        self.proofs = self._generate_proofs()

    def _generate_proofs(self) -> dict[int, list[tuple[str, str]]]:
        """Generate proofs for all matched transactions."""
        return {idx: self.full_tree.get_proof(idx) for idx in self.matched_indices}

    def verify_transaction(self, transaction_hash: str, index: int) -> bool:
        """
        Verify a transaction in the partial tree.

        Args:
            transaction_hash: Hash of transaction.
            index: Index in transaction list.

        Returns:
            True if transaction verifies against merkle root.
        """
        if index not in self.matched_indices:
            return False

        proof = self.proofs[index]
        return verify_merkle_proof(transaction_hash, proof, self.full_tree.root)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize partial merkle tree.

        Returns:
            Dictionary representation.
        """
        return {
            "root": self.full_tree.root,
            "matched_count": len(self.matched_indices),
            "total_count": len(self.full_tree.transaction_hashes),
        }
