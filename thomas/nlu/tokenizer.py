"""
Tokenization module for the NLU system.

Provides rule-based tokenization, sentence boundary detection, word normalization,
byte pair encoding (BPE), and character n-gram extraction with full span tracking.
"""

import unicodedata
from collections import defaultdict

from thomas.nlu._exceptions import TokenizationError
from thomas.nlu._types import Sentence, Span, Token


class Tokenizer:
    """
    Rule-based tokenizer with sentence boundary detection and span tracking.

    Performs tokenization by splitting on whitespace and punctuation, detects
    sentence boundaries with abbreviation awareness, normalizes text, and tracks
    exact character offsets of all tokens.
    """

    # Common abbreviations that should not trigger sentence boundary
    ABBREVIATIONS = {
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "jr",
        "st",
        "ave",
        "rd",
        "blvd",
        "inc",
        "ltd",
        "corp",
        "co",
        "org",
        "gov",
        "edu",
        "www",
        "etc",
        "e.g",
        "i.e",
        "vs",
        "viz",
        "cf",
        "al",
        "et",
        "no",
        "pp",
    }

    # Punctuation that marks sentence boundaries (when followed by space/newline)
    SENTENCE_DELIMITERS = {".", "!", "?"}

    # Punctuation that should be split from words
    PUNCT_CHARS = set('.,;:!?\'"()[]{}«»„"…–—')

    # Contractions to handle
    CONTRACTIONS = {
        "n't": "not",
        "'re": "are",
        "'ve": "have",
        "'ll": "will",
        "'d": "would",
        "'m": "am",
        "'s": "is",  # Also possessive, context-dependent
    }

    def __init__(self, lowercase: bool = False) -> None:
        """
        Initialize tokenizer.

        Args:
            lowercase: Whether to lowercase tokens during normalization
        """
        self.lowercase = lowercase

    def tokenize(self, text: str) -> list[Token]:
        """
        Tokenize text into tokens with span tracking.

        Args:
            text: Text to tokenize

        Returns:
            List of Token objects with character offsets
        """
        if not text:
            return []

        # Normalize unicode
        text = self._normalize_unicode(text)

        tokens = []
        current_pos = 0

        for word in text.split():
            # Find word position in original text
            word_start = text.find(word, current_pos)
            if word_start == -1:
                continue

            # Split word on punctuation
            sub_tokens = self._split_on_punctuation(word, word_start)
            tokens.extend(sub_tokens)
            current_pos = word_start + len(word)

        return tokens

    def tokenize_sentences(self, text: str) -> list[Sentence]:
        """
        Tokenize text into sentences with internal tokenization.

        Args:
            text: Text to tokenize

        Returns:
            List of Sentence objects
        """
        if not text:
            return []

        # Normalize
        text = self._normalize_unicode(text)

        # Split into sentences
        sent_texts = self._split_sentences(text)

        sentences = []
        for sent_text in sent_texts:
            # Find sentence position in original text
            sent_start = text.find(sent_text)
            if sent_start == -1:
                continue

            # Tokenize sentence
            sent_tokens = self.tokenize(sent_text)

            # Adjust spans to document position
            for token in sent_tokens:
                token.span = Span(sent_start + token.span.start, sent_start + token.span.end)

            sentences.append(Sentence(text=sent_text.strip(), tokens=sent_tokens))

        return sentences

    def _split_sentences(self, text: str) -> list[str]:
        """
        Split text into sentences with abbreviation handling.

        Args:
            text: Text to split

        Returns:
            List of sentence strings
        """
        sentences = []
        current_sent = []
        i = 0

        while i < len(text):
            char = text[i]

            if char in self.SENTENCE_DELIMITERS:
                current_sent.append(char)

                # Look ahead for sentence boundary
                if i + 1 < len(text) and text[i + 1] in (" ", "\n", "\t"):
                    # Check if it's an abbreviation
                    word_before = "".join(current_sent).strip().split()[-1].lower()
                    word_before = word_before.rstrip(".")

                    # If not abbreviation, sentence boundary
                    if word_before not in self.ABBREVIATIONS:
                        sentences.append("".join(current_sent).strip())
                        current_sent = []
                        # Skip whitespace
                        while i + 1 < len(text) and text[i + 1] in (" ", "\n", "\t"):
                            i += 1

            else:
                current_sent.append(char)

            i += 1

        if current_sent:
            sentences.append("".join(current_sent).strip())

        return [s for s in sentences if s]

    def _split_on_punctuation(self, word: str, word_start: int) -> list[Token]:
        """
        Split word on punctuation marks.

        Args:
            word: Word to split
            word_start: Character offset of word in document

        Returns:
            List of tokens
        """
        tokens = []
        current_token = []
        current_offset = word_start

        for i, char in enumerate(word):
            if char in self.PUNCT_CHARS:
                # Emit previous token
                if current_token:
                    token_text = "".join(current_token)
                    token_span = Span(current_offset, current_offset + len(token_text))
                    tokens.append(Token(text=token_text, span=token_span))
                    current_offset += len(token_text)
                    current_token = []

                # Emit punctuation as token
                token_span = Span(current_offset, current_offset + 1)
                tokens.append(Token(text=char, span=token_span))
                current_offset += 1
            else:
                current_token.append(char)

        # Emit final token
        if current_token:
            token_text = "".join(current_token)
            token_span = Span(current_offset, current_offset + len(token_text))
            tokens.append(Token(text=token_text, span=token_span))

        return tokens

    def _normalize_unicode(self, text: str) -> str:
        """
        Normalize unicode text (NFC normalization).

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        # NFC normalization
        text = unicodedata.normalize("NFC", text)

        # Replace smart quotes
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(""", "'").replace(""", "'")

        if self.lowercase:
            text = text.lower()

        return text


class BPETokenizer:
    """
    Byte Pair Encoding (BPE) tokenizer for subword tokenization.

    Implements BPE algorithm from scratch for learning and applying BPE
    vocabulary to tokenize text into subwords.
    """

    def __init__(self, vocab_size: int = 1000, min_freq: int = 2) -> None:
        """
        Initialize BPE tokenizer.

        Args:
            vocab_size: Target vocabulary size
            min_freq: Minimum frequency for pair merging
        """
        self.vocab_size = vocab_size
        self.min_freq = min_freq
        self.bpe_ranks: dict[tuple[str, str], int] = {}
        self.word_freq: dict[str, int] = defaultdict(int)
        self.vocab: set[str] = set()
        self.base_tokenizer = Tokenizer(lowercase=False)

    def train(self, texts: list[str]) -> None:
        """
        Train BPE vocabulary on texts.

        Args:
            texts: List of texts to train on
        """
        # Count word frequencies
        for text in texts:
            for token in self.base_tokenizer.tokenize(text):
                self.word_freq[token.text.lower()] += 1

        # Initialize with character vocabulary
        vocab = set()
        for word in self.word_freq:
            vocab.update(list(word) + ["</w>"])

        # Learn merges
        num_merges = 0
        while num_merges < self.vocab_size and len(vocab) < self.vocab_size:
            # Count pair frequencies
            pair_freq = self._count_pairs(self.word_freq, vocab)
            if not pair_freq:
                break

            # Find most frequent pair
            best_pair = max(pair_freq, key=pair_freq.get)
            if pair_freq[best_pair] < self.min_freq:
                break

            # Merge the pair
            vocab = self._merge_pair(best_pair, self.word_freq, vocab)
            self.bpe_ranks[best_pair] = num_merges
            num_merges += 1

        self.vocab = vocab

    def tokenize(self, text: str) -> list[str]:
        """
        Tokenize text using learned BPE.

        Args:
            text: Text to tokenize

        Returns:
            List of subword tokens
        """
        if not self.bpe_ranks:
            raise TokenizationError("BPE model not trained. Call train() first.")

        # First pass: word tokenization
        tokens = self.base_tokenizer.tokenize(text)
        word_list = [t.text.lower() for t in tokens]

        # Convert words to character-based with word boundary marker
        character_list = []
        for word in word_list:
            chars = list(word) + ["</w>"]
            character_list.append(" ".join(chars))

        # Apply BPE merges
        subword_tokens = []
        for word in character_list:
            chars = word.split()
            while len(chars) > 1:
                # Find best pair to merge
                pair_to_merge = None
                best_rank = float("inf")

                for i in range(len(chars) - 1):
                    pair = (chars[i], chars[i + 1])
                    if pair in self.bpe_ranks and self.bpe_ranks[pair] < best_rank:
                        best_rank = self.bpe_ranks[pair]
                        pair_to_merge = (i, pair)

                if pair_to_merge is None:
                    break

                idx, (left, right) = pair_to_merge
                chars = chars[:idx] + [left + right] + chars[idx + 2 :]

            subword_tokens.extend(chars)

        return subword_tokens

    def _count_pairs(self, word_freq: dict[str, int], vocab: set[str]) -> dict[tuple[str, str], int]:
        """
        Count adjacent pair frequencies in vocabulary.

        Args:
            word_freq: Word frequencies
            vocab: Current vocabulary

        Returns:
            Dictionary of pair frequencies
        """
        pair_freq: dict[tuple[str, str], int] = defaultdict(int)

        for word, freq in word_freq.items():
            chars = list(word) + ["</w>"]
            for i in range(len(chars) - 1):
                pair = (chars[i], chars[i + 1])
                if pair[0] in vocab and pair[1] in vocab:
                    pair_freq[pair] += freq

        return pair_freq

    def _merge_pair(self, pair: tuple[str, str], word_freq: dict[str, int], vocab: set[str]) -> set[str]:
        """
        Merge a pair in the vocabulary.

        Args:
            pair: Pair to merge
            word_freq: Word frequencies (modified in place)
            vocab: Current vocabulary

        Returns:
            Updated vocabulary
        """
        new_vocab = vocab.copy()
        new_vocab.add("".join(pair))

        new_word_freq = {}
        for word, freq in word_freq.items():
            new_word = word.replace("".join(pair), "|".join(pair))
            new_word = new_word.replace("|", "")
            new_word_freq[new_word] = freq

        word_freq.clear()
        word_freq.update(new_word_freq)

        return new_vocab


class CharacterNGramExtractor:
    """
    Extracts character n-grams from text.

    Useful for feature extraction in NLP tasks like language identification,
    text classification, and spelling correction.
    """

    def __init__(self, n: int = 3, include_boundaries: bool = True) -> None:
        """
        Initialize n-gram extractor.

        Args:
            n: N-gram size
            include_boundaries: Whether to include start/end boundary markers
        """
        self.n = n
        self.include_boundaries = include_boundaries

    def extract(self, word: str) -> list[str]:
        """
        Extract character n-grams from a word.

        Args:
            word: Word to extract n-grams from

        Returns:
            List of character n-grams
        """
        if len(word) < self.n:
            return [word]

        # Add boundary markers
        if self.include_boundaries:
            word = f"#{word}#"

        # Extract n-grams
        ngrams = []
        for i in range(len(word) - self.n + 1):
            ngrams.append(word[i : i + self.n])

        return ngrams

    def extract_all_ngrams(self, word: str) -> dict[int, list[str]]:
        """
        Extract all n-grams from 1 to n.

        Args:
            word: Word to extract n-grams from

        Returns:
            Dictionary mapping n to list of n-grams
        """
        ngrams = {}
        for size in range(1, self.n + 1):
            if len(word) >= size:
                boundary_word = f"#{word}#" if self.include_boundaries else word
                size_ngrams = []
                for i in range(len(boundary_word) - size + 1):
                    size_ngrams.append(boundary_word[i : i + size])
                ngrams[size] = size_ngrams

        return ngrams
