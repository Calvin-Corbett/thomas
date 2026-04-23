"""Tests for document summarization module."""

import pytest

from thomas.marketplace.doc_processing._types import Document, Page, Sentence
from thomas.marketplace.doc_processing.summarization import (
    DocumentSummarizer,
    LexRankSummarizer,
    LSASummarizer,
    SentenceScorer,
    SentenceSimilarityCalculator,
    TextRankSummarizer,
)


class TestSentenceSimilarityCalculator:
    """Test sentence similarity calculation."""

    def test_calculate_tfidf(self) -> None:
        """Test TF-IDF calculation."""
        calculator = SentenceSimilarityCalculator()
        sentence = "hello world test"
        all_sentences = ["hello world test", "another sentence", "hello world"]

        tfidf = calculator.calculate_tfidf(sentence, all_sentences)

        assert isinstance(tfidf, dict)
        assert len(tfidf) > 0

    def test_cosine_similarity(self) -> None:
        """Test cosine similarity."""
        calculator = SentenceSimilarityCalculator()
        vec1 = {"hello": 0.5, "world": 0.5}
        vec2 = {"hello": 0.5, "world": 0.5}

        similarity = calculator.cosine_similarity(vec1, vec2)

        assert similarity > 0.99  # Should be very similar
        assert 0 <= similarity <= 1

    def test_similarity_different_vectors(self) -> None:
        """Test similarity of different vectors."""
        calculator = SentenceSimilarityCalculator()
        vec1 = {"hello": 0.5, "world": 0.5}
        vec2 = {"foo": 0.5, "bar": 0.5}

        similarity = calculator.cosine_similarity(vec1, vec2)

        assert similarity == 0.0  # No overlap


class TestSentenceScorer:
    """Test sentence scoring."""

    def test_score_position(self) -> None:
        """Test position-based scoring."""
        scorer = SentenceScorer()

        first = scorer.score_position(0, 10)
        middle = scorer.score_position(5, 10)
        last = scorer.score_position(9, 10)

        assert first > middle
        assert middle > last

    def test_score_length(self) -> None:
        """Test length-based scoring."""
        scorer = SentenceScorer()

        short = scorer.score_length(3)
        optimal = scorer.score_length(12)
        long = scorer.score_length(100)

        assert optimal >= short
        assert optimal >= long

    def test_score_title_similarity(self) -> None:
        """Test title similarity scoring."""
        scorer = SentenceScorer()

        title = "Python Programming"
        similar = "Python is great for programming"
        different = "The weather is nice"

        sim_score = scorer.score_title_similarity(similar, title)
        diff_score = scorer.score_title_similarity(different, title)

        assert sim_score > diff_score

    def test_score_keyword_overlap(self) -> None:
        """Test keyword overlap scoring."""
        scorer = SentenceScorer()
        keywords = ["python", "programming", "code"]

        with_keywords = "Python programming is important for code development"
        without_keywords = "The sky is blue today"

        with_score = scorer.score_keyword_overlap(with_keywords, keywords)
        without_score = scorer.score_keyword_overlap(without_keywords, keywords)

        assert with_score > without_score


class TestTextRankSummarizer:
    """Test TextRank summarization."""

    def test_summarize(self) -> None:
        """Test TextRank summarization."""
        sentences = [
            Sentence(tokens=[], text="First sentence about topic."),
            Sentence(tokens=[], text="Second sentence continues discussion."),
            Sentence(tokens=[], text="Third sentence adds more details."),
            Sentence(tokens=[], text="Fourth sentence concludes everything."),
        ]

        summarizer = TextRankSummarizer()
        summary = summarizer.summarize(sentences, summary_length=2)

        assert len(summary) <= 2
        assert len(summary) > 0

    def test_short_input(self) -> None:
        """Test with input shorter than target."""
        sentences = [
            Sentence(tokens=[], text="Only one sentence."),
        ]

        summarizer = TextRankSummarizer()
        summary = summarizer.summarize(sentences, summary_length=5)

        assert len(summary) == 1


class TestLexRankSummarizer:
    """Test LexRank summarization."""

    def test_summarize(self) -> None:
        """Test LexRank summarization."""
        sentences = [
            Sentence(tokens=[], text="First sentence about topic."),
            Sentence(tokens=[], text="Second sentence continues discussion."),
            Sentence(tokens=[], text="Third sentence adds more details."),
            Sentence(tokens=[], text="Fourth sentence concludes everything."),
        ]

        summarizer = LexRankSummarizer()
        summary = summarizer.summarize(sentences, summary_length=2)

        assert len(summary) <= 2
        assert len(summary) > 0


class TestLSASummarizer:
    """Test LSA summarization."""

    def test_summarize(self) -> None:
        """Test LSA summarization."""
        sentences = [
            Sentence(tokens=[], text="First sentence about topic."),
            Sentence(tokens=[], text="Second sentence continues discussion."),
            Sentence(tokens=[], text="Third sentence adds more details."),
            Sentence(tokens=[], text="Fourth sentence concludes everything."),
        ]

        summarizer = LSASummarizer()
        summary = summarizer.summarize(sentences, summary_length=2)

        assert len(summary) <= 2
        assert len(summary) > 0

    def test_empty_input(self) -> None:
        """Test with empty input."""
        summarizer = LSASummarizer()
        summary = summarizer.summarize([], summary_length=2)

        assert len(summary) == 0


class TestDocumentSummarizer:
    """Test high-level document summarization."""

    def test_summarize_with_textrank(self) -> None:
        """Test summarization with TextRank."""
        # Create a simple document
        text = "This is the first sentence. This is the second sentence. This is the third sentence. This is the fourth sentence."
        sentences = [
            Sentence(tokens=[], text="This is the first sentence."),
            Sentence(tokens=[], text="This is the second sentence."),
            Sentence(tokens=[], text="This is the third sentence."),
            Sentence(tokens=[], text="This is the fourth sentence."),
        ]

        # Create document with sentences in blocks
        from thomas.marketplace.doc_processing._types import Paragraph, TextBlock

        para = Paragraph(sentences=sentences, text=text)
        block = TextBlock(text=text, bbox=None, paragraphs=[para])
        page = Page(page_number=1, text=text, text_blocks=[block])
        doc = Document(pages=[page], text=text)

        summarizer = DocumentSummarizer(method="textrank")
        summary = summarizer.summarize(doc, summary_ratio=0.5)

        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_invalid_method(self) -> None:
        """Test with invalid method."""
        with pytest.raises(ValueError):
            DocumentSummarizer(method="invalid")
