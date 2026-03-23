"""
Tests for phylogenetics module.
"""

import pytest

from thomas.marketplace.bioinformatics._types import PhyloTree, Sequence, SequenceType
from thomas.marketplace.bioinformatics.phylogenetics import (
    bootstrap_support,
    distance_matrix,
    neighbor_joining,
    parse_newick,
    upgma_tree,
    write_newick,
)


class TestDistanceMatrix:
    """Test distance matrix calculation."""

    def test_distance_matrix_two_sequences(self) -> None:
        """Test distance matrix with two sequences."""
        seqs = [
            Sequence("seq1", "ACGTACGT", SequenceType.DNA),
            Sequence("seq2", "ACGTACGT", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        assert len(ids) == 2
        assert len(matrix) == 2
        assert matrix[0][1] == matrix[1][0]  # Symmetry

    def test_distance_matrix_identical(self) -> None:
        """Test distance matrix for identical sequences."""
        seqs = [
            Sequence("seq1", "ACGT", SequenceType.DNA),
            Sequence("seq2", "ACGT", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        assert matrix[0][1] == 0.0

    def test_distance_matrix_different(self) -> None:
        """Test distance matrix for different sequences."""
        seqs = [
            Sequence("seq1", "ACGTACGT", SequenceType.DNA),
            Sequence("seq2", "TTTTTTTT", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        assert matrix[0][1] > 0

    def test_distance_matrix_multiple(self) -> None:
        """Test distance matrix with multiple sequences."""
        seqs = [
            Sequence("seq1", "ACGT", SequenceType.DNA),
            Sequence("seq2", "ACGT", SequenceType.DNA),
            Sequence("seq3", "GGGG", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        assert len(ids) == 3
        assert len(matrix) == 3
        assert all(len(row) == 3 for row in matrix)

    def test_distance_matrix_diagonal(self) -> None:
        """Test that diagonal is zero."""
        seqs = [
            Sequence("seq1", "ACGT", SequenceType.DNA),
            Sequence("seq2", "CGTA", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        assert matrix[0][0] == 0.0
        assert matrix[1][1] == 0.0

    def test_distance_matrix_single_sequence(self) -> None:
        """Test with single sequence."""
        seqs = [Sequence("seq1", "ACGT", SequenceType.DNA)]
        with pytest.raises(ValueError):
            distance_matrix(seqs)

    def test_distance_models(self) -> None:
        """Test different distance models."""
        seqs = [
            Sequence("seq1", "ACGTACGT", SequenceType.DNA),
            Sequence("seq2", "ACGTACGT", SequenceType.DNA),
        ]
        ids1, matrix1 = distance_matrix(seqs, model="jukes_cantor")
        ids2, matrix2 = distance_matrix(seqs, model="kimura")
        # Both should return valid distances
        assert matrix1[0][1] == 0.0
        assert matrix2[0][1] == 0.0


class TestUPGMA:
    """Test UPGMA tree construction."""

    def test_upgma_two_sequences(self) -> None:
        """Test UPGMA with two sequences."""
        seqs = [
            Sequence("seq1", "ACGT", SequenceType.DNA),
            Sequence("seq2", "ACGT", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        tree = upgma_tree(ids, matrix)
        assert tree is not None
        assert not tree.is_leaf()

    def test_upgma_three_sequences(self) -> None:
        """Test UPGMA with three sequences."""
        seqs = [
            Sequence("seq1", "ACGTACGT", SequenceType.DNA),
            Sequence("seq2", "ACGTACGT", SequenceType.DNA),
            Sequence("seq3", "GGGGGGGG", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        tree = upgma_tree(ids, matrix)
        assert tree is not None

    def test_upgma_tree_structure(self) -> None:
        """Test UPGMA tree has correct structure."""
        seqs = [
            Sequence("seq1", "ACGT", SequenceType.DNA),
            Sequence("seq2", "ACGT", SequenceType.DNA),
            Sequence("seq3", "GGGG", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        tree = upgma_tree(ids, matrix)

        # Root should be internal node
        assert not tree.is_leaf()
        # Should have branch lengths
        if tree.left_child:
            assert tree.left_child.branch_length >= 0
        if tree.right_child:
            assert tree.right_child.branch_length >= 0


class TestNeighborJoining:
    """Test neighbor-joining tree construction."""

    def test_neighbor_joining_two_sequences(self) -> None:
        """Test neighbor-joining with two sequences."""
        seqs = [
            Sequence("seq1", "ACGT", SequenceType.DNA),
            Sequence("seq2", "ACGT", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        tree = neighbor_joining(ids, matrix)
        assert tree is not None

    def test_neighbor_joining_multiple(self) -> None:
        """Test neighbor-joining with multiple sequences."""
        seqs = [
            Sequence("seq1", "ACGTACGT", SequenceType.DNA),
            Sequence("seq2", "ACGTACGT", SequenceType.DNA),
            Sequence("seq3", "GGGGGGGG", SequenceType.DNA),
            Sequence("seq4", "TTTTTTTT", SequenceType.DNA),
        ]
        ids, matrix = distance_matrix(seqs)
        tree = neighbor_joining(ids, matrix)
        assert tree is not None


class TestTreeParsing:
    """Test Newick format parsing."""

    def test_parse_newick_simple(self) -> None:
        """Test parsing simple Newick."""
        newick = "(A:0.1,B:0.2);"
        tree = parse_newick(newick)
        assert tree.left_child is not None
        assert tree.right_child is not None

    def test_parse_newick_with_name(self) -> None:
        """Test parsing Newick with internal names."""
        newick = "(A:0.1,B:0.2)C:0.5;"
        tree = parse_newick(newick)
        assert tree.name == "C"

    def test_parse_newick_nested(self) -> None:
        """Test parsing nested Newick."""
        newick = "((A:0.1,B:0.1):0.2,C:0.3);"
        tree = parse_newick(newick)
        assert tree.left_child is not None
        assert tree.left_child.left_child is not None

    def test_parse_newick_no_lengths(self) -> None:
        """Test parsing Newick without branch lengths."""
        newick = "(A,B);"
        tree = parse_newick(newick)
        assert tree.left_child is not None
        assert tree.right_child is not None


class TestTreeWriting:
    """Test Newick format writing."""

    def test_write_newick_simple(self) -> None:
        """Test writing simple Newick."""
        tree = PhyloTree()
        tree.left_child = PhyloTree(name="A", branch_length=0.1)
        tree.right_child = PhyloTree(name="B", branch_length=0.2)
        newick = write_newick(tree)
        assert "A" in newick
        assert "B" in newick
        assert "0.1" in newick or "0.2" in newick

    def test_write_newick_single(self) -> None:
        """Test writing single leaf."""
        tree = PhyloTree(name="A")
        newick = write_newick(tree)
        assert "A" in newick
        assert ";" in newick

    def test_newick_roundtrip(self) -> None:
        """Test write/parse roundtrip."""
        newick_original = "(A:0.1,B:0.2)C:0.3;"
        tree = parse_newick(newick_original)
        newick_written = write_newick(tree)
        # Parse again to verify structure
        tree2 = parse_newick(newick_written)
        assert tree2.left_child is not None


class TestPhyloTree:
    """Test PhyloTree class."""

    def test_tree_creation(self) -> None:
        """Test tree node creation."""
        tree = PhyloTree(name="A")
        assert tree.name == "A"
        assert tree.is_leaf()

    def test_tree_internal_node(self) -> None:
        """Test internal node."""
        tree = PhyloTree()
        tree.left_child = PhyloTree(name="A")
        tree.right_child = PhyloTree(name="B")
        assert not tree.is_leaf()

    def test_tree_get_leaves(self) -> None:
        """Test getting leaf nodes."""
        tree = PhyloTree()
        tree.left_child = PhyloTree(name="A")
        tree.right_child = PhyloTree(name="B")
        leaves = tree.get_leaves()
        assert len(leaves) == 2

    def test_tree_nested_leaves(self) -> None:
        """Test leaf collection from nested tree."""
        tree = PhyloTree()
        tree.left_child = PhyloTree()
        tree.left_child.left_child = PhyloTree(name="A")
        tree.left_child.right_child = PhyloTree(name="B")
        tree.right_child = PhyloTree(name="C")
        leaves = tree.get_leaves()
        assert len(leaves) == 3


class TestBootstrap:
    """Test bootstrap support calculation."""

    def test_bootstrap_support(self) -> None:
        """Test bootstrap support calculation."""
        seqs = [
            Sequence("seq1", "ACGTACGTACGT", SequenceType.DNA),
            Sequence("seq2", "ACGTACGTACGT", SequenceType.DNA),
            Sequence("seq3", "GGGGGGGGGGGG", SequenceType.DNA),
        ]
        support = bootstrap_support(seqs, replicates=10, seed=42)
        assert isinstance(support, dict)
        assert len(support) == 3
        # Support values should be percentages
        for val in support.values():
            assert 0 <= val <= 100
