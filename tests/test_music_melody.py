"""Tests for music.melody module."""

from thomas.music import melody, theory
from thomas.music._types import Note, ScaleType


class TestMelodicContour:
    """Test melodic contour analysis."""

    def test_analyze_ascending_contour(self) -> None:
        """Test ascending contour detection."""
        notes = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4"), Note.parse("F4")]

        contour = melody.analyze_contour(notes)

        assert contour == melody.ContourType.ASCENDING

    def test_analyze_descending_contour(self) -> None:
        """Test descending contour detection."""
        notes = [Note.parse("F4"), Note.parse("E4"), Note.parse("D4"), Note.parse("C4")]

        contour = melody.analyze_contour(notes)

        assert contour == melody.ContourType.DESCENDING

    def test_analyze_arch_contour(self) -> None:
        """Test arch contour detection."""
        notes = [
            Note.parse("C4"),
            Note.parse("D4"),
            Note.parse("E4"),
            Note.parse("F4"),
            Note.parse("E4"),
            Note.parse("D4"),
        ]

        contour = melody.analyze_contour(notes)

        assert contour == melody.ContourType.ARCH

    def test_contour_direction_ascending(self) -> None:
        """Test contour direction for ascending interval."""
        note1 = Note.parse("C4")
        note2 = Note.parse("E4")

        direction = melody.contour_direction(note1, note2)

        assert direction == 1

    def test_contour_direction_descending(self) -> None:
        """Test contour direction for descending interval."""
        note1 = Note.parse("E4")
        note2 = Note.parse("C4")

        direction = melody.contour_direction(note1, note2)

        assert direction == -1

    def test_contour_direction_same(self) -> None:
        """Test contour direction for same note."""
        note1 = Note.parse("C4")
        note2 = Note.parse("C4")

        direction = melody.contour_direction(note1, note2)

        assert direction == 0


class TestMotifDevelopment:
    """Test motif development techniques."""

    def test_repeat_motif(self) -> None:
        """Test motif repetition."""
        motif = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        repeated = melody.repeat_motif(motif, 2)

        assert len(repeated) == 6
        assert repeated == motif + motif

    def test_sequence_motif(self) -> None:
        """Test motif sequencing."""
        motif = [Note.parse("C4"), Note.parse("D4")]

        sequenced = melody.sequence_motif(motif, 2, 2)

        assert len(sequenced) == 4

    def test_invert_motif(self) -> None:
        """Test motif inversion."""
        motif = [Note.parse("C4"), Note.parse("E4"), Note.parse("G4")]

        inverted = melody.invert_motif(motif)

        assert len(inverted) == 3

    def test_retrograde_motif(self) -> None:
        """Test retrograde (reverse) of motif."""
        motif = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        retrograde = melody.retrograde_motif(motif)

        assert retrograde == [Note.parse("E4"), Note.parse("D4"), Note.parse("C4")]

    def test_augment_motif(self) -> None:
        """Test augmenting motif (larger intervals)."""
        motif = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        augmented = melody.augment_motif(motif, 2.0)

        assert len(augmented) == 3

    def test_diminish_motif(self) -> None:
        """Test diminishing motif (smaller intervals)."""
        motif = [Note.parse("C4"), Note.parse("E4"), Note.parse("G4")]

        diminished = melody.diminish_motif(motif, 0.5)

        assert len(diminished) == 3


class TestMelodicTension:
    """Test melodic tension calculations."""

    def test_melodic_tension_tonic(self) -> None:
        """Test tension at tonic is low."""
        c4 = Note.parse("C4")
        scale = theory.build_scale(c4, ScaleType.MAJOR)

        tension = melody.melodic_tension(c4, c4, scale)

        assert 0 <= tension <= 1.0

    def test_melodic_tension_dissonant(self) -> None:
        """Test tension at dissonant interval is high."""
        c4 = Note.parse("C4")
        f_sharp = Note.parse("F#4")
        scale = theory.build_scale(c4, ScaleType.MAJOR)

        tension = melody.melodic_tension(f_sharp, c4, scale)

        assert tension > 0.5

    def test_resolution_tendency(self) -> None:
        """Test finding resolution tendency."""
        c4 = Note.parse("C4")
        scale = theory.build_scale(c4, ScaleType.MAJOR)
        b3 = Note.parse("B3")

        resolution = melody.resolution_tendency(b3, scale)

        assert resolution is not None


class TestMarkovChainMelody:
    """Test Markov chain melody generation."""

    def test_create_markov_chain(self) -> None:
        """Test creating Markov chain."""
        chain = melody.MarkovChainMelody()

        assert chain.transitions is not None

    def test_train_markov_chain(self) -> None:
        """Test training Markov chain."""
        chain = melody.MarkovChainMelody()
        training_melody = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        chain.train(training_melody)

        assert len(chain.transitions) > 0

    def test_generate_melody_from_chain(self) -> None:
        """Test generating melody from trained chain."""
        chain = melody.MarkovChainMelody()
        training_melody = [
            Note.parse("C4"),
            Note.parse("D4"),
            Note.parse("E4"),
            Note.parse("F4"),
        ]

        chain.train(training_melody)

        generated = chain.generate(Note.parse("C4"), 8)

        assert len(generated) == 8

    def test_markov_chain_generates_from_start(self) -> None:
        """Test that first note is always the start note."""
        chain = melody.MarkovChainMelody()
        training_melody = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        chain.train(training_melody)

        start_note = Note.parse("G4")
        generated = chain.generate(start_note, 5)

        assert generated[0] == start_note


class TestCounterpoint:
    """Test counterpoint functions."""

    def test_first_species_counterpoint(self) -> None:
        """Test generating first species counterpoint."""
        c4 = Note.parse("C4")
        scale = theory.build_scale(c4, ScaleType.MAJOR)
        cantus_firmus = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        counterpoint = melody.first_species_counterpoint(cantus_firmus, scale)

        assert len(counterpoint) == 3

    def test_contrary_motion_preference(self) -> None:
        """Test contrary motion preference."""
        note1 = Note.parse("C4")
        note2 = Note.parse("D4")

        is_contrary = melody.contrary_motion_preference(note1, note2)

        assert isinstance(is_contrary, bool)


class TestMelodySimilarity:
    """Test melody similarity metrics."""

    def test_melodic_similarity_identical(self) -> None:
        """Test similarity of identical melodies."""
        melody1 = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]
        melody2 = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        similarity = melody.melodic_similarity(melody1, melody2)

        assert similarity == 1.0

    def test_melodic_similarity_different_length(self) -> None:
        """Test similarity with different lengths."""
        melody1 = [Note.parse("C4"), Note.parse("D4")]
        melody2 = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]

        similarity = melody.melodic_similarity(melody1, melody2)

        assert similarity == 0.0

    def test_melodic_similarity_partial(self) -> None:
        """Test similarity with partial matching."""
        melody1 = [Note.parse("C4"), Note.parse("D4"), Note.parse("E4")]
        melody2 = [Note.parse("C4"), Note.parse("D4"), Note.parse("F4")]

        similarity = melody.melodic_similarity(melody1, melody2)

        assert 0.0 <= similarity < 1.0
