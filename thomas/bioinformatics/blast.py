"""
BLAST-like homology search implementation.

Provides rapid sequence database searching using k-mer indexing,
seed-and-extend approach, and statistical significance assessment.
"""

import math

from thomas.bioinformatics._types import BLASTHit, Sequence, SequenceType
from thomas.bioinformatics.alignment import smith_waterman


class BLASTDatabase:
    """
    Database of sequences for BLAST search.

    Builds k-mer indices for efficient searching.
    """

    def __init__(self, word_size: int = 11) -> None:
        """
        Initialize BLAST database.

        Args:
            word_size: Size of k-mers for indexing
        """
        self.word_size = word_size
        self.sequences: list[Sequence] = []
        self.kmer_index: dict[str, list[tuple[int, int]]] = {}
        self.total_length = 0

    def add_sequence(self, seq: Sequence) -> None:
        """
        Add sequence to database.

        Args:
            seq: Sequence object
        """
        seq_id = len(self.sequences)
        self.sequences.append(seq)
        self.total_length += len(seq.seq)

        # Build k-mer index
        for i in range(len(seq.seq) - self.word_size + 1):
            kmer = seq.seq[i : i + self.word_size]
            if kmer not in self.kmer_index:
                self.kmer_index[kmer] = []
            self.kmer_index[kmer].append((seq_id, i))

    def search(self, query: str, evalue_threshold: float = 0.001, word_size: int | None = None) -> list[BLASTHit]:
        """
        Search query against database.

        Args:
            query: Query sequence
            evalue_threshold: E-value threshold for reporting
            word_size: Override word size for this search

        Returns:
            List of BLASTHit results
        """
        word_size = word_size or self.word_size
        hits: list[BLASTHit] = []

        if len(query) < word_size:
            return hits

        # Find k-mer seeds
        seeds: dict[int, list[tuple[int, int]]] = {}

        for i in range(len(query) - word_size + 1):
            kmer = query[i : i + word_size]
            if kmer in self.kmer_index:
                for seq_id, pos in self.kmer_index[kmer]:
                    if seq_id not in seeds:
                        seeds[seq_id] = []
                    seeds[seq_id].append((i, pos))

        # Extend seeds and align
        for seq_id, seed_list in seeds.items():
            subject = self.sequences[seq_id].seq

            # Cluster seeds into alignments
            for qstart, sstart in seed_list:
                # Extend alignment around seed
                qend = min(qstart + word_size, len(query))
                send = min(sstart + word_size, len(subject))

                # Local alignment
                alignment = smith_waterman(query, subject)

                if alignment.score > 0:
                    evalue = calculate_evalue(
                        alignment.score,
                        len(query),
                        self.total_length,
                        self.sequences[seq_id].seq_type == SequenceType.PROTEIN,
                    )

                    if evalue <= evalue_threshold:
                        hits.append(
                            BLASTHit(
                                query_id="query",
                                subject_id=self.sequences[seq_id].id,
                                percent_identity=alignment.identity,
                                alignment_length=alignment.alignment_length,
                                mismatches=int(
                                    alignment.alignment_length - alignment.identity / 100 * alignment.alignment_length
                                ),
                                gap_openings=alignment.gap_openings,
                                query_start=qstart,
                                query_end=qend,
                                subject_start=sstart,
                                subject_end=send,
                                evalue=evalue,
                                bit_score=_score_to_bits(alignment.score),
                            )
                        )

        # Sort by bit score
        hits.sort(key=lambda h: h.bit_score, reverse=True)

        return hits


def calculate_evalue(score: float, query_length: int, database_length: int, is_protein: bool = False) -> float:
    """
    Calculate E-value using Karlin-Altschul statistics.

    Args:
        score: Raw alignment score
        query_length: Length of query sequence
        database_length: Total length of database
        is_protein: True for protein sequences

    Returns:
        E-value (expected value)
    """
    # Karlin-Altschul parameters
    if is_protein:
        lambda_param = 0.267  # λ for protein
        kappa = 0.0410  # κ for protein
    else:
        lambda_param = 0.693  # λ for DNA
        kappa = 1.38  # κ for DNA

    # Calculate E-value
    m = query_length
    n = database_length
    bits = _score_to_bits(score)

    evalue = kappa * m * n * math.exp(-lambda_param * bits)

    return evalue


def _score_to_bits(score: float, lambda_param: float = 0.267) -> float:
    """Convert raw score to bit score."""
    if score <= 0:
        return 0.0
    return lambda_param * score / math.log(2)


def blast_search(
    query: str, database_file: str, evalue_threshold: float = 0.001, word_size: int = 11, task: str = "blastn"
) -> list[BLASTHit]:
    """
    Perform BLAST search on a sequence database.

    Args:
        query: Query sequence
        database_file: Path to database file (FASTA format)
        evalue_threshold: E-value threshold
        word_size: Word size for seeding
        task: Search task type (blastn or blastp)

    Returns:
        List of BLASTHit results

    Note:
        This is a simplified implementation for demonstration.
    """
    db = BLASTDatabase(word_size=word_size)

    # Load database
    try:
        with open(database_file) as f:
            content = f.read()
            # Parse FASTA and add sequences
            current_id = None
            current_seq = []

            for line in content.split("\n"):
                if line.startswith(">"):
                    if current_id:
                        seq_obj = Sequence(
                            id=current_id,
                            seq="".join(current_seq).upper(),
                            seq_type=SequenceType.DNA if task == "blastn" else SequenceType.PROTEIN,
                        )
                        db.add_sequence(seq_obj)

                    current_id = line[1:].split()[0]
                    current_seq = []
                else:
                    current_seq.append(line.strip())

            if current_id:
                seq_obj = Sequence(
                    id=current_id,
                    seq="".join(current_seq).upper(),
                    seq_type=SequenceType.DNA if task == "blastn" else SequenceType.PROTEIN,
                )
                db.add_sequence(seq_obj)

    except FileNotFoundError:
        raise FileNotFoundError(f"Database file not found: {database_file}")

    return db.search(query, evalue_threshold=evalue_threshold)


def format_blast_report(hits: list[BLASTHit], query_id: str = "Query", max_alignments: int = 250) -> str:
    """
    Format BLAST results as text report.

    Args:
        hits: List of BLASTHit results
        query_id: Query sequence identifier
        max_alignments: Maximum number of alignments to show

    Returns:
        Formatted BLAST report string
    """
    lines: list[str] = []

    lines.append("=" * 70)
    lines.append("BLAST Results")
    lines.append(f"Query: {query_id}")
    lines.append(f"Database Hits: {len(hits)}")
    lines.append("=" * 70)
    lines.append("")

    lines.append("Significant alignments:")
    lines.append("")
    lines.append(f"{'Description':<40} {'Bit Score':<12} {'E-value':<12}")
    lines.append("-" * 70)

    for i, hit in enumerate(hits[:max_alignments]):
        lines.append(f"{hit.subject_id:<40} {hit.bit_score:<12.2f} {hit.evalue:<12.2e}")

    lines.append("")

    return "\n".join(lines)
