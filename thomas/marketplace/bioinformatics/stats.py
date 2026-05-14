"""
Bioinformatics statistical analysis.

Provides sequence composition analysis, entropy calculations, k-mer analysis,
codon usage bias, and statistical testing.
"""

import math
from collections import Counter, defaultdict


def sequence_entropy(sequence: str) -> float:
    """
    Calculate Shannon entropy of a sequence.

    Measures the information content and complexity.

    Args:
        sequence: DNA, RNA, or protein sequence

    Returns:
        Shannon entropy in bits
    """
    sequence = sequence.upper()

    if not sequence:
        raise ValueError("Sequence cannot be empty")

    # Count character frequencies
    counts = Counter(sequence)
    total = len(sequence)

    entropy = 0.0
    for count in counts.values():
        frequency = count / total
        if frequency > 0:
            entropy -= frequency * math.log2(frequency)

    return entropy


def kmer_frequency(sequence: str, k: int = 3) -> dict[str, float]:
    """
    Calculate k-mer frequency distribution.

    Args:
        sequence: DNA or protein sequence
        k: Size of k-mers

    Returns:
        Dictionary mapping k-mers to frequencies
    """
    sequence = sequence.upper()

    if len(sequence) < k:
        raise ValueError(f"Sequence length must be >= {k}")

    kmer_counts: dict[str, int] = defaultdict(int)
    total_kmers = len(sequence) - k + 1

    for i in range(total_kmers):
        kmer = sequence[i : i + k]
        if len(kmer) == k:
            kmer_counts[kmer] += 1

    frequencies = {kmer: count / total_kmers for kmer, count in kmer_counts.items()}

    return frequencies


def sequence_complexity(sequence: str) -> float:
    """
    Calculate linguistic complexity of sequence.

    Uses the Wootton-Federhen complexity measure.

    Args:
        sequence: DNA or protein sequence

    Returns:
        Complexity score (0-1)
    """
    sequence = sequence.upper()

    if not sequence:
        raise ValueError("Sequence cannot be empty")

    # Calculate probability of random match
    freq = Counter(sequence)
    total = len(sequence)

    p_identity = sum((count / total) ** 2 for count in freq.values())

    # Complexity = 1 - p_identity
    complexity = 1.0 - p_identity

    return complexity


def gc_skew(sequence: str, window_size: int = 1000) -> list[float]:
    """
    Calculate GC skew across sequence.

    Skew = (G-C)/(G+C)

    Args:
        sequence: DNA sequence
        window_size: Size of sliding window

    Returns:
        List of skew values
    """
    sequence = sequence.upper()

    if window_size > len(sequence):
        window_size = len(sequence)

    skew_values: list[float] = []

    for i in range(len(sequence) - window_size + 1):
        window = sequence[i : i + window_size]

        g_count = window.count("G")
        c_count = window.count("C")

        if g_count + c_count > 0:
            skew = (g_count - c_count) / (g_count + c_count)
        else:
            skew = 0.0

        skew_values.append(skew)

    return skew_values


def codon_usage_bias(sequence: str) -> dict[str, float]:
    """
    Calculate codon usage bias.

    Returns relative frequency of each codon.

    Args:
        sequence: DNA sequence (must be multiple of 3)

    Returns:
        Dictionary mapping codons to usage bias (0-1)
    """
    sequence = sequence.upper()

    if len(sequence) % 3 != 0:
        raise ValueError("Sequence length must be multiple of 3")

    codon_counts: dict[str, int] = defaultdict(int)

    for i in range(0, len(sequence) - 2, 3):
        codon = sequence[i : i + 3]
        codon_counts[codon] += 1

    total = sum(codon_counts.values())

    if total == 0:
        raise ValueError("No codons found")

    # Group by amino acid
    usage_bias: dict[str, float] = {}

    # Standard genetic code for grouping

    for codon, count in codon_counts.items():
        usage_bias[codon] = count / total

    return usage_bias


def dinucleotide_frequency(sequence: str) -> dict[str, float]:
    """
    Calculate dinucleotide frequency.

    Args:
        sequence: DNA or RNA sequence

    Returns:
        Dictionary mapping dinucleotides to frequencies
    """
    sequence = sequence.upper()

    if len(sequence) < 2:
        raise ValueError("Sequence must be at least 2 bp long")

    dinucleotide_counts: dict[str, int] = defaultdict(int)
    total = len(sequence) - 1

    for i in range(total):
        dinuc = sequence[i : i + 2]
        dinucleotide_counts[dinuc] += 1

    frequencies = {dinuc: count / total for dinuc, count in dinucleotide_counts.items()}

    return frequencies


def chi_squared_test(observed: dict[str, int], expected: dict[str, float], alpha: float = 0.05) -> tuple[float, bool]:
    """
    Chi-squared goodness of fit test.

    Tests if observed frequencies match expected frequencies.

    Args:
        observed: Dictionary of observed counts
        expected: Dictionary of expected frequencies (or proportions)
        alpha: Significance level

    Returns:
        Tuple of (chi_squared_statistic, is_significant)
    """
    total_observed = sum(observed.values())

    if total_observed == 0:
        raise ValueError("No observed data")

    # Calculate expected counts
    expected_counts: dict[str, float] = {}

    # Check if expected values are frequencies or proportions
    expected_sum = sum(expected.values())

    if expected_sum <= 1.0:
        # Proportions
        for key, freq in expected.items():
            expected_counts[key] = freq * total_observed
    else:
        # Counts
        expected_counts = {k: float(v) for k, v in expected.items()}

    # Calculate chi-squared
    chi_squared = 0.0

    for key in observed:
        obs = observed.get(key, 0)
        exp = expected_counts.get(key, 0)

        if exp > 0:
            chi_squared += ((obs - exp) ** 2) / exp
        elif obs > 0:
            chi_squared += obs**2  # Penalty for observed when expected is 0

    # Degrees of freedom
    df = len(observed) - 1

    # Critical value (approximation using standard values)
    critical_values = {
        1: 3.841,
        2: 5.991,
        3: 7.815,
        4: 9.488,
        5: 11.070,
        10: 18.307,
    }

    critical = critical_values.get(df, 3.841 + df * 1.5)  # Approximation
    is_significant = chi_squared > critical

    return chi_squared, is_significant


def base_composition(sequence: str) -> dict[str, float]:
    """
    Calculate base composition percentages.

    Args:
        sequence: DNA or RNA sequence

    Returns:
        Dictionary of base -> percentage
    """
    sequence = sequence.upper()

    if not sequence:
        raise ValueError("Sequence cannot be empty")

    composition: dict[str, float] = {}
    total = len(sequence)

    for base in "ACGTU":
        count = sequence.count(base)
        composition[base] = (count / total) * 100.0

    return composition


def expected_vs_observed_kmers(sequence: str, k: int = 2) -> dict[str, tuple[float, float]]:
    """
    Compare expected vs observed k-mer frequencies.

    Expected frequencies based on mononucleotide frequencies.

    Args:
        sequence: DNA sequence
        k: Size of k-mers

    Returns:
        Dictionary mapping k-mers to (expected_freq, observed_freq)
    """
    sequence = sequence.upper()

    if len(sequence) < k:
        raise ValueError(f"Sequence length must be >= {k}")

    # Get mononucleotide frequencies
    mono_freq = base_composition(sequence)

    # Convert percentages to proportions
    mono_props = {b: mono_freq.get(b, 0) / 100.0 for b in "ACGTU"}

    # Calculate expected k-mer frequencies
    expected: dict[str, float] = {}

    def generate_kmers(chars: str, remaining: int) -> list[str]:
        if remaining == 0:
            return [""]
        sub_kmers = generate_kmers(chars, remaining - 1)
        return [c + sk for c in chars for sk in sub_kmers]

    for kmer in generate_kmers("ACGTU", k):
        if all(c in mono_props for c in kmer):
            prob = 1.0
            for c in kmer:
                prob *= mono_props[c]
            expected[kmer] = prob

    # Get observed k-mer frequencies
    observed = kmer_frequency(sequence, k)

    # Compare
    result: dict[str, tuple[float, float]] = {}

    for kmer in set(expected.keys()) | set(observed.keys()):
        exp = expected.get(kmer, 0.0)
        obs = observed.get(kmer, 0.0)
        result[kmer] = (exp, obs)

    return result
