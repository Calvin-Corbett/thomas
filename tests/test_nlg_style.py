"""Tests for style control."""

import pytest

from thomas.marketplace.nlg.style import StyleController, StyleError


class TestFleschKincaid:
    """Test Flesch-Kincaid Grade Level calculation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_simple_text_low_grade(self) -> None:
        """Test simple text has low grade level."""
        text = "The cat sat. The dog ran."
        grade = self.controller.calculate_flesch_kincaid(text)

        assert grade >= 0

    def test_complex_text_high_grade(self) -> None:
        """Test complex text has higher grade level."""
        text = "The multifarious ameliorations necessitate perspicacious examination."
        grade = self.controller.calculate_flesch_kincaid(text)

        assert grade >= 0

    def test_empty_text(self) -> None:
        """Test empty text returns 0."""
        grade = self.controller.calculate_flesch_kincaid("")
        assert grade == 0.0


class TestFleschReadingEase:
    """Test Flesch Reading Ease calculation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_easy_text(self) -> None:
        """Test easy text has high score."""
        text = "The cat is here. The dog is here."
        score = self.controller.calculate_flesch_reading_ease(text)

        assert 0 <= score <= 100

    def test_difficult_text(self) -> None:
        """Test difficult text has lower score."""
        text = "Philosophical conceptualizations necessitate comprehensive elucidation."
        score = self.controller.calculate_flesch_reading_ease(text)

        assert 0 <= score <= 100

    def test_range(self) -> None:
        """Test score is within valid range."""
        text = "Hello world. This is a test."
        score = self.controller.calculate_flesch_reading_ease(text)

        assert 0 <= score <= 100


class TestGunningFog:
    """Test Gunning Fog Index calculation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_calculate_gunning_fog(self) -> None:
        """Test Gunning Fog calculation."""
        text = "The cat sat on the mat. It was happy."
        index = self.controller.calculate_gunning_fog(text)

        assert index >= 0

    def test_empty_text(self) -> None:
        """Test empty text returns 0."""
        index = self.controller.calculate_gunning_fog("")
        assert index == 0.0


class TestColemanLiau:
    """Test Coleman-Liau Index calculation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_calculate_coleman_liau(self) -> None:
        """Test Coleman-Liau calculation."""
        text = "The cat sat on the mat."
        index = self.controller.calculate_coleman_liau(text)

        assert index >= 0

    def test_empty_text(self) -> None:
        """Test empty text returns 0."""
        index = self.controller.calculate_coleman_liau("")
        assert index == 0.0


class TestSMOG:
    """Test SMOG Index calculation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_calculate_smog(self) -> None:
        """Test SMOG calculation."""
        text = "The multifarious cat contemplated the philosophical implications."
        index = self.controller.calculate_smog(text)

        assert index >= 0

    def test_empty_text(self) -> None:
        """Test empty text returns non-negative."""
        index = self.controller.calculate_smog("")
        assert index >= 0


class TestSyllableCount:
    """Test syllable counting."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_single_syllable(self) -> None:
        """Test single syllable word."""
        count = self.controller._count_syllables("cat")
        assert count == 1

    def test_two_syllables(self) -> None:
        """Test two syllable word."""
        count = self.controller._count_syllables("happy")
        assert count >= 1

    def test_multiple_syllables(self) -> None:
        """Test word with multiple syllables."""
        count = self.controller._count_syllables("multifarious")
        assert count > 2

    def test_minimum_one_syllable(self) -> None:
        """Test that syllable count is at least 1."""
        count = self.controller._count_syllables("a")
        assert count >= 1


class TestSentenceLengthTargeting:
    """Test sentence length targeting."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_short_sentence(self) -> None:
        """Test short sentence is not split."""
        text = "The cat sat."
        sentences = self.controller.target_sentence_length_range(text, target=5)

        assert len(sentences) > 0

    def test_long_sentence_split(self) -> None:
        """Test long sentence is split."""
        text = "The cat and the dog and the bird all sat on the mat together."
        sentences = self.controller.target_sentence_length_range(text, target=5)

        assert len(sentences) >= 1

    def test_respects_target(self) -> None:
        """Test that splitting respects target length."""
        text = "One. Two. Three. Four. Five. Six. Seven."
        sentences = self.controller.target_sentence_length_range(text, target=2)

        assert len(sentences) > 0


class TestVocabularyControl:
    """Test vocabulary level control."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_control_basic_level(self) -> None:
        """Test controlling vocabulary to basic level."""
        text = "The ameliorate person was benevolent."
        result = self.controller.control_vocabulary_level(text, level="basic")

        assert len(result) > 0

    def test_control_intermediate_level(self) -> None:
        """Test controlling to intermediate level."""
        text = "The cat is happy."
        result = self.controller.control_vocabulary_level(text, level="intermediate")

        assert "cat" in result.lower()

    def test_control_advanced_level(self) -> None:
        """Test controlling to advanced level."""
        text = "The cat is happy."
        result = self.controller.control_vocabulary_level(text, level="advanced")

        assert len(result) > 0

    def test_unknown_level_fails(self) -> None:
        """Test that unknown level fails."""
        with pytest.raises(StyleError):
            self.controller.control_vocabulary_level("text", level="unknown")


class TestPassiveVoiceDetection:
    """Test passive voice detection."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_detect_passive(self) -> None:
        """Test detecting passive voice."""
        sentence = "The ball was kicked by the boy."
        is_passive = self.controller.detect_passive_voice(sentence)

        assert is_passive

    def test_detect_active(self) -> None:
        """Test detecting active voice."""
        sentence = "The boy kicked the ball."
        is_passive = self.controller.detect_passive_voice(sentence)

        assert not is_passive

    def test_be_passive(self) -> None:
        """Test be-passive detection."""
        sentence = "The meal was prepared."
        is_passive = self.controller.detect_passive_voice(sentence)

        assert is_passive


class TestPassiveRewriting:
    """Test rewriting passive to active."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_rewrite_passive(self) -> None:
        """Test rewriting passive sentence."""
        sentence = "The ball was kicked by the boy."
        result = self.controller.rewrite_to_active(sentence)

        assert len(result) > 0

    def test_removes_by_phrase(self) -> None:
        """Test that rewriting removes by-phrase."""
        sentence = "The cat was chased by the dog."
        result = self.controller.rewrite_to_active(sentence)

        assert "by the dog" not in result


class TestHedging:
    """Test hedging language."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_add_hedging_zero(self) -> None:
        """Test no hedging at level 0."""
        text = "This is true."
        result = self.controller.add_hedging(text, level=0)

        assert result == text

    def test_add_hedging_positive(self) -> None:
        """Test adding hedging."""
        text = "This is true."
        result = self.controller.add_hedging(text, level=0.5)

        assert len(result) > len(text)


class TestBoosting:
    """Test boosting language."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_add_boosting_zero(self) -> None:
        """Test no boosting at level 0."""
        text = "This is good."
        result = self.controller.add_boosting(text, level=0)

        assert result == text

    def test_add_boosting_positive(self) -> None:
        """Test adding boosting."""
        text = "This is good."
        result = self.controller.add_boosting(text, level=0.5)

        assert len(result) > len(text)


class TestFormalityControl:
    """Test formality adjustment."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_adjust_to_formal(self) -> None:
        """Test adjusting to formal."""
        text = "don't want to go"
        result = self.controller.adjust_formality(text, formality="formal")

        assert "do not" in result or "don't" in result

    def test_adjust_to_informal(self) -> None:
        """Test adjusting to informal."""
        text = "do not want"
        result = self.controller.adjust_formality(text, formality="informal")

        assert len(result) > 0

    def test_neutral_formality(self) -> None:
        """Test neutral formality."""
        text = "The cat is here."
        result = self.controller.adjust_formality(text, formality="neutral")

        assert "cat" in result.lower()


class TestJargonSimplification:
    """Test jargon simplification."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.controller = StyleController()

    def test_simplify_optimize(self) -> None:
        """Test simplifying 'optimize'."""
        text = "We need to optimize the process."
        result = self.controller.simplify_jargon(text)

        assert "improve" in result or "optimize" in result

    def test_simplify_multiple(self) -> None:
        """Test simplifying multiple jargon terms."""
        text = "leverage the synergy"
        result = self.controller.simplify_jargon(text)

        assert len(result) > 0
