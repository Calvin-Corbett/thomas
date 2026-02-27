"""Chord system - construction, analysis, voicing, and symbol parsing."""

from __future__ import annotations

import re

from thomas.music import theory
from thomas.music._exceptions import InvalidChordError
from thomas.music._types import (
    Accidental,
    Chord,
    ChordQuality,
    Note,
    NoteName,
    Pitch,
)

# ============================================================================
# Chord Construction
# ============================================================================


def build_chord_from_intervals(
    root: Note,
    intervals: list[int],
    quality: ChordQuality | None = None,
) -> Chord:
    """Build a chord from a root note and list of semitone intervals.

    Args:
        root: Root note of the chord.
        intervals: List of semitone intervals (should start with 0).

    Returns:
        Chord object with notes built from intervals.

    Raises:
        InvalidChordError: If intervals are invalid.

    Example:
        >>> root = Note(Pitch(NoteName.C), 4)
        >>> major_thirds = [0, 4, 7]  # Root, major third, perfect fifth
        >>> chord = build_chord_from_intervals(root, major_thirds)
    """
    if not intervals or intervals[0] != 0:
        raise InvalidChordError("First interval must be 0 (root)")

    notes: list[Note] = []
    for interval in intervals:
        transposed = theory.transpose(root, interval)
        notes.append(transposed)

    if quality is None:
        quality_map: dict[tuple[int, ...], ChordQuality] = {
            (0, 4, 7): ChordQuality.MAJOR,
            (0, 3, 7): ChordQuality.MINOR,
            (0, 3, 6): ChordQuality.DIMINISHED,
            (0, 4, 8): ChordQuality.AUGMENTED,
            (0, 4, 7, 10): ChordQuality.DOMINANT_7,
            (0, 4, 7, 11): ChordQuality.MAJOR_7,
            (0, 3, 7, 10): ChordQuality.MINOR_7,
            (0, 3, 6, 9): ChordQuality.DIMINISHED_7,
            (0, 3, 6, 10): ChordQuality.HALF_DIMINISHED,
            (0, 2, 7): ChordQuality.SUS2,
            (0, 5, 7): ChordQuality.SUS4,
            (0, 4, 7, 14): ChordQuality.ADD9,
        }
        quality = quality_map.get(tuple(intervals), ChordQuality.MAJOR)

    return Chord(root, quality, tuple(notes), 0)


def major_chord(root: Note) -> Chord:
    """Create a major triad (root, major third, perfect fifth).

    Args:
        root: Root note.

    Returns:
        Major triad.
    """
    return build_chord_from_intervals(root, [0, 4, 7], ChordQuality.MAJOR)


def minor_chord(root: Note) -> Chord:
    """Create a minor triad (root, minor third, perfect fifth).

    Args:
        root: Root note.

    Returns:
        Minor triad.
    """
    return build_chord_from_intervals(root, [0, 3, 7], ChordQuality.MINOR)


def diminished_chord(root: Note) -> Chord:
    """Create a diminished triad (root, minor third, diminished fifth).

    Args:
        root: Root note.

    Returns:
        Diminished triad.
    """
    return build_chord_from_intervals(root, [0, 3, 6], ChordQuality.DIMINISHED)


def augmented_chord(root: Note) -> Chord:
    """Create an augmented triad (root, major third, augmented fifth).

    Args:
        root: Root note.

    Returns:
        Augmented triad.
    """
    return build_chord_from_intervals(root, [0, 4, 8], ChordQuality.AUGMENTED)


def dominant_seventh_chord(root: Note) -> Chord:
    """Create a dominant seventh chord (root, major third, perfect fifth, minor seventh).

    Args:
        root: Root note.

    Returns:
        Dominant seventh chord.
    """
    return build_chord_from_intervals(root, [0, 4, 7, 10], ChordQuality.DOMINANT_7)


def major_seventh_chord(root: Note) -> Chord:
    """Create a major seventh chord (root, major third, perfect fifth, major seventh).

    Args:
        root: Root note.

    Returns:
        Major seventh chord.
    """
    return build_chord_from_intervals(root, [0, 4, 7, 11], ChordQuality.MAJOR_7)


def minor_seventh_chord(root: Note) -> Chord:
    """Create a minor seventh chord (root, minor third, perfect fifth, minor seventh).

    Args:
        root: Root note.

    Returns:
        Minor seventh chord.
    """
    return build_chord_from_intervals(root, [0, 3, 7, 10], ChordQuality.MINOR_7)


def diminished_seventh_chord(root: Note) -> Chord:
    """Create a diminished seventh chord (root, minor third, diminished fifth, diminished seventh).

    Args:
        root: Root note.

    Returns:
        Diminished seventh chord.
    """
    return build_chord_from_intervals(root, [0, 3, 6, 9], ChordQuality.DIMINISHED_7)


def half_diminished_chord(root: Note) -> Chord:
    """Create a half-diminished seventh chord (root, minor third, diminished fifth, minor seventh).

    Args:
        root: Root note.

    Returns:
        Half-diminished seventh chord.
    """
    return build_chord_from_intervals(root, [0, 3, 6, 10], ChordQuality.HALF_DIMINISHED)


def sus2_chord(root: Note) -> Chord:
    """Create a sus2 chord (root, major second, perfect fifth).

    Args:
        root: Root note.

    Returns:
        Sus2 chord.
    """
    return build_chord_from_intervals(root, [0, 2, 7], ChordQuality.SUS2)


def sus4_chord(root: Note) -> Chord:
    """Create a sus4 chord (root, perfect fourth, perfect fifth).

    Args:
        root: Root note.

    Returns:
        Sus4 chord.
    """
    return build_chord_from_intervals(root, [0, 5, 7], ChordQuality.SUS4)


def add9_chord(root: Note) -> Chord:
    """Create a chord with added 9th (root, major third, perfect fifth, major ninth).

    Args:
        root: Root note.

    Returns:
        Add9 chord.
    """
    return build_chord_from_intervals(root, [0, 4, 7, 14], ChordQuality.ADD9)


def chord_from_quality(root: Note, quality: ChordQuality) -> Chord:
    """Create a chord from root and quality.

    Args:
        root: Root note.
        quality: Chord quality.

    Returns:
        Chord with specified quality.

    Raises:
        InvalidChordError: If quality is not supported.
    """
    quality_builders: dict[ChordQuality, callable] = {
        ChordQuality.MAJOR: major_chord,
        ChordQuality.MINOR: minor_chord,
        ChordQuality.DIMINISHED: diminished_chord,
        ChordQuality.AUGMENTED: augmented_chord,
        ChordQuality.DOMINANT_7: dominant_seventh_chord,
        ChordQuality.MAJOR_7: major_seventh_chord,
        ChordQuality.MINOR_7: minor_seventh_chord,
        ChordQuality.DIMINISHED_7: diminished_seventh_chord,
        ChordQuality.HALF_DIMINISHED: half_diminished_chord,
        ChordQuality.SUS2: sus2_chord,
        ChordQuality.SUS4: sus4_chord,
        ChordQuality.ADD9: add9_chord,
    }

    if quality not in quality_builders:
        raise InvalidChordError(f"Unsupported chord quality: {quality}")

    return quality_builders[quality](root)


# ============================================================================
# Chord Inversion
# ============================================================================


def invert_chord(chord: Chord, inversion: int = 1) -> Chord:
    """Create an inversion of a chord.

    Args:
        chord: Original chord.
        inversion: Inversion level (1 = first inversion, 2 = second inversion, etc.).

    Returns:
        Inverted chord.

    Raises:
        InvalidChordError: If inversion is invalid.

    Example:
        >>> root = Note(Pitch(NoteName.C), 4)
        >>> c_major = major_chord(root)
        >>> c_first_inv = invert_chord(c_major, 1)
        >>> str(c_first_inv.bass_note())
        'E4'
    """
    if inversion <= 0:
        raise InvalidChordError(f"Invalid inversion: {inversion}")

    if inversion >= len(chord.notes):
        raise InvalidChordError(f"Chord only has {len(chord.notes)} notes")

    notes = list(chord.notes)
    for _ in range(inversion):
        bass = notes.pop(0)
        transposed_up = theory.transpose(bass, 12)
        notes.append(transposed_up)

    return Chord(chord.root, chord.quality, tuple(notes), inversion)


def root_position(chord: Chord) -> Chord:
    """Get root position of a chord.

    Args:
        chord: Chord in any inversion.

    Returns:
        Chord in root position.
    """
    if chord.inversion == 0:
        return chord

    notes = list(chord.notes)
    root_note = chord.root

    sorted_notes = sorted(notes, key=lambda n: n.to_midi_number())
    sorted_notes.sort(key=lambda n: abs(n.to_midi_number() - root_note.to_midi_number()))

    return Chord(chord.root, chord.quality, tuple(sorted_notes), 0)


# ============================================================================
# Chord Voicing
# ============================================================================


def voice_chord_close_position(chord: Chord, lowest_note: Note) -> Chord:
    """Arrange chord in close position (stacked closely).

    Args:
        chord: Chord to voice.
        lowest_note: Lowest note of the voicing.

    Returns:
        Voiced chord in close position.
    """
    pitch_classes = {n.pitch.note for n in chord.notes}

    voiced_notes: list[Note] = []
    current_octave = lowest_note.octave
    current_midi = lowest_note.to_midi_number()

    notes_to_voice = list(chord.notes)

    for note in notes_to_voice:
        midi_note = note.to_midi_number() % 12
        lowest_midi = lowest_note.to_midi_number() % 12

        target_midi = (current_octave * 12) + 12 + midi_note

        if target_midi <= current_midi:
            target_midi += 12

        voiced_notes.append(Note.from_midi_number(target_midi))
        current_midi = target_midi

    return Chord(chord.root, chord.quality, tuple(voiced_notes), 0)


def voice_chord_open_position(chord: Chord, lowest_note: Note, spacing: int = 12) -> Chord:
    """Arrange chord in open position (spread out).

    Args:
        chord: Chord to voice.
        lowest_note: Lowest note of the voicing.
        spacing: Minimum spacing in semitones between notes.

    Returns:
        Voiced chord in open position.
    """
    voiced_notes: list[Note] = []
    current_midi = lowest_note.to_midi_number()

    for note in chord.notes:
        midi_note = note.to_midi_number() % 12
        target_midi = current_midi + spacing

        while (target_midi % 12) != midi_note:
            target_midi += 1

        voiced_notes.append(Note.from_midi_number(target_midi))
        current_midi = target_midi

    return Chord(chord.root, chord.quality, tuple(voiced_notes), 0)


# ============================================================================
# Chord Symbol Parsing
# ============================================================================


def parse_chord_symbol(symbol: str) -> Chord:
    """Parse a chord symbol like 'Cmaj7', 'F#m', 'Bb7#9'.

    Args:
        symbol: Chord symbol string.

    Returns:
        Parsed chord.

    Raises:
        InvalidChordError: If symbol cannot be parsed.

    Example:
        >>> chord = parse_chord_symbol("Cmaj7")
        >>> chord.quality
        <ChordQuality.MAJOR_7: 'major_7'>
    """
    symbol = symbol.strip()

    pattern = r"^([A-G])(#{1,2}|b{1,2})?(.*)$"
    match = re.match(pattern, symbol)

    if not match:
        raise InvalidChordError(f"Invalid chord symbol: {symbol}")

    note_name, accidental, quality_str = match.groups()

    note = NoteName[note_name]
    accidental_obj = Accidental.NATURAL

    if accidental:
        accidental_map = {
            "#": Accidental.SHARP,
            "##": Accidental.DOUBLE_SHARP,
            "b": Accidental.FLAT,
            "bb": Accidental.DOUBLE_FLAT,
        }
        accidental_obj = accidental_map.get(accidental, Accidental.NATURAL)

    root = Note(Pitch(note, accidental_obj), 4)

    quality_map: dict[str, ChordQuality] = {
        "": ChordQuality.MAJOR,
        "m": ChordQuality.MINOR,
        "min": ChordQuality.MINOR,
        "maj7": ChordQuality.MAJOR_7,
        "M7": ChordQuality.MAJOR_7,
        "7": ChordQuality.DOMINANT_7,
        "m7": ChordQuality.MINOR_7,
        "dim": ChordQuality.DIMINISHED,
        "°": ChordQuality.DIMINISHED,
        "dim7": ChordQuality.DIMINISHED_7,
        "°7": ChordQuality.DIMINISHED_7,
        "ø": ChordQuality.HALF_DIMINISHED,
        "ø7": ChordQuality.HALF_DIMINISHED,
        "m7b5": ChordQuality.HALF_DIMINISHED,
        "aug": ChordQuality.AUGMENTED,
        "+": ChordQuality.AUGMENTED,
        "sus2": ChordQuality.SUS2,
        "sus4": ChordQuality.SUS4,
        "add9": ChordQuality.ADD9,
    }

    quality = quality_map.get(quality_str, ChordQuality.MAJOR)

    return chord_from_quality(root, quality)


# ============================================================================
# Roman Numeral Analysis
# ============================================================================


def chord_to_roman_numeral(chord: Chord, key_root: Note) -> str:
    """Convert a chord to Roman numeral notation in a key.

    Args:
        chord: Chord to analyze.
        key_root: Root of the key.

    Returns:
        Roman numeral string (e.g., "IV", "vi", "V7").

    Example:
        >>> c = Note(Pitch(NoteName.C), 4)
        >>> f = Note(Pitch(NoteName.F), 4)
        >>> chord = major_chord(f)
        >>> chord_to_roman_numeral(chord, c)
        'IV'
    """
    scale = theory.build_scale(key_root, theory.ScaleType.MAJOR)

    root_midi = chord.root.to_midi_number() % 12
    key_midi = key_root.to_midi_number() % 12

    degree_offset = (root_midi - key_midi) % 12

    degree_semitones = [0, 2, 4, 5, 7, 9, 11]
    if degree_offset not in degree_semitones:
        return "?"

    degree = degree_semitones.index(degree_offset)

    roman_numerals = ["I", "II", "III", "IV", "V", "VI", "VII"]
    roman = roman_numerals[degree]

    if chord.quality == ChordQuality.MINOR:
        roman = roman.lower()
    elif chord.quality == ChordQuality.DIMINISHED:
        roman = roman.lower() + "°"
    elif chord.quality == ChordQuality.AUGMENTED:
        roman = roman + "+"

    if chord.quality in [ChordQuality.DOMINANT_7, ChordQuality.MAJOR_7, ChordQuality.MINOR_7]:
        if chord.quality == ChordQuality.DOMINANT_7:
            roman += "7"
        elif chord.quality == ChordQuality.MAJOR_7:
            roman += "maj7"
        elif chord.quality == ChordQuality.MINOR_7:
            roman = roman.lower() + "7"

    return roman


def roman_numeral_to_chord(roman: str, key_root: Note) -> Chord:
    """Convert Roman numeral to chord in a key.

    Args:
        roman: Roman numeral (e.g., "IV", "vi", "V7").
        key_root: Root of the key.

    Returns:
        Chord in the key.

    Raises:
        InvalidChordError: If Roman numeral is invalid.

    Example:
        >>> c = Note(Pitch(NoteName.C), 4)
        >>> chord = roman_numeral_to_chord("IV", c)
        >>> chord.root.pitch.note
        <NoteName.F: 5>
    """
    scale = theory.build_scale(key_root, theory.ScaleType.MAJOR)

    roman_map = {"i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6}

    roman_lower = roman.lower().replace("°", "").replace("+", "").replace("7", "").replace("maj", "")

    if roman_lower not in roman_map:
        raise InvalidChordError(f"Invalid Roman numeral: {roman}")

    degree = roman_map[roman_lower]
    chord_root = scale.notes[degree]

    if "maj7" in roman.lower():
        quality = ChordQuality.MAJOR_7
    elif "7" in roman.lower() and roman[0].islower():
        quality = ChordQuality.MINOR_7
    elif "7" in roman.lower():
        quality = ChordQuality.DOMINANT_7
    elif "°" in roman:
        quality = ChordQuality.DIMINISHED
    elif "+" in roman:
        quality = ChordQuality.AUGMENTED
    elif roman[0].islower():
        quality = ChordQuality.MINOR
    else:
        quality = ChordQuality.MAJOR

    return chord_from_quality(chord_root, quality)


# ============================================================================
# Chord Progression Analysis
# ============================================================================


def is_valid_progression(chords: list[Chord]) -> bool:
    """Check if a chord progression follows basic voice leading rules.

    Args:
        chords: List of chords in sequence.

    Returns:
        True if progression is valid.
    """
    if len(chords) < 2:
        return True

    for i in range(len(chords) - 1):
        curr = chords[i]
        next_chord = chords[i + 1]

        curr_bass = curr.bass_note().to_midi_number()
        next_bass = next_chord.bass_note().to_midi_number()

        motion = abs(next_bass - curr_bass)
        if motion > 12:
            return False

    return True


def progression_strength(chords: list[Chord], key_root: Note) -> float:
    """Calculate harmonic strength of a chord progression (0.0 to 1.0).

    Args:
        chords: List of chords.
        key_root: Key root for analysis.

    Returns:
        Strength score (higher = more standard progression).
    """
    if len(chords) < 2:
        return 1.0

    standard_progressions = [
        ["I", "IV", "V", "I"],
        ["I", "vi", "IV", "V"],
        ["vi", "IV", "I", "V"],
        ["I", "V", "vi", "IV"],
    ]

    current_progression = [chord_to_roman_numeral(c, key_root) for c in chords]

    for standard in standard_progressions:
        if current_progression == standard:
            return 1.0

    return 0.5
