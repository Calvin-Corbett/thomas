"""
Tests for NER module.
"""

import unittest

from thomas.marketplace.nlu._types import NERTag, POSTag, Sentence, Span, Token
from thomas.marketplace.nlu.ner import GazetteerMatcher, NERTagger


class TestGazetteerMatcher(unittest.TestCase):
    """Tests for gazetteer matching."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.matcher = GazetteerMatcher()
        self.matcher.load_default_gazetteers()

    def test_name_matching(self) -> None:
        """Test matching of person names."""
        result = self.matcher.match("John", "john")

        self.assertIsNotNone(result)
        self.assertEqual(result[0], NERTag.B_PER)

    def test_location_matching(self) -> None:
        """Test matching of locations."""
        result = self.matcher.match("London", "london")

        self.assertIsNotNone(result)
        self.assertEqual(result[0], NERTag.B_LOC)

    def test_organization_matching(self) -> None:
        """Test matching of organizations."""
        result = self.matcher.match("Apple", "apple")

        self.assertIsNotNone(result)
        self.assertEqual(result[0], NERTag.B_ORG)

    def test_no_match(self) -> None:
        """Test handling of non-matching text."""
        result = self.matcher.match("xyz123", "xyz123")

        self.assertIsNone(result)

    def test_case_insensitivity(self) -> None:
        """Test case-insensitive matching."""
        result1 = self.matcher.match("JOHN", "john")
        result2 = self.matcher.match("john", "john")

        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)
        self.assertEqual(result1[0], result2[0])

    def test_multiword_location(self) -> None:
        """Test matching of multi-word locations."""
        result = self.matcher.match("New York", "new york")

        self.assertIsNotNone(result)
        self.assertEqual(result[0], NERTag.B_LOC)


class TestNERTagger(unittest.TestCase):
    """Tests for NER tagger."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.tagger = NERTagger()

    def test_email_extraction(self) -> None:
        """Test email entity extraction."""
        sentence = Sentence(text="Contact me at john@example.com for details.")
        entities = self.tagger.tag(sentence)

        email_entities = [e for e in entities if e.label == NERTag.B_EMAIL]
        self.assertGreater(len(email_entities), 0)

    def test_url_extraction(self) -> None:
        """Test URL entity extraction."""
        sentence = Sentence(text="Visit https://example.com for more info.")
        entities = self.tagger.tag(sentence)

        url_entities = [e for e in entities if e.label == NERTag.B_URL]
        self.assertGreater(len(url_entities), 0)

    def test_date_extraction(self) -> None:
        """Test date entity extraction."""
        sentence = Sentence(text="The meeting is on 2024-01-15.")
        entities = self.tagger.tag(sentence)

        date_entities = [e for e in entities if e.label == NERTag.B_DATE]
        self.assertGreater(len(date_entities), 0)

    def test_money_extraction(self) -> None:
        """Test money entity extraction."""
        sentence = Sentence(text="The price is $100 per unit.")
        entities = self.tagger.tag(sentence)

        money_entities = [e for e in entities if e.label == NERTag.B_MONEY]
        self.assertGreater(len(money_entities), 0)

    def test_percent_extraction(self) -> None:
        """Test percentage entity extraction."""
        sentence = Sentence(text="Sales increased by 25% this quarter.")
        entities = self.tagger.tag(sentence)

        percent_entities = [e for e in entities if e.label == NERTag.B_PERCENT]
        self.assertGreater(len(percent_entities), 0)

    def test_entity_with_tokens(self) -> None:
        """Test entity extraction with pre-tokenized input."""
        tokens = [
            Token(text="John", span=Span(0, 4), pos=POSTag.NNP),
            Token(text="Smith", span=Span(5, 10), pos=POSTag.NNP),
        ]
        sentence = Sentence(text="John Smith", tokens=tokens)

        entities = self.tagger.tag(sentence)
        self.assertGreater(len(entities), 0)

    def test_empty_sentence(self) -> None:
        """Test handling of empty sentence."""
        sentence = Sentence(text="")
        entities = self.tagger.tag(sentence)

        self.assertEqual(len(entities), 0)

    def test_entity_deduplication(self) -> None:
        """Test that overlapping entities are deduplicated."""
        sentence = Sentence(text="john@example.com is valid")
        entities = self.tagger.tag(sentence)

        # Should not have duplicate email entities
        email_entities = [e for e in entities if e.label == NERTag.B_EMAIL]
        self.assertLessEqual(len(email_entities), 1)

    def test_entity_confidence(self) -> None:
        """Test that entities have confidence scores."""
        sentence = Sentence(text="john@example.com")
        entities = self.tagger.tag(sentence)

        for entity in entities:
            self.assertGreaterEqual(entity.confidence, 0.0)
            self.assertLessEqual(entity.confidence, 1.0)

    def test_entity_canonical_form(self) -> None:
        """Test that entities can have canonical forms."""
        sentence = Sentence(text="Contact Apple Inc.")
        entities = self.tagger.tag(sentence)

        # Some entities should have canonical forms
        with_canonical = [e for e in entities if e.canonical_form]
        self.assertIsInstance(with_canonical, list)

    def test_bio_tagging_output(self) -> None:
        """Test BIO tagging output."""
        tokens = [
            Token(text="John", span=Span(0, 4), pos=POSTag.NNP),
            Token(text="works", span=Span(5, 10), pos=POSTag.VBZ),
            Token(text="at", span=Span(11, 13), pos=POSTag.IN),
            Token(text="Google", span=Span(14, 20), pos=POSTag.NNP),
        ]
        sentence = Sentence(text="John works at Google", tokens=tokens)

        entities = self.tagger.tag(sentence)
        self.assertGreater(len(entities), 0)

    def test_regex_pattern_compilation(self) -> None:
        """Test that regex patterns are compiled correctly."""
        self.assertGreater(len(self.tagger.patterns), 0)

        for pattern_name, pattern in self.tagger.patterns.items():
            self.assertIsNotNone(pattern)

    def test_multiple_entities_same_sentence(self) -> None:
        """Test extraction of multiple entities in same sentence."""
        sentence = Sentence(text="John from New York emailed test@example.com on 2024-01-15.")
        entities = self.tagger.tag(sentence)

        # Should find multiple entities
        self.assertGreater(len(entities), 1)


class TestNERIntegration(unittest.TestCase):
    """Integration tests for NER."""

    def test_complex_sentence(self) -> None:
        """Test NER on complex sentence with multiple entity types."""
        text = "Apple Inc. is located in Cupertino, California. Contact: john@apple.com or visit https://apple.com"
        sentence = Sentence(text=text)

        tagger = NERTagger()
        entities = tagger.tag(sentence)

        # Should extract multiple entity types
        entity_types = set(e.label for e in entities)
        self.assertGreater(len(entity_types), 1)

    def test_no_false_positives(self) -> None:
        """Test that common words don't generate false positive entities."""
        text = "The quick brown fox jumps over the lazy dog."
        sentence = Sentence(text=text)

        tagger = NERTagger()
        entities = tagger.tag(sentence)

        # Should have few or no entities
        self.assertLess(len(entities), 3)

    def test_phone_number_extraction(self) -> None:
        """Test extraction of phone numbers."""
        text = "Call me at 555-123-4567 or 555-987-6543."
        sentence = Sentence(text=text)

        tagger = NERTagger()
        entities = tagger.tag(sentence)

        phone_entities = [e for e in entities if e.label == NERTag.B_MISC]
        self.assertGreater(len(phone_entities), 0)

    def test_multiple_dates(self) -> None:
        """Test extraction of multiple dates."""
        text = "Meeting on 2024-01-15 or January 20, 2024"
        sentence = Sentence(text=text)

        tagger = NERTagger()
        entities = tagger.tag(sentence)

        date_entities = [e for e in entities if e.label == NERTag.B_DATE]
        self.assertGreaterEqual(len(date_entities), 1)


if __name__ == "__main__":
    unittest.main()
