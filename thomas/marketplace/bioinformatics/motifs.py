"""
Sequence motif analysis and discovery.

Implements position weight matrices, motif scoring, consensus generation,
and basic pattern discovery using regular expressions and Gibbs sampling.
"""

import math
import random
import re
from collections import defaultdict


class PositionWeightMatrix:
    """
    Position weight matrix for motif representation and scoring.

    Encodes nucleotide/amino acid frequencies at each position.
    """

    def __init__(self, matrix: dict[str, list[float]], alphabet: str = "ACGT", pseudocount: float = 0.1) -> None:
        """
        Initialize PWM.

        Args:
            matrix: Dictionary mapping characters to frequency lists
            alphabet: Character alphabet
            pseudocount: Pseudocount for probability smoothing
        """
        self.matrix = matrix
        self.alphabet = alphabet
        self.pseudocount = pseudocount
        self.width = len(next(iter(matrix.values()))) if matrix else 0

    @staticmethod
    def from_alignment(
        sequences: list[str], alphabet: str = "ACGT", pseudocount: float = 0.1
    ) -> "PositionWeightMatrix":
        """
        Create PWM from aligned sequences.

        Args:
            sequences: Aligned sequences of equal length
            alphabet: Character alphabet
            pseudocount: Pseudocount for smoothing

        Returns:
            PositionWeightMatrix object
        """
        if not sequences:
            raise ValueError("No sequences provided")

        width = len(sequences[0])

        # Check all sequences have same length
        if not all(len(s) == width for s in sequences):
            raise ValueError("All sequences must have equal length")

        # Count frequencies
        counts: dict[str, list[float]] = {c: [0.0] * width for c in alphabet}

        for seq in sequences:
            for pos, char in enumerate(seq.upper()):
                if char in counts:
                    counts[char][pos] += 1

        # Convert to frequencies with pseudocount
        matrix: dict[str, list[float]] = {}
        total = len(sequences) + pseudocount * len(alphabet)

        for char in alphabet:
            matrix[char] = [(counts[char][i] + pseudocount) / total for i in range(width)]

        return PositionWeightMatrix(matrix, alphabet, pseudocount)

    def consensus(self) -> str:
        """Get consensus sequence from PWM."""
        consensus = []

        for pos in range(self.width):
            max_char = None
            max_freq = 0.0

            for char in self.alphabet:
                if char in self.matrix and self.matrix[char][pos] > max_freq:
                    max_freq = self.matrix[char][pos]
                    max_char = char

            if max_char:
                consensus.append(max_char)

        return "".join(consensus)

    def information_content(self) -> list[float]:
        """
        Calculate information content at each position.

        Returns:
            List of IC values (in bits)
        """
        ic_values: list[float] = []
        bg_freq = 1.0 / len(self.alphabet)

        for pos in range(self.width):
            ic = 0.0

            for char in self.alphabet:
                if char in self.matrix:
                    freq = self.matrix[char][pos]
                    if freq > 0:
                        ic += freq * math.log2(freq / bg_freq)

            ic_values.append(max(0.0, ic))

        return ic_values

    def score_sequence(self, seq: str) -> float:
        """
        Score a sequence against the PWM.

        Args:
            seq: Sequence to score

        Returns:
            Log-odds score
        """
        if len(seq) != self.width:
            raise ValueError(f"Sequence must be {self.width} bp long")

        score = 0.0
        bg_freq = 1.0 / len(self.alphabet)

        for pos, char in enumerate(seq.upper()):
            if char in self.matrix:
                freq = self.matrix[char][pos]
                if freq > 0:
                    score += math.log2(freq / bg_freq)
            else:
                score -= 5.0  # Penalty for unknown character

        return score

    def find_sites(self, sequence: str, threshold: float = 0.0) -> list[tuple[int, float]]:
        """
        Find PWM matches in a sequence.

        Args:
            sequence: Sequence to search
            threshold: Minimum score for reporting

        Returns:
            List of (position, score) tuples
        """
        matches: list[tuple[int, float]] = []

        for i in range(len(sequence) - self.width + 1):
            subseq = sequence[i : i + self.width]
            score = self.score_sequence(subseq)

            if score >= threshold:
                matches.append((i, score))

        return matches


def find_motif_occurrences(pattern: str, sequence: str, allow_mismatch: int = 0) -> list[tuple[int, str]]:
    """
    Find motif pattern occurrences in a sequence.

    Supports regular expression patterns and mismatches.

    Args:
        pattern: Motif pattern (IUPAC codes supported)
        sequence: Sequence to search
        allow_mismatch: Number of allowed mismatches

    Returns:
        List of (position, matched_sequence) tuples
    """
    # Convert IUPAC to regex if needed
    iupac_map = {
        "N": "[ACGT]",
        "R": "[AG]",
        "Y": "[CT]",
        "S": "[GC]",
        "W": "[AT]",
        "K": "[GT]",
        "M": "[AC]",
        "B": "[CGT]",
        "D": "[AGT]",
        "H": "[ACT]",
        "V": "[ACG]",
    }

    regex_pattern = pattern.upper()
    for iupac, regex in iupac_map.items():
        regex_pattern = regex_pattern.replace(iupac, regex)

    matches: list[tuple[int, str]] = []

    try:
        for match in re.finditer(regex_pattern, sequence.upper()):
            matches.append((match.start(), match.group()))
    except re.error:
        # Fall back to exact matching
        for i in range(len(sequence) - len(pattern) + 1):
            if sequence[i : i + len(pattern)].upper() == pattern.upper():
                matches.append((i, sequence[i : i + len(pattern)]))

    return matches


RESTRICTION_ENZYMES: dict[str, tuple[str, int]] = {
    "EcoRI": ("GAATTC", 1),
    "BamHI": ("GGATCC", 1),
    "HindIII": ("AAGCTT", 1),
    "SmaI": ("CCCGGG", 3),
    "PstI": ("CTGCAG", 3),
    "SalI": ("GTCGAC", 1),
    "KpnI": ("GGTACC", 1),
    "XhoI": ("CTCGAG", 1),
    "NotI": ("GCGGCCGC", 2),
    "XbaI": ("TCTAGA", 1),
}


def find_restriction_sites(sequence: str, enzyme: str | None = None) -> dict[str, list[tuple[int, int]]]:
    """
    Find restriction enzyme cut sites in a sequence.

    Args:
        sequence: DNA sequence
        enzyme: Specific enzyme to search for (None = all)

    Returns:
        Dictionary mapping enzyme names to lists of (cut_pos, cut_offset) tuples
    """
    sites: dict[str, list[tuple[int, int]]] = defaultdict(list)
    sequence = sequence.upper()

    enzymes = {enzyme: RESTRICTION_ENZYMES[enzyme]} if enzyme else RESTRICTION_ENZYMES

    for enz_name, (pattern, offset) in enzymes.items():
        for match in re.finditer(pattern, sequence):
            sites[enz_name].append((match.start(), offset))

    return dict(sites)


def gibbs_sampler(
    sequences: list[str], motif_width: int = 8, iterations: int = 100, seed: int | None = None
) -> tuple[list[int], "PositionWeightMatrix"]:
    """
    Discover motifs using Gibbs sampling.

    Simplified implementation for demonstration.

    Args:
        sequences: Set of DNA sequences
        motif_width: Width of motif to discover
        iterations: Number of sampling iterations
        seed: Random seed for reproducibility

    Returns:
        Tuple of (starting_positions, PWM)
    """
    if seed is not None:
        random.seed(seed)

    n_seq = len(sequences)
    positions = [random.randint(0, len(seq) - motif_width) for seq in sequences]

    best_score = float("-inf")
    best_positions = positions[:]

    for iteration in range(iterations):
        # Build PWM from current positions
        motifs = [sequences[i][positions[i] : positions[i] + motif_width] for i in range(n_seq)]

        try:
            pwm = PositionWeightMatrix.from_alignment(motifs)

            # Score this PWM
            score = sum(pwm.score_sequence(m) for m in motifs)

            if score > best_score:
                best_score = score
                best_positions = positions[:]

            # Sample new position for random sequence
            sample_seq = random.randint(0, n_seq - 1)
            seq = sequences[sample_seq]

            scores = []
            for pos in range(len(seq) - motif_width + 1):
                subseq = seq[pos : pos + motif_width]
                s = pwm.score_sequence(subseq)
                scores.append(s)

            if scores:
                max_score = max(scores)
                if max_score > 0:
                    probs = [math.exp(s - max_score) for s in scores]
                    total_prob = sum(probs)
                    probs = [p / total_prob for p in probs]

                    positions[sample_seq] = random.choices(range(len(seq) - motif_width + 1), weights=probs)[0]

        except ValueError:
            continue

    motifs = [sequences[i][best_positions[i] : best_positions[i] + motif_width] for i in range(n_seq)]
    pwm = PositionWeightMatrix.from_alignment(motifs)

    return best_positions, pwm
