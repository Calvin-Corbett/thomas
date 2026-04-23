"""Music notation - ABC, MusicXML, LilyPond, note spelling, beaming."""

from __future__ import annotations

from dataclasses import dataclass

from thomas.marketplace.music import theory
from thomas.marketplace.music._exceptions import NotationError
from thomas.marketplace.music._types import (
    Accidental,
    Duration,
    Key,
    Note,
    NoteName,
    Pitch,
    TimeSignature,
)

# ============================================================================
# Note Spelling
# ============================================================================


def choose_accidental_for_key(midi_number: int, key: Key | None) -> tuple[NoteName, Accidental]:
    """Choose appropriate note name and accidental for a key signature.

    Args:
        midi_number: MIDI note number.
        key: Musical key context (None = chromatic).

    Returns:
        Tuple of (NoteName, Accidental).
    """
    pitch, _ = Pitch.from_midi_number(midi_number)

    if key is None:
        return (pitch.note, pitch.accidental)

    key_sig_sharps, _ = theory.key_signature(key)

    if key_sig_sharps == "sharps":
        if midi_number % 12 in [1, 6, 8, 3, 10]:
            return (pitch.note, Accidental.SHARP)

    elif key_sig_sharps == "flats":
        if midi_number % 12 in [1, 3, 6, 8, 10]:
            return (pitch.note, Accidental.FLAT)

    return (pitch.note, Accidental.NATURAL)


# ============================================================================
# ABC Notation
# ============================================================================


@dataclass
class AbcHeader:
    """ABC notation file header."""

    reference_number: int = 1
    title: str = "Untitled"
    meter: str = "4/4"
    unit_note_length: str = "1/8"
    tempo: int = 120
    key: str = "C"


class AbcNotation:
    """Handles ABC notation parsing and generation."""

    def __init__(self) -> None:
        """Initialize ABC notation handler."""
        self.header = AbcHeader()

    def note_to_abc(self, note: Note, key: Key | None = None) -> str:
        """Convert note to ABC notation.

        Args:
            note: Note to convert.
            key: Key context for accidentals.

        Returns:
            ABC notation string.

        Example:
            >>> note = Note.parse("C4")
            >>> abc = AbcNotation()
            >>> abc.note_to_abc(note)
            'C'
        """
        midi = note.to_midi_number()
        octave_num = note.octave

        note_names = {
            NoteName.C: "C",
            NoteName.D: "D",
            NoteName.E: "E",
            NoteName.F: "F",
            NoteName.G: "G",
            NoteName.A: "A",
            NoteName.B: "B",
        }

        accidental_map = {
            Accidental.FLAT: "b",
            Accidental.NATURAL: "",
            Accidental.SHARP: "^",
            Accidental.DOUBLE_FLAT: "bb",
            Accidental.DOUBLE_SHARP: "^^",
        }

        note_name = note_names[note.pitch.note]
        accidental = accidental_map[note.pitch.accidental]

        if octave_num < 4:
            note_name = note_name.lower()
            octave_marks = "," * (4 - octave_num - 1)
        else:
            octave_marks = "'" * (octave_num - 4)

        return f"{accidental}{note_name}{octave_marks}"

    def abc_to_note(self, abc_str: str) -> Note:
        """Parse ABC notation to note.

        Args:
            abc_str: ABC notation string.

        Returns:
            Note object.

        Raises:
            NotationError: If notation is invalid.

        Example:
            >>> abc = AbcNotation()
            >>> note = abc.abc_to_note("C")
            >>> str(note)
            'C4'
        """
        if not abc_str:
            raise NotationError("Empty ABC string")

        pos = 0
        accidental = Accidental.NATURAL

        if abc_str[0] in "^_=":
            if abc_str[0] == "^":
                accidental = Accidental.SHARP if len(abc_str) < 2 or abc_str[1] != "^" else Accidental.DOUBLE_SHARP
            elif abc_str[0] == "_":
                accidental = Accidental.FLAT if len(abc_str) < 2 or abc_str[1] != "_" else Accidental.DOUBLE_FLAT
            else:
                accidental = Accidental.NATURAL

            pos += 1
            if pos < len(abc_str) and abc_str[pos] in "^_":
                pos += 1

        if pos >= len(abc_str):
            raise NotationError(f"Invalid ABC notation: {abc_str}")

        note_char = abc_str[pos].upper()
        pos += 1

        try:
            note_name = NoteName[note_char]
        except KeyError:
            raise NotationError(f"Invalid note name: {note_char}")

        octave = 4
        if abc_str[pos - 1].islower():
            octave = 3

        while pos < len(abc_str):
            if abc_str[pos] == "'":
                octave += 1
            elif abc_str[pos] == ",":
                octave -= 1
            else:
                break
            pos += 1

        pitch = Pitch(note_name, accidental)
        return Note(pitch, octave)

    def melody_to_abc(self, notes: list[Note]) -> str:
        """Convert melody to ABC notation.

        Args:
            notes: List of notes.

        Returns:
            ABC notation string.
        """
        abc_notes = [self.note_to_abc(note) for note in notes]
        return " ".join(abc_notes)

    def generate_abc_file(self, title: str, notes: list[Note], meter: str = "4/4") -> str:
        """Generate complete ABC file string.

        Args:
            title: Composition title.
            notes: List of notes.
            meter: Time signature.

        Returns:
            Complete ABC notation file.
        """
        lines = [
            "X: 1",
            f"T: {title}",
            f"M: {meter}",
            "L: 1/8",
            "K: C",
            self.melody_to_abc(notes),
        ]

        return "\n".join(lines)


# ============================================================================
# MusicXML Basics
# ============================================================================


def note_to_musicxml(note: Note, duration: Duration, divisions: int = 4) -> str:
    """Convert note to MusicXML note element.

    Args:
        note: Note to convert.
        duration: Note duration.
        divisions: Quarter note divisions (default 4 = sixteenth notes).

    Returns:
        MusicXML note element string.
    """
    midi = note.to_midi_number()
    octave = note.octave

    note_names = ["C", "D", "E", "F", "G", "A", "B"]
    pitch_class = midi % 12

    pitch_to_note = {
        0: ("C", 0),
        1: ("C", 1),
        2: ("D", 0),
        3: ("D", 1),
        4: ("E", 0),
        5: ("F", 0),
        6: ("F", 1),
        7: ("G", 0),
        8: ("G", 1),
        9: ("A", 0),
        10: ("A", 1),
        11: ("B", 0),
    }

    note_name, alter = pitch_to_note.get(pitch_class, ("C", 0))

    duration_value = int(duration.total_duration() * divisions)

    alter_str = f"<alter>{alter}</alter>" if alter != 0 else ""

    xml = f"""<note>
    <pitch>
        <step>{note_name}</step>
        {alter_str}
        <octave>{octave}</octave>
    </pitch>
    <duration>{duration_value}</duration>
</note>"""

    return xml


# ============================================================================
# LilyPond Notation
# ============================================================================


def note_to_lilypond(note: Note) -> str:
    """Convert note to LilyPond notation.

    Args:
        note: Note to convert.

    Returns:
        LilyPond notation string.

    Example:
        >>> note = Note.parse("F#4")
        >>> note_to_lilypond(note)
        "fis'"
    """
    note_map = {
        NoteName.C: "c",
        NoteName.D: "d",
        NoteName.E: "e",
        NoteName.F: "f",
        NoteName.G: "g",
        NoteName.A: "a",
        NoteName.B: "b",
    }

    accidental_map = {
        Accidental.FLAT: "es",
        Accidental.NATURAL: "",
        Accidental.SHARP: "is",
        Accidental.DOUBLE_FLAT: "eses",
        Accidental.DOUBLE_SHARP: "isis",
    }

    note_name = note_map[note.pitch.note]
    accidental = accidental_map[note.pitch.accidental]

    lilypond_note = note_name + accidental

    if note.octave < 4:
        octave_marks = "," * (4 - note.octave - 1)
    else:
        octave_marks = "'" * (note.octave - 3)

    return lilypond_note + octave_marks


def duration_to_lilypond(duration: Duration) -> str:
    """Convert duration to LilyPond rhythm notation.

    Args:
        duration: Duration to convert.

    Returns:
        LilyPond duration string.

    Example:
        >>> dur = Duration(0.25)
        >>> duration_to_lilypond(dur)
        '4'
    """
    value_map = {
        1.0: "1",
        0.5: "2",
        0.25: "4",
        0.125: "8",
        0.0625: "16",
        0.03125: "32",
    }

    base_value = value_map.get(duration.value, str(int(1.0 / duration.value)))

    dot_str = "." * duration.dots

    return base_value + dot_str


def melody_to_lilypond(notes: list[Note], durations: list[Duration]) -> str:
    """Convert melody to LilyPond notation.

    Args:
        notes: List of notes.
        durations: List of durations (one per note).

    Returns:
        LilyPond notation string.
    """
    if len(notes) != len(durations):
        raise NotationError("Number of notes and durations must match")

    tokens = []

    for note, duration in zip(notes, durations):
        note_str = note_to_lilypond(note)
        duration_str = duration_to_lilypond(duration)
        tokens.append(note_str + duration_str)

    return " ".join(tokens)


# ============================================================================
# Beaming
# ============================================================================


def group_notes_for_beaming(notes: list[Note], durations: list[Duration], time_sig: TimeSignature) -> list[list[int]]:
    """Group note indices for automatic beaming.

    Args:
        notes: List of notes.
        durations: List of durations.
        time_sig: Time signature.

    Returns:
        List of groups (each group is a list of note indices to beam together).
    """
    groups: list[list[int]] = []
    current_group: list[int] = []
    current_beat_position = 0.0
    beat_value = 4.0 / time_sig.denominator

    for i, duration in enumerate(durations):
        dur_value = duration.total_duration()

        if current_group and current_beat_position > 0 and (current_beat_position % beat_value < 0.001):
            groups.append(current_group)
            current_group = []

        current_group.append(i)
        current_beat_position += dur_value

    if current_group:
        groups.append(current_group)

    return groups


# ============================================================================
# Lyric Alignment
# ============================================================================


def align_lyrics_to_notes(lyrics: list[str], notes: list[Note]) -> dict[int, str]:
    """Align lyrics syllables to notes.

    Args:
        lyrics: List of syllables.
        notes: List of notes.

    Returns:
        Dictionary mapping note index to lyric.
    """
    alignment: dict[int, str] = {}

    for i, (lyric, note) in enumerate(zip(lyrics, notes)):
        alignment[i] = lyric

    return alignment
