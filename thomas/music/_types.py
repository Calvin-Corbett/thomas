"""Core data types for music representation.

Defines fundamental musical entities like notes, pitches, intervals, scales,
chords, time signatures, and MIDI events.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from thomas.music._exceptions import (
    InvalidChordError,
    InvalidIntervalError,
    InvalidNoteError,
    InvalidScaleError,
    InvalidTimeSignatureError,
)

# ============================================================================
# Enums
# ============================================================================


class NoteName(enum.Enum):
    """Chromatic note names."""

    C = 0
    D = 2
    E = 4
    F = 5
    G = 7
    A = 9
    B = 11


class Accidental(enum.Enum):
    """Accidental modifiers for notes."""

    DOUBLE_FLAT = -2
    FLAT = -1
    NATURAL = 0
    SHARP = 1
    DOUBLE_SHARP = 2


class IntervalQuality(enum.Enum):
    """Quality of an interval."""

    DIMINISHED = "diminished"
    MINOR = "minor"
    PERFECT = "perfect"
    MAJOR = "major"
    AUGMENTED = "augmented"


class ScaleType(enum.Enum):
    """Types of scales."""

    MAJOR = "major"
    NATURAL_MINOR = "natural_minor"
    HARMONIC_MINOR = "harmonic_minor"
    MELODIC_MINOR = "melodic_minor"
    PENTATONIC_MAJOR = "pentatonic_major"
    PENTATONIC_MINOR = "pentatonic_minor"
    BLUES = "blues"
    WHOLE_TONE = "whole_tone"
    CHROMATIC = "chromatic"
    DORIAN = "dorian"
    PHRYGIAN = "phrygian"
    LYDIAN = "lydian"
    MIXOLYDIAN = "mixolydian"
    AEOLIAN = "aeolian"
    LOCRIAN = "locrian"


class ChordQuality(enum.Enum):
    """Types of chord qualities."""

    MAJOR = "major"
    MINOR = "minor"
    DIMINISHED = "diminished"
    AUGMENTED = "augmented"
    DOMINANT_7 = "dominant_7"
    MAJOR_7 = "major_7"
    MINOR_7 = "minor_7"
    DIMINISHED_7 = "diminished_7"
    HALF_DIMINISHED = "half_diminished"
    SUS2 = "sus2"
    SUS4 = "sus4"
    ADD9 = "add9"
    ADD11 = "add11"
    ADD13 = "add13"
    MAJOR_ADD9 = "major_add9"
    MINOR_ADD9 = "minor_add9"


class Clef(enum.Enum):
    """Musical clefs."""

    TREBLE = "treble"
    BASS = "bass"
    ALTO = "alto"
    TENOR = "tenor"


class Dynamics(enum.Enum):
    """Dynamics markings."""

    PPPP = 5  # Quadruple piano
    PPP = 10
    PP = 20
    P = 30
    MP = 40
    MF = 50
    F = 60
    FF = 70
    FFF = 80
    FFFF = 85


class Articulation(enum.Enum):
    """Articulation types."""

    ACCENT = "accent"
    STACCATO = "staccato"
    TENUTO = "tenuto"
    MARCATO = "marcato"
    PIZZICATO = "pizzicato"
    TREMOLO = "tremolo"
    PORTAMENTO = "portamento"
    VIBRATO = "vibrato"


# ============================================================================
# Core Types
# ============================================================================


@dataclass(frozen=True)
class Pitch:
    """Represents a musical pitch with note name and accidental.

    Attributes:
        note: The base note name (C, D, E, F, G, A, B).
        accidental: Accidental modifier (flat, natural, sharp, etc.).
    """

    note: NoteName
    accidental: Accidental = Accidental.NATURAL

    def __post_init__(self) -> None:
        """Validate pitch creation."""
        midi_number = self.to_midi_number(4)
        if not (0 <= midi_number <= 127):
            raise InvalidNoteError(f"Invalid pitch: {self}")

    def to_midi_number(self, octave: int) -> int:
        """Convert pitch to MIDI note number.

        Args:
            octave: Octave number (C4 is middle C).

        Returns:
            MIDI note number (0-127).
        """
        return (octave + 1) * 12 + self.note.value + self.accidental.value

    def to_frequency(self, octave: int, a4_freq: float = 440.0) -> float:
        """Convert pitch to frequency in Hz using equal temperament.

        Args:
            octave: Octave number.
            a4_freq: Frequency of A4 (default 440 Hz).

        Returns:
            Frequency in Hz.
        """
        midi_num = self.to_midi_number(octave)
        return a4_freq * (2.0 ** ((midi_num - 69) / 12.0))

    @staticmethod
    def from_midi_number(midi_num: int) -> tuple[Pitch, int]:
        """Create pitch from MIDI note number.

        Args:
            midi_num: MIDI note number (0-127).

        Returns:
            Tuple of (Pitch, octave).
        """
        if not (0 <= midi_num <= 127):
            raise InvalidNoteError(f"Invalid MIDI number: {midi_num}")

        octave = (midi_num // 12) - 1
        note_value = midi_num % 12
        midi_to_pitch = {
            0: (NoteName.C, Accidental.NATURAL),
            1: (NoteName.C, Accidental.SHARP),
            2: (NoteName.D, Accidental.NATURAL),
            3: (NoteName.D, Accidental.SHARP),
            4: (NoteName.E, Accidental.NATURAL),
            5: (NoteName.F, Accidental.NATURAL),
            6: (NoteName.F, Accidental.SHARP),
            7: (NoteName.G, Accidental.NATURAL),
            8: (NoteName.G, Accidental.SHARP),
            9: (NoteName.A, Accidental.NATURAL),
            10: (NoteName.A, Accidental.SHARP),
            11: (NoteName.B, Accidental.NATURAL),
        }
        note_info = midi_to_pitch.get(note_value)
        if note_info is None:
            raise InvalidNoteError(f"Cannot convert MIDI {midi_num}")
        note_name, accidental = note_info
        return Pitch(note_name, accidental), octave

    def __str__(self) -> str:
        """String representation."""
        acc_str = {
            Accidental.DOUBLE_FLAT: "bb",
            Accidental.FLAT: "b",
            Accidental.NATURAL: "",
            Accidental.SHARP: "#",
            Accidental.DOUBLE_SHARP: "##",
        }[self.accidental]
        return f"{self.note.name}{acc_str}"


@dataclass(frozen=True)
class Note:
    """Represents a musical note with pitch and octave.

    Attributes:
        pitch: The note's pitch (note name + accidental).
        octave: Octave number (4 = middle octave).
    """

    pitch: Pitch
    octave: int

    def __post_init__(self) -> None:
        """Validate note creation."""
        if not (0 <= self.octave <= 8):
            raise InvalidNoteError(f"Invalid octave: {self.octave}")

    def to_midi_number(self) -> int:
        """Convert to MIDI note number."""
        return self.pitch.to_midi_number(self.octave)

    def to_frequency(self, a4_freq: float = 440.0) -> float:
        """Convert to frequency in Hz."""
        return self.pitch.to_frequency(self.octave, a4_freq)

    @staticmethod
    def from_midi_number(midi_num: int) -> Note:
        """Create note from MIDI number."""
        pitch, octave = Pitch.from_midi_number(midi_num)
        return Note(pitch, octave)

    @staticmethod
    def parse(note_str: str) -> Note:
        """Parse note from string like 'C4', 'F#5', 'Bb3'."""
        if len(note_str) < 2:
            raise InvalidNoteError(f"Invalid note string: {note_str}")

        note_char = note_str[0].upper()
        accidental_str = note_str[1:-1]
        octave_str = note_str[-1]

        try:
            note_name = NoteName[note_char]
        except KeyError:
            raise InvalidNoteError(f"Invalid note name: {note_char}")

        accidental_map = {
            "": Accidental.NATURAL,
            "#": Accidental.SHARP,
            "b": Accidental.FLAT,
            "##": Accidental.DOUBLE_SHARP,
            "bb": Accidental.DOUBLE_FLAT,
        }

        if accidental_str not in accidental_map:
            raise InvalidNoteError(f"Invalid accidental: {accidental_str}")

        try:
            octave = int(octave_str)
        except ValueError:
            raise InvalidNoteError(f"Invalid octave: {octave_str}")

        pitch = Pitch(note_name, accidental_map[accidental_str])
        return Note(pitch, octave)

    def __str__(self) -> str:
        """String representation."""
        return f"{self.pitch}{self.octave}"


@dataclass(frozen=True)
class Interval:
    """Represents a musical interval between two notes.

    Attributes:
        quality: The interval quality (major, minor, perfect, etc.).
        semitones: Number of semitones.
        name: Interval name (unison, second, third, etc.).
    """

    quality: IntervalQuality
    semitones: int
    name: str

    def __post_init__(self) -> None:
        """Validate interval."""
        if not (0 <= self.semitones <= 12):
            raise InvalidIntervalError(f"Invalid semitones: {self.semitones}")

    def is_ascending(self) -> bool:
        """Check if interval is ascending."""
        return self.semitones >= 0

    def invert(self) -> Interval:
        """Get the inverted interval."""
        inverted_semitones = 12 - self.semitones

        quality_map = {
            IntervalQuality.MAJOR: IntervalQuality.MINOR,
            IntervalQuality.MINOR: IntervalQuality.MAJOR,
            IntervalQuality.PERFECT: IntervalQuality.PERFECT,
            IntervalQuality.AUGMENTED: IntervalQuality.DIMINISHED,
            IntervalQuality.DIMINISHED: IntervalQuality.AUGMENTED,
        }

        return Interval(quality_map[self.quality], inverted_semitones, self.name)

    def __str__(self) -> str:
        """String representation."""
        return f"{self.quality.value.capitalize()} {self.name} ({self.semitones} semitones)"


@dataclass(frozen=True)
class Scale:
    """Represents a musical scale.

    Attributes:
        root: Root note of the scale.
        scale_type: Type of scale (major, minor, etc.).
        notes: List of notes in the scale.
    """

    root: Note
    scale_type: ScaleType
    notes: tuple[Note, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate scale."""
        if not self.notes:
            raise InvalidScaleError("Scale must have at least one note")

    def contains_pitch_class(self, pitch: Pitch) -> bool:
        """Check if scale contains a pitch class (ignoring octave)."""
        target_pc = (pitch.note.value + pitch.accidental.value) % 12
        pitch_classes = {(n.pitch.note.value + n.pitch.accidental.value) % 12 for n in self.notes}
        return target_pc in pitch_classes

    def degree(self, n: int) -> Note:
        """Get the nth scale degree (1-indexed)."""
        if not (1 <= n <= len(self.notes)):
            raise InvalidScaleError(f"Invalid scale degree: {n}")
        return self.notes[n - 1]

    def __str__(self) -> str:
        """String representation."""
        notes_str = " ".join(str(n) for n in self.notes)
        return f"{self.root} {self.scale_type.value}: {notes_str}"


@dataclass(frozen=True)
class Key:
    """Represents a musical key.

    Attributes:
        tonic: Tonic note of the key.
        scale_type: Scale type of the key (major, minor, etc.).
        scale: The scale for this key.
    """

    tonic: Note
    scale_type: ScaleType
    scale: Scale

    def sharps(self) -> int:
        """Number of sharps in key signature (positive) or flats (negative)."""
        # Circle of fifths: number of sharps for major keys
        roots = ["C", "G", "D", "A", "E", "B", "F#", "C#", "F", "Bb", "Eb", "Ab"]
        sharps_map = {0: 0, 1: 7, 2: 2, 3: 9, 4: 4, 5: 11, 6: 6, 7: 1, 8: 8, 9: -1, 10: -2, 11: -3}

        root_str = self.tonic.pitch.note.name
        try:
            idx = roots.index(root_str)
            return sharps_map.get(idx, 0)
        except ValueError:
            return 0

    def contains_pitch_class(self, pitch: Pitch) -> bool:
        """Check if key contains a pitch class."""
        return self.scale.contains_pitch_class(pitch)

    def __str__(self) -> str:
        """String representation."""
        return f"{self.tonic} {self.scale_type.value}"


@dataclass(frozen=True)
class Chord:
    """Represents a musical chord.

    Attributes:
        root: Root note of the chord.
        quality: Chord quality (major, minor, etc.).
        notes: Notes in the chord.
        inversion: Inversion level (0=root position, 1=first inversion, etc.).
    """

    root: Note
    quality: ChordQuality
    notes: tuple[Note, ...] = field(default_factory=tuple)
    inversion: int = 0

    def __post_init__(self) -> None:
        """Validate chord."""
        if not self.notes:
            raise InvalidChordError("Chord must have at least one note")
        if self.inversion < 0:
            raise InvalidChordError(f"Invalid inversion: {self.inversion}")

    def bass_note(self) -> Note:
        """Get the bass (lowest) note of the chord."""
        return self.notes[0]

    def contains_pitch_class(self, pitch: Pitch) -> bool:
        """Check if chord contains a pitch class."""
        target_pc = (pitch.note.value + pitch.accidental.value) % 12
        return any(((n.pitch.note.value + n.pitch.accidental.value) % 12) == target_pc for n in self.notes)

    def __str__(self) -> str:
        """String representation."""
        inv_str = f"/{self.bass_note()}" if self.inversion > 0 else ""
        return f"{self.root}{self.quality.value}{inv_str}"


@dataclass(frozen=True)
class TimeSignature:
    """Represents a time signature.

    Attributes:
        numerator: Beats per measure.
        denominator: Note value that gets one beat.
    """

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        """Validate time signature."""
        valid_denominators = [1, 2, 4, 8, 16, 32]
        if self.numerator <= 0 or self.denominator not in valid_denominators:
            raise InvalidTimeSignatureError(f"Invalid time signature: {self.numerator}/{self.denominator}")

    def is_compound(self) -> bool:
        """Check if time signature is compound meter."""
        return self.numerator % 3 == 0 and self.numerator >= 9

    def beats_per_measure(self) -> int:
        """Get number of beats per measure."""
        return self.numerator

    def beat_value(self) -> float:
        """Get the duration of one beat in whole notes."""
        return 4.0 / self.denominator

    def measure_duration(self) -> float:
        """Get duration of one measure in whole notes."""
        return self.beat_value() * self.numerator

    def __str__(self) -> str:
        """String representation."""
        return f"{self.numerator}/{self.denominator}"


@dataclass(frozen=True)
class Tempo:
    """Represents a tempo marking.

    Attributes:
        bpm: Beats per minute.
        beat_value: Note value that gets the beat (default 4 = quarter note).
    """

    bpm: float
    beat_value: int = 4

    def __post_init__(self) -> None:
        """Validate tempo."""
        if self.bpm <= 0:
            raise ValueError(f"Invalid tempo: {self.bpm}")

    def seconds_per_beat(self) -> float:
        """Get duration of one beat in seconds."""
        return 60.0 / self.bpm

    def seconds_per_quarter_note(self) -> float:
        """Get duration of one quarter note in seconds."""
        return 60.0 / self.bpm * (4.0 / self.beat_value)

    def __str__(self) -> str:
        """String representation."""
        return f"♩ = {int(self.bpm)} BPM"


@dataclass(frozen=True)
class Duration:
    """Represents a note duration.

    Attributes:
        value: Duration in whole notes (0.25 = quarter note).
        dots: Number of dots (dotted notes).
        tied: Whether note is tied to next note.
    """

    value: float
    dots: int = 0
    tied: bool = False

    def __post_init__(self) -> None:
        """Validate duration."""
        if self.value <= 0:
            raise ValueError(f"Invalid duration value: {self.value}")
        if self.dots < 0:
            raise ValueError(f"Invalid dots: {self.dots}")

    def total_duration(self) -> float:
        """Get total duration including dots."""
        result = self.value
        current = self.value / 2.0
        for _ in range(self.dots):
            result += current
            current /= 2.0
        return result

    def __str__(self) -> str:
        """String representation."""
        names = {
            1.0: "whole",
            0.5: "half",
            0.25: "quarter",
            0.125: "eighth",
            0.0625: "sixteenth",
        }
        name = names.get(self.value, f"{self.value}")
        dot_str = "." * self.dots
        return f"{name}{dot_str}"


@dataclass(frozen=True)
class Rest:
    """Represents a musical rest.

    Attributes:
        duration: Duration of the rest.
    """

    duration: Duration

    def __str__(self) -> str:
        """String representation."""
        return f"Rest({self.duration})"


@dataclass(frozen=True)
class Measure:
    """Represents a measure in a musical score.

    Attributes:
        number: Measure number.
        time_signature: Time signature of the measure.
        notes_and_rests: List of notes and rests in the measure.
    """

    number: int
    time_signature: TimeSignature
    notes_and_rests: list[Note | Rest] = field(default_factory=list)

    def total_duration(self) -> float:
        """Get total duration of notes/rests in measure."""
        return sum(
            (item.duration if isinstance(item, Rest) else Duration(0.25)).total_duration()
            for item in self.notes_and_rests
        )

    def is_full(self) -> bool:
        """Check if measure is full according to time signature."""
        return abs(self.total_duration() - self.time_signature.measure_duration()) < 0.001


@dataclass
class Voice:
    """Represents a voice in a musical score.

    Attributes:
        number: Voice number (1-4 for SATB).
        clef: Clef for this voice.
        measures: List of measures.
    """

    number: int
    clef: Clef
    measures: list[Measure] = field(default_factory=list)

    def add_measure(self, measure: Measure) -> None:
        """Add a measure to the voice."""
        self.measures.append(measure)

    def __str__(self) -> str:
        """String representation."""
        return f"Voice {self.number} ({self.clef.value})"


@dataclass
class Part:
    """Represents a single instrument part.

    Attributes:
        name: Name of the part (e.g., "Violin 1").
        instrument: Instrument name.
        voices: List of voices.
        program: MIDI program number (0-127).
    """

    name: str
    instrument: str
    voices: list[Voice] = field(default_factory=list)
    program: int = 0

    def add_voice(self, voice: Voice) -> None:
        """Add a voice to the part."""
        self.voices.append(voice)

    def __str__(self) -> str:
        """String representation."""
        return f"{self.name} ({self.instrument})"


@dataclass
class Score:
    """Represents a complete musical score.

    Attributes:
        title: Title of the composition.
        composer: Composer name.
        parts: List of parts.
        key: Musical key.
        time_signature: Time signature.
        tempo: Tempo marking.
    """

    title: str
    composer: str
    parts: list[Part] = field(default_factory=list)
    key: Key | None = None
    time_signature: TimeSignature | None = None
    tempo: Tempo | None = None

    def add_part(self, part: Part) -> None:
        """Add a part to the score."""
        self.parts.append(part)

    def __str__(self) -> str:
        """String representation."""
        return f'"{self.title}" by {self.composer}'


# ============================================================================
# MIDI Types
# ============================================================================


@dataclass(frozen=True)
class MidiEvent:
    """Represents a MIDI event.

    Attributes:
        delta_time: Time in ticks since last event.
        event_type: Type of MIDI event (note_on, note_off, control_change, etc.).
        channel: MIDI channel (0-15).
        data: Event-specific data (note number, velocity, controller, etc.).
    """

    delta_time: int
    event_type: str
    channel: int
    data: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate MIDI event."""
        if not (0 <= self.channel <= 15):
            raise ValueError(f"Invalid MIDI channel: {self.channel}")


@dataclass
class MidiTrack:
    """Represents a MIDI track.

    Attributes:
        name: Track name.
        program: MIDI program number (0-127).
        channel: MIDI channel (0-15).
        events: List of MIDI events.
    """

    name: str = "Track"
    program: int = 0
    channel: int = 0
    events: list[MidiEvent] = field(default_factory=list)

    def add_event(self, event: MidiEvent) -> None:
        """Add a MIDI event to the track."""
        self.events.append(event)

    def __str__(self) -> str:
        """String representation."""
        return f"MidiTrack '{self.name}' (Program {self.program}, Channel {self.channel})"
