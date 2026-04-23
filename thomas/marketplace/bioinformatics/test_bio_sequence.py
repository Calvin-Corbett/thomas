"""
Tests for sequence module.
"""

import pytest

from thomas.marketplace.bioinformatics._exceptions import InvalidSequenceError
from thomas.marketplace.bioinformatics.sequence import (
    Sequence,
    SequenceType,
    complement,
    find_orfs,
    gc_content,
    nucleotide_frequency,
    parse_fasta,
    reverse_complement,
    transcribe,
    translate,
    validate_dna,
    validate_protein,
    validate_rna,
    write_fasta,
)


class TestValidation:
    """Test sequence validation functions."""

    def test_validate_dna_valid(self) -> None:
        """Test valid DNA sequence."""
        assert validate_dna("ACGTACGT")
        assert validate_dna("acgtacgt")

    def test_validate_dna_invalid(self) -> None:
        """Test invalid DNA sequence."""
        with pytest.raises(InvalidSequenceError):
            validate_dna("ACGTU")  # Contains U
        with pytest.raises(InvalidSequenceError):
            validate_dna("")

    def test_validate_rna_valid(self) -> None:
        """Test valid RNA sequence."""
        assert validate_rna("ACGUACGU")
        assert validate_rna("acguacgu")

    def test_validate_rna_invalid(self) -> None:
        """Test invalid RNA sequence."""
        with pytest.raises(InvalidSequenceError):
            validate_rna("ACGTA")  # Contains T

    def test_validate_protein_valid(self) -> None:
        """Test valid protein sequence."""
        assert validate_protein("MVHLTPEEKS")
        assert validate_protein("mvhltpeeks")

    def test_validate_protein_invalid(self) -> None:
        """Test invalid protein sequence."""
        with pytest.raises(InvalidSequenceError):
            validate_protein("MVHLT$PEEKS")  # Contains invalid char


class TestComplement:
    """Test complementation functions."""

    def test_complement_basic(self) -> None:
        """Test basic complementation."""
        assert complement("ACGT") == "TGCA"
        assert complement("A") == "T"
        assert complement("G") == "C"

    def test_complement_case_insensitive(self) -> None:
        """Test case insensitivity."""
        assert complement("acgt") == "tgca"
        assert complement("AcGt") == "TgCa"

    def test_reverse_complement(self) -> None:
        """Test reverse complementation."""
        assert reverse_complement("ACGT") == "ACGT"
        assert reverse_complement("AAAA") == "TTTT"
        assert reverse_complement("ATCG") == "CGAT"


class TestTranscription:
    """Test transcription function."""

    def test_transcribe_basic(self) -> None:
        """Test basic transcription."""
        assert transcribe("ACGTACGT") == "ACGUACGU"
        assert transcribe("TTT") == "UUU"

    def test_transcribe_case(self) -> None:
        """Test transcription case handling."""
        assert transcribe("acgtacgt") == "ACGUACGU"


class TestTranslation:
    """Test translation function."""

    def test_translate_basic(self) -> None:
        """Test basic translation."""
        # ATG (start), TAC (Y), CAG (Q), TAA (stop)
        result = translate("ATGTACAGAA")
        assert result[0] == "M"

    def test_translate_stop_codon(self) -> None:
        """Test stop codon handling."""
        # Include stop codon
        result = translate("ATGTAA")
        assert "*" in result

    def test_translate_unknown_codon(self) -> None:
        """Test unknown codon."""
        result = translate("NNN")
        assert "X" in result


class TestComposition:
    """Test composition analysis."""

    def test_gc_content(self) -> None:
        """Test GC content calculation."""
        assert gc_content("GCGCGC") == 100.0
        assert gc_content("AAAAAA") == 0.0
        assert gc_content("ACGT") == 50.0

    def test_gc_content_empty(self) -> None:
        """Test GC content with empty sequence."""
        with pytest.raises(InvalidSequenceError):
            gc_content("")

    def test_nucleotide_frequency(self) -> None:
        """Test nucleotide frequency."""
        freq = nucleotide_frequency("ACGTACGT")
        assert freq["A"] == 0.25
        assert freq["C"] == 0.25
        assert freq["G"] == 0.25
        assert freq["T"] == 0.25

    def test_nucleotide_frequency_skewed(self) -> None:
        """Test skewed nucleotide frequency."""
        freq = nucleotide_frequency("AAAA")
        assert freq["A"] == 1.0
        assert freq["C"] == 0.0


class TestORFs:
    """Test ORF finding."""

    def test_find_orfs_basic(self) -> None:
        """Test basic ORF finding."""
        # ATG (start), three codons, TAA (stop)
        seq = "ATGAAACCCGGGTAA"
        orfs = find_orfs(seq, min_length=12)
        assert len(orfs) > 0
        assert orfs[0][0] == 0

    def test_find_orfs_minimum_length(self) -> None:
        """Test minimum length filtering."""
        seq = "ATGAA"  # Too short
        orfs = find_orfs(seq, min_length=100)
        assert len(orfs) == 0


class TestFasta:
    """Test FASTA parsing and writing."""

    def test_parse_fasta_single(self) -> None:
        """Test parsing single sequence."""
        fasta = ">seq1\nACGT\nACGT"
        seqs = parse_fasta(fasta)
        assert len(seqs) == 1
        assert seqs[0].id == "seq1"
        assert seqs[0].seq == "ACGTACGT"

    def test_parse_fasta_multiple(self) -> None:
        """Test parsing multiple sequences."""
        fasta = ">seq1\nACGT\n>seq2\nTTGG"
        seqs = parse_fasta(fasta)
        assert len(seqs) == 2
        assert seqs[0].id == "seq1"
        assert seqs[1].id == "seq2"

    def test_parse_fasta_with_description(self) -> None:
        """Test parsing with descriptions."""
        fasta = ">seq1 test sequence\nACGT"
        seqs = parse_fasta(fasta)
        assert seqs[0].description == "test sequence"

    def test_write_fasta(self) -> None:
        """Test FASTA writing."""
        seqs = [Sequence("seq1", "ACGTACGTACGT", SequenceType.DNA)]
        fasta = write_fasta(seqs, line_width=4)
        assert ">seq1" in fasta
        assert "ACGT" in fasta

    def test_fasta_roundtrip(self) -> None:
        """Test FASTA write/read roundtrip."""
        original = [
            Sequence("seq1", "ACGTACGTACGT", SequenceType.DNA, "test sequence"),
            Sequence("seq2", "TTGGTTGGTTGG", SequenceType.DNA),
        ]
        fasta = write_fasta(original)
        parsed = parse_fasta(fasta)
        assert len(parsed) == len(original)
        assert parsed[0].id == original[0].id
        assert parsed[0].seq == original[0].seq


class TestSequenceObject:
    """Test Sequence class."""

    def test_sequence_creation(self) -> None:
        """Test Sequence object creation."""
        seq = Sequence("id1", "ACGT", SequenceType.DNA)
        assert seq.id == "id1"
        assert len(seq) == 4

    def test_sequence_slicing(self) -> None:
        """Test sequence slicing."""
        seq = Sequence("id1", "ACGTACGT", SequenceType.DNA)
        assert seq[0:4] == "ACGT"
        assert seq[2] == "G"

    def test_sequence_repr(self) -> None:
        """Test sequence representation."""
        seq = Sequence("id1", "ACGT", SequenceType.DNA)
        repr_str = repr(seq)
        assert "id1" in repr_str
        assert "DNA" in repr_str


class TestSequenceTypeDetection:
    """Test sequence type detection."""

    def test_detect_dna(self) -> None:
        """Test DNA detection."""
        fasta = ">seq\nACGT"
        seqs = parse_fasta(fasta)
        assert seqs[0].seq_type == SequenceType.DNA

    def test_detect_rna(self) -> None:
        """Test RNA detection."""
        fasta = ">seq\nACGU"
        seqs = parse_fasta(fasta)
        assert seqs[0].seq_type == SequenceType.RNA

    def test_detect_protein(self) -> None:
        """Test protein detection."""
        fasta = ">seq\nMVHLTPEEKS"
        seqs = parse_fasta(fasta)
        assert seqs[0].seq_type == SequenceType.PROTEIN
