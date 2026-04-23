"""
Protein analysis and characterization.

Provides methods for calculating protein properties including molecular weight,
isoelectric point, composition, hydrophobicity, and secondary structure prediction.
"""

from thomas.marketplace.bioinformatics._exceptions import InvalidSequenceError

# Amino acid molecular weights (monoisotopic, in Da)
AA_WEIGHTS: dict[str, float] = {
    "A": 71.037,
    "R": 156.101,
    "N": 114.043,
    "D": 115.027,
    "C": 103.009,
    "Q": 128.059,
    "E": 129.043,
    "G": 57.021,
    "H": 137.059,
    "I": 113.084,
    "L": 113.084,
    "K": 128.095,
    "M": 131.040,
    "F": 147.068,
    "P": 97.053,
    "S": 87.032,
    "T": 101.048,
    "W": 186.079,
    "Y": 163.063,
    "V": 99.068,
}

# pKa values for Henderson-Hasselbalch equation
PKA_VALUES: dict[str, tuple[float, float, float | None]] = {
    "A": (2.34, 9.60, None),
    "R": (2.18, 9.09, 12.48),
    "N": (2.18, 8.80, None),
    "D": (2.10, 9.60, 3.86),
    "C": (1.96, 10.28, 8.18),
    "Q": (2.17, 9.13, None),
    "E": (2.19, 9.67, 4.25),
    "G": (2.34, 9.60, None),
    "H": (1.82, 9.17, 6.10),
    "I": (2.32, 9.76, None),
    "L": (2.36, 9.60, None),
    "K": (2.18, 8.95, 10.53),
    "M": (2.28, 9.21, None),
    "F": (2.58, 9.24, None),
    "P": (1.99, 10.60, None),
    "S": (2.21, 9.15, None),
    "T": (2.34, 9.62, None),
    "W": (2.83, 9.39, None),
    "Y": (2.20, 9.11, 10.07),
    "V": (2.32, 9.62, None),
}

# Kyte-Doolittle hydrophobicity scale
HYDROPHOBICITY: dict[str, float] = {
    "A": 1.8,
    "R": -4.5,
    "N": -3.5,
    "D": -3.5,
    "C": 2.5,
    "Q": -3.5,
    "E": -3.5,
    "G": -0.4,
    "H": -3.2,
    "I": 4.5,
    "L": 3.8,
    "K": -3.9,
    "M": 1.9,
    "F": 2.8,
    "P": -1.6,
    "S": -0.8,
    "T": -0.7,
    "W": -0.9,
    "Y": -1.3,
    "V": 4.2,
}

# Secondary structure propensities (Chou-Fasman)
CHOU_FASMAN: dict[str, tuple[float, float, float]] = {
    "A": (1.42, 0.83, 0.66),  # H, E, C
    "R": (0.98, 0.93, 0.95),
    "N": (0.67, 0.89, 1.56),
    "D": (1.01, 0.54, 1.30),
    "C": (0.70, 1.19, 1.70),
    "Q": (1.11, 1.10, 0.98),
    "E": (1.51, 0.37, 0.74),
    "G": (0.57, 0.75, 1.57),
    "H": (1.00, 0.87, 0.95),
    "I": (1.08, 1.60, 0.47),
    "L": (1.21, 1.30, 0.59),
    "K": (1.16, 0.74, 1.01),
    "M": (1.45, 1.05, 0.60),
    "F": (1.13, 1.38, 0.60),
    "P": (0.57, 0.55, 1.52),
    "S": (0.77, 0.75, 1.43),
    "T": (0.83, 1.08, 1.27),
    "W": (1.08, 1.37, 0.96),
    "Y": (0.69, 1.47, 1.14),
    "V": (1.06, 1.70, 0.50),
}

# Extinction coefficients (M^-1 cm^-1)
EXTINCTION_COEFFICIENTS: dict[str, tuple[int, int]] = {
    "C": (120, 250),  # (reduced, disulfide)
    "W": (5500, 5500),
    "Y": (1490, 1490),
}


def molecular_weight(sequence: str) -> float:
    """
    Calculate protein molecular weight.

    Args:
        sequence: Amino acid sequence

    Returns:
        Molecular weight in Da
    """
    sequence = sequence.upper()
    weight = 18.015  # Water molecule

    for aa in sequence:
        if aa not in AA_WEIGHTS:
            raise InvalidSequenceError(f"Unknown amino acid: {aa}")
        weight += AA_WEIGHTS[aa]

    return weight


def isoelectric_point(sequence: str, ph_range: tuple[float, float] = (0.0, 14.0)) -> float:
    """
    Calculate protein isoelectric point (pI).

    Uses Henderson-Hasselbalch equation to find pH where net charge is zero.

    Args:
        sequence: Amino acid sequence
        ph_range: pH range to search

    Returns:
        Isoelectric point (pH)
    """
    sequence = sequence.upper()

    def net_charge(pH: float) -> float:
        charge = 0.0

        # N-terminus
        pka = 8.0
        charge += 1.0 / (1.0 + 10.0 ** (pka - pH))

        # C-terminus
        pka = 3.1
        charge -= 1.0 / (1.0 + 10.0 ** (pH - pka))

        # Amino acids
        for aa in sequence:
            if aa not in PKA_VALUES:
                continue

            _, pka_n, pka_side = PKA_VALUES[aa]

            if aa in "DEKRY":
                if pka_side:
                    charge -= 1.0 / (1.0 + 10.0 ** (pka_side - pH))
                else:
                    charge -= 1.0 / (1.0 + 10.0 ** (pka_n - pH))
            elif aa in "HCY":
                if pka_side:
                    charge += 1.0 / (1.0 + 10.0 ** (pH - pka_side))

        return charge

    # Binary search for pI
    low, high = ph_range
    epsilon = 0.0001

    for _ in range(100):
        mid = (low + high) / 2.0
        charge = net_charge(mid)

        if abs(charge) < epsilon:
            return mid

        if charge > 0:
            low = mid
        else:
            high = mid

    return (low + high) / 2.0


def amino_acid_composition(sequence: str) -> dict[str, float]:
    """
    Calculate amino acid composition.

    Args:
        sequence: Amino acid sequence

    Returns:
        Dictionary of amino acid percentages
    """
    sequence = sequence.upper()

    if not sequence:
        raise InvalidSequenceError("Sequence cannot be empty")

    composition: dict[str, float] = {}
    total = len(sequence)

    for aa in set(sequence):
        count = sequence.count(aa)
        composition[aa] = (count / total) * 100.0

    return composition


def hydrophobicity_plot(sequence: str, window_size: int = 9) -> list[float]:
    """
    Calculate Kyte-Doolittle hydrophobicity plot.

    Uses sliding window average of hydrophobicity values.

    Args:
        sequence: Amino acid sequence
        window_size: Size of sliding window

    Returns:
        List of hydrophobicity values
    """
    sequence = sequence.upper()

    if window_size > len(sequence):
        raise InvalidSequenceError("Window size larger than sequence")

    if window_size % 2 == 0:
        window_size += 1

    hydro: list[float] = []
    offset = window_size // 2

    for i in range(len(sequence)):
        start = max(0, i - offset)
        end = min(len(sequence), i + offset + 1)

        window = sequence[start:end]
        avg_hydro = sum(HYDROPHOBICITY.get(aa, 0) for aa in window) / len(window)
        hydro.append(avg_hydro)

    return hydro


def secondary_structure_prediction(sequence: str) -> tuple[str, list[str]]:
    """
    Simple secondary structure prediction using Chou-Fasman rules.

    Returns propensities for each position.

    Args:
        sequence: Amino acid sequence

    Returns:
        Tuple of (assignment_string, propensity_list)
    """
    sequence = sequence.upper()

    if not all(aa in CHOU_FASMAN for aa in sequence):
        raise InvalidSequenceError("Sequence contains unknown amino acids")

    window = 6
    half_window = window // 2

    propensities = []
    assignment = []

    for i in range(len(sequence)):
        start = max(0, i - half_window)
        end = min(len(sequence), i + half_window + 1)

        h_sum = e_sum = c_sum = 0.0
        count = 0

        for j in range(start, end):
            aa = sequence[j]
            if aa in CHOU_FASMAN:
                h, e, c = CHOU_FASMAN[aa]
                h_sum += h
                e_sum += e
                c_sum += c
                count += 1

        if count > 0:
            h_avg = h_sum / count
            e_avg = e_sum / count
            c_avg = c_sum / count

            if h_avg > 1.05:
                assign = "H"
            elif e_avg > 1.05:
                assign = "E"
            else:
                assign = "C"

            propensities.append((h_avg, e_avg, c_avg))
            assignment.append(assign)
        else:
            propensities.append((0.0, 0.0, 0.0))
            assignment.append("C")

    return "".join(assignment), [str(p) for p in propensities]


def extinction_coefficient(sequence: str, reduced: bool = False) -> float:
    """
    Calculate extinction coefficient at 280 nm.

    Args:
        sequence: Amino acid sequence
        reduced: If True, assumes free cysteines; if False, disulfide bonds

    Returns:
        Extinction coefficient in M^-1 cm^-1
    """
    sequence = sequence.upper()

    ec = 0.0

    for aa in sequence:
        if aa == "C":
            idx = 0 if reduced else 1
            ec += EXTINCTION_COEFFICIENTS["C"][idx]
        elif aa in EXTINCTION_COEFFICIENTS:
            ec += EXTINCTION_COEFFICIENTS[aa][0]

    return ec


def protein_domains(sequence: str, patterns: dict[str, str] | None = None) -> dict[str, list[tuple[int, int]]]:
    """
    Simple protein domain detection using pattern matching.

    Args:
        sequence: Amino acid sequence
        patterns: Dictionary of domain name -> regex pattern

    Returns:
        Dictionary of domain name -> list of (start, end) positions
    """
    import re

    sequence = sequence.upper()
    domains: dict[str, list[tuple[int, int]]] = {}

    if patterns is None:
        patterns = {
            "NLS": "K{4}",
            "Helix": "[AILMFV]{6,}",
        }

    for domain_name, pattern in patterns.items():
        matches = []
        try:
            for match in re.finditer(pattern, sequence):
                matches.append((match.start(), match.end()))
        except re.error:
            pass

        if matches:
            domains[domain_name] = matches

    return domains
