"""
Core data types for bioinformatics module.

Defines fundamental types and classes used throughout the bioinformatics
package for sequence representation, alignment results, phylogenetic trees,
and related structures.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SequenceType(str, Enum):
    """Enumeration of sequence types."""

    DNA = "DNA"
    RNA = "RNA"
    PROTEIN = "PROTEIN"


@dataclass
class Sequence:
    """
    Represents a biological sequence (DNA, RNA, or protein).

    Attributes:
        id: Unique identifier for the sequence
        seq: The sequence string (uppercase)
        seq_type: Type of sequence (DNA, RNA, or PROTEIN)
        description: Optional description of the sequence
        metadata: Optional dictionary of additional metadata
    """

    id: str
    seq: str
    seq_type: SequenceType
    description: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        """Return the length of the sequence."""
        return len(self.seq)

    def __getitem__(self, index: int | slice) -> str:
        """Get subsequence by index or slice."""
        return self.seq[index]

    def __repr__(self) -> str:
        """String representation."""
        return f"Sequence(id={self.id}, type={self.seq_type}, len={len(self)})"


@dataclass
class AlignmentResult:
    """
    Result of a pairwise sequence alignment.

    Attributes:
        score: Alignment score
        aligned_seq1: First aligned sequence (with gaps)
        aligned_seq2: Second aligned sequence (with gaps)
        identity: Percentage identity (0-100)
        similarity: Percentage similarity (0-100)
        gap_openings: Number of gap openings
        alignment_length: Length of alignment (including gaps)
    """

    score: float
    aligned_seq1: str
    aligned_seq2: str
    identity: float
    similarity: float
    gap_openings: int = 0
    alignment_length: int = 0

    def __post_init__(self) -> None:
        """Validate alignment result."""
        if len(self.aligned_seq1) != len(self.aligned_seq2):
            raise ValueError("Aligned sequences must have equal length")
        if not (0 <= self.identity <= 100):
            raise ValueError("Identity must be between 0 and 100")
        self.alignment_length = len(self.aligned_seq1)


@dataclass
class CodonTable:
    """
    Genetic code table mapping codons to amino acids.

    Attributes:
        name: Name of the codon table
        table_id: NCBI genetic code ID
        codons: Dictionary mapping 3-letter codons to amino acids
        start_codons: List of start codons
        stop_codons: List of stop codons
    """

    name: str
    table_id: int
    codons: dict[str, str]
    start_codons: list[str]
    stop_codons: list[str]


@dataclass
class AminoAcid:
    """
    Amino acid properties.

    Attributes:
        code_1: Single-letter code
        code_3: Three-letter code
        name: Full name
        molecular_weight: Molecular weight in Da
        pka_cooh: pKa of carboxyl group
        pka_nh3: pKa of amino group
        pka_sidechain: pKa of side chain (if applicable)
        isoelectric_point: Isoelectric point
        hydrophobicity: Kyte-Doolittle hydrophobicity
    """

    code_1: str
    code_3: str
    name: str
    molecular_weight: float
    pka_cooh: float
    pka_nh3: float
    pka_sidechain: float | None
    isoelectric_point: float
    hydrophobicity: float


@dataclass
class BLASTHit:
    """
    Result of a BLAST search hit.

    Attributes:
        query_id: Query sequence ID
        subject_id: Subject (database) sequence ID
        percent_identity: Percentage identity
        alignment_length: Length of alignment
        mismatches: Number of mismatches
        gap_openings: Number of gap openings
        query_start: Start position in query
        query_end: End position in query
        subject_start: Start position in subject
        subject_end: End position in subject
        evalue: E-value (expected value)
        bit_score: Bit score
    """

    query_id: str
    subject_id: str
    percent_identity: float
    alignment_length: int
    mismatches: int
    gap_openings: int
    query_start: int
    query_end: int
    subject_start: int
    subject_end: int
    evalue: float
    bit_score: float


@dataclass
class PhyloTree:
    """
    Phylogenetic tree node.

    Attributes:
        name: Taxon name (for leaves) or internal node ID
        branch_length: Length of branch to parent
        bootstrap_support: Bootstrap support value (0-100)
        left_child: Left child node (if internal)
        right_child: Right child node (if internal)
    """

    name: str | None = None
    branch_length: float = 0.0
    bootstrap_support: float | None = None
    left_child: Optional["PhyloTree"] = None
    right_child: Optional["PhyloTree"] = None

    def is_leaf(self) -> bool:
        """Check if node is a leaf."""
        return self.left_child is None and self.right_child is None

    def get_leaves(self) -> list["PhyloTree"]:
        """Get all leaf nodes in subtree."""
        if self.is_leaf():
            return [self]
        leaves: list[PhyloTree] = []
        if self.left_child:
            leaves.extend(self.left_child.get_leaves())
        if self.right_child:
            leaves.extend(self.right_child.get_leaves())
        return leaves


@dataclass
class GeneFeature:
    """
    Genomic feature (gene, exon, intron, etc.).

    Attributes:
        feature_type: Type of feature (e.g., 'gene', 'exon', 'CDS')
        start: Start position (0-based, inclusive)
        end: End position (0-based, exclusive)
        strand: '+' for forward, '-' for reverse
        qualifiers: Dictionary of feature qualifiers
    """

    feature_type: str
    start: int
    end: int
    strand: str = "+"
    qualifiers: dict[str, list[str]] = field(default_factory=dict)

    def __len__(self) -> int:
        """Return feature length."""
        return self.end - self.start


@dataclass
class SequenceStats:
    """
    Statistical summary of a sequence.

    Attributes:
        length: Sequence length
        gc_content: GC content percentage
        nucleotide_freqs: Dictionary of nucleotide frequencies
        codon_usage: Dictionary of codon frequencies
        entropy: Shannon entropy
        complexity: Linguistic complexity measure
    """

    length: int
    gc_content: float
    nucleotide_freqs: dict[str, float]
    codon_usage: dict[str, int] | None = None
    entropy: float | None = None
    complexity: float | None = None


class SubstitutionMatrix:
    """
    Amino acid substitution matrix for sequence alignment.

    Provides scoring for amino acid matches and mismatches.
    Includes commonly used matrices like BLOSUM62 and PAM250.
    """

    def __init__(self, name: str, matrix: dict[tuple[str, str], int], alphabet: str = "ACDEFGHIKLMNPQRSTVWY") -> None:
        """
        Initialize substitution matrix.

        Args:
            name: Name of the matrix
            matrix: Dictionary mapping (aa1, aa2) pairs to scores
            alphabet: Amino acid alphabet
        """
        self.name = name
        self.matrix = matrix
        self.alphabet = alphabet

    def score(self, aa1: str, aa2: str) -> int:
        """
        Get substitution score for two amino acids.

        Args:
            aa1: First amino acid
            aa2: Second amino acid

        Returns:
            Substitution score
        """
        key = (aa1, aa2) if (aa1, aa2) in self.matrix else (aa2, aa1)
        return self.matrix.get(key, 0)

    @staticmethod
    def blosum62() -> "SubstitutionMatrix":
        """Create BLOSUM62 substitution matrix."""
        blosum62_data = {
            ("A", "A"): 4,
            ("A", "R"): -1,
            ("A", "N"): -2,
            ("A", "D"): -2,
            ("A", "C"): 0,
            ("A", "Q"): -1,
            ("A", "E"): -1,
            ("A", "G"): 0,
            ("A", "H"): -2,
            ("A", "I"): -1,
            ("A", "L"): -1,
            ("A", "K"): -1,
            ("A", "M"): -1,
            ("A", "F"): -2,
            ("A", "P"): -1,
            ("A", "S"): 1,
            ("A", "T"): 0,
            ("A", "W"): -3,
            ("A", "Y"): -2,
            ("A", "V"): 0,
            ("R", "R"): 5,
            ("R", "N"): 0,
            ("R", "D"): -2,
            ("R", "C"): -3,
            ("R", "Q"): 1,
            ("R", "E"): 0,
            ("R", "G"): -3,
            ("R", "H"): 0,
            ("R", "I"): -3,
            ("R", "L"): -3,
            ("R", "K"): 2,
            ("R", "M"): -1,
            ("R", "F"): -3,
            ("R", "P"): -2,
            ("R", "S"): -1,
            ("R", "T"): -1,
            ("R", "W"): -3,
            ("R", "Y"): -2,
            ("R", "V"): -3,
            ("N", "N"): 6,
            ("N", "D"): 1,
            ("N", "C"): -3,
            ("N", "Q"): 0,
            ("N", "E"): 0,
            ("N", "G"): 0,
            ("N", "H"): 1,
            ("N", "I"): -3,
            ("N", "L"): -4,
            ("N", "K"): 0,
            ("N", "M"): -2,
            ("N", "F"): -3,
            ("N", "P"): -2,
            ("N", "S"): 1,
            ("N", "T"): 0,
            ("N", "W"): -4,
            ("N", "Y"): -2,
            ("N", "V"): -3,
            ("D", "D"): 6,
            ("D", "C"): -3,
            ("D", "Q"): 0,
            ("D", "E"): 2,
            ("D", "G"): -1,
            ("D", "H"): -1,
            ("D", "I"): -3,
            ("D", "L"): -4,
            ("D", "K"): -1,
            ("D", "M"): -3,
            ("D", "F"): -3,
            ("D", "P"): -1,
            ("D", "S"): 0,
            ("D", "T"): -1,
            ("D", "W"): -4,
            ("D", "Y"): -3,
            ("D", "V"): -3,
            ("C", "C"): 9,
            ("C", "Q"): -3,
            ("C", "E"): -4,
            ("C", "G"): -3,
            ("C", "H"): -3,
            ("C", "I"): -1,
            ("C", "L"): -1,
            ("C", "K"): -3,
            ("C", "M"): -1,
            ("C", "F"): -2,
            ("C", "P"): -3,
            ("C", "S"): -1,
            ("C", "T"): -1,
            ("C", "W"): -2,
            ("C", "Y"): -2,
            ("C", "V"): -1,
            ("Q", "Q"): 5,
            ("Q", "E"): 2,
            ("Q", "G"): -2,
            ("Q", "H"): 0,
            ("Q", "I"): -3,
            ("Q", "L"): -2,
            ("Q", "K"): 1,
            ("Q", "M"): 0,
            ("Q", "F"): -3,
            ("Q", "P"): -1,
            ("Q", "S"): 0,
            ("Q", "T"): -1,
            ("Q", "W"): -2,
            ("Q", "Y"): -1,
            ("Q", "V"): -2,
            ("E", "E"): 5,
            ("E", "G"): -2,
            ("E", "H"): -1,
            ("E", "I"): -3,
            ("E", "L"): -3,
            ("E", "K"): 1,
            ("E", "M"): -2,
            ("E", "F"): -3,
            ("E", "P"): -1,
            ("E", "S"): 0,
            ("E", "T"): -1,
            ("E", "W"): -3,
            ("E", "Y"): -2,
            ("E", "V"): -2,
            ("G", "G"): 6,
            ("G", "H"): -2,
            ("G", "I"): -4,
            ("G", "L"): -4,
            ("G", "K"): -2,
            ("G", "M"): -3,
            ("G", "F"): -3,
            ("G", "P"): -2,
            ("G", "S"): 0,
            ("G", "T"): -2,
            ("G", "W"): -2,
            ("G", "Y"): -3,
            ("G", "V"): -3,
            ("H", "H"): 8,
            ("H", "I"): -3,
            ("H", "L"): -3,
            ("H", "K"): -1,
            ("H", "M"): -2,
            ("H", "F"): -1,
            ("H", "P"): -2,
            ("H", "S"): -1,
            ("H", "T"): -2,
            ("H", "W"): -2,
            ("H", "Y"): 2,
            ("H", "V"): -3,
            ("I", "I"): 4,
            ("I", "L"): 2,
            ("I", "K"): -3,
            ("I", "M"): 1,
            ("I", "F"): 0,
            ("I", "P"): -3,
            ("I", "S"): -2,
            ("I", "T"): -1,
            ("I", "W"): -3,
            ("I", "Y"): -1,
            ("I", "V"): 3,
            ("L", "L"): 4,
            ("L", "K"): -2,
            ("L", "M"): 2,
            ("L", "F"): 0,
            ("L", "P"): -3,
            ("L", "S"): -2,
            ("L", "T"): -1,
            ("L", "W"): -2,
            ("L", "Y"): -1,
            ("L", "V"): 1,
            ("K", "K"): 5,
            ("K", "M"): -1,
            ("K", "F"): -3,
            ("K", "P"): -1,
            ("K", "S"): 0,
            ("K", "T"): -1,
            ("K", "W"): -3,
            ("K", "Y"): -2,
            ("K", "V"): -2,
            ("M", "M"): 5,
            ("M", "F"): 0,
            ("M", "P"): -2,
            ("M", "S"): -1,
            ("M", "T"): -1,
            ("M", "W"): -1,
            ("M", "Y"): -1,
            ("M", "V"): 1,
            ("F", "F"): 6,
            ("F", "P"): -4,
            ("F", "S"): -2,
            ("F", "T"): -2,
            ("F", "W"): 1,
            ("F", "Y"): 3,
            ("F", "V"): -1,
            ("P", "P"): 7,
            ("P", "S"): -1,
            ("P", "T"): -1,
            ("P", "W"): -4,
            ("P", "Y"): -3,
            ("P", "V"): -2,
            ("S", "S"): 4,
            ("S", "T"): 1,
            ("S", "W"): -3,
            ("S", "Y"): -2,
            ("S", "V"): -2,
            ("T", "T"): 5,
            ("T", "W"): -2,
            ("T", "Y"): -2,
            ("T", "V"): 0,
            ("W", "W"): 11,
            ("W", "Y"): 2,
            ("W", "V"): -3,
            ("Y", "Y"): 7,
            ("Y", "V"): -1,
            ("V", "V"): 4,
        }
        return SubstitutionMatrix("BLOSUM62", blosum62_data)

    @staticmethod
    def pam250() -> "SubstitutionMatrix":
        """Create PAM250 substitution matrix."""
        pam250_data = {
            ("A", "A"): 13,
            ("A", "R"): -6,
            ("A", "N"): -8,
            ("A", "D"): -7,
            ("A", "C"): -8,
            ("A", "Q"): -7,
            ("A", "E"): -7,
            ("A", "G"): 9,
            ("A", "H"): -9,
            ("A", "I"): -8,
            ("A", "L"): -6,
            ("A", "K"): -7,
            ("A", "M"): -8,
            ("A", "F"): -9,
            ("A", "P"): 10,
            ("A", "S"): 6,
            ("A", "T"): 7,
            ("A", "W"): -15,
            ("A", "Y"): -10,
            ("A", "V"): -5,
            ("R", "R"): 17,
            ("R", "N"): -4,
            ("R", "D"): -12,
            ("R", "C"): -12,
            ("R", "Q"): 0,
            ("R", "E"): -10,
            ("R", "G"): -9,
            ("R", "H"): 10,
            ("R", "I"): -6,
            ("R", "L"): -8,
            ("R", "K"): 7,
            ("R", "M"): -2,
            ("R", "F"): -13,
            ("R", "P"): -7,
            ("R", "S"): -1,
            ("R", "T"): -4,
            ("R", "W"): 8,
            ("R", "Y"): -10,
            ("R", "V"): -7,
            ("N", "N"): 10,
            ("N", "D"): 2,
            ("N", "C"): -14,
            ("N", "Q"): -3,
            ("N", "E"): -4,
            ("N", "G"): -9,
            ("N", "H"): 0,
            ("N", "I"): -10,
            ("N", "L"): -7,
            ("N", "K"): 0,
            ("N", "M"): -9,
            ("N", "F"): -13,
            ("N", "P"): -8,
            ("N", "S"): 2,
            ("N", "T"): -1,
            ("N", "W"): -15,
            ("N", "Y"): -8,
            ("N", "V"): -9,
            ("D", "D"): 12,
            ("D", "C"): -16,
            ("D", "Q"): -3,
            ("D", "E"): 4,
            ("D", "G"): -1,
            ("D", "H"): -4,
            ("D", "I"): -11,
            ("D", "L"): -13,
            ("D", "K"): -4,
            ("D", "M"): -11,
            ("D", "F"): -16,
            ("D", "P"): -8,
            ("D", "S"): 0,
            ("D", "T"): -2,
            ("D", "W"): -15,
            ("D", "Y"): -11,
            ("D", "V"): -11,
            ("C", "C"): 12,
            ("C", "Q"): -14,
            ("C", "E"): -14,
            ("C", "G"): -9,
            ("C", "H"): -7,
            ("C", "I"): -2,
            ("C", "L"): -15,
            ("C", "K"): -12,
            ("C", "M"): -13,
            ("C", "F"): -12,
            ("C", "P"): -8,
            ("C", "S"): 0,
            ("C", "T"): -5,
            ("C", "W"): -8,
            ("C", "Y"): 0,
            ("C", "V"): -2,
            ("Q", "Q"): 11,
            ("Q", "E"): 2,
            ("Q", "G"): -5,
            ("Q", "H"): 1,
            ("Q", "I"): -8,
            ("Q", "L"): -5,
            ("Q", "K"): 3,
            ("Q", "M"): 0,
            ("Q", "F"): -13,
            ("Q", "P"): -3,
            ("Q", "S"): -1,
            ("Q", "T"): -2,
            ("Q", "W"): -2,
            ("Q", "Y"): -8,
            ("Q", "V"): -8,
            ("E", "E"): 12,
            ("E", "G"): -5,
            ("E", "H"): -4,
            ("E", "I"): -8,
            ("E", "L"): -6,
            ("E", "K"): 3,
            ("E", "M"): -5,
            ("E", "F"): -11,
            ("E", "P"): -5,
            ("E", "S"): -1,
            ("E", "T"): -3,
            ("E", "W"): -15,
            ("E", "Y"): -8,
            ("E", "V"): -6,
            ("G", "G"): 12,
            ("G", "H"): -9,
            ("G", "I"): -5,
            ("G", "L"): -10,
            ("G", "K"): -5,
            ("G", "M"): -8,
            ("G", "F"): -14,
            ("G", "P"): -2,
            ("G", "S"): 3,
            ("G", "T"): -3,
            ("G", "W"): -7,
            ("G", "Y"): -14,
            ("G", "V"): -5,
            ("H", "H"): 15,
            ("H", "I"): -9,
            ("H", "L"): -5,
            ("H", "K"): -4,
            ("H", "M"): -4,
            ("H", "F"): 0,
            ("H", "P"): 0,
            ("H", "S"): -4,
            ("H", "T"): -6,
            ("H", "W"): 3,
            ("H", "Y"): 10,
            ("H", "V"): -8,
            ("I", "I"): 5,
            ("I", "L"): 2,
            ("I", "K"): -8,
            ("I", "M"): 1,
            ("I", "F"): 1,
            ("I", "P"): -8,
            ("I", "S"): -7,
            ("I", "T"): -1,
            ("I", "W"): -14,
            ("I", "Y"): -6,
            ("I", "V"): 4,
            ("L", "L"): 6,
            ("L", "K"): -7,
            ("L", "M"): 4,
            ("L", "F"): 2,
            ("L", "P"): -5,
            ("L", "S"): -8,
            ("L", "T"): -6,
            ("L", "W"): -2,
            ("L", "Y"): -7,
            ("L", "V"): 2,
            ("K", "K"): 10,
            ("K", "M"): 0,
            ("K", "F"): -14,
            ("K", "P"): -4,
            ("K", "S"): -1,
            ("K", "T"): 0,
            ("K", "W"): -4,
            ("K", "Y"): -8,
            ("K", "V"): -6,
            ("M", "M"): 11,
            ("M", "F"): -4,
            ("M", "P"): -8,
            ("M", "S"): -5,
            ("M", "T"): -2,
            ("M", "W"): -4,
            ("M", "Y"): -7,
            ("M", "V"): 1,
            ("F", "F"): 9,
            ("F", "P"): -10,
            ("F", "S"): -6,
            ("F", "T"): -7,
            ("F", "W"): 0,
            ("F", "Y"): 7,
            ("F", "V"): -1,
            ("P", "P"): 12,
            ("P", "S"): 1,
            ("P", "T"): -1,
            ("P", "W"): -13,
            ("P", "Y"): -10,
            ("P", "V"): -6,
            ("S", "S"): 9,
            ("S", "T"): 1,
            ("S", "W"): -7,
            ("S", "Y"): -7,
            ("S", "V"): -7,
            ("T", "T"): 11,
            ("T", "W"): -13,
            ("T", "Y"): -6,
            ("T", "V"): -2,
            ("W", "W"): 15,
            ("W", "Y"): 0,
            ("W", "V"): -14,
            ("Y", "Y"): 10,
            ("Y", "V"): -6,
            ("V", "V"): 4,
        }
        return SubstitutionMatrix("PAM250", pam250_data)
