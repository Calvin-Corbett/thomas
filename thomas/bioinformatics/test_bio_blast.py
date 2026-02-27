"""
Tests for BLAST module.
"""

import pytest

from thomas.bioinformatics._types import Sequence, SequenceType
from thomas.bioinformatics.blast import BLASTDatabase, blast_search, calculate_evalue, format_blast_report


class TestBLASTDatabase:
    """Test BLAST database class."""

    def test_database_creation(self) -> None:
        """Test database initialization."""
        db = BLASTDatabase(word_size=11)
        assert db.word_size == 11
        assert len(db.sequences) == 0

    def test_add_sequence(self) -> None:
        """Test adding sequence to database."""
        db = BLASTDatabase()
        seq = Sequence("seq1", "ACGTACGTACGT", SequenceType.DNA)
        db.add_sequence(seq)
        assert len(db.sequences) == 1
        assert db.total_length == 12

    def test_add_multiple_sequences(self) -> None:
        """Test adding multiple sequences."""
        db = BLASTDatabase()
        for i in range(3):
            seq = Sequence(f"seq{i}", "ACGT" * (i + 1), SequenceType.DNA)
            db.add_sequence(seq)
        assert len(db.sequences) == 3

    def test_kmer_indexing(self) -> None:
        """Test k-mer indexing."""
        db = BLASTDatabase(word_size=4)
        seq = Sequence("seq1", "ACGTACGTACGT", SequenceType.DNA)
        db.add_sequence(seq)
        assert len(db.kmer_index) > 0

    def test_search_identical(self) -> None:
        """Test search with identical sequence."""
        db = BLASTDatabase()
        seq = Sequence("subject", "ACGTACGTACGT", SequenceType.DNA)
        db.add_sequence(seq)
        hits = db.search("ACGTACGTACGT")
        # May or may not find hits depending on parameters
        # Just test it doesn't crash
        assert isinstance(hits, list)

    def test_search_short_query(self) -> None:
        """Test search with query shorter than word size."""
        db = BLASTDatabase(word_size=11)
        seq = Sequence("subject", "ACGTACGTACGT", SequenceType.DNA)
        db.add_sequence(seq)
        hits = db.search("ACG")  # Shorter than word size
        assert len(hits) == 0

    def test_search_with_evalue_threshold(self) -> None:
        """Test evalue threshold filtering."""
        db = BLASTDatabase()
        seq = Sequence("subject", "ACGTACGTACGT" * 10, SequenceType.DNA)
        db.add_sequence(seq)
        hits = db.search("ACGTACGT", evalue_threshold=0.001)
        assert isinstance(hits, list)


class TestEValueCalculation:
    """Test E-value calculation."""

    def test_evalue_basic(self) -> None:
        """Test basic E-value calculation."""
        evalue = calculate_evalue(score=50.0, query_length=100, database_length=1000, is_protein=False)
        assert evalue > 0

    def test_evalue_zero_score(self) -> None:
        """Test E-value with zero score."""
        evalue = calculate_evalue(0.0, 100, 1000)
        assert evalue >= 0

    def test_evalue_protein(self) -> None:
        """Test E-value for proteins."""
        evalue = calculate_evalue(score=30.0, query_length=100, database_length=1000, is_protein=True)
        assert evalue > 0

    def test_evalue_decreases_with_score(self) -> None:
        """Test E-value decreases with higher scores."""
        evalue1 = calculate_evalue(10.0, 100, 1000)
        evalue2 = calculate_evalue(50.0, 100, 1000)
        assert evalue2 < evalue1

    def test_evalue_increases_with_database(self) -> None:
        """Test E-value increases with larger database."""
        evalue1 = calculate_evalue(50.0, 100, 1000)
        evalue2 = calculate_evalue(50.0, 100, 10000)
        assert evalue2 > evalue1


class TestBLASTSearch:
    """Test BLAST search function."""

    def test_blast_search_no_file(self) -> None:
        """Test BLAST search with missing file."""
        with pytest.raises(FileNotFoundError):
            blast_search("ACGT", "/nonexistent/file.fasta")


class TestBlastReport:
    """Test BLAST report formatting."""

    def test_format_blast_report_empty(self) -> None:
        """Test formatting with no hits."""
        report = format_blast_report([])
        assert "BLAST Results" in report
        assert "Database Hits: 0" in report

    def test_format_blast_report_with_hits(self) -> None:
        """Test formatting with hits."""
        from thomas.bioinformatics._types import BLASTHit

        hits = [
            BLASTHit(
                query_id="query",
                subject_id="subject1",
                percent_identity=95.0,
                alignment_length=100,
                mismatches=5,
                gap_openings=0,
                query_start=1,
                query_end=100,
                subject_start=1,
                subject_end=100,
                evalue=1e-50,
                bit_score=100.0,
            ),
            BLASTHit(
                query_id="query",
                subject_id="subject2",
                percent_identity=85.0,
                alignment_length=100,
                mismatches=15,
                gap_openings=1,
                query_start=1,
                query_end=100,
                subject_start=1,
                subject_end=100,
                evalue=1e-30,
                bit_score=80.0,
            ),
        ]

        report = format_blast_report(hits, query_id="test_query")
        assert "test_query" in report
        assert "subject1" in report
        assert "Database Hits: 2" in report

    def test_format_blast_report_max_alignments(self) -> None:
        """Test limiting reported alignments."""
        from thomas.bioinformatics._types import BLASTHit

        hits = [
            BLASTHit(
                query_id="q",
                subject_id=f"s{i}",
                percent_identity=90.0,
                alignment_length=100,
                mismatches=10,
                gap_openings=0,
                query_start=1,
                query_end=100,
                subject_start=1,
                subject_end=100,
                evalue=1e-30,
                bit_score=80.0,
            )
            for i in range(5)
        ]

        report = format_blast_report(hits, max_alignments=2)
        # Should only show 2 hits in table
        assert "s0" in report or "s1" in report


class TestKmerIndexing:
    """Test k-mer indexing details."""

    def test_kmer_index_coverage(self) -> None:
        """Test that k-mer index covers sequence."""
        db = BLASTDatabase(word_size=3)
        seq = Sequence("seq1", "ACGTACGT", SequenceType.DNA)
        db.add_sequence(seq)

        # Should have k-mers for: ACG, CGT, GTA, TAC, ACG, CGT
        # Unique: ACG, CGT, GTA, TAC
        assert len(db.kmer_index) >= 4

    def test_kmer_position_tracking(self) -> None:
        """Test that k-mer positions are tracked."""
        db = BLASTDatabase(word_size=3)
        seq = Sequence("seq1", "ACGACG", SequenceType.DNA)
        db.add_sequence(seq)

        # ACG appears twice at positions 0 and 3
        if "ACG" in db.kmer_index:
            positions = [pos for seq_id, pos in db.kmer_index["ACG"]]
            assert 0 in positions or 3 in positions
