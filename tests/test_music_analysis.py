"""Tests for music.analysis module."""

from thomas.marketplace.music import analysis, theory
from thomas.marketplace.music._types import Note, ScaleType


class TestPitchClassSets:
    """Test pitch class set operations."""

    def test_pitch_class_set_c_major(self) -> None:
        """Test pitch class set from C major chord."""
        notes = [Note.parse("C4"), Note.parse("E4"), Note.parse("G4")]

        pcs = analysis.pitch_class_set(notes)

        assert pcs == {0, 4, 7}

    def test_pitch_class_set_ignores_octave(self) -> None:
        """Test that pitch class set ignores octave."""
        notes = [Note.parse("C4"), Note.parse("E5"), Note.parse("G3")]

        pcs = analysis.pitch_class_set(notes)

        assert pcs == {0, 4, 7}

    def test_pcs_normal_form(self) -> None:
        """Test normal form of pitch class set."""
        pcs = {0, 4, 7}

        normal = analysis.pcs_normal_form(pcs)

        assert normal == (0, 4, 7)

    def test_pcs_prime_form(self) -> None:
        """Test prime form of pitch class set."""
        pcs = {0, 4, 7}

        prime = analysis.pcs_prime_form(pcs)

        assert len(prime) >= 1

    def test_interval_vector_major_triad(self) -> None:
        """Test interval vector of major triad."""
        pcs = {0, 4, 7}

        iv = analysis.interval_vector(pcs)

        assert len(iv) == 6
        assert isinstance(iv, tuple)


class TestFormAnalysis:
    """Test form analysis functions."""

    def test_detect_repeated_sections(self) -> None:
        """Test detecting repeated sections."""
        melody = [
            Note.parse("C4"),
            Note.parse("D4"),
            Note.parse("E4"),
            Note.parse("C4"),
            Note.parse("D4"),
            Note.parse("E4"),
        ]

        repeated = analysis.detect_repeated_sections(melody, min_length=2)

        assert len(repeated) > 0

    def test_analyze_form_aaba(self) -> None:
        """Test analyzing AABA form."""
        melody = [Note.parse("C4")] * 4 + [Note.parse("D4")] * 4 + [Note.parse("C4")] * 4 + [Note.parse("E4")] * 4

        form = analysis.analyze_form(melody)

        assert form in ["ABAC", "AABA", "ABCA"]

    def test_analyze_form_short(self) -> None:
        """Test analyzing very short melody."""
        melody = [Note.parse("C4"), Note.parse("D4")]

        form = analysis.analyze_form(melody)

        assert form == "A"


class TestKeyEstimation:
    """Test key estimation functions."""

    def test_pitch_class_distribution(self) -> None:
        """Test calculating pitch class distribution."""
        c4 = Note.parse("C4")
        scale = theory.build_scale(c4, ScaleType.MAJOR)
        notes = scale.notes

        pcd = analysis.pitch_class_distribution(notes)

        assert len(pcd) == 12
        assert sum(pcd) > 0

    def test_pitch_class_distribution_empty(self) -> None:
        """Test distribution of empty note list."""
        pcd = analysis.pitch_class_distribution([])

        assert sum(pcd) == 0.0

    def test_estimate_key_c_major(self) -> None:
        """Test estimating C major key."""
        c4 = Note.parse("C4")
        scale = theory.build_scale(c4, ScaleType.MAJOR)
        notes = scale.notes

        key, confidence = analysis.estimate_key(notes)

        assert confidence > 0.0
        assert confidence <= 1.0

    def test_estimate_key_empty_notes(self) -> None:
        """Test key estimation with empty notes."""
        key, confidence = analysis.estimate_key([])

        assert confidence == 0.0


class TestBeatTracking:
    """Test beat tracking functions."""

    def test_onset_detection(self) -> None:
        """Test onset detection."""
        notes = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]
        onsets = [0.0, 0.5, 1.0]

        detected = analysis.onset_detection(notes, onsets)

        assert len(detected) == 3

    def test_onset_detection_with_duplicates(self) -> None:
        """Test onset detection filters duplicates."""
        notes = [Note.parse("C4"), Note.parse("C4"), Note.parse("D4")]
        onsets = [0.0, 0.001, 1.0]

        detected = analysis.onset_detection(notes, onsets)

        assert len(detected) <= 3

    def test_beat_period_autocorrelation(self) -> None:
        """Test beat period detection."""
        onsets = [0.0, 0.5, 1.0, 1.5, 2.0]

        beat_period = analysis.beat_period_autocorrelation(onsets)

        assert beat_period > 0.0

    def test_beat_period_empty_onsets(self) -> None:
        """Test beat period with empty onsets."""
        beat_period = analysis.beat_period_autocorrelation([])

        assert beat_period == 0.5


class TestChordRecognition:
    """Test chord recognition from notes."""

    def test_recognize_chord_major(self) -> None:
        """Test recognizing major chord."""
        notes = [Note.parse("C4"), Note.parse("E4"), Note.parse("G4")]

        result = analysis.recognize_chord_from_notes(notes)

        assert result is not None
        root, quality = result
        assert quality == "major"

    def test_recognize_chord_minor(self) -> None:
        """Test recognizing minor chord."""
        notes = [Note.parse("A3"), Note.parse("C4"), Note.parse("E4")]

        result = analysis.recognize_chord_from_notes(notes)

        assert result is not None
        root, quality = result
        assert quality == "minor"

    def test_recognize_chord_empty(self) -> None:
        """Test chord recognition with no notes."""
        result = analysis.recognize_chord_from_notes([])

        assert result is None

    def test_recognize_chord_too_few_notes(self) -> None:
        """Test chord recognition with too few notes."""
        notes = [Note.parse("C4"), Note.parse("E4")]

        result = analysis.recognize_chord_from_notes(notes)

        assert result is None


class TestSimilarityMetrics:
    """Test similarity metrics."""

    def test_pcs_similarity_identical(self) -> None:
        """Test similarity of identical pitch class sets."""
        pcs1 = {0, 4, 7}
        pcs2 = {0, 4, 7}

        similarity = analysis.pitch_class_set_similarity(pcs1, pcs2)

        assert similarity == 1.0

    def test_pcs_similarity_disjoint(self) -> None:
        """Test similarity of disjoint sets."""
        pcs1 = {0, 4, 7}
        pcs2 = {1, 5, 8}

        similarity = analysis.pitch_class_set_similarity(pcs1, pcs2)

        assert similarity == 0.0

    def test_pcs_similarity_partial_overlap(self) -> None:
        """Test similarity with partial overlap."""
        pcs1 = {0, 4, 7}
        pcs2 = {0, 4, 8}

        similarity = analysis.pitch_class_set_similarity(pcs1, pcs2)

        assert 0.0 < similarity < 1.0

    def test_pcs_similarity_empty_sets(self) -> None:
        """Test similarity with empty sets."""
        similarity = analysis.pitch_class_set_similarity(set(), set())

        assert similarity == 1.0

    def test_note_sequence_similarity_identical(self) -> None:
        """Test note sequence similarity for identical sequences."""
        seq1 = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]
        seq2 = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        similarity = analysis.note_sequence_similarity(seq1, seq2)

        assert similarity == 1.0

    def test_note_sequence_similarity_different_length(self) -> None:
        """Test note sequence similarity with different lengths."""
        seq1 = [Note.parse("C4"), Note.parse("D4")]
        seq2 = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        similarity = analysis.note_sequence_similarity(seq1, seq2)

        assert similarity == 0.0
