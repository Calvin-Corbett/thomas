"""
Population genetics calculations and analysis.

Implements Hardy-Weinberg equilibrium testing, allele frequency calculations,
genetic diversity measures, and selection coefficient estimation.
"""

import math
from collections import defaultdict


def hardy_weinberg_test(genotypes: dict[str, int], alpha: float = 0.05) -> tuple[float, bool]:
    """
    Test for Hardy-Weinberg equilibrium using chi-squared test.

    Tests if observed genotype frequencies match expected frequencies under HWE.

    Args:
        genotypes: Dictionary mapping genotype strings (e.g., 'AA', 'Aa', 'aa') to counts
        alpha: Significance level

    Returns:
        Tuple of (chi_squared, is_equilibrium)
    """
    total = sum(genotypes.values())

    if total == 0:
        raise ValueError("No genotypes provided")

    # Calculate allele frequencies
    allele_counts: dict[str, int] = defaultdict(int)

    for genotype, count in genotypes.items():
        if len(genotype) == 2:
            allele_counts[genotype[0]] += count
            allele_counts[genotype[1]] += count

    total_alleles = sum(allele_counts.values())

    if total_alleles == 0:
        raise ValueError("No valid genotypes")

    allele_freqs = {a: c / total_alleles for a, c in allele_counts.items()}

    # Get unique alleles
    alleles = sorted(allele_freqs.keys())

    if len(alleles) > 2:
        raise ValueError("Function supports only biallelic loci")

    if len(alleles) < 2:
        return 0.0, True

    p = allele_freqs[alleles[0]]
    q = allele_freqs[alleles[1]]

    # Expected genotype frequencies
    expected: dict[str, float] = {
        alleles[0] + alleles[0]: p * p * total,
        alleles[0] + alleles[1]: 2 * p * q * total,
        alleles[1] + alleles[1]: q * q * total,
    }

    # Chi-squared test
    chi_squared = 0.0

    for genotype in expected:
        obs = genotypes.get(genotype, 0)
        exp = expected[genotype]

        if exp > 0:
            chi_squared += ((obs - exp) ** 2) / exp

    # 1 degree of freedom for biallelic locus
    critical_value = 3.841  # Chi-squared critical value for alpha=0.05, df=1

    is_equilibrium = chi_squared < critical_value

    return chi_squared, is_equilibrium


def allele_frequency(genotypes: dict[str, int]) -> dict[str, float]:
    """
    Calculate allele frequencies from genotype counts.

    Args:
        genotypes: Dictionary mapping genotype strings to counts

    Returns:
        Dictionary mapping alleles to frequencies
    """
    allele_counts: dict[str, int] = defaultdict(int)
    total_alleles = 0

    for genotype, count in genotypes.items():
        if len(genotype) >= 2:
            for allele in genotype[:2]:
                allele_counts[allele] += count
                total_alleles += count

    if total_alleles == 0:
        raise ValueError("No valid genotypes")

    frequencies = {a: c / total_alleles for a, c in allele_counts.items()}

    return frequencies


def heterozygosity(genotypes: dict[str, int]) -> tuple[float, float]:
    """
    Calculate observed and expected heterozygosity.

    Args:
        genotypes: Dictionary mapping genotype strings to counts

    Returns:
        Tuple of (observed_heterozygosity, expected_heterozygosity)
    """
    total = sum(genotypes.values())

    if total == 0:
        raise ValueError("No genotypes provided")

    # Observed heterozygosity
    het_count = sum(count for genotype, count in genotypes.items() if len(set(genotype[:2])) > 1)
    obs_het = het_count / total

    # Expected heterozygosity (Nei's gene diversity)
    freqs = allele_frequency(genotypes)

    exp_het = 1.0
    for freq in freqs.values():
        exp_het -= freq**2

    return obs_het, exp_het


def calculate_fst(pop1_freqs: dict[str, float], pop2_freqs: dict[str, float]) -> float:
    """
    Calculate Fst (population differentiation index).

    Args:
        pop1_freqs: Allele frequencies in population 1
        pop2_freqs: Allele frequencies in population 2

    Returns:
        Fst value (0-1)
    """
    # Get common alleles
    alleles = set(pop1_freqs.keys()) & set(pop2_freqs.keys())

    if len(alleles) == 0:
        return 0.0

    # Calculate average allele frequencies
    avg_freqs = {}
    for allele in alleles:
        avg = (pop1_freqs[allele] + pop2_freqs[allele]) / 2.0
        avg_freqs[allele] = avg

    # Calculate Ht (total heterozygosity)
    ht = 0.0
    for freq in avg_freqs.values():
        ht += freq * (1.0 - freq)

    ht *= 2.0

    # Calculate Hs (within-population heterozygosity)
    hs1 = 0.0
    for allele in alleles:
        freq = pop1_freqs[allele]
        hs1 += freq * (1.0 - freq)

    hs1 *= 2.0

    hs2 = 0.0
    for allele in alleles:
        freq = pop2_freqs[allele]
        hs2 += freq * (1.0 - freq)

    hs2 *= 2.0

    hs = (hs1 + hs2) / 2.0

    # Calculate Fst
    if ht == 0:
        return 0.0

    fst = (ht - hs) / ht

    return max(0.0, fst)


def nei_distance(pop1_freqs: dict[str, float], pop2_freqs: dict[str, float]) -> float:
    """
    Calculate Nei's genetic distance between populations.

    Args:
        pop1_freqs: Allele frequencies in population 1
        pop2_freqs: Allele frequencies in population 2

    Returns:
        Nei's distance
    """
    # Get common alleles
    alleles = set(pop1_freqs.keys()) & set(pop2_freqs.keys())

    if len(alleles) == 0:
        return float("inf")

    # Calculate J (identity)
    j = 0.0

    for allele in alleles:
        p = pop1_freqs[allele]
        q = pop2_freqs[allele]
        j += p * q

    # Calculate D (distance)
    if j > 0:
        d = -math.log(j)
    else:
        d = float("inf")

    return d


def linkage_disequilibrium(haplotypes: dict[str, int]) -> tuple[float, float, float]:
    """
    Calculate linkage disequilibrium statistics.

    Returns D, D', and r² for two biallelic loci.

    Args:
        haplotypes: Dictionary mapping haplotype strings to counts (e.g., 'AB': 10)

    Returns:
        Tuple of (D, Dprime, r_squared)
    """
    total = sum(haplotypes.values())

    if total == 0:
        raise ValueError("No haplotypes provided")

    # Extract haplotype frequencies
    freq_ab = haplotypes.get("AB", 0) / total
    freq_Ab = haplotypes.get("Ab", 0) / total
    freq_aB = haplotypes.get("aB", 0) / total
    freq_ab_complement = haplotypes.get("ab", 0) / total

    # Allele frequencies
    p_a = freq_ab + freq_Ab
    p_b = freq_ab + freq_aB

    # Calculate D
    d = freq_ab - (p_a * p_b)

    # Calculate D'
    if d > 0:
        d_max = min(p_a * (1.0 - p_b), (1.0 - p_a) * p_b)
    else:
        d_max = min(p_a * p_b, (1.0 - p_a) * (1.0 - p_b))

    d_prime = d / d_max if d_max > 0 else 0.0

    # Calculate r²
    if p_a > 0 and (1.0 - p_a) > 0 and p_b > 0 and (1.0 - p_b) > 0:
        r_squared = (d**2) / (p_a * (1.0 - p_a) * p_b * (1.0 - p_b))
    else:
        r_squared = 0.0

    return d, abs(d_prime), r_squared


def selection_coefficient(genotypes: dict[str, int], reference_allele: str = "A") -> float:
    """
    Estimate selection coefficient from genotype frequencies.

    Simple one-locus diploid selection model.

    Args:
        genotypes: Dictionary of genotype counts
        reference_allele: Reference allele for defining fitness

    Returns:
        Estimated selection coefficient (s)
    """
    freqs = allele_frequency(genotypes)

    if reference_allele not in freqs:
        raise ValueError(f"Reference allele {reference_allele} not found")

    # Simple estimate based on allele frequency change
    p = freqs.get(reference_allele, 0)

    if p <= 0 or p >= 1:
        return 0.0

    # Use average fitness decline estimate
    s = 1.0 - (p * (1.0 - p)) / (p**2 + 2 * p * (1.0 - p))

    return max(0.0, min(1.0, s))


def nucleotide_diversity(sequences: list[str]) -> tuple[float, int]:
    """
    Calculate nucleotide diversity (pi) from sequence sample.

    Args:
        sequences: List of aligned DNA sequences

    Returns:
        Tuple of (nucleotide_diversity, number_of_segregating_sites)
    """
    if len(sequences) < 2:
        raise ValueError("Need at least 2 sequences")

    seq_len = len(sequences[0])

    if not all(len(s) == seq_len for s in sequences):
        raise ValueError("All sequences must have equal length")

    total_pairwise_diffs = 0
    seg_sites = 0

    for pos in range(seq_len):
        alleles = [s[pos].upper() for s in sequences]

        # Check if segregating
        if len(set(alleles)) > 1:
            seg_sites += 1

            # Count pairwise differences
            for i in range(len(sequences)):
                for j in range(i + 1, len(sequences)):
                    if alleles[i] != alleles[j]:
                        total_pairwise_diffs += 1

    n = len(sequences)
    n_pairs = n * (n - 1) / 2.0

    pi = total_pairwise_diffs / n_pairs / seq_len if n_pairs > 0 else 0.0

    return pi, seg_sites
