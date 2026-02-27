"""Music analysis - pitch class sets, form, key estimation, beat tracking."""

from __future__ import annotations

import math
from collections import defaultdict

from thomas.music._types import Note

# ============================================================================
# Pitch Class Set Theory
# ============================================================================


def pitch_class_set(notes: list[Note]) -> set[int]:
    """Extract pitch class set from notes (ignoring octave).

    Args:
        notes: List of notes.

    Returns:
        Set of pitch classes (0-11).

    Example:
        >>> notes = [Note.parse("C4"), Note.parse("E4"), Note.parse("G4")]
        >>> pcs = pitch_class_set(notes)
        >>> pcs == {0, 4, 7}
        True
    """
    return set(note.to_midi_number() % 12 for note in notes)


def pcs_normal_form(pcs: set[int]) -> tuple[int, ...]:
    """Get normal form of a pitch class set.

    Normal form is the most compact rotation.

    Args:
        pcs: Pitch class set.

    Returns:
        Tuple representing normal form.
    """
    if not pcs:
        return ()

    sorted_pcs = sorted(pcs)
    rotations: list[tuple[int, ...]] = []

    for i in range(len(sorted_pcs)):
        # Keep each rotation in ascending order by lifting wrapped values by +12.
        lifted = sorted_pcs[i:] + [pc + 12 for pc in sorted_pcs[:i]]
        rotations.append(tuple(lifted))

    best = min(rotations, key=lambda r: (r[-1] - r[0], r))
    return tuple(pc % 12 for pc in best)


def pcs_prime_form(pcs: set[int]) -> tuple[int, ...]:
    """Get prime form of a pitch class set.

    Prime form is most compact form considering inversions.

    Args:
        pcs: Pitch class set.

    Returns:
        Tuple representing prime form.
    """
    normal = pcs_normal_form(pcs)

    inverted = set((12 - pc) % 12 for pc in pcs)
    inverted_normal = pcs_normal_form(inverted)

    if len(inverted_normal) < len(normal):
        return inverted_normal

    if inverted_normal[0] < normal[0]:
        return inverted_normal

    return normal


def interval_vector(pcs: set[int]) -> tuple[int, ...]:
    """Calculate interval vector of a pitch class set.

    Counts occurrences of each interval class (1-6 semitones).

    Args:
        pcs: Pitch class set.

    Returns:
        Tuple of 6 integers (interval class 1 through 6).

    Example:
        >>> pcs = {0, 4, 7}
        >>> iv = interval_vector(pcs)
        >>> iv
        (0, 0, 1, 1, 1, 0)
    """
    vector = [0, 0, 0, 0, 0, 0]

    sorted_pcs = sorted(pcs)

    for i in range(len(sorted_pcs)):
        for j in range(i + 1, len(sorted_pcs)):
            pc1 = sorted_pcs[i]
            pc2 = sorted_pcs[j]

            interval = (pc2 - pc1) % 12
            interval_class = min(interval, 12 - interval)

            if 1 <= interval_class <= 6:
                vector[interval_class - 1] += 1

    return tuple(vector)


# ============================================================================
# Form Analysis
# ============================================================================


def detect_repeated_sections(melody: list[Note], min_length: int = 2) -> dict[str, list[int]]:
    """Detect repeated sections in a melody.

    Args:
        melody: Melody to analyze.
        min_length: Minimum section length.

    Returns:
        Dictionary mapping section signature to list of start indices.
    """
    repeated_sections: dict[str, list[int]] = defaultdict(list)

    for start in range(len(melody) - min_length):
        for length in range(min_length, len(melody) - start + 1):
            section = tuple(n.to_midi_number() % 12 for n in melody[start : start + length])
            section_key = str(section)

            repeated_sections[section_key].append(start)

    non_empty = {k: v for k, v in repeated_sections.items() if len(v) > 1}

    return non_empty


def analyze_form(melody: list[Note]) -> str:
    """Analyze overall form of a melody (e.g., ABA, AABB).

    Args:
        melody: Melody to analyze.

    Returns:
        Form string (e.g., 'ABA', 'AABB', 'ABAC').
    """
    if len(melody) < 4:
        return "A"

    quarter = len(melody) // 4
    sections = [tuple(n.to_midi_number() % 12 for n in melody[i * quarter : (i + 1) * quarter]) for i in range(4)]

    label_for_section: dict[tuple[int, ...], str] = {}
    next_label_ord = ord("A")
    form_parts: list[str] = []

    for section in sections:
        if section not in label_for_section:
            label_for_section[section] = chr(next_label_ord)
            next_label_ord += 1
        form_parts.append(label_for_section[section])

    return "".join(form_parts)


# ============================================================================
# Key Estimation
# ============================================================================


KRUMHANSL_PROFILES = {
    "C_major": [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
    "C_minor": [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
}


def pitch_class_distribution(notes: list[Note]) -> list[float]:
    """Calculate pitch class distribution of notes.

    Args:
        notes: List of notes.

    Returns:
        List of 12 values (one per pitch class).
    """
    distribution = [0.0] * 12

    for note in notes:
        pc = note.to_midi_number() % 12
        distribution[pc] += 1.0

    total = sum(distribution)
    if total > 0:
        distribution = [x / total for x in distribution]

    return distribution


def estimate_key(notes: list[Note]) -> tuple[str, float]:
    """Estimate the key of a note sequence using Krumhansl-Schmuckler algorithm.

    Args:
        notes: List of notes.

    Returns:
        Tuple of (key_name, confidence_0_to_1).

    Example:
        >>> c_major = [Note.parse(f"{n}4") for n in ["C", "D", "E", "F", "G", "A", "B"]]
        >>> key, confidence = estimate_key(c_major)
        >>> key.startswith("C")
        True
    """
    if not notes:
        return ("Unknown", 0.0)

    pcd = pitch_class_distribution(notes)

    best_key = "C_major"
    best_correlation = -1.0

    for key_name, profile in KRUMHANSL_PROFILES.items():
        correlation = sum(p * d for p, d in zip(profile, pcd)) / (
            math.sqrt(sum(x**2 for x in profile)) * math.sqrt(sum(x**2 for x in pcd)) + 1e-6
        )

        if correlation > best_correlation:
            best_correlation = correlation
            best_key = key_name

    key_name = best_key.replace("_", " ")
    confidence = max(0.0, min(1.0, (best_correlation + 1) / 2))

    return (key_name, confidence)


# ============================================================================
# Beat Tracking
# ============================================================================


def onset_detection(notes: list[Note], onsets: list[float]) -> list[float]:
    """Detect note onsets from time values.

    Args:
        notes: List of notes.
        onsets: List of onset times in seconds.

    Returns:
        Filtered list of significant onsets.
    """
    if not onsets:
        return []

    significant_onsets = []
    min_gap = 0.05

    for onset in sorted(set(onsets)):
        if not significant_onsets or (onset - significant_onsets[-1] > min_gap):
            significant_onsets.append(onset)

    return significant_onsets


def beat_period_autocorrelation(onsets: list[float], min_bpm: float = 40, max_bpm: float = 240) -> float:
    """Estimate beat period using autocorrelation of onsets.

    Args:
        onsets: List of onset times in seconds.
        min_bpm: Minimum BPM to search.
        max_bpm: Maximum BPM to search.

    Returns:
        Estimated beat period in seconds.
    """
    if len(onsets) < 2:
        return 0.5

    min_period = 60.0 / max_bpm
    max_period = 60.0 / min_bpm

    best_period = min_period
    best_score = 0.0

    for period in [min_period + i * 0.01 for i in range(int((max_period - min_period) / 0.01))]:
        score = 0.0

        for onset in onsets:
            beat_aligned_distance = min(abs(onset % period - 0), abs(onset % period - period))

            if beat_aligned_distance < 0.05:
                score += 1.0

        if score > best_score:
            best_score = score
            best_period = period

    return best_period


# ============================================================================
# Chord Recognition
# ============================================================================


def recognize_chord_from_notes(notes: list[Note]) -> tuple[str, str] | None:
    """Identify chord from notes.

    Args:
        notes: List of notes (typically 3-7).

    Returns:
        Tuple of (root_note_string, chord_quality_string) or None.
    """
    if not notes:
        return None

    pcs = pitch_class_set(notes)

    if len(pcs) < 3:
        return None

    chord_signatures = {
        (0, 4, 7): "major",
        (0, 3, 7): "minor",
        (0, 3, 6): "diminished",
        (0, 4, 8): "augmented",
        (0, 4, 7, 10): "dominant7",
        (0, 4, 7, 11): "major7",
        (0, 3, 7, 10): "minor7",
        (0, 3, 6, 9): "diminished7",
        (0, 2, 7): "sus2",
        (0, 5, 7): "sus4",
    }

    pc_to_name = {
        0: "C",
        1: "C#",
        2: "D",
        3: "D#",
        4: "E",
        5: "F",
        6: "F#",
        7: "G",
        8: "G#",
        9: "A",
        10: "A#",
        11: "B",
    }

    for root_pc in sorted(pcs):
        intervals_from_root = {(pc - root_pc) % 12 for pc in pcs}
        for signature, quality in chord_signatures.items():
            if all(interval in intervals_from_root for interval in signature):
                return (pc_to_name[root_pc % 12], quality)

    return None


# ============================================================================
# Similarity Metrics
# ============================================================================


def pitch_class_set_similarity(pcs1: set[int], pcs2: set[int]) -> float:
    """Calculate similarity between two pitch class sets.

    Uses Jaccard similarity.

    Args:
        pcs1: First pitch class set.
        pcs2: Second pitch class set.

    Returns:
        Similarity score (0.0 to 1.0).
    """
    if not pcs1 and not pcs2:
        return 1.0

    if not pcs1 or not pcs2:
        return 0.0

    intersection = len(pcs1 & pcs2)
    union = len(pcs1 | pcs2)

    return intersection / union if union > 0 else 0.0


def note_sequence_similarity(seq1: list[Note], seq2: list[Note]) -> float:
    """Calculate similarity between two note sequences.

    Args:
        seq1: First sequence.
        seq2: Second sequence.

    Returns:
        Similarity score (0.0 to 1.0).
    """
    if len(seq1) != len(seq2):
        return 0.0

    if not seq1:
        return 1.0

    matching = sum(1 for n1, n2 in zip(seq1, seq2) if n1.to_midi_number() == n2.to_midi_number())

    return matching / len(seq1)
