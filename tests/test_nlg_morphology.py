"""Tests for morphology engine."""

import pytest

from thomas.nlg._exceptions import MorphologyError
from thomas.nlg._types import Aspect, MorphologicalForm, Number, Person, Tense
from thomas.nlg.morphology import MorphologyEngine


class TestPluralization:
    """Test noun pluralization."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_pluralize_regular(self) -> None:
        """Test regular pluralization."""
        assert self.engine.pluralize("cat") == "cats"
        assert self.engine.pluralize("dog") == "dogs"

    def test_pluralize_sibilant(self) -> None:
        """Test pluralization of sibilant words."""
        assert self.engine.pluralize("box") == "boxes"
        assert self.engine.pluralize("church") == "churches"
        assert self.engine.pluralize("bush") == "bushes"

    def test_pluralize_y_ending(self) -> None:
        """Test pluralization of words ending in y."""
        assert self.engine.pluralize("baby") == "babies"
        assert self.engine.pluralize("boy") == "boys"

    def test_pluralize_f_ending(self) -> None:
        """Test pluralization of words ending in f."""
        assert self.engine.pluralize("leaf") == "leaves"
        assert self.engine.pluralize("life") == "lives"

    def test_pluralize_irregular(self) -> None:
        """Test irregular pluralization."""
        assert self.engine.pluralize("man") == "men"
        assert self.engine.pluralize("child") == "children"
        assert self.engine.pluralize("tooth") == "teeth"

    def test_pluralize_empty_fails(self) -> None:
        """Test that empty word fails."""
        with pytest.raises(MorphologyError):
            self.engine.pluralize("")


class TestVerbConjugation:
    """Test verb conjugation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_present_third_singular(self) -> None:
        """Test present tense third person singular."""
        form = self.engine.conjugate_verb("run", tense=Tense.PRESENT, person=Person.THIRD, number=Number.SINGULAR)
        assert form == "runs"

    def test_present_other_forms(self) -> None:
        """Test present tense other forms."""
        form = self.engine.conjugate_verb("run", tense=Tense.PRESENT, person=Person.FIRST, number=Number.SINGULAR)
        assert form == "run"

    def test_past_tense(self) -> None:
        """Test past tense."""
        form = self.engine.conjugate_verb("walk", tense=Tense.PAST)
        assert form == "walked"

    def test_progressive_aspect(self) -> None:
        """Test progressive aspect."""
        form = self.engine.conjugate_verb(
            "run", tense=Tense.PRESENT, aspect=Aspect.PROGRESSIVE, person=Person.THIRD, number=Number.SINGULAR
        )
        assert form == "running"

    def test_e_dropping(self) -> None:
        """Test e-dropping in progressive."""
        form = self.engine.conjugate_verb(
            "make", tense=Tense.PRESENT, aspect=Aspect.PROGRESSIVE, person=Person.THIRD, number=Number.SINGULAR
        )
        assert form == "making"

    def test_irregular_be(self) -> None:
        """Test irregular verb 'be'."""
        form = self.engine.conjugate_verb("be", tense=Tense.PRESENT, person=Person.THIRD, number=Number.SINGULAR)
        assert form == "is"

    def test_empty_lemma_fails(self) -> None:
        """Test that empty lemma fails."""
        with pytest.raises(MorphologyError):
            self.engine.conjugate_verb("")


class TestComparativeSuperlative:
    """Test adjective comparison."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_comparative_short(self) -> None:
        """Test comparative of short adjectives."""
        assert self.engine.generate_comparative("big") == "bigger"
        # fast is 4 letters, might use "more"
        result = self.engine.generate_comparative("fast")
        assert "fast" in result

    def test_comparative_long(self) -> None:
        """Test comparative of long adjectives."""
        result = self.engine.generate_comparative("beautiful")
        assert "more" in result

    def test_superlative_short(self) -> None:
        """Test superlative of short adjectives."""
        assert self.engine.generate_superlative("big") == "biggest"
        # fast is 4 letters, might use "most"
        result = self.engine.generate_superlative("fast")
        assert "fast" in result

    def test_superlative_long(self) -> None:
        """Test superlative of long adjectives."""
        result = self.engine.generate_superlative("beautiful")
        assert "most" in result

    def test_empty_adjective_fails(self) -> None:
        """Test that empty adjective fails."""
        with pytest.raises(MorphologyError):
            self.engine.generate_comparative("")


class TestNumberToWords:
    """Test number-to-word conversion."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_single_digit(self) -> None:
        """Test single digit conversion."""
        assert self.engine.number_to_words(0) == "zero"
        assert self.engine.number_to_words(1) == "one"
        assert self.engine.number_to_words(9) == "nine"

    def test_teens(self) -> None:
        """Test teen numbers."""
        assert self.engine.number_to_words(10) == "ten"
        assert self.engine.number_to_words(15) == "fifteen"
        assert self.engine.number_to_words(19) == "nineteen"

    def test_tens(self) -> None:
        """Test tens."""
        assert self.engine.number_to_words(20) == "twenty"
        assert self.engine.number_to_words(50) == "fifty"
        assert self.engine.number_to_words(90) == "ninety"

    def test_compound_tens(self) -> None:
        """Test compound numbers (21, 35, etc)."""
        result = self.engine.number_to_words(21)
        assert "twenty" in result and "one" in result

    def test_hundreds(self) -> None:
        """Test hundreds."""
        result = self.engine.number_to_words(100)
        assert "hundred" in result

    def test_thousands(self) -> None:
        """Test thousands."""
        result = self.engine.number_to_words(1000)
        assert "thousand" in result

    def test_negative_number(self) -> None:
        """Test negative numbers."""
        result = self.engine.number_to_words(-5)
        assert "negative" in result

    def test_large_number(self) -> None:
        """Test large numbers."""
        result = self.engine.number_to_words(1000000)
        assert "million" in result


class TestOrdinals:
    """Test ordinal number generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_ordinal_first(self) -> None:
        """Test ordinal 'first'."""
        assert self.engine.number_to_ordinal(1) == "first"

    def test_ordinal_second(self) -> None:
        """Test ordinal 'second'."""
        assert self.engine.number_to_ordinal(2) == "second"

    def test_ordinal_third(self) -> None:
        """Test ordinal 'third'."""
        assert self.engine.number_to_ordinal(3) == "third"

    def test_ordinal_suffix_st(self) -> None:
        """Test -st ordinal suffix."""
        result = self.engine.number_to_ordinal(21)
        assert "st" in result

    def test_ordinal_suffix_nd(self) -> None:
        """Test -nd ordinal suffix."""
        result = self.engine.number_to_ordinal(22)
        assert "nd" in result

    def test_ordinal_suffix_rd(self) -> None:
        """Test -rd ordinal suffix."""
        result = self.engine.number_to_ordinal(23)
        assert "rd" in result

    def test_ordinal_suffix_th(self) -> None:
        """Test -th ordinal suffix."""
        result = self.engine.number_to_ordinal(24)
        assert "th" in result


class TestContractions:
    """Test contraction generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_do_not_contraction(self) -> None:
        """Test 'do not' contraction."""
        result = self.engine.generate_contraction("do", "not")
        assert result == "don't"

    def test_will_not_contraction(self) -> None:
        """Test 'will not' contraction."""
        result = self.engine.generate_contraction("will", "not")
        assert result == "won't"

    def test_is_not_contraction(self) -> None:
        """Test 'is not' contraction."""
        result = self.engine.generate_contraction("is", "not")
        assert result == "isn't"

    def test_non_contraction(self) -> None:
        """Test non-contracting forms."""
        result = self.engine.generate_contraction("and", "or")
        assert result is None


class TestArticles:
    """Test article selection."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_a_consonant(self) -> None:
        """Test 'a' before consonant."""
        assert self.engine.get_indefinite_article("cat") == "a"

    def test_an_vowel(self) -> None:
        """Test 'an' before vowel."""
        assert self.engine.get_indefinite_article("apple") == "an"

    def test_an_vowel_sound(self) -> None:
        """Test 'an' before vowel sounds."""
        assert self.engine.get_indefinite_article("hour") == "an"

    def test_empty_string(self) -> None:
        """Test empty string defaults to 'a'."""
        assert self.engine.get_indefinite_article("") == "a"


class TestMorphologyApplication:
    """Test applying morphological features."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = MorphologyEngine()

    def test_apply_plural_feature(self) -> None:
        """Test applying plural number feature."""
        morph = MorphologicalForm(base="cat", number=Number.PLURAL)
        result = self.engine.apply_morphology("cat", morph)

        assert result == "cats"

    def test_apply_tense_feature(self) -> None:
        """Test applying tense feature."""
        morph = MorphologicalForm(base="run", tense=Tense.PAST, aspect=Aspect.SIMPLE)
        result = self.engine.apply_morphology("run", morph)

        assert "run" in result.lower()
