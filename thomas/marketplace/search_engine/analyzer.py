"""Text analysis pipeline for the search engine."""

import re
from abc import ABC, abstractmethod

from ._types import TokenInfo


class TokenFilter(ABC):
    """Base class for token filters."""

    @abstractmethod
    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Apply filter to token stream."""
        pass


class Tokenizer(TokenFilter):
    """Base tokenizer class."""

    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Tokenizers don't filter existing tokens."""
        return tokens


class WhitespaceTokenizer(Tokenizer):
    """Splits text on whitespace."""

    def tokenize(self, text: str) -> list[TokenInfo]:
        """Tokenize text by splitting on whitespace."""
        tokens: list[TokenInfo] = []
        position = 0
        for match in re.finditer(r"\S+", text):
            term = match.group()
            tokens.append(TokenInfo(term=term, position=position, offset_start=match.start(), offset_end=match.end()))
            position += 1
        return tokens


class StandardTokenizer(Tokenizer):
    """Splits on whitespace and punctuation, with punctuation handling."""

    def tokenize(self, text: str) -> list[TokenInfo]:
        """Tokenize text intelligently handling punctuation."""
        tokens: list[TokenInfo] = []
        position = 0

        # Pattern: word characters and apostrophes in words, or individual punctuation
        pattern = r"\b[\w']+\b|[^\w\s]"
        for match in re.finditer(pattern, text, re.UNICODE):
            term = match.group()
            # Skip pure punctuation unless it's meaningful
            if term and (re.match(r"\w", term, re.UNICODE) or term == "'"):
                if term != "'":  # Don't include standalone apostrophes
                    tokens.append(
                        TokenInfo(term=term, position=position, offset_start=match.start(), offset_end=match.end())
                    )
                    position += 1
        return tokens


class LowercaseFilter(TokenFilter):
    """Converts all tokens to lowercase."""

    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Convert tokens to lowercase."""
        for token in tokens:
            token.term = token.term.lower()
        return tokens


class StopWordFilter(TokenFilter):
    """Removes common stop words."""

    DEFAULT_STOP_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "will",
        "with",
    }

    def __init__(self, stop_words: set[str] | None = None) -> None:
        """Initialize with optional custom stop word list."""
        self.stop_words = stop_words or self.DEFAULT_STOP_WORDS

    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Remove stop words from token stream."""
        result = []
        new_position = 0
        for token in tokens:
            if token.term.lower() not in self.stop_words:
                token.position = new_position
                result.append(token)
                new_position += 1
        return result


class PorterStemmer(TokenFilter):
    """Porter stemming algorithm implementation."""

    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Apply Porter stemming to tokens."""
        for token in tokens:
            token.term = self._stem(token.term)
        return tokens

    def _stem(self, word: str) -> str:
        """Implement Porter stemming algorithm."""
        if len(word) <= 2:
            return word

        word = word.lower()
        step1a = self._step1a(word)
        step1b = self._step1b(step1a)
        step1c = self._step1c(step1b)
        step2 = self._step2(step1c)
        step3 = self._step3(step2)
        step4 = self._step4(step3)
        step5 = self._step5(step4)
        return step5

    def _is_consonant(self, word: str, i: int) -> bool:
        """Check if character at position i is consonant."""
        if i >= len(word):
            return False
        ch = word[i]
        if ch in "aeiou":
            return False
        if ch == "y":
            return i == 0 or not self._is_consonant(word, i - 1)
        return True

    def _measure(self, word: str) -> int:
        """Calculate measure (VC count) of word."""
        count = 0
        in_vc = False
        for i, ch in enumerate(word):
            is_cons = self._is_consonant(word, i)
            if not is_cons and in_vc:
                count += 1
                in_vc = False
            elif is_cons and not in_vc:
                in_vc = True
        return count

    def _ends_double_consonant(self, word: str) -> bool:
        """Check if word ends in double consonant."""
        if len(word) < 2:
            return False
        return word[-1] == word[-2] and self._is_consonant(word, len(word) - 1)

    def _ends_cvc(self, word: str) -> bool:
        """Check if word ends in consonant-vowel-consonant pattern."""
        if len(word) < 3:
            return False
        return (
            self._is_consonant(word, len(word) - 3)
            and not self._is_consonant(word, len(word) - 2)
            and self._is_consonant(word, len(word) - 1)
            and word[-1] not in "wxy"
        )

    def _step1a(self, word: str) -> str:
        """Step 1a of Porter stemmer."""
        if word.endswith("sses") or word.endswith("ies"):
            return word[:-2]
        elif word.endswith("ss"):
            return word
        elif word.endswith("s"):
            return word[:-1]
        return word

    def _step1b(self, word: str) -> str:
        """Step 1b of Porter stemmer."""
        if word.endswith("eed"):
            stem = word[:-3]
            if self._measure(stem) > 0:
                return stem + "ee"
            return word
        elif word.endswith("ed") or word.endswith("ing"):
            stem = word[:-2] if word.endswith("ed") else word[:-3]
            if any(self._is_consonant(stem, i) is False for i in range(len(stem))):
                return self._step1b_suffix(stem)
        return word

    def _step1b_suffix(self, word: str) -> str:
        """Apply suffix rules for step 1b."""
        if word.endswith("at") or word.endswith("bl") or word.endswith("iz"):
            return word + "e"
        if self._ends_double_consonant(word) and word[-1] not in "lsz":
            return word[:-1]
        if self._measure(word) == 1 and self._ends_cvc(word):
            return word + "e"
        return word

    def _step1c(self, word: str) -> str:
        """Step 1c of Porter stemmer."""
        if len(word) > 1 and word[-1] in "yY":
            stem = word[:-1]
            if any(self._is_consonant(stem, i) is False for i in range(len(stem))):
                return stem + "i"
        return word

    def _step2(self, word: str) -> str:
        """Step 2 of Porter stemmer."""
        mapping = {
            "ational": "ate",
            "tional": "tion",
            "enci": "ence",
            "anci": "ance",
            "izer": "ize",
            "bli": "ble",
            "alli": "al",
            "entli": "ent",
            "eli": "e",
            "ousli": "ous",
            "ization": "ize",
            "ation": "ate",
            "ator": "ate",
            "alism": "al",
            "iveness": "ive",
            "fulness": "ful",
            "ousness": "ous",
            "aliti": "al",
            "iviti": "ive",
            "biliti": "ble",
        }
        for suffix, replacement in mapping.items():
            if word.endswith(suffix):
                stem = word[: -len(suffix)]
                if self._measure(stem) > 0:
                    return stem + replacement
        return word

    def _step3(self, word: str) -> str:
        """Step 3 of Porter stemmer."""
        mapping = {"icate": "ic", "ative": "", "alize": "al", "iciti": "ic", "ical": "ic", "ful": "", "ness": ""}
        for suffix, replacement in mapping.items():
            if word.endswith(suffix):
                stem = word[: -len(suffix)]
                if self._measure(stem) > 0:
                    return stem + replacement
        return word

    def _step4(self, word: str) -> str:
        """Step 4 of Porter stemmer."""
        suffixes = [
            "al",
            "ance",
            "ence",
            "er",
            "ic",
            "able",
            "ible",
            "ant",
            "ement",
            "ment",
            "ent",
            "ion",
            "ou",
            "ism",
            "ate",
            "iti",
            "ous",
            "ive",
            "ize",
        ]
        for suffix in suffixes:
            if word.endswith(suffix):
                stem = word[: -len(suffix)]
                if suffix == "ion" and len(stem) > 0:
                    if stem[-1] not in "st":
                        continue
                if self._measure(stem) > 1:
                    return stem
        return word

    def _step5(self, word: str) -> str:
        """Step 5 of Porter stemmer."""
        if word.endswith("e"):
            stem = word[:-1]
            measure = self._measure(stem)
            if measure > 1 or measure == 1 and not self._ends_cvc(stem):
                return stem
        if word.endswith("ll") and self._measure(word[:-1]) > 1:
            return word[:-1]
        return word


class NGramFilter(TokenFilter):
    """Generates n-grams from tokens."""

    def __init__(self, min_gram: int = 2, max_gram: int = 3) -> None:
        """Initialize with gram size boundaries."""
        self.min_gram = min_gram
        self.max_gram = max_gram

    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Generate n-grams from tokens."""
        result: list[TokenInfo] = []
        for token in tokens:
            for gram_size in range(self.min_gram, self.max_gram + 1):
                for i in range(len(token.term) - gram_size + 1):
                    gram = token.term[i : i + gram_size]
                    result.append(
                        TokenInfo(
                            term=gram,
                            position=token.position,
                            offset_start=token.offset_start + i,
                            offset_end=token.offset_start + i + gram_size,
                        )
                    )
        return result


class EdgeNGramFilter(TokenFilter):
    """Generates edge n-grams for prefix matching."""

    def __init__(self, min_gram: int = 1, max_gram: int = 10) -> None:
        """Initialize with gram size boundaries."""
        self.min_gram = min_gram
        self.max_gram = max_gram

    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Generate edge n-grams from start of tokens."""
        result: list[TokenInfo] = []
        for token in tokens:
            for gram_size in range(self.min_gram, min(self.max_gram + 1, len(token.term) + 1)):
                gram = token.term[:gram_size]
                result.append(
                    TokenInfo(
                        term=gram,
                        position=token.position,
                        offset_start=token.offset_start,
                        offset_end=token.offset_start + gram_size,
                    )
                )
        return result


class SynonymFilter(TokenFilter):
    """Expands tokens using synonym mapping."""

    def __init__(self, synonyms: dict[str, list[str]] | None = None) -> None:
        """Initialize with synonym mappings."""
        self.synonyms = synonyms or {}

    def filter(self, tokens: list[TokenInfo]) -> list[TokenInfo]:
        """Expand tokens with synonyms."""
        result: list[TokenInfo] = []
        for token in tokens:
            result.append(token)
            if token.term in self.synonyms:
                for synonym in self.synonyms[token.term]:
                    result.append(
                        TokenInfo(
                            term=synonym,
                            position=token.position,
                            offset_start=token.offset_start,
                            offset_end=token.offset_end,
                        )
                    )
        return result


class Analyzer:
    """Composable text analysis pipeline."""

    def __init__(self, tokenizer: Tokenizer, filters: list[TokenFilter] | None = None) -> None:
        """Initialize analyzer with tokenizer and optional filters."""
        self.tokenizer = tokenizer
        self.filters = filters or []

    def analyze(self, text: str) -> list[TokenInfo]:
        """Analyze text and return token stream."""
        if not text:
            return []

        tokens = self.tokenizer.tokenize(text)
        for filter_obj in self.filters:
            tokens = filter_obj.filter(tokens)
        return tokens


class AnalyzerFactory:
    """Factory for creating standard analyzers."""

    @staticmethod
    def create_standard() -> Analyzer:
        """Create standard analyzer: tokenize, lowercase, remove stops, stem."""
        return Analyzer(tokenizer=StandardTokenizer(), filters=[LowercaseFilter(), StopWordFilter(), PorterStemmer()])

    @staticmethod
    def create_keyword() -> Analyzer:
        """Create keyword analyzer: no tokenization, just lowercase."""
        return Analyzer(tokenizer=WhitespaceTokenizer(), filters=[LowercaseFilter()])

    @staticmethod
    def create_simple() -> Analyzer:
        """Create simple analyzer: tokenize and lowercase."""
        return Analyzer(tokenizer=StandardTokenizer(), filters=[LowercaseFilter()])

    @staticmethod
    def create_ngram(min_gram: int = 2, max_gram: int = 3) -> Analyzer:
        """Create n-gram analyzer."""
        return Analyzer(
            tokenizer=StandardTokenizer(),
            filters=[LowercaseFilter(), NGramFilter(min_gram=min_gram, max_gram=max_gram)],
        )

    @staticmethod
    def create_autocomplete(min_gram: int = 1, max_gram: int = 10) -> Analyzer:
        """Create autocomplete analyzer: edge n-grams."""
        return Analyzer(
            tokenizer=StandardTokenizer(),
            filters=[LowercaseFilter(), EdgeNGramFilter(min_gram=min_gram, max_gram=max_gram)],
        )
