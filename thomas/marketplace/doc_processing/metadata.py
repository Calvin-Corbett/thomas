"""Metadata extraction and analysis.

Extracts authors, titles, dates, keywords, citations, and
computes document statistics.
"""

import re
from collections import Counter


class MetadataExtractor:
    """Extract metadata from document text."""

    @staticmethod
    def extract_title(text: str) -> str | None:
        """Extract document title.

        Uses heuristics: first line, text marked with special formatting,
        or detected as title through capitalization.

        Args:
            text: Document text.

        Returns:
            Extracted title or None.
        """
        if not text:
            return None

        lines = text.split("\n")

        # First non-empty line could be title
        for line in lines:
            stripped = line.strip()
            if stripped:
                # Title heuristic: short, capitalized line
                if len(stripped) < 100 and len(stripped.split()) < 15 and stripped[0].isupper():
                    return stripped
                break

        return None

    @staticmethod
    def extract_author(text: str) -> str | None:
        """Extract author name.

        Looks for common patterns like "By Author Name", "Author: Name", etc.

        Args:
            text: Document text.

        Returns:
            Extracted author or None.
        """
        # Pattern: "By Author Name" or "Author: Name" or "© Author Name"
        patterns = [
            r"[Bb]y\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            r"[Aa]uthor:?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            r"©\s+(\d{4}\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:500])  # Search first 500 chars
            if match:
                # Return the last group (name)
                groups = match.groups()
                return groups[-1] if groups else None

        return None

    @staticmethod
    def extract_date(text: str) -> str | None:
        """Extract publication/creation date.

        Args:
            text: Document text.

        Returns:
            Extracted date or None.
        """
        # Pattern: various date formats
        patterns = [
            r"\d{4}-\d{2}-\d{2}",  # YYYY-MM-DD
            r"\d{1,2}/\d{1,2}/\d{4}",  # MM/DD/YYYY
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
            r"\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}",
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:1000])
            if match:
                return match.group(0)

        return None

    @staticmethod
    def extract_keywords(text: str, method: str = "tfidf", top_k: int = 10) -> list[str]:
        """Extract keywords using TF-IDF or RAKE.

        Args:
            text: Document text.
            method: "tfidf" or "rake".
            top_k: Number of top keywords.

        Returns:
            List of keywords.
        """
        if method == "rake":
            return KeywordExtractor.rake(text, top_k)
        else:
            return KeywordExtractor.tfidf(text, top_k)


class KeywordExtractor:
    """Extract keywords using various algorithms."""

    @staticmethod
    def tfidf(text: str, top_k: int = 10) -> list[str]:
        """Extract keywords using TF-IDF.

        Args:
            text: Document text.
            top_k: Number of keywords.

        Returns:
            List of keywords.
        """
        words = text.lower().split()

        if not words:
            return []

        word_freq = Counter(words)

        # Simple TF-IDF: weight by frequency, penalize common words
        common_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "is",
            "are",
            "was",
            "were",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
        }

        scores: dict[str, float] = {}

        for word, freq in word_freq.items():
            if word not in common_words and len(word) > 3:
                # Higher frequency = higher score, penalize common words
                scores[word] = freq / len(words)

        # Get top keywords
        sorted_keywords = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        return [kw for kw, _ in sorted_keywords[:top_k]]

    @staticmethod
    def rake(text: str, top_k: int = 10) -> list[str]:
        """Extract keywords using RAKE (Rapid Automatic Keyword Extraction).

        Args:
            text: Document text.
            top_k: Number of keywords.

        Returns:
            List of keywords.
        """
        # Split by stop words and punctuation
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "is",
            "are",
            "was",
            "were",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
        }

        # Extract candidate keywords
        candidates = re.split(r"[.,;:!?\"'\s]+", text.lower())
        candidates = [c for c in candidates if c and c not in stop_words and len(c) > 2]

        # Score by frequency
        scores: dict[str, float] = {}
        word_freq = Counter(candidates)

        for word, freq in word_freq.items():
            # Co-occurrence scoring would go here
            scores[word] = freq

        sorted_keywords = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        return [kw for kw, _ in sorted_keywords[:top_k]]


class CitationExtractor:
    """Extract citations from text."""

    @staticmethod
    def extract_citations(text: str) -> dict[str, list[str]]:
        """Extract citations in various formats.

        Args:
            text: Document text.

        Returns:
            Dictionary of citation_format -> citations.
        """
        citations: dict[str, list[str]] = {
            "APA": CitationExtractor._extract_apa(text),
            "MLA": CitationExtractor._extract_mla(text),
            "Chicago": CitationExtractor._extract_chicago(text),
            "IEEE": CitationExtractor._extract_ieee(text),
        }

        return citations

    @staticmethod
    def _extract_apa(text: str) -> list[str]:
        """Extract APA format citations.

        Format: Author, A. A., & Author, B. B. (year). Title. Journal, volume(issue), pages.

        Args:
            text: Document text.

        Returns:
            List of APA citations.
        """
        pattern = r"[A-Z][a-z]+,\s+[A-Z]\.(?:\s+[A-Z]\.)?.*?\(\d{4}\).*?(?:\.|$)"
        matches = re.findall(pattern, text)
        return matches

    @staticmethod
    def _extract_mla(text: str) -> list[str]:
        """Extract MLA format citations.

        Format: Author Last Name, First Name. "Title." Journal, volume, pages, year.

        Args:
            text: Document text.

        Returns:
            List of MLA citations.
        """
        pattern = r"[A-Z][a-z]+,\s+[A-Z][a-z]+\..*?\d{4}.*?(?:\.|$)"
        matches = re.findall(pattern, text)
        return matches

    @staticmethod
    def _extract_chicago(text: str) -> list[str]:
        """Extract Chicago style citations.

        Args:
            text: Document text.

        Returns:
            List of citations.
        """
        # Chicago Notes format
        pattern = r"\d+\.\s+[A-Z][a-z]+\s+[A-Z][a-z]+,.*?(?:\n|$)"
        matches = re.findall(pattern, text)
        return matches

    @staticmethod
    def _extract_ieee(text: str) -> list[str]:
        """Extract IEEE format citations.

        Format: [#] Initial. Surname, "Title," Journal, vol., pp., year.

        Args:
            text: Document text.

        Returns:
            List of IEEE citations.
        """
        pattern = r"\[\d+\]\s+[A-Z]\.\s+[A-Z][a-z]+.*?(?:\.|$)"
        matches = re.findall(pattern, text)
        return matches


class ReferenceParser:
    """Parse bibliographic references."""

    @staticmethod
    def parse_reference(reference: str) -> dict[str, str]:
        """Parse a single reference into components.

        Args:
            reference: Reference text.

        Returns:
            Dictionary with author, title, year, journal, etc.
        """
        parsed: dict[str, str] = {
            "author": "",
            "title": "",
            "year": "",
            "journal": "",
            "pages": "",
            "volume": "",
        }

        # Extract year
        year_match = re.search(r"\b(19|20)\d{2}\b", reference)
        if year_match:
            parsed["year"] = year_match.group(0)

        # Extract pages
        pages_match = re.search(r"pp?\.?\s*(\d+-\d+|\d+)", reference)
        if pages_match:
            parsed["pages"] = pages_match.group(1)

        # Extract author (first name before year or title)
        author_match = re.match(r"^([^,(]+?)(?:[,\(]|$)", reference)
        if author_match:
            parsed["author"] = author_match.group(1).strip()

        # Extract title (in quotes or before journal)
        title_match = re.search(r'"([^"]+)"|\'([^\']+)\'', reference)
        if title_match:
            parsed["title"] = title_match.group(1) or title_match.group(2)

        return parsed


class DocumentStatistics:
    """Calculate document statistics."""

    @staticmethod
    def word_count(text: str) -> int:
        """Count words in text.

        Args:
            text: Document text.

        Returns:
            Word count.
        """
        return len(text.split())

    @staticmethod
    def sentence_count(text: str) -> int:
        """Count sentences.

        Args:
            text: Document text.

        Returns:
            Sentence count.
        """
        sentences = re.split(r"[.!?]+", text)
        return len([s for s in sentences if s.strip()])

    @staticmethod
    def reading_time_minutes(text: str, wpm: int = 200) -> float:
        """Estimate reading time.

        Args:
            text: Document text.
            wpm: Words per minute (average 200).

        Returns:
            Estimated reading time in minutes.
        """
        word_count = DocumentStatistics.word_count(text)
        return word_count / wpm

    @staticmethod
    def vocabulary_richness(text: str) -> float:
        """Calculate vocabulary richness (type-token ratio).

        Args:
            text: Document text.

        Returns:
            Ratio of unique words to total words (0-1).
        """
        words = text.lower().split()
        if not words:
            return 0.0

        unique_words = len(set(words))
        return unique_words / len(words)

    @staticmethod
    def average_word_length(text: str) -> float:
        """Calculate average word length.

        Args:
            text: Document text.

        Returns:
            Average word length in characters.
        """
        words = text.split()
        if not words:
            return 0.0

        return sum(len(w) for w in words) / len(words)

    @staticmethod
    def average_sentence_length(text: str) -> float:
        """Calculate average sentence length.

        Args:
            text: Document text.

        Returns:
            Average words per sentence.
        """
        sentences = re.split(r"[.!?]+", text)
        sentences = [s for s in sentences if s.strip()]

        if not sentences:
            return 0.0

        total_words = sum(len(s.split()) for s in sentences)
        return total_words / len(sentences)

    @staticmethod
    def calculate_all(text: str) -> dict[str, any]:
        """Calculate all statistics.

        Args:
            text: Document text.

        Returns:
            Dictionary of statistics.
        """
        return {
            "word_count": DocumentStatistics.word_count(text),
            "sentence_count": DocumentStatistics.sentence_count(text),
            "reading_time_minutes": DocumentStatistics.reading_time_minutes(text),
            "vocabulary_richness": DocumentStatistics.vocabulary_richness(text),
            "average_word_length": DocumentStatistics.average_word_length(text),
            "average_sentence_length": DocumentStatistics.average_sentence_length(text),
        }
