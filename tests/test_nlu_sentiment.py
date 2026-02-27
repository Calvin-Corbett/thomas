"""
Tests for sentiment analysis module.
"""

import unittest

from thomas.nlu._types import POSTag, Sentence, Span, Token
from thomas.nlu.sentiment import SentimentAnalyzer


class TestSentimentAnalyzer(unittest.TestCase):
    """Tests for sentiment analyzer."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.analyzer = SentimentAnalyzer()

    def test_positive_sentiment(self) -> None:
        """Test detection of positive sentiment."""
        sentence = Sentence(text="This movie is absolutely fantastic!")
        tokens = [
            Token(text="This", span=Span(0, 4), pos=POSTag.DT),
            Token(text="movie", span=Span(5, 10), pos=POSTag.NN),
            Token(text="is", span=Span(11, 13), pos=POSTag.VBZ),
            Token(text="absolutely", span=Span(14, 24), pos=POSTag.RB),
            Token(text="fantastic", span=Span(25, 34), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = self.analyzer.analyze(sentence)

        self.assertGreater(result.polarity, 0.0)

    def test_negative_sentiment(self) -> None:
        """Test detection of negative sentiment."""
        sentence = Sentence(text="This movie is terrible and awful.")
        tokens = [
            Token(text="This", span=Span(0, 4), pos=POSTag.DT),
            Token(text="movie", span=Span(5, 10), pos=POSTag.NN),
            Token(text="is", span=Span(11, 13), pos=POSTag.VBZ),
            Token(text="terrible", span=Span(14, 22), pos=POSTag.JJ),
            Token(text="and", span=Span(23, 26), pos=POSTag.CC),
            Token(text="awful", span=Span(27, 32), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = self.analyzer.analyze(sentence)

        self.assertLess(result.polarity, 0.0)

    def test_neutral_sentiment(self) -> None:
        """Test neutral sentiment."""
        sentence = Sentence(text="The weather is normal.")
        tokens = [
            Token(text="The", span=Span(0, 3), pos=POSTag.DT),
            Token(text="weather", span=Span(4, 11), pos=POSTag.NN),
            Token(text="is", span=Span(12, 14), pos=POSTag.VBZ),
            Token(text="normal", span=Span(15, 21), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = self.analyzer.analyze(sentence)

        # Neutral should be close to 0
        self.assertGreater(result.polarity, -0.3)
        self.assertLess(result.polarity, 0.3)

    def test_negation_handling(self) -> None:
        """Test that negation reverses sentiment."""
        pos_sentence = Sentence(text="This is good.")
        neg_sentence = Sentence(text="This is not good.")

        pos_tokens = [
            Token(text="This", span=Span(0, 4), pos=POSTag.DT),
            Token(text="is", span=Span(5, 7), pos=POSTag.VBZ),
            Token(text="good", span=Span(8, 12), pos=POSTag.JJ),
        ]
        neg_tokens = [
            Token(text="This", span=Span(0, 4), pos=POSTag.DT),
            Token(text="is", span=Span(5, 7), pos=POSTag.VBZ),
            Token(text="not", span=Span(8, 11), pos=POSTag.RB),
            Token(text="good", span=Span(12, 16), pos=POSTag.JJ),
        ]

        pos_sentence.tokens = pos_tokens
        neg_sentence.tokens = neg_tokens

        pos_result = self.analyzer.analyze(pos_sentence)
        neg_result = self.analyzer.analyze(neg_sentence)

        # Negation should reverse sentiment
        self.assertGreater(pos_result.polarity, neg_result.polarity)

    def test_intensifier_handling(self) -> None:
        """Test that intensifiers increase sentiment strength."""
        weak_sentence = Sentence(text="This is good.")
        strong_sentence = Sentence(text="This is very good.")

        weak_tokens = [
            Token(text="This", span=Span(0, 4), pos=POSTag.DT),
            Token(text="is", span=Span(5, 7), pos=POSTag.VBZ),
            Token(text="good", span=Span(8, 12), pos=POSTag.JJ),
        ]
        strong_tokens = [
            Token(text="This", span=Span(0, 4), pos=POSTag.DT),
            Token(text="is", span=Span(5, 7), pos=POSTag.VBZ),
            Token(text="very", span=Span(8, 12), pos=POSTag.RB),
            Token(text="good", span=Span(13, 17), pos=POSTag.JJ),
        ]

        weak_sentence.tokens = weak_tokens
        strong_sentence.tokens = strong_tokens

        weak_result = self.analyzer.analyze(weak_sentence)
        strong_result = self.analyzer.analyze(strong_sentence)

        # Intensifier should increase positive sentiment
        self.assertLess(weak_result.polarity, strong_result.polarity)

    def test_confidence_score(self) -> None:
        """Test that confidence scores are valid."""
        sentence = Sentence(text="This is great!")
        tokens = [
            Token(text="This", span=Span(0, 4), pos=POSTag.DT),
            Token(text="is", span=Span(5, 7), pos=POSTag.VBZ),
            Token(text="great", span=Span(8, 13), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = self.analyzer.analyze(sentence)

        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_subjectivity_score(self) -> None:
        """Test subjectivity computation."""
        objective = Sentence(text="The sky is blue.")
        subjective = Sentence(text="I think the movie was great.")

        obj_tokens = [
            Token(text="The", span=Span(0, 3), pos=POSTag.DT),
            Token(text="sky", span=Span(4, 7), pos=POSTag.NN),
        ]
        subj_tokens = [
            Token(text="I", span=Span(0, 1), pos=POSTag.PRP),
            Token(text="think", span=Span(2, 7), pos=POSTag.VBP),
        ]

        objective.tokens = obj_tokens
        subjective.tokens = subj_tokens

        obj_result = self.analyzer.analyze(objective)
        subj_result = self.analyzer.analyze(subjective)

        # Subjective should have higher subjectivity
        self.assertGreater(subj_result.subjectivity, obj_result.subjectivity)

    def test_emotion_detection(self) -> None:
        """Test emotion detection."""
        happy_sentence = Sentence(text="I'm so happy!")
        angry_sentence = Sentence(text="I'm very angry!")

        happy_tokens = [
            Token(text="I'm", span=Span(0, 3), pos=POSTag.PRP),
            Token(text="happy", span=Span(7, 12), pos=POSTag.JJ),
        ]
        angry_tokens = [
            Token(text="I'm", span=Span(0, 3), pos=POSTag.PRP),
            Token(text="angry", span=Span(9, 14), pos=POSTag.JJ),
        ]

        happy_sentence.tokens = happy_tokens
        angry_sentence.tokens = angry_tokens

        happy_result = self.analyzer.analyze(happy_sentence)
        angry_result = self.analyzer.analyze(angry_sentence)

        # Should detect emotions
        self.assertGreater(len(happy_result.emotions), 0)
        self.assertGreater(len(angry_result.emotions), 0)

    def test_positive_phrases(self) -> None:
        """Test extraction of positive phrases."""
        sentence = Sentence(text="The movie is absolutely wonderful and great!")
        tokens = [
            Token(text="wonderful", span=Span(20, 29), pos=POSTag.JJ),
            Token(text="great", span=Span(34, 39), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = self.analyzer.analyze(sentence)

        self.assertGreater(len(result.positive_phrases), 0)

    def test_negative_phrases(self) -> None:
        """Test extraction of negative phrases."""
        sentence = Sentence(text="This is bad and terrible.")
        tokens = [
            Token(text="bad", span=Span(8, 11), pos=POSTag.JJ),
            Token(text="terrible", span=Span(16, 24), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = self.analyzer.analyze(sentence)

        self.assertGreater(len(result.negative_phrases), 0)

    def test_empty_sentence(self) -> None:
        """Test handling of empty sentence."""
        sentence = Sentence(text="")

        result = self.analyzer.analyze(sentence)

        self.assertEqual(result.polarity, 0.0)
        self.assertEqual(result.confidence, 0.0)


class TestSentimentLexicons(unittest.TestCase):
    """Test sentiment lexicon loading."""

    def test_positive_lexicon(self) -> None:
        """Test that positive lexicon is loaded."""
        analyzer = SentimentAnalyzer()

        self.assertGreater(len(analyzer.positive_words), 0)
        self.assertIn("good", analyzer.positive_words)
        self.assertIn("great", analyzer.positive_words)

    def test_negative_lexicon(self) -> None:
        """Test that negative lexicon is loaded."""
        analyzer = SentimentAnalyzer()

        self.assertGreater(len(analyzer.negative_words), 0)
        self.assertIn("bad", analyzer.negative_words)
        self.assertIn("terrible", analyzer.negative_words)

    def test_emotion_lexicon(self) -> None:
        """Test that emotion lexicon is loaded."""
        analyzer = SentimentAnalyzer()

        self.assertGreater(len(analyzer.emotions), 0)
        self.assertIn("happy", analyzer.emotions)
        self.assertIn("sad", analyzer.emotions)

    def test_intensifiers(self) -> None:
        """Test intensifier set."""
        analyzer = SentimentAnalyzer()

        self.assertIn("very", analyzer.intensifiers)
        self.assertIn("extremely", analyzer.intensifiers)

    def test_negations(self) -> None:
        """Test negation set."""
        analyzer = SentimentAnalyzer()

        self.assertIn("not", analyzer.negations)
        self.assertIn("n't", analyzer.negations)


class TestSentimentEdgeCases(unittest.TestCase):
    """Test edge cases in sentiment analysis."""

    def test_mixed_sentiment(self) -> None:
        """Test mixed positive and negative sentiment."""
        sentence = Sentence(text="Good but not great.")
        tokens = [
            Token(text="Good", span=Span(0, 4), pos=POSTag.JJ),
            Token(text="but", span=Span(5, 8), pos=POSTag.CC),
            Token(text="great", span=Span(15, 20), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = SentimentAnalyzer().analyze(sentence)

        # Should have mixed sentiment (between -1 and 1)
        self.assertGreater(result.polarity, -1.0)
        self.assertLess(result.polarity, 1.0)

    def test_repeated_words(self) -> None:
        """Test sentiment with repeated sentiment words."""
        sentence = Sentence(text="Good good good!")
        tokens = [
            Token(text="Good", span=Span(0, 4), pos=POSTag.JJ),
            Token(text="good", span=Span(5, 9), pos=POSTag.JJ),
            Token(text="good", span=Span(10, 14), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = SentimentAnalyzer().analyze(sentence)

        self.assertGreater(result.polarity, 0.0)

    def test_sarcasm_limitation(self) -> None:
        """Test that literal approach struggles with sarcasm."""
        sentence = Sentence(text="Oh great, just what I needed!")
        tokens = [
            Token(text="great", span=Span(4, 9), pos=POSTag.JJ),
        ]
        sentence.tokens = tokens

        result = SentimentAnalyzer().analyze(sentence)

        # Lexicon-based approach will see 'great' as positive
        # even though this is sarcastic
        self.assertNotEqual(result.polarity, 0.0)


if __name__ == "__main__":
    unittest.main()
