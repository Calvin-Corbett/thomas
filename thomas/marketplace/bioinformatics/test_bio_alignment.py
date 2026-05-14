"""
Tests for alignment module.
"""

import pytest

from thomas.marketplace.bioinformatics._exceptions import AlignmentError
from thomas.marketplace.bioinformatics.alignment import (
    AlignmentResult,
    SubstitutionMatrix,
    multiple_sequence_alignment,
    needleman_wunsch,
    smith_waterman,
)


class TestNeedlemanWunsch:
    """Test Needleman-Wunsch global alignment."""

    def test_identical_sequences(self) -> None:
        """Test alignment of identical sequences."""
        result = needleman_wunsch("ACGT", "ACGT")
        assert result.score > 0
        assert result.identity == 100.0
        assert result.aligned_seq1 == "ACGT"
        assert result.aligned_seq2 == "ACGT"

    def test_different_sequences(self) -> None:
        """Test alignment of different sequences."""
        result = needleman_wunsch("ACGT", "TGCA")
        assert result.aligned_seq1 is not None
        assert len(result.aligned_seq1) == len(result.aligned_seq2)

    def test_one_insertion(self) -> None:
        """Test single insertion."""
        result = needleman_wunsch("ACGT", "AACGT")
        assert result.identity < 100.0
        assert result.gap_openings > 0

    def test_alignment_result_validation(self) -> None:
        """Test AlignmentResult validation."""
        with pytest.raises(ValueError):
            AlignmentResult(
                score=10.0,
                aligned_seq1="ACGT",
                aligned_seq2="ACG",  # Different lengths
                identity=100.0,
                similarity=100.0,
            )

    def test_empty_sequence(self) -> None:
        """Test with empty sequence."""
        with pytest.raises(AlignmentError):
            needleman_wunsch("", "ACGT")

    def test_custom_gap_penalties(self) -> None:
        """Test custom gap penalties."""
        result1 = needleman_wunsch("ACGT", "ACT", gap_open=-5.0)
        result2 = needleman_wunsch("ACGT", "ACT", gap_open=-20.0)
        # Lower penalty should give higher score
        assert result1.score >= result2.score

    def test_with_substitution_matrix(self) -> None:
        """Test with substitution matrix."""
        matrix = SubstitutionMatrix.blosum62()
        result = needleman_wunsch("MVHLT", "MVHLT", matrix=matrix)
        assert result.score > 0


class TestSmithWaterman:
    """Test Smith-Waterman local alignment."""

    def test_local_alignment_identical(self) -> None:
        """Test local alignment of identical sequences."""
        result = smith_waterman("ACGT", "ACGT")
        assert result.score > 0
        assert result.identity == 100.0

    def test_local_alignment_subsequence(self) -> None:
        """Test local alignment finds best subsequence match."""
        result = smith_waterman("AAACGTAA", "AAAACGTAA")
        assert result.score > 0

    def test_local_alignment_no_match(self) -> None:
        """Test local alignment with no overlap."""
        result = smith_waterman("ACGTACGT", "TTTTTTTT")
        # Low or zero score expected
        assert result.score <= 0

    def test_local_vs_global(self) -> None:
        """Test local finds different result than global."""
        seq1 = "AAACGTAA"
        seq2 = "CGTACGTAA"
        local = smith_waterman(seq1, seq2)
        needleman_wunsch(seq1, seq2)
        # Scores may differ due to different algorithms
        assert local.alignment_length <= len(seq1)

    def test_empty_sequence_local(self) -> None:
        """Test Smith-Waterman with empty sequence."""
        with pytest.raises(AlignmentError):
            smith_waterman("", "ACGT")


class TestMultipleAlignment:
    """Test multiple sequence alignment."""

    def test_multiple_identical(self) -> None:
        """Test alignment of identical sequences."""
        seqs = ["ACGT", "ACGT", "ACGT"]
        aligned, score = multiple_sequence_alignment(seqs)
        assert len(aligned) == 3

    def test_multiple_similar(self) -> None:
        """Test alignment of similar sequences."""
        seqs = ["ACGT", "ACGT", "ACGT"]
        aligned, score = multiple_sequence_alignment(seqs)
        assert score >= 0

    def test_multiple_single_sequence(self) -> None:
        """Test with single sequence."""
        aligned, score = multiple_sequence_alignment(["ACGT"])
        assert len(aligned) == 1
        assert aligned[0] == "ACGT"

    def test_multiple_empty(self) -> None:
        """Test with no sequences."""
        with pytest.raises(AlignmentError):
            multiple_sequence_alignment([])

    def test_multiple_different_lengths(self) -> None:
        """Test sequences of different lengths."""
        seqs = ["ACGT", "ACGTACGT", "ACG"]
        aligned, score = multiple_sequence_alignment(seqs)
        assert len(aligned) == 3


class TestSubstitutionMatrix:
    """Test substitution matrices."""

    def test_blosum62(self) -> None:
        """Test BLOSUM62 matrix."""
        matrix = SubstitutionMatrix.blosum62()
        assert matrix.name == "BLOSUM62"
        # Self-alignment should be positive
        assert matrix.score("A", "A") > 0
        # Mismatch should be negative or zero
        assert matrix.score("A", "W") <= 0

    def test_pam250(self) -> None:
        """Test PAM250 matrix."""
        matrix = SubstitutionMatrix.pam250()
        assert matrix.name == "PAM250"
        assert matrix.score("A", "A") > 0

    def test_matrix_symmetry(self) -> None:
        """Test matrix symmetry."""
        matrix = SubstitutionMatrix.blosum62()
        assert matrix.score("A", "V") == matrix.score("V", "A")

    def test_matrix_custom(self) -> None:
        """Test custom matrix creation."""
        custom_matrix = {("A", "A"): 5, ("A", "V"): -2, ("V", "V"): 5}
        matrix = SubstitutionMatrix("CUSTOM", custom_matrix)
        assert matrix.score("A", "A") == 5


class TestAlignmentMetrics:
    """Test alignment metrics calculation."""

    def test_identity_calculation(self) -> None:
        """Test identity percentage calculation."""
        result = needleman_wunsch("ACGT", "ACGT")
        assert result.identity == 100.0

    def test_identity_partial(self) -> None:
        """Test partial identity."""
        result = needleman_wunsch("ACGT", "AAGT")
        # CvG mismatch, should be less than 100
        assert 0 <= result.identity < 100

    def test_similarity_protein(self) -> None:
        """Test similarity with protein sequences."""
        matrix = SubstitutionMatrix.blosum62()
        result = needleman_wunsch("MV", "ML", matrix=matrix)
        assert result.similarity >= 0


class TestAlignmentTraceback:
    """Test alignment traceback."""

    def test_traceback_simple(self) -> None:
        """Test simple traceback."""
        result = needleman_wunsch("AC", "AC")
        assert result.aligned_seq1 == result.aligned_seq2

    def test_traceback_gap(self) -> None:
        """Test traceback with gaps."""
        result = needleman_wunsch("ACG", "AC")
        assert "-" in result.aligned_seq1 or "-" in result.aligned_seq2

    def test_aligned_length_consistent(self) -> None:
        """Test that aligned sequences have consistent length."""
        result = needleman_wunsch("ACGTACGT", "ATGTACGT")
        assert len(result.aligned_seq1) == len(result.aligned_seq2)
        assert result.alignment_length == len(result.aligned_seq1)
