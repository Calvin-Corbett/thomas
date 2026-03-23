"""
Sequence manipulation and analysis functions.

Provides core functionality for DNA, RNA, and protein sequence operations
including validation, transcription, translation, composition analysis,
and file I/O.
"""

from thomas.marketplace.bioinformatics._exceptions import InvalidSequenceError
from thomas.marketplace.bioinformatics._types import Sequence, SequenceType

# Standard genetic code (NCBI code 1)
STANDARD_GENETIC_CODE: dict[str, str] = {
    "TTT": "F",
    "TTC": "F",
    "TTA": "L",
    "TTG": "L",
    "TCT": "S",
    "TCC": "S",
    "TCA": "S",
    "TCG": "S",
    "TAT": "Y",
    "TAC": "Y",
    "TAA": "*",
    "TAG": "*",
    "TGT": "C",
    "TGC": "C",
    "TGA": "*",
    "TGG": "W",
    "CTT": "L",
    "CTC": "L",
    "CTA": "L",
    "CTG": "L",
    "CCT": "P",
    "CCC": "P",
    "CCA": "P",
    "CCG": "P",
    "CAT": "H",
    "CAC": "H",
    "CAA": "Q",
    "CAG": "Q",
    "CGT": "R",
    "CGC": "R",
    "CGA": "R",
    "CGG": "R",
    "ATT": "I",
    "ATC": "I",
    "ATA": "I",
    "ATG": "M",
    "ACT": "T",
    "ACC": "T",
    "ACA": "T",
    "ACG": "T",
    "AAT": "N",
    "AAC": "N",
    "AAA": "K",
    "AAG": "K",
    "AGT": "S",
    "AGC": "S",
    "AGA": "R",
    "AGG": "R",
    "GTT": "V",
    "GTC": "V",
    "GTA": "V",
    "GTG": "V",
    "GCT": "A",
    "GCC": "A",
    "GCA": "A",
    "GCG": "A",
    "GAT": "D",
    "GAC": "D",
    "GAA": "E",
    "GAG": "E",
    "GGT": "G",
    "GGC": "G",
    "GGA": "G",
    "GGG": "G",
}

# Start codons
START_CODONS: set[str] = {"ATG"}

# Stop codons
STOP_CODONS: set[str] = {"TAA", "TAG", "TGA"}


def validate_dna(seq: str) -> bool:
    """
    Validate that a sequence contains only DNA characters (ACGT).

    Args:
        seq: Sequence string to validate

    Returns:
        True if valid, raises InvalidSequenceError otherwise
    """
    if not seq:
        raise InvalidSequenceError("Sequence cannot be empty")

    valid_chars = set("ACGTacgt")
    if not all(c in valid_chars for c in seq):
        raise InvalidSequenceError("Invalid DNA characters in sequence")

    return True


def validate_rna(seq: str) -> bool:
    """
    Validate that a sequence contains only RNA characters (ACGU).

    Args:
        seq: Sequence string to validate

    Returns:
        True if valid, raises InvalidSequenceError otherwise
    """
    if not seq:
        raise InvalidSequenceError("Sequence cannot be empty")

    valid_chars = set("ACGUacgu")
    if not all(c in valid_chars for c in seq):
        raise InvalidSequenceError("Invalid RNA characters in sequence")

    return True


def validate_protein(seq: str) -> bool:
    """
    Validate that a sequence contains only valid amino acid codes.

    Args:
        seq: Sequence string to validate

    Returns:
        True if valid, raises InvalidSequenceError otherwise
    """
    if not seq:
        raise InvalidSequenceError("Sequence cannot be empty")

    valid_chars = set("ACDEFGHIKLMNPQRSTVWYBXZUP*acdefghiklmnpqrstvwybxzup")
    if not all(c in valid_chars for c in seq):
        raise InvalidSequenceError("Invalid amino acid characters in sequence")

    return True


def complement(seq: str) -> str:
    """
    Get the complement of a DNA sequence.

    Args:
        seq: DNA sequence

    Returns:
        Complementary sequence
    """
    validate_dna(seq)
    complement_map = {"A": "T", "T": "A", "G": "C", "C": "G", "a": "t", "t": "a", "g": "c", "c": "g"}
    return "".join(complement_map[c] for c in seq)


def reverse_complement(seq: str) -> str:
    """
    Get the reverse complement of a DNA sequence.

    Args:
        seq: DNA sequence

    Returns:
        Reverse complement sequence
    """
    return complement(seq)[::-1]


def transcribe(seq: str) -> str:
    """
    Transcribe DNA sequence to RNA (T -> U).

    Args:
        seq: DNA sequence

    Returns:
        RNA sequence
    """
    validate_dna(seq)
    return seq.upper().replace("T", "U")


def translate(seq: str, start: int = 0, genetic_code: dict[str, str] | None = None) -> str:
    """
    Translate RNA sequence to protein using genetic code.

    Handles start codons (ATG->M) and stop codons (*).

    Args:
        seq: RNA sequence (will handle both RNA and DNA)
        start: Starting position in sequence
        genetic_code: Codon table (defaults to standard genetic code)

    Returns:
        Protein sequence
    """
    seq = seq.upper().replace("U", "T")
    validate_dna(seq)

    if genetic_code is None:
        genetic_code = STANDARD_GENETIC_CODE

    protein = []
    for i in range(start, len(seq) - 2, 3):
        codon = seq[i : i + 3]
        if len(codon) == 3:
            aa = genetic_code.get(codon, "X")
            protein.append(aa)
            if aa == "*":
                break

    return "".join(protein)


def gc_content(seq: str) -> float:
    """
    Calculate GC content as percentage.

    Args:
        seq: DNA or RNA sequence

    Returns:
        GC content as percentage (0-100)
    """
    seq = seq.upper()
    if len(seq) == 0:
        raise InvalidSequenceError("Sequence cannot be empty")

    gc_count = seq.count("G") + seq.count("C")
    return (gc_count / len(seq)) * 100


def nucleotide_frequency(seq: str) -> dict[str, float]:
    """
    Calculate nucleotide frequency.

    Args:
        seq: DNA or RNA sequence

    Returns:
        Dictionary of nucleotide frequencies (0-1)
    """
    seq = seq.upper()
    if len(seq) == 0:
        raise InvalidSequenceError("Sequence cannot be empty")

    freq: dict[str, float] = {}
    total = len(seq)

    for nucleotide in "ACGT":
        count = seq.count(nucleotide)
        freq[nucleotide] = count / total

    return freq


def find_orfs(seq: str, min_length: int = 100) -> list[tuple[int, int, int]]:
    """
    Find open reading frames (ORFs) in a sequence.

    Returns ORFs on both forward and reverse complement strands.

    Args:
        seq: DNA sequence
        min_length: Minimum ORF length in nucleotides

    Returns:
        List of (start, end, strand) tuples where strand is +1 or -1
    """
    validate_dna(seq)
    seq = seq.upper()
    orfs: list[tuple[int, int, int]] = []

    # Search forward strand
    for frame in range(3):
        for i in range(frame, len(seq) - 2, 3):
            codon = seq[i : i + 3]
            if codon in START_CODONS:
                # Look for stop codon
                for j in range(i + 3, len(seq) - 2, 3):
                    stop_codon = seq[j : j + 3]
                    if stop_codon in STOP_CODONS:
                        if (j - i + 3) >= min_length:
                            orfs.append((i, j + 3, 1))
                        break

    # Search reverse complement strand
    rev_seq = reverse_complement(seq)
    for frame in range(3):
        for i in range(frame, len(rev_seq) - 2, 3):
            codon = rev_seq[i : i + 3]
            if codon in START_CODONS:
                for j in range(i + 3, len(rev_seq) - 2, 3):
                    stop_codon = rev_seq[j : j + 3]
                    if stop_codon in STOP_CODONS:
                        if (j - i + 3) >= min_length:
                            # Convert coordinates back to original sequence
                            orig_start = len(seq) - (j + 3)
                            orig_end = len(seq) - i
                            orfs.append((orig_start, orig_end, -1))
                        break

    return orfs


def parse_fasta(fasta_str: str) -> list[Sequence]:
    """
    Parse FASTA format string into Sequence objects.

    Args:
        fasta_str: FASTA format string

    Returns:
        List of Sequence objects
    """
    sequences: list[Sequence] = []
    current_id: str | None = None
    current_desc: str = ""
    current_seq: list[str] = []

    for line in fasta_str.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith(">"):
            # Save previous sequence
            if current_id is not None:
                seq_str = "".join(current_seq)
                seq_type = _detect_sequence_type(seq_str)
                sequences.append(
                    Sequence(id=current_id, seq=seq_str.upper(), seq_type=seq_type, description=current_desc)
                )

            # Parse header
            header = line[1:]
            parts = header.split(None, 1)
            current_id = parts[0]
            current_desc = parts[1] if len(parts) > 1 else ""
            current_seq = []
        else:
            current_seq.append(line)

    # Save last sequence
    if current_id is not None:
        seq_str = "".join(current_seq)
        seq_type = _detect_sequence_type(seq_str)
        sequences.append(Sequence(id=current_id, seq=seq_str.upper(), seq_type=seq_type, description=current_desc))

    return sequences


def write_fasta(sequences: list[Sequence], line_width: int = 70) -> str:
    """
    Write sequences in FASTA format.

    Args:
        sequences: List of Sequence objects
        line_width: Characters per line

    Returns:
        FASTA format string
    """
    lines: list[str] = []

    for seq in sequences:
        # Write header
        header = f">{seq.id}"
        if seq.description:
            header += f" {seq.description}"
        lines.append(header)

        # Write sequence with line wrapping
        for i in range(0, len(seq.seq), line_width):
            lines.append(seq.seq[i : i + line_width])

    return "\n".join(lines) + "\n"


def _detect_sequence_type(seq: str) -> SequenceType:
    """
    Detect sequence type based on composition.

    Args:
        seq: Sequence string

    Returns:
        Detected sequence type
    """
    seq = seq.upper()

    has_u = "U" in seq
    has_t = "T" in seq

    if has_u and not has_t:
        return SequenceType.RNA
    elif has_t and not has_u:
        return SequenceType.DNA
    else:
        # Check if it looks like protein
        protein_chars = set("ACDEFGHIKLMNPQRSTVWY")
        non_dna = set("EFIPQZ")

        if any(c in seq for c in non_dna):
            return SequenceType.PROTEIN

        return SequenceType.DNA
