"""
Tests for voice phonetics module.
"""

import pytest

from thomas.voice._exceptions import PhoneticsError
from thomas.voice._types import PhonemeType, StressLevel
from thomas.voice.phonetics import (
    PhonemeSet,
    PhoneticsProcessor,
)


class TestPhonemeSet:
    """Tests for PhonemeSet class."""

    def test_phoneme_exists(self) -> None:
        """Test phoneme exists in set."""
        assert "AA" in PhonemeSet.PHONEMES
        assert "B" in PhonemeSet.PHONEMES

    def test_get_phoneme_properties(self) -> None:
        """Test getting phoneme properties."""
        props = PhonemeSet.get_phoneme_properties("AA")

        assert "type" in props
        assert props["type"] == PhonemeType.VOWEL

    def test_get_invalid_phoneme(self) -> None:
        """Test getting invalid phoneme raises error."""
        with pytest.raises(PhoneticsError):
            PhonemeSet.get_phoneme_properties("XX")

    def test_is_vowel(self) -> None:
        """Test vowel classification."""
        assert PhonemeSet.is_vowel("AA")
        assert PhonemeSet.is_vowel("EH")
        assert not PhonemeSet.is_vowel("B")
        assert not PhonemeSet.is_vowel("T")

    def test_is_consonant(self) -> None:
        """Test consonant classification."""
        assert PhonemeSet.is_consonant("B")
        assert PhonemeSet.is_consonant("T")
        assert not PhonemeSet.is_consonant("AA")
        assert not PhonemeSet.is_consonant("EH")

    def test_unknown_phoneme_is_vowel(self) -> None:
        """Test is_vowel returns False for unknown phoneme."""
        assert not PhonemeSet.is_vowel("XX")

    def test_unknown_phoneme_is_consonant(self) -> None:
        """Test is_consonant returns False for unknown phoneme."""
        assert not PhonemeSet.is_consonant("XX")

    def test_phoneme_count(self) -> None:
        """Test total phoneme count."""
        # Should have 39 phonemes (14 vowels + 25 consonants)
        assert len(PhonemeSet.PHONEMES) == 39

    def test_dictionary_lookup(self) -> None:
        """Test pronunciation dictionary."""
        assert "hello" in PhonemeSet.DICTIONARY
        assert "cat" in PhonemeSet.DICTIONARY

    def test_duration_statistics(self) -> None:
        """Test duration statistics."""
        assert "AA" in PhonemeSet.DURATION_STATISTICS
        stats = PhonemeSet.DURATION_STATISTICS["AA"]
        assert "mean" in stats
        assert "std" in stats


class TestPhoneticsProcessor:
    """Tests for PhoneticsProcessor class."""

    @pytest.fixture
    def processor(self) -> PhoneticsProcessor:
        """Create phonetics processor."""
        return PhoneticsProcessor()

    def test_grapheme_to_phoneme_dictionary_word(self, processor: PhoneticsProcessor) -> None:
        """Test grapheme-to-phoneme with dictionary lookup."""
        phonemes = processor.grapheme_to_phoneme("hello")

        assert isinstance(phonemes, list)
        assert len(phonemes) > 0

    def test_grapheme_to_phoneme_unknown_word(self, processor: PhoneticsProcessor) -> None:
        """Test grapheme-to-phoneme with unknown word."""
        phonemes = processor.grapheme_to_phoneme("xyzabc")

        # Should fallback to rules
        assert isinstance(phonemes, list)

    def test_grapheme_to_phoneme_case_insensitive(self, processor: PhoneticsProcessor) -> None:
        """Test grapheme-to-phoneme is case insensitive."""
        phonemes_lower = processor.grapheme_to_phoneme("hello")
        phonemes_upper = processor.grapheme_to_phoneme("HELLO")

        assert phonemes_lower == phonemes_upper

    def test_syllabify(self, processor: PhoneticsProcessor) -> None:
        """Test syllabification."""
        phonemes = ["HH", "EH", "L", "OW"]
        syllables = processor.syllabify(phonemes)

        assert isinstance(syllables, list)
        assert len(syllables) > 0

    def test_assign_stress(self, processor: PhoneticsProcessor) -> None:
        """Test stress assignment."""
        phonemes = ["HH", "EH", "L", "OW"]
        stress = processor.assign_stress(phonemes)

        assert len(stress) == len(phonemes)
        assert all(isinstance(s, StressLevel) for s in stress)

    def test_get_phoneme_duration(self, processor: PhoneticsProcessor) -> None:
        """Test phoneme duration estimation."""
        mean, std = processor.get_phoneme_duration("AA")

        assert mean > 0
        assert std > 0
        assert mean > std  # Mean should be larger than std

    def test_get_phoneme_duration_default(self, processor: PhoneticsProcessor) -> None:
        """Test phoneme duration for unknown phoneme."""
        mean, std = processor.get_phoneme_duration("XX")

        # Should return default values
        assert mean > 0
        assert std > 0

    def test_create_phoneme(self, processor: PhoneticsProcessor) -> None:
        """Test phoneme creation."""
        phoneme = processor.create_phoneme("AA", start_time=0.0, end_time=0.1)

        assert phoneme.arpabet == "AA"
        assert phoneme.start_time == 0.0
        assert phoneme.end_time == 0.1
        assert phoneme.phoneme_type == PhonemeType.VOWEL

    def test_create_phoneme_duration(self, processor: PhoneticsProcessor) -> None:
        """Test phoneme duration property."""
        phoneme = processor.create_phoneme("AA", start_time=0.0, end_time=0.15)

        assert phoneme.duration == 0.15

    def test_lookup_pronunciation(self, processor: PhoneticsProcessor) -> None:
        """Test pronunciation dictionary lookup."""
        pronunciation = processor.lookup_pronunciation("hello")

        assert pronunciation is not None
        assert isinstance(pronunciation, list)

    def test_lookup_pronunciation_missing(self, processor: PhoneticsProcessor) -> None:
        """Test pronunciation lookup for missing word."""
        pronunciation = processor.lookup_pronunciation("xyznotaword")

        assert pronunciation is None

    def test_lookup_pronunciation_case_insensitive(self, processor: PhoneticsProcessor) -> None:
        """Test pronunciation lookup is case insensitive."""
        result_lower = processor.lookup_pronunciation("hello")
        result_upper = processor.lookup_pronunciation("HELLO")

        assert result_lower == result_upper

    def test_create_invalid_phoneme(self, processor: PhoneticsProcessor) -> None:
        """Test creating invalid phoneme."""
        with pytest.raises(PhoneticsError):
            processor.create_phoneme("XX", 0.0, 0.1)

    def test_voiced_consonant_properties(self, processor: PhoneticsProcessor) -> None:
        """Test voiced consonant properties."""
        phoneme = processor.create_phoneme("B", 0.0, 0.05)

        assert phoneme.is_voiced

    def test_unvoiced_consonant_properties(self, processor: PhoneticsProcessor) -> None:
        """Test unvoiced consonant properties."""
        phoneme = processor.create_phoneme("P", 0.0, 0.05)

        assert not phoneme.is_voiced

    def test_syllabify_single_phoneme(self, processor: PhoneticsProcessor) -> None:
        """Test syllabification of single phoneme."""
        phonemes = ["AA"]
        syllables = processor.syllabify(phonemes)

        assert len(syllables) > 0

    def test_stress_list_length(self, processor: PhoneticsProcessor) -> None:
        """Test stress list has same length as phonemes."""
        phonemes = processor.grapheme_to_phoneme("hello")
        stress = processor.assign_stress(phonemes)

        assert len(stress) == len(phonemes)

    def test_phoneme_count_exhaustive(self) -> None:
        """Test all phonemes are accessible."""
        for phoneme_code in PhonemeSet.PHONEMES:
            props = PhonemeSet.get_phoneme_properties(phoneme_code)
            assert props["type"] in [PhonemeType.VOWEL, PhonemeType.CONSONANT]

    def test_grapheme_to_phoneme_consistency(self, processor: PhoneticsProcessor) -> None:
        """Test grapheme-to-phoneme consistency."""
        phonemes1 = processor.grapheme_to_phoneme("hello")
        phonemes2 = processor.grapheme_to_phoneme("hello")

        assert phonemes1 == phonemes2
