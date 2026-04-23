"""Music theory module - intervals, scales, keys, frequencies, and transposition."""

from __future__ import annotations

import math

from thomas.marketplace.music._exceptions import InvalidIntervalError, InvalidNoteError, InvalidScaleError
from thomas.marketplace.music._types import (
    Accidental,
    Interval,
    IntervalQuality,
    Key,
    Note,
    NoteName,
    Pitch,
    Scale,
    ScaleType,
)

# ============================================================================
# Interval Calculations
# ============================================================================


def semitones_between(note1: Note, note2: Note) -> int:
    """Calculate semitones between two notes (ascending from note1 to note2).

    Args:
        note1: Starting note.
        note2: Ending note.

    Returns:
        Number of semitones (can be negative for descending intervals).

    Example:
        >>> semitones_between(Note(Pitch(NoteName.C), 4), Note(Pitch(NoteName.E), 4))
        4
    """
    midi1 = note1.to_midi_number()
    midi2 = note2.to_midi_number()
    return midi2 - midi1


def interval_from_notes(note1: Note, note2: Note) -> Interval:
    """Calculate interval between two notes.

    Args:
        note1: Starting note.
        note2: Ending note.

    Returns:
        Interval between the notes.

    Raises:
        InvalidIntervalError: If interval cannot be determined.
    """
    semitones = semitones_between(note1, note2) % 12

    quality_map: dict[int, tuple[IntervalQuality, str]] = {
        0: (IntervalQuality.PERFECT, "unison"),
        1: (IntervalQuality.MINOR, "second"),
        2: (IntervalQuality.MAJOR, "second"),
        3: (IntervalQuality.MINOR, "third"),
        4: (IntervalQuality.MAJOR, "third"),
        5: (IntervalQuality.PERFECT, "fourth"),
        6: (IntervalQuality.AUGMENTED, "fourth"),
        7: (IntervalQuality.PERFECT, "fifth"),
        8: (IntervalQuality.MINOR, "sixth"),
        9: (IntervalQuality.MAJOR, "sixth"),
        10: (IntervalQuality.MINOR, "seventh"),
        11: (IntervalQuality.MAJOR, "seventh"),
    }

    if semitones not in quality_map:
        raise InvalidIntervalError(f"Invalid interval: {semitones} semitones")

    quality, name = quality_map[semitones]
    return Interval(quality, semitones, name)


def interval_from_semitones(semitones: int, interval_name: str) -> Interval:
    """Create an interval from semitones and interval name.

    Args:
        semitones: Number of semitones.
        interval_name: Interval name (e.g., 'third', 'fifth').

    Returns:
        Interval object.

    Raises:
        InvalidIntervalError: If interval is invalid.
    """
    interval_qualities = {
        "unison": {0: IntervalQuality.PERFECT},
        "second": {
            0: IntervalQuality.DIMINISHED,
            1: IntervalQuality.MINOR,
            2: IntervalQuality.MAJOR,
            3: IntervalQuality.AUGMENTED,
        },
        "third": {
            2: IntervalQuality.DIMINISHED,
            3: IntervalQuality.MINOR,
            4: IntervalQuality.MAJOR,
            5: IntervalQuality.AUGMENTED,
        },
        "fourth": {4: IntervalQuality.DIMINISHED, 5: IntervalQuality.PERFECT, 6: IntervalQuality.AUGMENTED},
        "fifth": {6: IntervalQuality.DIMINISHED, 7: IntervalQuality.PERFECT, 8: IntervalQuality.AUGMENTED},
        "sixth": {
            7: IntervalQuality.DIMINISHED,
            8: IntervalQuality.MINOR,
            9: IntervalQuality.MAJOR,
            10: IntervalQuality.AUGMENTED,
        },
        "seventh": {
            9: IntervalQuality.DIMINISHED,
            10: IntervalQuality.MINOR,
            11: IntervalQuality.MAJOR,
            12: IntervalQuality.AUGMENTED,
        },
    }

    if interval_name not in interval_qualities:
        raise InvalidIntervalError(f"Unknown interval: {interval_name}")

    if semitones not in interval_qualities[interval_name]:
        raise InvalidIntervalError(f"Invalid interval: {semitones} semitones for {interval_name}")

    quality = interval_qualities[interval_name][semitones]
    return Interval(quality, semitones, interval_name)


# ============================================================================
# Scale Construction
# ============================================================================


def build_scale(root: Note, scale_type: ScaleType) -> Scale:
    """Build a scale starting from a root note.

    Args:
        root: Root note of the scale.
        scale_type: Type of scale to build.

    Returns:
        Scale object containing all notes in the scale.

    Raises:
        InvalidScaleError: If scale cannot be built.

    Example:
        >>> root = Note(Pitch(NoteName.C), 4)
        >>> scale = build_scale(root, ScaleType.MAJOR)
        >>> len(scale.notes)
        8  # C, D, E, F, G, A, B, C
    """
    intervals_map: dict[ScaleType, list[int]] = {
        ScaleType.MAJOR: [0, 2, 4, 5, 7, 9, 11, 12],
        ScaleType.NATURAL_MINOR: [0, 2, 3, 5, 7, 8, 10, 12],
        ScaleType.HARMONIC_MINOR: [0, 2, 3, 5, 7, 8, 11, 12],
        ScaleType.MELODIC_MINOR: [0, 2, 3, 5, 7, 9, 11, 12],
        ScaleType.PENTATONIC_MAJOR: [0, 2, 4, 7, 9, 12],
        ScaleType.PENTATONIC_MINOR: [0, 3, 5, 7, 10, 12],
        ScaleType.BLUES: [0, 3, 5, 6, 7, 10, 12],
        ScaleType.WHOLE_TONE: [0, 2, 4, 6, 8, 10],
        ScaleType.CHROMATIC: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        ScaleType.DORIAN: [0, 2, 3, 5, 7, 9, 10, 12],
        ScaleType.PHRYGIAN: [0, 1, 3, 5, 7, 8, 10, 12],
        ScaleType.LYDIAN: [0, 2, 4, 6, 7, 9, 11, 12],
        ScaleType.MIXOLYDIAN: [0, 2, 4, 5, 7, 9, 10, 12],
        ScaleType.AEOLIAN: [0, 2, 3, 5, 7, 8, 10, 12],
        ScaleType.LOCRIAN: [0, 1, 3, 5, 6, 8, 10, 12],
    }

    if scale_type not in intervals_map:
        raise InvalidScaleError(f"Unknown scale type: {scale_type}")

    intervals = intervals_map[scale_type]
    root_midi = root.to_midi_number()

    notes: list[Note] = []
    for semitone_offset in intervals:
        midi_num = root_midi + semitone_offset
        note = Note.from_midi_number(midi_num)
        notes.append(note)

    return Scale(root, scale_type, tuple(notes))


def scale_degrees(scale: Scale) -> dict[int, Note]:
    """Get scale degrees from a scale.

    Args:
        scale: The scale to analyze.

    Returns:
        Dictionary mapping degree (1-based) to note.
    """
    return {i + 1: note for i, note in enumerate(scale.notes)}


def mode_from_scale(scale: Scale, degree: int) -> Scale:
    """Generate a mode starting from a scale degree.

    Args:
        scale: Parent scale.
        degree: Scale degree (1-based).

    Returns:
        New scale in the mode.

    Raises:
        InvalidScaleError: If degree is invalid.
    """
    if not (1 <= degree <= len(scale.notes)):
        raise InvalidScaleError(f"Invalid scale degree: {degree}")

    root_note = scale.notes[degree - 1]
    return build_scale(root_note, ScaleType.MAJOR)


# ============================================================================
# Key Signatures
# ============================================================================


def build_key(tonic: Note, scale_type: ScaleType) -> Key:
    """Build a musical key.

    Args:
        tonic: Tonic note of the key.
        scale_type: Scale type of the key.

    Returns:
        Key object.
    """
    scale = build_scale(tonic, scale_type)
    return Key(tonic, scale_type, scale)


def key_signature(key: Key) -> tuple[str, int]:
    """Get key signature (sharps or flats) for a key.

    Args:
        key: The key.

    Returns:
        Tuple of (accidental_type, count) where accidental_type is 'sharps' or 'flats'.

    Example:
        >>> key = build_key(Note(Pitch(NoteName.G), 4), ScaleType.MAJOR)
        >>> key_signature(key)
        ('sharps', 1)
    """
    circle_of_fifths: dict[str, tuple[str, int]] = {
        "C": ("natural", 0),
        "G": ("sharps", 1),
        "D": ("sharps", 2),
        "A": ("sharps", 3),
        "E": ("sharps", 4),
        "B": ("sharps", 5),
        "F#": ("sharps", 6),
        "C#": ("sharps", 7),
        "F": ("flats", 1),
        "Bb": ("flats", 2),
        "Eb": ("flats", 3),
        "Ab": ("flats", 4),
        "Db": ("flats", 5),
        "Gb": ("flats", 6),
        "Cb": ("flats", 7),
    }

    root_str = str(key.tonic.pitch)
    if root_str in circle_of_fifths:
        accidental_type, count = circle_of_fifths[root_str]
        return (accidental_type, count)

    return ("natural", 0)


def enharmonic_equivalent(note: Note) -> Note:
    """Get the enharmonic equivalent of a note.

    Enharmonic equivalents have the same pitch but different names
    (e.g., C# and Db).

    Args:
        note: The note.

    Returns:
        Enharmonic equivalent note.
    """
    enharmonic_map: dict[tuple[NoteName, Accidental], tuple[NoteName, Accidental, int]] = {
        (NoteName.C, Accidental.SHARP): (NoteName.D, Accidental.FLAT, 0),
        (NoteName.D, Accidental.SHARP): (NoteName.E, Accidental.FLAT, 0),
        (NoteName.F, Accidental.SHARP): (NoteName.G, Accidental.FLAT, 0),
        (NoteName.G, Accidental.SHARP): (NoteName.A, Accidental.FLAT, 0),
        (NoteName.A, Accidental.SHARP): (NoteName.B, Accidental.FLAT, 0),
        (NoteName.E, Accidental.SHARP): (NoteName.F, Accidental.NATURAL, 0),
        (NoteName.B, Accidental.SHARP): (NoteName.C, Accidental.NATURAL, 1),
        (NoteName.D, Accidental.FLAT): (NoteName.C, Accidental.SHARP, 0),
        (NoteName.E, Accidental.FLAT): (NoteName.D, Accidental.SHARP, 0),
        (NoteName.G, Accidental.FLAT): (NoteName.F, Accidental.SHARP, 0),
        (NoteName.A, Accidental.FLAT): (NoteName.G, Accidental.SHARP, 0),
        (NoteName.B, Accidental.FLAT): (NoteName.A, Accidental.SHARP, 0),
        (NoteName.C, Accidental.FLAT): (NoteName.B, Accidental.NATURAL, -1),
        (NoteName.F, Accidental.FLAT): (NoteName.E, Accidental.NATURAL, 0),
    }

    mapped = enharmonic_map.get((note.pitch.note, note.pitch.accidental))
    if mapped is None:
        return note

    new_note_name, new_accidental, octave_shift = mapped
    return Note(Pitch(new_note_name, new_accidental), note.octave + octave_shift)


def transpose(note: Note, semitones: int) -> Note:
    """Transpose a note by a number of semitones.

    Args:
        note: Note to transpose.
        semitones: Number of semitones to transpose (positive = up, negative = down).

    Returns:
        Transposed note.

    Raises:
        InvalidNoteError: If transposed note is outside valid range.

    Example:
        >>> note = Note(Pitch(NoteName.C), 4)
        >>> transposed = transpose(note, 2)
        >>> str(transposed)
        'D4'
    """
    midi_num = note.to_midi_number()
    new_midi_num = midi_num + semitones

    if not (0 <= new_midi_num <= 127):
        raise InvalidNoteError(f"Transposed note out of range: {new_midi_num}")

    return Note.from_midi_number(new_midi_num)


# ============================================================================
# Frequency Calculations
# ============================================================================


def note_to_frequency(note: Note, a4_freq: float = 440.0) -> float:
    """Convert a note to frequency in Hz.

    Uses equal temperament with A4 as the reference.

    Args:
        note: The note.
        a4_freq: Frequency of A4 in Hz (default 440).

    Returns:
        Frequency in Hz.

    Example:
        >>> note = Note(Pitch(NoteName.A), 4)
        >>> freq = note_to_frequency(note)
        >>> abs(freq - 440.0) < 0.01
        True
    """
    return note.to_frequency(a4_freq)


def frequency_to_note(frequency: float, a4_freq: float = 440.0) -> Note:
    """Convert frequency in Hz to nearest MIDI note.

    Args:
        frequency: Frequency in Hz.
        a4_freq: Frequency of A4 in Hz (default 440).

    Returns:
        Nearest note.

    Raises:
        InvalidNoteError: If frequency is outside valid range.
    """
    midi_num = round(69 + 12 * math.log2(frequency / a4_freq))

    if not (0 <= midi_num <= 127):
        raise InvalidNoteError(f"Frequency out of MIDI range: {frequency} Hz")

    return Note.from_midi_number(midi_num)


# ============================================================================
# Consonance and Dissonance
# ============================================================================


def is_consonant_interval(interval: Interval) -> bool:
    """Check if an interval is consonant.

    Consonant intervals: unison, perfect fourth/fifth, major/minor third/sixth.

    Args:
        interval: The interval.

    Returns:
        True if interval is consonant.
    """
    consonant_intervals = {
        (IntervalQuality.PERFECT, 0),
        (IntervalQuality.PERFECT, 5),
        (IntervalQuality.PERFECT, 7),
        (IntervalQuality.MAJOR, 4),
        (IntervalQuality.MINOR, 3),
        (IntervalQuality.MAJOR, 9),
        (IntervalQuality.MINOR, 8),
    }

    return (interval.quality, interval.semitones) in consonant_intervals


def is_perfect_interval(interval: Interval) -> bool:
    """Check if an interval is perfect.

    Perfect intervals: unison, fourth, fifth, octave.

    Args:
        interval: The interval.

    Returns:
        True if interval is perfect.
    """
    return interval.quality == IntervalQuality.PERFECT


# ============================================================================
# Pitch Class Sets
# ============================================================================


def get_pitch_classes(notes: list[Note]) -> set[int]:
    """Get pitch classes (mod 12) from a list of notes.

    Args:
        notes: List of notes.

    Returns:
        Set of pitch classes (0-11).
    """
    return {note.to_midi_number() % 12 for note in notes}


def pitch_class_set_to_string(pitch_classes: set[int]) -> str:
    """Convert pitch class set to string notation.

    Args:
        pitch_classes: Set of pitch classes.

    Returns:
        String like "[0,1,4,7]".
    """
    sorted_pcs = sorted(pitch_classes)
    return "[" + ",".join(str(pc) for pc in sorted_pcs) + "]"
