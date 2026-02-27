"""
Integration tests combining multiple modules.
"""

import os
import tempfile

import pytest

from thomas.bioinformatics.alignment import needleman_wunsch, smith_waterman
from thomas.bioinformatics.io_formats import read_fasta, write_fasta_file
from thomas.bioinformatics.motifs import PositionWeightMatrix
from thomas.bioinformatics.phylogenetics import distance_matrix, upgma_tree
from thomas.bioinformatics.protein import isoelectric_point, molecular_weight
from thomas.bioinformatics.sequence import (
    Sequence,
    SequenceType,
    complement,
    find_orfs,
    parse_fasta,
    translate,
    write_fasta,
)
from thomas.bioinformatics.stats import kmer_frequency, sequence_entropy


class TestWorkflow:
    """Test complete bioinformatics workflows."""

    def test_sequence_to_protein_workflow(self) -> None:
        """Test DNA to protein workflow."""
        # Create DNA sequence
        dna = "ATGAAATACTGA"  # ATG (M), AAA (K), TAC (Y), TGA (stop)

        # Translate to protein
        protein = translate(dna)

        # Calculate properties
        weight = molecular_weight(protein)
        assert weight > 0

        pI = isoelectric_point(protein)
        assert 0 <= pI <= 14

    def test_fasta_roundtrip(self) -> None:
        """Test FASTA file write and read."""
        sequences = [
            Sequence("seq1", "ACGTACGTACGT", SequenceType.DNA),
            Sequence("seq2", "TTGGTTGGTTGG", SequenceType.DNA),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.fasta")

            # Write FASTA
            write_fasta_file(sequences, filepath)
            assert os.path.exists(filepath)

            # Read FASTA
            read_seqs = read_fasta(filepath)
            assert len(read_seqs) == 2
            assert read_seqs[0].id == "seq1"
            assert read_seqs[0].seq == "ACGTACGTACGT"

    def test_alignment_workflow(self) -> None:
        """Test alignment workflow."""
        seq1 = "ACGTACGTACGT"
        seq2 = "ACGTACGTACGT"

        # Perform alignment
        result = needleman_wunsch(seq1, seq2)

        # Check results
        assert result.identity == 100.0
        assert result.score > 0
        assert len(result.aligned_seq1) == len(result.aligned_seq2)

    def test_phylogenetics_workflow(self) -> None:
        """Test phylogenetics workflow."""
        # Create sequences
        seqs = [
            Sequence("species1", "ACGTACGTACGT", SequenceType.DNA),
            Sequence("species2", "ACGTACGTACGT", SequenceType.DNA),
            Sequence("species3", "GGGGGGGGGGGG", SequenceType.DNA),
        ]

        # Calculate distances
        ids, matrix = distance_matrix(seqs)
        assert len(ids) == 3

        # Build tree
        tree = upgma_tree(ids, matrix)
        assert tree is not None
        leaves = tree.get_leaves()
        assert len(leaves) > 0

    def test_motif_discovery_workflow(self) -> None:
        """Test motif discovery workflow."""
        # Aligned sequences with common motif
        sequences = [
            "ACGTACGTACGT",
            "ACGTACGTACGT",
            "ACGTACGTACGT",
        ]

        # Create PWM
        pwm = PositionWeightMatrix.from_alignment(sequences)

        # Get consensus
        consensus = pwm.consensus()
        assert len(consensus) == 12

        # Score sequences
        score = pwm.score_sequence("ACGTACGTACGT")
        assert score > 0

    def test_complex_sequence_analysis(self) -> None:
        """Test comprehensive sequence analysis."""
        dna = "ATGACGTACACGTACGTACGTAA"

        # Sequence properties
        entropy = sequence_entropy(dna)
        assert 0 <= entropy <= 2  # Max is log2(4) = 2 for DNA

        kmers = kmer_frequency(dna, k=3)
        assert len(kmers) > 0

        # Find ORFs
        orfs = find_orfs(dna, min_length=15)

        # Reverse complement
        rev_comp = complement(dna)
        assert len(rev_comp) == len(dna)

    def test_multiple_alignment_workflow(self) -> None:
        """Test multiple sequence alignment."""
        sequences = [
            "ACGTACGT",
            "ACGTACGT",
            "ACGTACGT",
        ]

        # Pairwise alignments
        result = needleman_wunsch(sequences[0], sequences[1])
        assert result.identity == 100.0

    def test_local_vs_global_alignment(self) -> None:
        """Test difference between local and global alignment."""
        seq1 = "AAACGTAA"
        seq2 = "CGTACGTAA"

        global_result = needleman_wunsch(seq1, seq2)
        local_result = smith_waterman(seq1, seq2)

        # Local alignment should find the matching region
        assert local_result.alignment_length <= max(len(seq1), len(seq2))
        assert global_result.alignment_length >= min(len(seq1), len(seq2))

    def test_sequence_statistics(self) -> None:
        """Test sequence statistics calculations."""
        from thomas.bioinformatics.stats import base_composition, dinucleotide_frequency, gc_skew

        dna = "ACGTACGTACGT"

        # Composition
        comp = base_composition(dna)
        total = sum(comp.values())
        assert 99 < total < 101

        # GC skew
        skew = gc_skew(dna, window_size=4)
        assert len(skew) > 0

        # Dinucleotides
        dinuc = dinucleotide_frequency(dna)
        assert len(dinuc) > 0

    def test_protein_analysis_workflow(self) -> None:
        """Test protein analysis workflow."""
        from thomas.bioinformatics.protein import (
            amino_acid_composition,
            hydrophobicity_plot,
            secondary_structure_prediction,
        )

        protein = "MVHLTPEEKS"

        # Composition
        comp = amino_acid_composition(protein)
        assert len(comp) > 0

        # Hydrophobicity
        hydro = hydrophobicity_plot(protein)
        assert len(hydro) == len(protein)

        # Secondary structure
        assignment, props = secondary_structure_prediction(protein)
        assert len(assignment) == len(protein)


class TestDataInteroperability:
    """Test data format interoperability."""

    def test_parse_write_consistency(self) -> None:
        """Test consistency between parsing and writing."""
        original_fasta = ">sequence1 description\nACGTACGT\n>sequence2\nTTGGTTGG"

        # Parse
        seqs = parse_fasta(original_fasta)

        # Write
        written = write_fasta(seqs)

        # Parse again
        seqs2 = parse_fasta(written)

        # Check consistency
        assert len(seqs) == len(seqs2)
        for i, seq in enumerate(seqs):
            assert seq.id == seqs2[i].id
            assert seq.seq == seqs2[i].seq

    def test_sequence_type_detection(self) -> None:
        """Test automatic sequence type detection."""
        # DNA
        dna = parse_fasta(">dna\nACGTACGT")
        assert dna[0].seq_type == SequenceType.DNA

        # RNA
        rna = parse_fasta(">rna\nACGUACGU")
        assert rna[0].seq_type == SequenceType.RNA

        # Protein
        protein = parse_fasta(">protein\nMVHLTPEEKS")
        assert protein[0].seq_type == SequenceType.PROTEIN


class TestErrorHandling:
    """Test error handling across modules."""

    def test_invalid_sequence_handling(self) -> None:
        """Test handling of invalid sequences."""
        from thomas.bioinformatics._exceptions import InvalidSequenceError

        with pytest.raises(InvalidSequenceError):
            from thomas.bioinformatics.sequence import validate_dna

            validate_dna("ACGTU")  # Contains U (invalid for DNA)

    def test_empty_sequence_handling(self) -> None:
        """Test handling of empty sequences."""
        from thomas.bioinformatics._exceptions import InvalidSequenceError

        with pytest.raises(InvalidSequenceError):
            from thomas.bioinformatics.sequence import gc_content

            gc_content("")

    def test_alignment_validation(self) -> None:
        """Test alignment result validation."""
        from thomas.bioinformatics._types import AlignmentResult

        with pytest.raises(ValueError):
            AlignmentResult(
                score=10.0,
                aligned_seq1="ACGT",
                aligned_seq2="ACG",  # Different length
                identity=100.0,
                similarity=100.0,
            )


class TestPerformance:
    """Test performance characteristics."""

    def test_large_sequence_handling(self) -> None:
        """Test handling of large sequences."""
        # Create a 10000 bp sequence
        large_seq = "ACGT" * 2500

        # Should not crash
        entropy = sequence_entropy(large_seq)
        assert entropy > 0

        kmers = kmer_frequency(large_seq, k=3)
        assert len(kmers) > 0

    def test_many_sequences(self) -> None:
        """Test handling of many sequences."""
        # Create 100 sequences
        sequences = [Sequence(f"seq{i}", "ACGTACGT", SequenceType.DNA) for i in range(100)]

        # FASTA writing/parsing
        fasta = write_fasta(sequences)
        parsed = parse_fasta(fasta)
        assert len(parsed) == 100

    def test_large_alignment(self) -> None:
        """Test large sequence alignment."""
        seq1 = "ACGTACGT" * 25  # 200 bp
        seq2 = "ACGTACGT" * 25  # 200 bp

        result = smith_waterman(seq1, seq2)
        assert result.score > 0
        assert len(result.aligned_seq1) == len(result.aligned_seq2)
