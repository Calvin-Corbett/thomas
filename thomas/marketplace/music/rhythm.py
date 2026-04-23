"""Rhythm module - time signatures, beat subdivision, syncopation, swing, polyrhythm."""

from __future__ import annotations

from dataclasses import dataclass

from thomas.marketplace.music._types import TimeSignature

# ============================================================================
# Time Signature Analysis
# ============================================================================


def beats_per_measure(time_sig: TimeSignature) -> int:
    """Get the number of beats in a measure.

    Args:
        time_sig: Time signature.

    Returns:
        Number of beats per measure.

    Example:
        >>> ts = TimeSignature(4, 4)
        >>> beats_per_measure(ts)
        4
    """
    return time_sig.numerator


def beat_unit_value(time_sig: TimeSignature) -> float:
    """Get the value of one beat unit in whole notes.

    Args:
        time_sig: Time signature.

    Returns:
        Beat unit value (4.0 for quarter note, 2.0 for half note, etc.).
    """
    return 4.0 / time_sig.denominator


def measure_duration(time_sig: TimeSignature) -> float:
    """Get the duration of a full measure in whole notes.

    Args:
        time_sig: Time signature.

    Returns:
        Measure duration in whole notes.

    Example:
        >>> ts = TimeSignature(3, 4)
        >>> measure_duration(ts)
        0.75
    """
    return beat_unit_value(time_sig) * beats_per_measure(time_sig)


def is_compound_meter(time_sig: TimeSignature) -> bool:
    """Check if time signature is compound meter (beats divide into three).

    Args:
        time_sig: Time signature.

    Returns:
        True if compound meter.

    Example:
        >>> ts = TimeSignature(6, 8)
        >>> is_compound_meter(ts)
        True
    """
    return time_sig.numerator % 3 == 0 and time_sig.numerator > 3


def is_simple_meter(time_sig: TimeSignature) -> bool:
    """Check if time signature is simple meter (beats divide into two).

    Args:
        time_sig: Time signature.

    Returns:
        True if simple meter.
    """
    return not is_compound_meter(time_sig)


# ============================================================================
# Beat Subdivision
# ============================================================================


@dataclass
class NoteValue:
    """Represents a note value with duration."""

    name: str
    value: float  # In whole notes
    dots: int = 0

    def get_duration(self) -> float:
        """Get total duration including dots."""
        duration = self.value
        current = self.value / 2.0
        for _ in range(self.dots):
            duration += current
            current /= 2.0
        return duration


def get_subdivisions(time_sig: TimeSignature) -> list[NoteValue]:
    """Get standard beat subdivisions for a time signature.

    Args:
        time_sig: Time signature.

    Returns:
        List of note values that fit within a beat.

    Example:
        >>> ts = TimeSignature(4, 4)
        >>> subs = get_subdivisions(ts)
        >>> len(subs)
        4
    """
    beat_value = beat_unit_value(time_sig)

    subdivisions: list[NoteValue] = []

    if is_simple_meter(time_sig):
        subdivisions = [
            NoteValue("whole", beat_value),
            NoteValue("half", beat_value / 2),
            NoteValue("quarter", beat_value / 4),
            NoteValue("eighth", beat_value / 8),
            NoteValue("sixteenth", beat_value / 16),
        ]
    else:
        subdivisions = [
            NoteValue("dotted", beat_value),
            NoteValue("quarter", beat_value / 3),
            NoteValue("eighth", beat_value / 6),
            NoteValue("sixteenth", beat_value / 12),
        ]

    return subdivisions


def get_beat_grid(time_sig: TimeSignature, subdivision_level: int = 4) -> list[float]:
    """Generate beat grid (onset times) for a measure.

    Args:
        time_sig: Time signature.
        subdivision_level: Number of subdivisions per beat (4=sixteenths).

    Returns:
        List of beat onset times in whole notes.

    Example:
        >>> ts = TimeSignature(4, 4)
        >>> grid = get_beat_grid(ts, 4)
        >>> len(grid)
        17
    """
    grid: list[float] = []
    beat_value = beat_unit_value(time_sig)
    num_beats = beats_per_measure(time_sig)

    step = beat_value / subdivision_level

    for beat in range(num_beats):
        for subdivision in range(subdivision_level + 1):
            grid.append(beat * beat_value + subdivision * step)

    return list(set(sorted(grid)))


# ============================================================================
# Syncopation Detection
# ============================================================================


def is_syncopated(onset: float, time_sig: TimeSignature) -> bool:
    """Check if a note onset is syncopated.

    A note is syncopated if it starts on a weak beat or subdivision.

    Args:
        onset: Onset time in whole notes within a measure.
        time_sig: Time signature.

    Returns:
        True if onset is syncopated.
    """
    beat_value = beat_unit_value(time_sig)

    beat_position = onset / beat_value
    beat_number = int(beat_position)

    if beat_number == 0 or beat_number == beats_per_measure(time_sig) - 1:
        return False

    fractional_part = beat_position - beat_number

    if abs(fractional_part) < 0.01 or abs(fractional_part - 1.0) < 0.01:
        return False

    return True


def syncopation_level(onsets: list[float], time_sig: TimeSignature) -> float:
    """Calculate syncopation level of a rhythm (0.0 to 1.0).

    Args:
        onsets: List of note onsets in whole notes.
        time_sig: Time signature.

    Returns:
        Syncopation level (0.0 = no syncopation, 1.0 = highly syncopated).
    """
    if not onsets:
        return 0.0

    syncopated_count = sum(1 for onset in onsets if is_syncopated(onset, time_sig))

    return syncopated_count / len(onsets)


# ============================================================================
# Swing Quantization
# ============================================================================


def apply_swing(onset: float, time_sig: TimeSignature, swing_ratio: float = 0.6) -> float:
    """Apply swing (triplet) feel to an onset.

    Swing is typically expressed as a ratio (0.5 = straight, 0.666... = full triplet).

    Args:
        onset: Original onset time in whole notes.
        time_sig: Time signature.
        swing_ratio: Swing ratio (0.5 to 0.7, where 0.5 is straight).

    Returns:
        Swung onset time.

    Example:
        >>> ts = TimeSignature(4, 4)
        >>> swung = apply_swing(0.25, ts, 0.666)
        >>> swung > 0.25
        True
    """
    beat_value = beat_unit_value(time_sig)
    triplet_value = beat_value / 3.0

    beat_position = onset / beat_value
    beat_number = int(beat_position)
    fractional = beat_position - beat_number

    if fractional < 0.5:
        return beat_number * beat_value + triplet_value * swing_ratio
    else:
        return beat_number * beat_value + triplet_value * (2 - swing_ratio)


def is_straight_rhythm(onsets: list[float], threshold: float = 0.05) -> bool:
    """Check if a rhythm is straight (not swung).

    Args:
        onsets: List of onset times.
        threshold: Tolerance for deviation.

    Returns:
        True if rhythm appears straight.
    """
    if len(onsets) < 2:
        return True

    intervals = []
    for i in range(len(onsets) - 1):
        intervals.append(onsets[i + 1] - onsets[i])

    intervals.sort()

    if len(intervals) > 1:
        smallest = intervals[0]
        expected_swing = smallest * 1.5

        for interval in intervals[1:]:
            if abs(interval - expected_swing) > threshold:
                continue

        return False

    return True


# ============================================================================
# Polyrhythm
# ============================================================================


def generate_polyrhythm(notes_first: int, notes_second: int, duration: float = 1.0) -> tuple[list[float], list[float]]:
    """Generate two polyrhythmic note sequences (e.g., 3 against 2).

    Args:
        notes_first: Number of notes in first rhythm.
        notes_second: Number of notes in second rhythm.
        duration: Duration of the polyrhythm in whole notes.

    Returns:
        Tuple of (first_onsets, second_onsets).

    Example:
        >>> onsets1, onsets2 = generate_polyrhythm(3, 2, 1.0)
        >>> len(onsets1)
        3
        >>> len(onsets2)
        2
    """
    first_onsets = [i * duration / notes_first for i in range(notes_first)]
    second_onsets = [i * duration / notes_second for i in range(notes_second)]

    return (first_onsets, second_onsets)


def polyrhythm_alignment(first: list[float], second: list[float]) -> list[float]:
    """Find aligned onsets (when two polyrhythms coincide).

    Args:
        first: First rhythm onsets.
        second: Second rhythm onsets.

    Returns:
        List of aligned onsets.
    """
    aligned: list[float] = []
    tolerance = 0.001

    for f_onset in first:
        for s_onset in second:
            if abs(f_onset - s_onset) < tolerance:
                aligned.append(f_onset)
                break

    return sorted(list(set(aligned)))


# ============================================================================
# Groove Templates
# ============================================================================


@dataclass
class GroovePattern:
    """Represents a groove/rhythm pattern."""

    name: str
    time_signature: TimeSignature
    onsets: list[float]
    velocities: list[int] | None = None


def rock_groove() -> GroovePattern:
    """Create a basic rock groove pattern (4/4).

    Returns:
        Rock groove pattern.
    """
    ts = TimeSignature(4, 4)
    onsets = [0.0, 0.25, 0.5, 0.75, 1.0]
    velocities = [100, 80, 100, 70, 100]

    return GroovePattern("rock", ts, onsets, velocities)


def jazz_swing_groove() -> GroovePattern:
    """Create a jazz swing groove pattern (4/4).

    Returns:
        Jazz swing groove pattern.
    """
    ts = TimeSignature(4, 4)

    onsets = [0.0, 1.0 / 3.0, 0.5, 5.0 / 6.0, 1.0]
    velocities = [100, 70, 85, 75, 100]

    return GroovePattern("jazz_swing", ts, onsets, velocities)


def bossa_nova_groove() -> GroovePattern:
    """Create a bossa nova groove pattern (2/4).

    Returns:
        Bossa nova groove pattern.
    """
    ts = TimeSignature(2, 4)
    onsets = [0.0, 0.375, 0.5, 0.75, 1.0]
    velocities = [100, 60, 80, 70, 100]

    return GroovePattern("bossa_nova", ts, onsets, velocities)


def waltz_groove() -> GroovePattern:
    """Create a waltz groove pattern (3/4).

    Returns:
        Waltz groove pattern.
    """
    ts = TimeSignature(3, 4)
    onsets = [0.0, 0.25, 0.5]
    velocities = [100, 70, 80]

    return GroovePattern("waltz", ts, onsets, velocities)


# ============================================================================
# Tempo Estimation
# ============================================================================


def estimate_tempo(note_onsets: list[float], time_signature: TimeSignature | None = None) -> tuple[float, float]:
    """Estimate tempo from note onsets.

    Uses autocorrelation-like analysis of inter-onset intervals.

    Args:
        note_onsets: List of note onset times in seconds.
        time_signature: Optional time signature for beat alignment.

    Returns:
        Tuple of (tempo_bpm, confidence_0_to_1).

    Example:
        >>> onsets = [0.0, 0.5, 1.0, 1.5, 2.0]
        >>> bpm, confidence = estimate_tempo(onsets)
        >>> 100 < bpm < 200
        True
    """
    if len(note_onsets) < 2:
        return (120.0, 0.0)

    intervals = []
    for i in range(len(note_onsets) - 1):
        intervals.append(note_onsets[i + 1] - note_onsets[i])

    intervals.sort()

    median_interval = intervals[len(intervals) // 2]

    if median_interval <= 0:
        return (120.0, 0.0)

    estimated_bpm = 60.0 / median_interval

    confidence = 0.7
    if time_signature:
        expected_beat_value = 60.0 / estimated_bpm
        expected_interval = expected_beat_value / time_signature.denominator * 4

        if abs(median_interval - expected_interval) < 0.01 * expected_interval:
            confidence = 0.95

    return (estimated_bpm, confidence)


def quantize_to_grid(onsets: list[float], grid: list[float], threshold: float = 0.05) -> list[float]:
    """Quantize onsets to nearest grid points.

    Args:
        onsets: List of onset times.
        grid: List of grid points.
        threshold: Maximum distance to snap to grid.

    Returns:
        List of quantized onsets.
    """
    quantized: list[float] = []

    for onset in onsets:
        closest_grid = min(grid, key=lambda g: abs(g - onset))

        if abs(closest_grid - onset) <= threshold:
            quantized.append(closest_grid)
        else:
            quantized.append(onset)

    return quantized
