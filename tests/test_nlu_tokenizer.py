"""
Tests for tokenizer module.
"""

import unittest

from thomas.marketplace.nlu.tokenizer import BPETokenizer, CharacterNGramExtractor, Tokenizer


class TestTokenizer(unittest.TestCase):
    """Tests for basic tokenizer."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.tokenizer = Tokenizer(lowercase=False)

    def test_simple_tokenization(self) -> None:
        """Test simple whitespace tokenization."""
        text = "Hello world"
        tokens = self.tokenizer.tokenize(text)

        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0].text, "Hello")
        self.assertEqual(tokens[1].text, "world")

    def test_token_spans(self) -> None:
        """Test that token spans are correct."""
        text = "Hello world"
        tokens = self.tokenizer.tokenize(text)

        # Hello is at position 0-5
        self.assertEqual(tokens[0].span.start, 0)
        self.assertEqual(tokens[0].span.end, 5)

        # world is at position 6-11
        self.assertEqual(tokens[1].span.start, 6)
        self.assertEqual(tokens[1].span.end, 11)

    def test_punctuation_splitting(self) -> None:
        """Test splitting on punctuation."""
        text = "Hello, world!"
        tokens = self.tokenizer.tokenize(text)

        # Should have Hello, comma, world, exclamation
        self.assertGreaterEqual(len(tokens), 3)
        self.assertIn("Hello", [t.text for t in tokens])
        self.assertIn("world", [t.text for t in tokens])

    def test_empty_text(self) -> None:
        """Test handling of empty text."""
        tokens = self.tokenizer.tokenize("")
        self.assertEqual(len(tokens), 0)

    def test_sentence_tokenization(self) -> None:
        """Test sentence splitting."""
        text = "Hello world. This is a test."
        sentences = self.tokenizer.tokenize_sentences(text)

        self.assertEqual(len(sentences), 2)
        self.assertIn("Hello", sentences[0].text)
        self.assertIn("This", sentences[1].text)

    def test_abbreviation_handling(self) -> None:
        """Test that abbreviations don't trigger sentence boundary."""
        text = "Dr. Smith went to the store."
        sentences = self.tokenizer.tokenize_sentences(text)

        # Should be one sentence (Dr. is abbreviation)
        self.assertEqual(len(sentences), 1)

    def test_unicode_normalization(self) -> None:
        """Test unicode normalization."""
        text = "café"
        tokens = self.tokenizer.tokenize(text)

        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].text, "café")

    def test_smart_quotes(self) -> None:
        """Test handling of smart quotes."""
        text = '"Hello"'
        tokens = self.tokenizer.tokenize(text)

        self.assertGreater(len(tokens), 0)

    def test_lowercase_normalization(self) -> None:
        """Test lowercase normalization."""
        tokenizer = Tokenizer(lowercase=True)
        tokens = tokenizer.tokenize("Hello WORLD")

        # Normalized should be lowercase
        self.assertEqual(tokens[0].normalized, "hello")
        self.assertEqual(tokens[1].normalized, "world")

    def test_multiple_spaces(self) -> None:
        """Test handling of multiple spaces."""
        text = "Hello    world"
        tokens = self.tokenizer.tokenize(text)

        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0].text, "Hello")
        self.assertEqual(tokens[1].text, "world")

    def test_newlines_and_tabs(self) -> None:
        """Test handling of newlines and tabs."""
        text = "Hello\tworld\ntest"
        tokens = self.tokenizer.tokenize(text)

        self.assertEqual(len(tokens), 3)

    def test_contraction_splitting(self) -> None:
        """Test that contractions are handled."""
        text = "don't can't"
        tokens = self.tokenizer.tokenize(text)

        # Should have tokens for contraction words
        self.assertGreater(len(tokens), 0)


class TestBPETokenizer(unittest.TestCase):
    """Tests for BPE tokenizer."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.bpe = BPETokenizer(vocab_size=100)

    def test_bpe_training(self) -> None:
        """Test BPE training."""
        texts = ["hello world", "hello there", "world peace"]

        self.bpe.train(texts)
        self.assertTrue(self.bpe.is_trained)

    def test_bpe_tokenization(self) -> None:
        """Test BPE tokenization after training."""
        texts = ["hello world", "hello there", "world peace"]

        self.bpe.train(texts)

        # Tokenize a word
        subwords = self.bpe.tokenize("hello")

        self.assertGreater(len(subwords), 0)

    def test_bpe_empty_train(self) -> None:
        """Test BPE with empty training data."""
        self.bpe.train([])
        self.assertTrue(self.bpe.is_trained)

    def test_bpe_untrained_error(self) -> None:
        """Test error when using untrained BPE."""
        from thomas.marketplace.nlu._exceptions import TokenizationError

        with self.assertRaises(TokenizationError):
            self.bpe.tokenize("test")

    def test_bpe_vocab_growth(self) -> None:
        """Test that vocabulary grows during training."""
        texts = ["a", "ab", "abc", "abcd"]
        self.bpe.train(texts)

        # Should have learned some merges
        self.assertGreater(len(self.bpe.bpe_ranks), 0)

    def test_bpe_repeated_characters(self) -> None:
        """Test BPE on repeated characters."""
        texts = ["aaa", "bbb", "ccc", "aaabbb"]
        self.bpe.train(texts)

        subwords = self.bpe.tokenize("aaa")
        self.assertGreater(len(subwords), 0)


class TestCharacterNGramExtractor(unittest.TestCase):
    """Tests for character n-gram extraction."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.extractor = CharacterNGramExtractor(n=3)

    def test_trigram_extraction(self) -> None:
        """Test trigram extraction."""
        ngrams = self.extractor.extract("hello")

        # With boundaries: #hello#
        # 3-grams: #he, hel, ell, llo, lo#
        self.assertGreater(len(ngrams), 0)

    def test_ngrams_without_boundaries(self) -> None:
        """Test n-grams without boundaries."""
        extractor = CharacterNGramExtractor(n=3, include_boundaries=False)
        ngrams = extractor.extract("hello")

        # 3-grams: hel, ell, llo
        self.assertEqual(len(ngrams), 3)

    def test_short_word(self) -> None:
        """Test extraction on word shorter than n."""
        extractor = CharacterNGramExtractor(n=5)
        ngrams = extractor.extract("ab")

        # Should return word itself
        self.assertIn("ab", ngrams)

    def test_all_ngrams(self) -> None:
        """Test extracting all n-gram sizes."""
        ngrams_by_size = self.extractor.extract_all_ngrams("abc")

        # Should have unigrams, bigrams, trigrams
        self.assertIn(1, ngrams_by_size)
        self.assertIn(2, ngrams_by_size)
        self.assertIn(3, ngrams_by_size)

    def test_ngram_order(self) -> None:
        """Test that n-grams are extracted in order."""
        ngrams = self.extractor.extract("abcde")

        # Verify order
        if len(ngrams) >= 2:
            first = ngrams[0]
            second = ngrams[1]

            # Second should be shifted by one position
            self.assertEqual(first[1:], second[:-1])

    def test_bigrams(self) -> None:
        """Test bigram extraction."""
        extractor = CharacterNGramExtractor(n=2)
        ngrams = extractor.extract("ab")

        self.assertGreater(len(ngrams), 0)

    def test_empty_word(self) -> None:
        """Test extraction on empty word."""
        ngrams = self.extractor.extract("")

        # Should handle gracefully
        self.assertIsInstance(ngrams, list)


class TestTokenizerIntegration(unittest.TestCase):
    """Integration tests for tokenizer."""

    def test_sentence_and_token_consistency(self) -> None:
        """Test that sentence tokenization is consistent with token tokenization."""
        text = "Hello world. This is a test."
        tokenizer = Tokenizer()

        sentences = tokenizer.tokenize_sentences(text)

        # All tokens should have valid spans
        for sentence in sentences:
            for token in sentence.tokens:
                self.assertLess(token.span.start, token.span.end)
                self.assertGreaterEqual(token.span.start, 0)

    def test_span_recovery(self) -> None:
        """Test that we can recover original text from spans."""
        text = "Hello, world!"
        tokenizer = Tokenizer()
        tokens = tokenizer.tokenize(text)

        recovered = ""
        for token in tokens:
            recovered += text[token.span.start : token.span.end]

        # Should be able to recover at least some content
        self.assertGreater(len(recovered), 0)

    def test_large_text(self) -> None:
        """Test tokenizer on larger text."""
        text = " ".join(["word"] * 1000)
        tokenizer = Tokenizer()

        tokens = tokenizer.tokenize(text)
        self.assertEqual(len(tokens), 1000)

    def test_special_characters(self) -> None:
        """Test handling of special characters."""
        text = "Email: test@example.com. Price: $100."
        tokenizer = Tokenizer()

        tokens = tokenizer.tokenize(text)
        self.assertGreater(len(tokens), 0)


if __name__ == "__main__":
    unittest.main()
