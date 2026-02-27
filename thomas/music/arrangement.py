"""Arrangement - instrument ranges, orchestration, patterns, accompaniment."""

from __future__ import annotations

from dataclasses import dataclass

from thomas.music import theory
from thomas.music._exceptions import InvalidNoteError
from thomas.music._types import Chord, Note, TimeSignature

# ============================================================================
# Instrument Definitions
# ============================================================================


@dataclass
class Instrument:
    """Represents a musical instrument."""

    name: str
    midi_program: int
    lowest_note: int
    highest_note: int
    transposition_semitones: int = 0

    def is_note_playable(self, note: Note) -> bool:
        """Check if note is in instrument's range.

        Args:
            note: Note to check.

        Returns:
            True if playable.
        """
        midi = note.to_midi_number()
        return self.lowest_note <= midi <= self.highest_note

    def clamp_to_range(self, note: Note) -> Note:
        """Clamp note to instrument's range.

        Args:
            note: Note to adjust.

        Returns:
            Note within range.
        """
        midi = note.to_midi_number()

        if midi < self.lowest_note:
            return Note.from_midi_number(self.lowest_note)
        elif midi > self.highest_note:
            return Note.from_midi_number(self.highest_note)
        else:
            return note


INSTRUMENTS: dict[str, Instrument] = {
    "soprano": Instrument("Soprano", 0, 60, 84),
    "alto": Instrument("Alto", 0, 53, 77),
    "tenor": Instrument("Tenor", 0, 40, 64),
    "bass": Instrument("Bass", 0, 28, 52),
    "violin": Instrument("Violin", 40, 55, 103),
    "viola": Instrument("Viola", 41, 48, 96),
    "cello": Instrument("Cello", 42, 36, 84),
    "bass_viol": Instrument("Double Bass", 43, 28, 67),
    "flute": Instrument("Flute", 73, 60, 108),
    "oboe": Instrument("Oboe", 68, 58, 91),
    "clarinet": Instrument("Clarinet", 71, 50, 103),
    "bassoon": Instrument("Bassoon", 70, 34, 87),
    "french_horn": Instrument("French Horn", 60, 34, 82),
    "trumpet": Instrument("Trumpet", 56, 52, 102),
    "trombone": Instrument("Trombone", 57, 40, 85),
    "tuba": Instrument("Tuba", 58, 28, 60),
    "acoustic_guitar": Instrument("Acoustic Guitar", 24, 40, 84),
    "electric_guitar": Instrument("Electric Guitar", 25, 28, 108),
    "acoustic_bass": Instrument("Acoustic Bass", 32, 28, 67),
    "electric_bass": Instrument("Electric Bass", 33, 28, 67),
    "piano": Instrument("Piano", 0, 21, 108),
    "organ": Instrument("Organ", 19, 28, 108),
}


def get_instrument(name: str) -> Instrument | None:
    """Get instrument by name.

    Args:
        name: Instrument name.

    Returns:
        Instrument object or None.
    """
    return INSTRUMENTS.get(name.lower())


# ============================================================================
# Orchestration
# ============================================================================


def double_melody_at_octave(melody: list[Note], doubling_octaves: int = 1) -> list[Note]:
    """Create doubling voice at octave(s) above/below.

    Args:
        melody: Melody to double.
        doubling_octaves: Number of octaves to double (positive=up, negative=down).

    Returns:
        Doubled melody.
    """
    doubled: list[Note] = []

    for note in melody:
        transposed = theory.transpose(note, 12 * doubling_octaves)
        doubled.append(transposed)

    return doubled


def voicing_for_pad(chord: Chord, lowest_midi: int = 36) -> list[Note]:
    """Create chord pad voicing (smooth, sustained sound).

    Args:
        chord: Chord to voice.
        lowest_midi: Lowest MIDI note.

    Returns:
        Voicing notes.
    """
    pitch_classes = set()
    voiced_notes: list[Note] = []

    for note in chord.notes:
        pitch_class = note.to_midi_number() % 12
        if pitch_class not in pitch_classes:
            pitch_classes.add(pitch_class)

            current_midi = lowest_midi
            while (current_midi % 12) != pitch_class:
                current_midi += 1

            if 0 <= current_midi <= 127:
                voiced_notes.append(Note.from_midi_number(current_midi))

    return voiced_notes


def bass_line_pattern(chords: list[Chord], pattern_type: str = "root") -> list[Note]:
    """Generate bass line from chord progression.

    Args:
        chords: Chord progression.
        pattern_type: Pattern type ('root', 'ascending', 'descending', 'arpeggio').

    Returns:
        Bass line notes.
    """
    bass_notes: list[Note] = []

    for chord in chords:
        if pattern_type == "root":
            bass_notes.append(chord.root)

        elif pattern_type == "ascending":
            sorted_notes = sorted(chord.notes, key=lambda n: n.to_midi_number())
            bass_notes.extend(sorted_notes)

        elif pattern_type == "descending":
            sorted_notes = sorted(chord.notes, key=lambda n: n.to_midi_number(), reverse=True)
            bass_notes.extend(sorted_notes)

        elif pattern_type == "arpeggio":
            notes = list(chord.notes)
            notes.append(chord.notes[0])
            bass_notes.extend(notes)

    return bass_notes


# ============================================================================
# Drum Patterns
# ============================================================================


@dataclass
class DrumPattern:
    """Represents a drum pattern."""

    name: str
    time_signature: TimeSignature
    kick: list[bool]
    snare: list[bool]
    hihat: list[bool]


def rock_drum_pattern() -> DrumPattern:
    """Create a basic rock drum pattern.

    Returns:
        Rock drum pattern.
    """
    ts = TimeSignature(4, 4)

    kick = [True, False, False, False, True, False, False, False, True, False, False, False, True, False, False, False]
    snare = [
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    hihat = [True] * 16

    return DrumPattern("rock", ts, kick, snare, hihat)


def jazz_drum_pattern() -> DrumPattern:
    """Create a jazz swing drum pattern.

    Returns:
        Jazz drum pattern.
    """
    ts = TimeSignature(4, 4)

    kick = [True, False, False, False, False, False, True, False, True, False, False, False, False, False, True, False]
    snare = [
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    hihat = [True, False, True, False, True, False, True, False, True, False, True, False, True, False, True, False]

    return DrumPattern("jazz", ts, kick, snare, hihat)


def pop_drum_pattern() -> DrumPattern:
    """Create a pop drum pattern.

    Returns:
        Pop drum pattern.
    """
    ts = TimeSignature(4, 4)

    kick = [True, False, False, False, False, False, True, False, False, False, True, False, False, False, True, False]
    snare = [
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        True,
        False,
        False,
        False,
    ]
    hihat = [True, True, True, True, True, True, True, True, True, True, True, True, True, True, True, True]

    return DrumPattern("pop", ts, kick, snare, hihat)


# ============================================================================
# Arpeggiator
# ============================================================================


class ArpeggiatorMode:
    """Arpeggiator patterns."""

    UP = "up"
    DOWN = "down"
    UP_DOWN = "up_down"
    DOWN_UP = "down_up"
    RANDOM = "random"
    PATTERN = "pattern"


def arpeggiate(chord: Chord, mode: str = ArpeggiatorMode.UP, repetitions: int = 1) -> list[Note]:
    """Generate arpeggio from chord.

    Args:
        chord: Chord to arpeggiate.
        mode: Arpeggiator mode.
        repetitions: Number of times to repeat pattern.

    Returns:
        Arpeggio notes.
    """
    notes = sorted(chord.notes, key=lambda n: n.to_midi_number())

    arpeggio: list[Note] = []

    for _ in range(repetitions):
        if mode == ArpeggiatorMode.UP:
            arpeggio.extend(notes)

        elif mode == ArpeggiatorMode.DOWN:
            arpeggio.extend(reversed(notes))

        elif mode == ArpeggiatorMode.UP_DOWN:
            arpeggio.extend(notes)
            arpeggio.extend(reversed(notes[:-1]))

        elif mode == ArpeggiatorMode.DOWN_UP:
            arpeggio.extend(reversed(notes))
            arpeggio.extend(notes[1:])

        elif mode == ArpeggiatorMode.RANDOM:
            import random

            shuffled = notes.copy()
            random.shuffle(shuffled)
            arpeggio.extend(shuffled)

    return arpeggio


# ============================================================================
# Auto-Accompaniment
# ============================================================================


def auto_accompany(chord: Chord, time_sig: TimeSignature, style: str = "basic") -> dict[str, list[Note]]:
    """Generate automatic accompaniment for a chord.

    Args:
        chord: Chord to accompany.
        time_sig: Time signature.
        style: Accompaniment style ('basic', 'rich', 'sparse').

    Returns:
        Dictionary with accompaniment parts ('bass', 'chords', 'rhythm').
    """
    accompaniment: dict[str, list[Note]] = {
        "bass": [],
        "chords": [],
        "rhythm": [],
    }

    if style == "basic":
        accompaniment["bass"] = [chord.root] * 4
        accompaniment["chords"] = chord.notes * 2
        accompaniment["rhythm"] = voicing_for_pad(chord, 36)

    elif style == "rich":
        accompaniment["bass"] = bass_line_pattern([chord], "arpeggio") * 2
        accompaniment["chords"] = voicing_for_pad(chord, 48)
        accompaniment["rhythm"] = chord.notes * 4

    elif style == "sparse":
        accompaniment["bass"] = [chord.root]
        accompaniment["chords"] = [chord.notes[0], chord.notes[-1]]
        accompaniment["rhythm"] = [chord.root]

    return accompaniment


# ============================================================================
# Texture Generation
# ============================================================================


def texture_density(melody: list[Note], density_level: float) -> list[Note]:
    """Add texture/filler notes based on density level.

    Args:
        melody: Original melody.
        density_level: Density (0.0 = sparse, 1.0 = dense).

    Returns:
        Melody with texture added.
    """
    import random

    textured: list[Note] = []

    for note in melody:
        textured.append(note)

        if random.random() < density_level:
            transposed = theory.transpose(note, random.choice([-12, -5, 5, 12]))
            try:
                textured.append(transposed)
            except InvalidNoteError:
                pass

    return textured


def orchestrate_for_ensemble(melody: list[Note], chord_progression: list[Chord]) -> dict[str, list[Note]]:
    """Create ensemble orchestration from melody and chords.

    Args:
        melody: Melodic line.
        chord_progression: Chord progression.

    Returns:
        Dictionary mapping instrument/part names to note sequences.
    """
    orchestration: dict[str, list[Note]] = {}

    orchestration["melody"] = melody

    orchestration["violin_doubling"] = double_melody_at_octave(melody, 1)

    all_bass = []
    for chord in chord_progression:
        all_bass.append(chord.root)
    orchestration["cello"] = all_bass

    all_chords = []
    for chord in chord_progression:
        voicing = voicing_for_pad(chord, 48)
        all_chords.extend(voicing)
    orchestration["strings_pad"] = all_chords

    return orchestration
