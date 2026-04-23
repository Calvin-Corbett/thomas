"""Tests for music.chords module."""

import pytest

from thomas.marketplace.music import chords
from thomas.marketplace.music._exceptions import InvalidChordError
from thomas.marketplace.music._types import Accidental, ChordQuality, Note, NoteName, Pitch


class TestChordConstruction:
    """Test chord construction functions."""

    def test_major_chord(self) -> None:
        """Test major triad construction."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.major_chord(c4)

        assert chord.quality == ChordQuality.MAJOR
        assert len(chord.notes) == 3
        assert chord.notes[0] == c4

    def test_minor_chord(self) -> None:
        """Test minor triad construction."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.minor_chord(c4)

        assert chord.quality == ChordQuality.MINOR
        assert len(chord.notes) == 3

    def test_diminished_chord(self) -> None:
        """Test diminished triad construction."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.diminished_chord(c4)

        assert chord.quality == ChordQuality.DIMINISHED
        assert len(chord.notes) == 3

    def test_augmented_chord(self) -> None:
        """Test augmented triad construction."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.augmented_chord(c4)

        assert chord.quality == ChordQuality.AUGMENTED
        assert len(chord.notes) == 3

    def test_dominant_seventh_chord(self) -> None:
        """Test dominant seventh chord."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.dominant_seventh_chord(c4)

        assert chord.quality == ChordQuality.DOMINANT_7
        assert len(chord.notes) == 4

    def test_major_seventh_chord(self) -> None:
        """Test major seventh chord."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.major_seventh_chord(c4)

        assert chord.quality == ChordQuality.MAJOR_7
        assert len(chord.notes) == 4

    def test_sus2_chord(self) -> None:
        """Test sus2 chord."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.sus2_chord(c4)

        assert chord.quality == ChordQuality.SUS2
        assert len(chord.notes) == 3

    def test_sus4_chord(self) -> None:
        """Test sus4 chord."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.sus4_chord(c4)

        assert chord.quality == ChordQuality.SUS4
        assert len(chord.notes) == 3


class TestChordInversion:
    """Test chord inversion."""

    def test_first_inversion(self) -> None:
        """Test first inversion of chord."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.major_chord(c4)

        inverted = chords.invert_chord(chord, 1)

        assert inverted.inversion == 1
        assert inverted.bass_note().pitch.note == NoteName.E

    def test_second_inversion(self) -> None:
        """Test second inversion of chord."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.major_chord(c4)

        inverted = chords.invert_chord(chord, 2)

        assert inverted.inversion == 2
        assert inverted.bass_note().pitch.note == NoteName.G

    def test_root_position_from_inversion(self) -> None:
        """Test converting inversion back to root position."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.major_chord(c4)
        inverted = chords.invert_chord(chord, 1)

        root_pos = chords.root_position(inverted)

        assert root_pos.inversion == 0
        assert root_pos.root == c4


class TestChordSymbolParsing:
    """Test chord symbol parsing."""

    def test_parse_major_chord(self) -> None:
        """Test parsing major chord symbol."""
        chord = chords.parse_chord_symbol("C")

        assert chord.quality == ChordQuality.MAJOR
        assert chord.root.pitch.note == NoteName.C

    def test_parse_minor_chord(self) -> None:
        """Test parsing minor chord symbol."""
        chord = chords.parse_chord_symbol("Cm")

        assert chord.quality == ChordQuality.MINOR
        assert chord.root.pitch.note == NoteName.C

    def test_parse_major_seventh(self) -> None:
        """Test parsing major seventh chord."""
        chord = chords.parse_chord_symbol("Cmaj7")

        assert chord.quality == ChordQuality.MAJOR_7

    def test_parse_dominant_seventh(self) -> None:
        """Test parsing dominant seventh chord."""
        chord = chords.parse_chord_symbol("C7")

        assert chord.quality == ChordQuality.DOMINANT_7

    def test_parse_chord_with_sharp(self) -> None:
        """Test parsing chord with sharp."""
        chord = chords.parse_chord_symbol("F#m")

        assert chord.root.pitch.note == NoteName.F
        assert chord.root.pitch.accidental == Accidental.SHARP
        assert chord.quality == ChordQuality.MINOR

    def test_parse_chord_with_flat(self) -> None:
        """Test parsing chord with flat."""
        chord = chords.parse_chord_symbol("Bbmaj7")

        assert chord.root.pitch.note == NoteName.B
        assert chord.root.pitch.accidental == Accidental.FLAT

    def test_parse_invalid_chord_symbol(self) -> None:
        """Test parsing invalid chord symbol."""
        with pytest.raises(InvalidChordError):
            chords.parse_chord_symbol("H")


class TestRomanNumeralAnalysis:
    """Test Roman numeral chord analysis."""

    def test_chord_to_roman_numeral_tonic(self) -> None:
        """Test chord to Roman numeral for tonic chord."""
        c4 = Note(Pitch(NoteName.C), 4)
        chord = chords.major_chord(c4)

        roman = chords.chord_to_roman_numeral(chord, c4)

        assert roman == "I"

    def test_chord_to_roman_numeral_subdominant(self) -> None:
        """Test Roman numeral for subdominant."""
        c4 = Note(Pitch(NoteName.C), 4)
        f4 = Note(Pitch(NoteName.F), 4)
        chord = chords.major_chord(f4)

        roman = chords.chord_to_roman_numeral(chord, c4)

        assert roman == "IV"

    def test_chord_to_roman_numeral_dominant(self) -> None:
        """Test Roman numeral for dominant."""
        c4 = Note(Pitch(NoteName.C), 4)
        g4 = Note(Pitch(NoteName.G), 4)
        chord = chords.major_chord(g4)

        roman = chords.chord_to_roman_numeral(chord, c4)

        assert roman == "V"

    def test_roman_numeral_to_chord_iv(self) -> None:
        """Test Roman numeral to chord conversion."""
        c4 = Note(Pitch(NoteName.C), 4)

        chord = chords.roman_numeral_to_chord("IV", c4)

        assert chord.root.pitch.note == NoteName.F

    def test_roman_numeral_to_chord_vi(self) -> None:
        """Test Roman numeral vi (relative minor)."""
        c4 = Note(Pitch(NoteName.C), 4)

        chord = chords.roman_numeral_to_chord("vi", c4)

        assert chord.root.pitch.note == NoteName.A
        assert chord.quality == ChordQuality.MINOR


class TestChordProgression:
    """Test chord progression analysis."""

    def test_is_valid_progression(self) -> None:
        """Test chord progression validation."""
        c4 = Note(Pitch(NoteName.C), 4)
        f4 = Note(Pitch(NoteName.F), 4)
        g4 = Note(Pitch(NoteName.G), 4)

        chord_progression = [
            chords.major_chord(c4),
            chords.major_chord(f4),
            chords.major_chord(g4),
            chords.major_chord(c4),
        ]

        assert chords.is_valid_progression(chord_progression)

    def test_progression_strength_standard(self) -> None:
        """Test strength of standard progression."""
        c4 = Note(Pitch(NoteName.C), 4)
        f4 = Note(Pitch(NoteName.F), 4)
        g4 = Note(Pitch(NoteName.G), 4)

        chord_progression = [
            chords.major_chord(c4),
            chords.major_chord(f4),
            chords.major_chord(g4),
            chords.major_chord(c4),
        ]

        strength = chords.progression_strength(chord_progression, c4)

        assert strength == 1.0
