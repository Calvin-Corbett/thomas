"""Tests for music.harmony module."""

from thomas.music import chords, harmony
from thomas.music._types import Note


class TestVoiceRanges:
    """Test voice range functions."""

    def test_soprano_range(self) -> None:
        """Test soprano voice range."""
        low, high = harmony.get_voice_range(harmony.VoiceType.SOPRANO)

        assert low == 60
        assert high == 72

    def test_bass_range(self) -> None:
        """Test bass voice range."""
        low, high = harmony.get_voice_range(harmony.VoiceType.BASS)

        assert low == 24
        assert high == 36

    def test_note_in_range_soprano(self) -> None:
        """Test if note is in soprano range."""
        note = Note.parse("E4")
        assert harmony.is_note_in_range(note, harmony.VoiceType.SOPRANO)

    def test_note_out_of_range_soprano(self) -> None:
        """Test if note is outside soprano range."""
        note = Note.parse("C2")
        assert not harmony.is_note_in_range(note, harmony.VoiceType.SOPRANO)

    def test_transpose_to_voice_range(self) -> None:
        """Test transposing note to fit in voice range."""
        note = Note.parse("C1")
        transposed = harmony.transpose_to_voice_range(note, harmony.VoiceType.SOPRANO)

        assert harmony.is_note_in_range(transposed, harmony.VoiceType.SOPRANO)


class TestVoiceLeading:
    """Test voice leading rules."""

    def test_detect_parallel_fifths(self) -> None:
        """Test detection of parallel perfect fifths."""
        notes1 = [Note.parse("C4"), Note.parse("G4")]
        notes2 = [Note.parse("D4"), Note.parse("A4")]

        assert harmony.detect_parallel_fifths(notes1, notes2)

    def test_detect_no_parallel_fifths(self) -> None:
        """Test no parallel fifths when none exist."""
        notes1 = [Note.parse("C4"), Note.parse("E4")]
        notes2 = [Note.parse("D4"), Note.parse("D4")]

        assert not harmony.detect_parallel_fifths(notes1, notes2)

    def test_detect_parallel_octaves(self) -> None:
        """Test detection of parallel perfect octaves."""
        notes1 = [Note.parse("C4")]
        notes2 = [Note.parse("C5")]

        assert harmony.detect_parallel_octaves(notes1, notes2)

    def test_detect_voice_crossing(self) -> None:
        """Test voice crossing detection."""
        soprano = [Note.parse("E4")]
        alto = [Note.parse("F4")]
        tenor = [Note.parse("C3")]
        bass = [Note.parse("G2")]

        voices = [soprano, alto, tenor, bass]

        assert harmony.detect_voice_crossing(voices)

    def test_minimize_motion(self) -> None:
        """Test voice motion minimization."""
        c4 = Note.parse("C4")
        c_major = chords.major_chord(c4)

        g4 = Note.parse("G4")
        g_major = chords.major_chord(g4)

        notes1, notes2 = harmony.minimize_motion(c_major, g_major)

        total_motion = sum(abs(n2.to_midi_number() - n1.to_midi_number()) for n1, n2 in zip(notes1, notes2))

        assert total_motion < 50


class TestCadences:
    """Test cadence detection."""

    def test_authentic_cadence(self) -> None:
        """Test authentic cadence (V-I)."""
        c4 = Note.parse("C4")
        g4 = Note.parse("G4")

        chord_v = chords.major_chord(g4)
        chord_i = chords.major_chord(c4)

        cadence = harmony.detect_cadence(chord_v, chord_i, c4)

        assert cadence == harmony.CadenceType.AUTHENTIC

    def test_plagal_cadence(self) -> None:
        """Test plagal cadence (IV-I)."""
        c4 = Note.parse("C4")
        f4 = Note.parse("F4")

        chord_iv = chords.major_chord(f4)
        chord_i = chords.major_chord(c4)

        cadence = harmony.detect_cadence(chord_iv, chord_i, c4)

        assert cadence == harmony.CadenceType.PLAGAL

    def test_half_cadence(self) -> None:
        """Test half cadence (X-V)."""
        c4 = Note.parse("C4")
        f4 = Note.parse("F4")
        g4 = Note.parse("G4")

        chord_iv = chords.major_chord(f4)
        chord_v = chords.major_chord(g4)

        cadence = harmony.detect_cadence(chord_iv, chord_v, c4)

        assert cadence == harmony.CadenceType.HALF

    def test_deceptive_cadence(self) -> None:
        """Test deceptive cadence (V-vi)."""
        c4 = Note.parse("C4")
        g4 = Note.parse("G4")
        a4 = Note.parse("A4")

        chord_v = chords.major_chord(g4)
        chord_vi = chords.minor_chord(a4)

        cadence = harmony.detect_cadence(chord_v, chord_vi, c4)

        assert cadence == harmony.CadenceType.DECEPTIVE

    def test_is_authentic_cadence(self) -> None:
        """Test is_authentic_cadence helper."""
        c4 = Note.parse("C4")
        g4 = Note.parse("G4")

        chord_v = chords.major_chord(g4)
        chord_i = chords.major_chord(c4)

        assert harmony.is_authentic_cadence(chord_v, chord_i, c4)

    def test_is_plagal_cadence(self) -> None:
        """Test is_plagal_cadence helper."""
        c4 = Note.parse("C4")
        f4 = Note.parse("F4")

        chord_iv = chords.major_chord(f4)
        chord_i = chords.major_chord(c4)

        assert harmony.is_plagal_cadence(chord_iv, chord_i, c4)


class TestHarmonicAnalysis:
    """Test harmonic function analysis."""

    def test_chord_function_tonic(self) -> None:
        """Test identifying tonic function."""
        c4 = Note.parse("C4")
        chord = chords.major_chord(c4)

        function = harmony.chord_function(chord, c4)

        assert function == "tonic"

    def test_chord_function_subdominant(self) -> None:
        """Test identifying subdominant function."""
        c4 = Note.parse("C4")
        f4 = Note.parse("F4")

        chord = chords.major_chord(f4)

        function = harmony.chord_function(chord, c4)

        assert function == "subdominant"

    def test_chord_function_dominant(self) -> None:
        """Test identifying dominant function."""
        c4 = Note.parse("C4")
        g4 = Note.parse("G4")

        chord = chords.major_chord(g4)

        function = harmony.chord_function(chord, c4)

        assert function == "dominant"


class TestModulation:
    """Test modulation detection."""

    def test_find_pivot_chord(self) -> None:
        """Test finding pivot chord between keys."""
        c4 = Note.parse("C4")
        g4 = Note.parse("G4")

        c_major = chords.major_chord(c4)
        g_major = chords.major_chord(g4)

        chord_list = [c_major, g_major]

        pivot = harmony.find_pivot_chord(chord_list, c4, g4)

        assert pivot is not None
        assert pivot[0] >= 0

    def test_pivot_chord_empty_list(self) -> None:
        """Test pivot chord with empty list."""
        c4 = Note.parse("C4")
        g4 = Note.parse("G4")

        pivot = harmony.find_pivot_chord([], c4, g4)

        assert pivot is None
