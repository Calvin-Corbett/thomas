"""Melody generation and analysis - contour, motifs, counterpoint, Markov chains."""

from __future__ import annotations

import enum
import random
from collections import defaultdict
from dataclasses import dataclass

from thomas.marketplace.music import theory
from thomas.marketplace.music._exceptions import InvalidNoteError
from thomas.marketplace.music._types import Note, Scale

# ============================================================================
# Melodic Contour
# ============================================================================


class ContourType(enum.Enum):
    """Types of melodic contours."""

    ASCENDING = "ascending"
    DESCENDING = "descending"
    ARCH = "arch"
    INVERTED_ARCH = "inverted_arch"
    PEAK = "peak"
    VALLEY = "valley"
    PLATEAU = "plateau"
    RANDOM = "random"


def analyze_contour(notes: list[Note]) -> ContourType:
    """Analyze melodic contour of a note sequence.

    Args:
        notes: List of notes.

    Returns:
        ContourType describing the overall shape.
    """
    if len(notes) < 2:
        return ContourType.PLATEAU

    midis = [n.to_midi_number() for n in notes]

    ascending_moves = sum(1 for i in range(len(midis) - 1) if midis[i + 1] > midis[i])
    descending_moves = sum(1 for i in range(len(midis) - 1) if midis[i + 1] < midis[i])
    plateau_moves = sum(1 for i in range(len(midis) - 1) if midis[i + 1] == midis[i])

    total_moves = len(midis) - 1

    if ascending_moves > descending_moves and descending_moves == 0:
        return ContourType.ASCENDING
    elif descending_moves > ascending_moves and ascending_moves == 0:
        return ContourType.DESCENDING
    elif plateau_moves == total_moves:
        return ContourType.PLATEAU

    mid_point = len(midis) // 2
    first_half_max = max(midis[:mid_point]) if mid_point > 0 else midis[0]
    second_half_max = max(midis[mid_point:])
    overall_max = max(midis)
    overall_min = min(midis)

    if first_half_max < second_half_max and second_half_max == overall_max:
        return ContourType.ARCH
    elif first_half_max > second_half_max and first_half_max == overall_max:
        return ContourType.INVERTED_ARCH

    max_idx = midis.index(overall_max)
    min_idx = midis.index(overall_min)

    if max_idx < len(midis) // 3:
        return ContourType.PEAK
    elif min_idx < len(midis) // 3:
        return ContourType.VALLEY

    return ContourType.RANDOM


def contour_direction(note1: Note, note2: Note) -> int:
    """Get direction between two notes.

    Args:
        note1: First note.
        note2: Second note.

    Returns:
        1 if ascending, -1 if descending, 0 if same.
    """
    midi1 = note1.to_midi_number()
    midi2 = note2.to_midi_number()

    if midi2 > midi1:
        return 1
    elif midi2 < midi1:
        return -1
    else:
        return 0


# ============================================================================
# Motif Development
# ============================================================================


def repeat_motif(motif: list[Note], times: int) -> list[Note]:
    """Repeat a motif multiple times.

    Args:
        motif: Motif to repeat.
        times: Number of repetitions.

    Returns:
        Repeated motif sequence.
    """
    return motif * times


def sequence_motif(motif: list[Note], times: int, transposition_steps: int = 2) -> list[Note]:
    """Create a sequence (repetition at different pitch levels).

    Args:
        motif: Motif to sequence.
        times: Number of repetitions.
        transposition_steps: Semitones to transpose each time.

    Returns:
        Sequenced motif.
    """
    result: list[Note] = []

    for i in range(times):
        for note in motif:
            transposed = theory.transpose(note, i * transposition_steps)
            result.append(transposed)

    return result


def invert_motif(motif: list[Note], axis: Note | None = None) -> list[Note]:
    """Create an inversion of a motif (flip melodic intervals).

    Args:
        motif: Motif to invert.
        axis: Axis note for inversion (default: first note).

    Returns:
        Inverted motif.
    """
    if not motif:
        return []

    if axis is None:
        axis = motif[0]

    axis_midi = axis.to_midi_number()
    inverted: list[Note] = []

    for note in motif:
        midi = note.to_midi_number()
        inverted_midi = 2 * axis_midi - midi

        if 0 <= inverted_midi <= 127:
            inverted.append(Note.from_midi_number(inverted_midi))
        else:
            inverted.append(note)

    return inverted


def retrograde_motif(motif: list[Note]) -> list[Note]:
    """Create retrograde (reverse) of a motif.

    Args:
        motif: Motif to reverse.

    Returns:
        Retrograde motif.
    """
    return list(reversed(motif))


def augment_motif(motif: list[Note], factor: float = 2.0) -> list[Note]:
    """Augment motif (increase intervals).

    This multiplies interval semitones by a factor.

    Args:
        motif: Motif to augment.
        factor: Augmentation factor.

    Returns:
        Augmented motif.
    """
    if not motif or len(motif) < 2:
        return motif

    motif[0].to_midi_number()
    augmented: list[Note] = [motif[0]]

    for i in range(1, len(motif)):
        prev_midi = motif[i - 1].to_midi_number()
        curr_midi = motif[i].to_midi_number()

        interval = curr_midi - prev_midi
        augmented_interval = int(interval * factor)

        new_midi = augmented[-1].to_midi_number() + augmented_interval

        if 0 <= new_midi <= 127:
            augmented.append(Note.from_midi_number(new_midi))
        else:
            augmented.append(motif[i])

    return augmented


def diminish_motif(motif: list[Note], factor: float = 0.5) -> list[Note]:
    """Diminish motif (decrease intervals).

    Args:
        motif: Motif to diminish.
        factor: Diminution factor.

    Returns:
        Diminished motif.
    """
    return augment_motif(motif, factor)


# ============================================================================
# Melodic Tension
# ============================================================================


def melodic_tension(note: Note, tonic: Note, scale: Scale) -> float:
    """Calculate melodic tension of a note.

    Tension increases with distance from tonic and dissonance.

    Args:
        note: Note to analyze.
        tonic: Tonic note.
        scale: Scale context.

    Returns:
        Tension value (0.0 to 1.0).
    """
    tonic_midi = tonic.to_midi_number()
    note_midi = note.to_midi_number()

    semitone_distance = abs((note_midi - tonic_midi) % 12)

    dissonance_values = {
        0: 0.0,
        1: 0.9,
        2: 0.4,
        3: 0.3,
        4: 0.1,
        5: 0.2,
        6: 0.8,
        7: 0.1,
        8: 0.3,
        9: 0.4,
        10: 0.6,
        11: 0.7,
    }

    return dissonance_values.get(semitone_distance, 0.5)


def resolution_tendency(note: Note, scale: Scale) -> Note | None:
    """Determine if a note has a natural resolution tendency in a scale.

    Args:
        note: Note to analyze.
        scale: Scale context.

    Returns:
        Suggested resolution note, or None if no tendency.
    """
    note_midi = note.to_midi_number() % 12

    tension = melodic_tension(note, scale.root, scale)

    if tension >= 0.7:
        up_semitone = (note_midi + 1) % 12
        down_semitone = (note_midi - 1) % 12

        for scale_note in scale.notes:
            if (scale_note.to_midi_number() % 12) == up_semitone or (scale_note.to_midi_number() % 12) == down_semitone:
                return scale_note

    return None


# ============================================================================
# Markov Chain Melody Generation
# ============================================================================


@dataclass
class MarkovChainMelody:
    """Markov chain model for melody generation."""

    transitions: dict[int, dict[int, int]] = None

    def __post_init__(self) -> None:
        """Initialize transitions."""
        if self.transitions is None:
            self.transitions = defaultdict(lambda: defaultdict(int))

    def train(self, melody: list[Note]) -> None:
        """Train Markov chain on a melody.

        Args:
            melody: List of notes to learn from.
        """
        midis = [n.to_midi_number() for n in melody]

        for i in range(len(midis) - 1):
            current = midis[i]
            next_note = midis[i + 1]

            self.transitions[current][next_note] += 1

    def generate(self, start_note: Note, length: int) -> list[Note]:
        """Generate a melody using the trained model.

        Args:
            start_note: Starting note.
            length: Number of notes to generate.

        Returns:
            Generated melody.
        """
        if not self.transitions:
            return [start_note] * length

        melody: list[Note] = [start_note]
        current_midi = start_note.to_midi_number()

        for _ in range(length - 1):
            if current_midi not in self.transitions:
                current_midi = random.choice(list(self.transitions.keys()))

            next_options = self.transitions[current_midi]

            if not next_options:
                current_midi = random.choice(list(self.transitions.keys()))
                next_options = self.transitions[current_midi]

            total_weight = sum(next_options.values())
            choice = random.uniform(0, total_weight)
            cumulative = 0

            selected_midi = current_midi
            for next_midi, count in next_options.items():
                cumulative += count
                if choice <= cumulative:
                    selected_midi = next_midi
                    break

            try:
                melody.append(Note.from_midi_number(selected_midi))
            except InvalidNoteError:
                continue

            current_midi = selected_midi

        return melody


# ============================================================================
# Counterpoint
# ============================================================================


def first_species_counterpoint(cantus_firmus: list[Note], scale: Scale) -> list[Note]:
    """Generate first species counterpoint against a cantus firmus.

    First species: all notes are consonant intervals.

    Args:
        cantus_firmus: Melodic line.
        scale: Scale context.

    Returns:
        Counterpoint melody.
    """
    counterpoint: list[Note] = []

    for cf_note in cantus_firmus:
        consonant_notes = []

        for scale_note in scale.notes:
            interval = theory.interval_from_notes(cf_note, scale_note)

            if theory.is_consonant_interval(interval):
                consonant_notes.append(scale_note)

        if consonant_notes:
            if counterpoint:
                closest = min(
                    consonant_notes,
                    key=lambda n: abs(n.to_midi_number() - counterpoint[-1].to_midi_number()),
                )
                counterpoint.append(closest)
            else:
                counterpoint.append(consonant_notes[0])
        else:
            if counterpoint:
                counterpoint.append(counterpoint[-1])
            else:
                counterpoint.append(cf_note)

    return counterpoint


def contrary_motion_preference(note1: Note, note2: Note) -> bool:
    """Check if notes move in contrary motion.

    Args:
        note1: First note.
        note2: Second note to compare.

    Returns:
        True if motion is contrary.
    """
    midi1 = note1.to_midi_number()
    midi2 = note2.to_midi_number()

    return (midi2 - midi1) * (midi2 - midi1) > 0


# ============================================================================
# Melody Similarity
# ============================================================================


def melodic_similarity(melody1: list[Note], melody2: list[Note]) -> float:
    """Calculate similarity between two melodies.

    Uses interval-based comparison.

    Args:
        melody1: First melody.
        melody2: Second melody.

    Returns:
        Similarity score (0.0 to 1.0).
    """
    if len(melody1) != len(melody2):
        return 0.0

    if not melody1:
        return 1.0

    intervals1 = []
    for i in range(len(melody1) - 1):
        interval = theory.semitones_between(melody1[i], melody1[i + 1])
        intervals1.append(interval)

    intervals2 = []
    for i in range(len(melody2) - 1):
        interval = theory.semitones_between(melody2[i], melody2[i + 1])
        intervals2.append(interval)

    if not intervals1:
        return 1.0

    matching_intervals = sum(1 for i1, i2 in zip(intervals1, intervals2) if i1 == i2)

    return matching_intervals / len(intervals1)
