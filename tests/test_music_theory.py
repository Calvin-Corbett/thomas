"""Tests for music.theory module."""

import pytest

from thomas.marketplace.music import theory
from thomas.marketplace.music._types import Accidental, IntervalQuality, Note, NoteName, Pitch, ScaleType


class TestIntervalCalculation:
    """Test interval calculation functions."""

    def test_semitones_between_ascending(self) -> None:
        """Test semitone calculation for ascending interval."""
        c4 = Note(Pitch(NoteName.C), 4)
        e4 = Note(Pitch(NoteName.E), 4)
        assert theory.semitones_between(c4, e4) == 4

    def test_semitones_between_descending(self) -> None:
        """Test semitone calculation for descending interval."""
        e4 = Note(Pitch(NoteName.E), 4)
        c4 = Note(Pitch(NoteName.C), 4)
        assert theory.semitones_between(e4, c4) == -4

    def test_semitones_between_octave(self) -> None:
        """Test semitones in an octave."""
        c4 = Note(Pitch(NoteName.C), 4)
        c5 = Note(Pitch(NoteName.C), 5)
        assert theory.semitones_between(c4, c5) == 12

    def test_interval_from_notes_major_third(self) -> None:
        """Test interval detection for major third."""
        c4 = Note(Pitch(NoteName.C), 4)
        e4 = Note(Pitch(NoteName.E), 4)
        interval = theory.interval_from_notes(c4, e4)
        assert interval.quality == IntervalQuality.MAJOR
        assert interval.semitones == 4
        assert "third" in interval.name.lower()

    def test_interval_from_notes_perfect_fifth(self) -> None:
        """Test interval detection for perfect fifth."""
        c4 = Note(Pitch(NoteName.C), 4)
        g4 = Note(Pitch(NoteName.G), 4)
        interval = theory.interval_from_notes(c4, g4)
        assert interval.quality == IntervalQuality.PERFECT
        assert interval.semitones == 7

    def test_interval_from_semitones(self) -> None:
        """Test interval creation from semitones."""
        interval = theory.interval_from_semitones(7, "fifth")
        assert interval.quality == IntervalQuality.PERFECT
        assert interval.semitones == 7

    def test_interval_inversion(self) -> None:
        """Test interval inversion."""
        interval = theory.interval_from_semitones(4, "third")
        inverted = interval.invert()
        assert inverted.quality == IntervalQuality.MINOR
        assert inverted.semitones == 8


class TestScaleConstruction:
    """Test scale building functions."""

    def test_build_major_scale(self) -> None:
        """Test major scale construction."""
        c4 = Note(Pitch(NoteName.C), 4)
        scale = theory.build_scale(c4, ScaleType.MAJOR)

        assert len(scale.notes) == 8
        assert scale.notes[0].pitch.note == NoteName.C
        assert scale.notes[1].pitch.note == NoteName.D
        assert scale.notes[4].pitch.note == NoteName.G

    def test_build_minor_scale(self) -> None:
        """Test natural minor scale construction."""
        a4 = Note(Pitch(NoteName.A), 4)
        scale = theory.build_scale(a4, ScaleType.NATURAL_MINOR)

        assert len(scale.notes) == 8
        assert scale.notes[0].pitch.note == NoteName.A

    def test_build_pentatonic_scale(self) -> None:
        """Test pentatonic scale construction."""
        g4 = Note(Pitch(NoteName.G), 4)
        scale = theory.build_scale(g4, ScaleType.PENTATONIC_MAJOR)

        assert len(scale.notes) == 6

    def test_scale_contains_pitch_class(self) -> None:
        """Test pitch class containment in scale."""
        c4 = Note(Pitch(NoteName.C), 4)
        scale = theory.build_scale(c4, ScaleType.MAJOR)

        assert scale.contains_pitch_class(Pitch(NoteName.E))
        assert not scale.contains_pitch_class(Pitch(NoteName.B, Accidental.FLAT))

    def test_scale_degree(self) -> None:
        """Test scale degree access."""
        c4 = Note(Pitch(NoteName.C), 4)
        scale = theory.build_scale(c4, ScaleType.MAJOR)

        assert scale.degree(1).pitch.note == NoteName.C
        assert scale.degree(4).pitch.note == NoteName.F
        assert scale.degree(7).pitch.note == NoteName.B


class TestKeySignatures:
    """Test key signature functions."""

    def test_key_signature_c_major(self) -> None:
        """Test C major key signature."""
        c4 = Note(Pitch(NoteName.C), 4)
        key = theory.build_key(c4, ScaleType.MAJOR)
        sig_type, count = theory.key_signature(key)

        assert sig_type == "natural"
        assert count == 0

    def test_key_signature_g_major(self) -> None:
        """Test G major key signature (1 sharp)."""
        g4 = Note(Pitch(NoteName.G), 4)
        key = theory.build_key(g4, ScaleType.MAJOR)
        sig_type, count = theory.key_signature(key)

        assert sig_type == "sharps"
        assert count == 1

    def test_key_signature_f_major(self) -> None:
        """Test F major key signature (1 flat)."""
        f4 = Note(Pitch(NoteName.F), 4)
        key = theory.build_key(f4, ScaleType.MAJOR)
        sig_type, count = theory.key_signature(key)

        assert sig_type == "flats"
        assert count == 1


class TestEnharmonic:
    """Test enharmonic equivalence."""

    def test_enharmonic_c_sharp_d_flat(self) -> None:
        """Test C# and Db enharmonic equivalence."""
        c_sharp = Note(Pitch(NoteName.C, Accidental.SHARP), 4)
        d_flat = theory.enharmonic_equivalent(c_sharp)

        assert d_flat.pitch.note == NoteName.D
        assert d_flat.pitch.accidental == Accidental.FLAT
        assert c_sharp.to_midi_number() == d_flat.to_midi_number()


class TestTransposition:
    """Test note transposition."""

    def test_transpose_up_semitones(self) -> None:
        """Test transposition up."""
        c4 = Note(Pitch(NoteName.C), 4)
        transposed = theory.transpose(c4, 2)

        assert transposed.pitch.note == NoteName.D
        assert transposed.octave == 4

    def test_transpose_down_semitones(self) -> None:
        """Test transposition down."""
        e4 = Note(Pitch(NoteName.E), 4)
        transposed = theory.transpose(e4, -2)

        assert transposed.pitch.note == NoteName.D
        assert transposed.octave == 4

    def test_transpose_across_octave(self) -> None:
        """Test transposition across octave boundary."""
        b3 = Note(Pitch(NoteName.B), 3)
        transposed = theory.transpose(b3, 2)

        assert transposed.pitch.note == NoteName.C
        assert transposed.octave == 4

    def test_transpose_out_of_range(self) -> None:
        """Test transposition out of MIDI range."""
        c0 = Note(Pitch(NoteName.C), 0)
        with pytest.raises(Exception):
            theory.transpose(c0, -100)


class TestFrequency:
    """Test frequency calculations."""

    def test_note_to_frequency_a4(self) -> None:
        """Test A4 = 440 Hz."""
        a4 = Note(Pitch(NoteName.A), 4)
        freq = theory.note_to_frequency(a4)

        assert abs(freq - 440.0) < 0.1

    def test_note_to_frequency_c4(self) -> None:
        """Test C4 frequency."""
        c4 = Note(Pitch(NoteName.C), 4)
        freq = theory.note_to_frequency(c4)

        assert 260 < freq < 270

    def test_frequency_to_note_a4(self) -> None:
        """Test frequency to note conversion."""
        note = theory.frequency_to_note(440.0)

        assert note.pitch.note == NoteName.A
        assert note.octave == 4

    def test_frequency_to_note_c4(self) -> None:
        """Test frequency to note conversion for C4."""
        c4_freq = theory.note_to_frequency(Note(Pitch(NoteName.C), 4))
        note = theory.frequency_to_note(c4_freq)

        assert note.pitch.note == NoteName.C
        assert note.octave == 4


class TestConsonance:
    """Test consonance detection."""

    def test_is_consonant_perfect_fifth(self) -> None:
        """Test perfect fifth is consonant."""
        interval = theory.interval_from_semitones(7, "fifth")
        assert theory.is_consonant_interval(interval)

    def test_is_consonant_major_third(self) -> None:
        """Test major third is consonant."""
        interval = theory.interval_from_semitones(4, "third")
        assert theory.is_consonant_interval(interval)

    def test_is_not_consonant_tritone(self) -> None:
        """Test tritone is dissonant."""
        interval = theory.interval_from_semitones(6, "fourth")
        assert not theory.is_consonant_interval(interval)

    def test_is_perfect_interval_fifth(self) -> None:
        """Test perfect fifth is perfect."""
        interval = theory.interval_from_semitones(7, "fifth")
        assert theory.is_perfect_interval(interval)

    def test_is_not_perfect_interval_third(self) -> None:
        """Test major third is not perfect."""
        interval = theory.interval_from_semitones(4, "third")
        assert not theory.is_perfect_interval(interval)


class TestPitchClassSets:
    """Test pitch class set operations."""

    def test_get_pitch_classes_c_major(self) -> None:
        """Test pitch classes of C major chord."""
        notes = [
            Note(Pitch(NoteName.C), 4),
            Note(Pitch(NoteName.E), 4),
            Note(Pitch(NoteName.G), 4),
        ]
        pcs = theory.get_pitch_classes(notes)

        assert pcs == {0, 4, 7}

    def test_pitch_class_set_to_string(self) -> None:
        """Test pitch class set string representation."""
        pcs = {0, 4, 7}
        result = theory.pitch_class_set_to_string(pcs)

        assert result == "[0,4,7]"
