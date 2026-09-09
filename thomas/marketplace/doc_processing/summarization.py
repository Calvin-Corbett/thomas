"""Document summarization using graph-based and statistical methods.

Implements TextRank, LexRank, and LSA-based summarization techniques
with sentence scoring and summary length control.
"""

import math

import numpy as np

from thomas.marketplace.doc_processing._types import Document, Sentence


class SentenceSimilarityCalculator:
    """Calculates similarity between sentences using TF-IDF."""

    def __init__(self) -> None:
        """Initialize calculator."""
        self.tf_cache: dict[str, dict[str, float]] = {}
        self.idf_cache: dict[str, float] = {}

    def calculate_tfidf(self, sentence: str, all_sentences: list[str]) -> dict[str, float]:
        """Calculate TF-IDF vector for sentence.

        Args:
            sentence: Sentence text.
            all_sentences: All sentences in document.

        Returns:
            Dictionary of word -> TF-IDF score.
        """
        words = sentence.lower().split()
        word_freq = {}
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1

        # Calculate TF
        tf: dict[str, float] = {}
        for word, freq in word_freq.items():
            tf[word] = freq / len(words) if words else 0.0

        # Calculate IDF
        idf: dict[str, float] = {}
        for word in word_freq:
            doc_count = sum(1 for s in all_sentences if word in s.lower())
            idf[word] = math.log(len(all_sentences) / (1 + doc_count))

        # TF-IDF
        tfidf: dict[str, float] = {}
        for word in word_freq:
            tfidf[word] = tf[word] * idf[word]

        return tfidf

    def cosine_similarity(self, tfidf1: dict[str, float], tfidf2: dict[str, float]) -> float:
        """Calculate cosine similarity between two TF-IDF vectors.

        Args:
            tfidf1: First TF-IDF vector.
            tfidf2: Second TF-IDF vector.

        Returns:
            Similarity score (0-1).
        """
        all_words = set(tfidf1.keys()) | set(tfidf2.keys())

        if not all_words:
            return 0.0

        dot_product = sum(tfidf1.get(word, 0.0) * tfidf2.get(word, 0.0) for word in all_words)

        norm1 = math.sqrt(sum(v**2 for v in tfidf1.values()))
        norm2 = math.sqrt(sum(v**2 for v in tfidf2.values()))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


class SentenceScorer:
    """Scores sentences based on multiple features."""

    def score_position(self, sentence_idx: int, total_sentences: int) -> float:
        """Score sentence by position (earlier sentences score higher).

        Args:
            sentence_idx: Index of sentence.
            total_sentences: Total sentence count.

        Returns:
            Score 0-1.
        """
        if total_sentences == 0:
            return 0.0
        # Exponential decay from start
        return math.exp(-sentence_idx / total_sentences)

    def score_length(self, word_count: int) -> float:
        """Score sentence by length (prefer 8-16 words).

        Args:
            word_count: Number of words.

        Returns:
            Score 0-1.
        """
        if word_count < 3:
            return 0.0
        if 8 <= word_count <= 16:
            return 1.0
        # Decay outside optimal range
        return max(0.0, 1.0 - abs(word_count - 12) / 20.0)

    def score_title_similarity(self, sentence: str, title: str) -> float:
        """Score sentence by similarity to title.

        Args:
            sentence: Sentence text.
            title: Document title.

        Returns:
            Score 0-1.
        """
        sentence_words = set(sentence.lower().split())
        title_words = set(title.lower().split())

        if not title_words:
            return 0.0

        overlap = len(sentence_words & title_words)
        return overlap / len(title_words)

    def score_keyword_overlap(self, sentence: str, keywords: list[str]) -> float:
        """Score sentence by keyword overlap.

        Args:
            sentence: Sentence text.
            keywords: List of important keywords.

        Returns:
            Score 0-1.
        """
        sentence_words = set(sentence.lower().split())
        keyword_set = set(kw.lower() for kw in keywords)

        if not keyword_set:
            return 0.0

        overlap = len(sentence_words & keyword_set)
        return min(1.0, overlap / len(keyword_set))


class TextRankSummarizer:
    """Extractive summarization using TextRank algorithm.

    Builds a sentence similarity graph, applies PageRank,
    and selects top-scoring sentences.
    """

    def __init__(self) -> None:
        """Initialize summarizer."""
        self.similarity_calc = SentenceSimilarityCalculator()

    def summarize(self, sentences: list[Sentence], summary_length: int = 3) -> list[Sentence]:
        """Summarize document using TextRank.

        Args:
            sentences: Input sentences.
            summary_length: Number of sentences in summary.

        Returns:
            Summary sentences in original order.
        """
        if len(sentences) <= summary_length:
            return sentences

        # Build similarity matrix
        sentence_texts = [s.text for s in sentences]
        similarity_matrix = self._build_similarity_matrix(sentence_texts)

        # Apply PageRank
        scores = self._pagerank(similarity_matrix)

        # Select top sentences
        top_indices = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)[:summary_length]

        # Return in original order
        top_indices.sort()
        return [sentences[i] for i in top_indices]

    def _build_similarity_matrix(self, sentences: list[str]) -> np.ndarray:
        """Build sentence similarity matrix.

        Args:
            sentences: List of sentence texts.

        Returns:
            Similarity matrix (n x n).
        """
        n = len(sentences)
        matrix = np.zeros((n, n))

        tfidf_vectors = [self.similarity_calc.calculate_tfidf(s, sentences) for s in sentences]

        for i in range(n):
            for j in range(n):
                if i != j:
                    matrix[i][j] = self.similarity_calc.cosine_similarity(tfidf_vectors[i], tfidf_vectors[j])

        return matrix

    def _pagerank(
        self,
        graph: np.ndarray,
        iterations: int = 20,
        damping: float = 0.85,
    ) -> list[float]:
        """Apply PageRank algorithm.

        Args:
            graph: Adjacency matrix.
            iterations: Number of iterations.
            damping: Damping factor.

        Returns:
            PageRank scores for each node.
        """
        n = graph.shape[0]
        scores = np.ones(n) / n

        for _ in range(iterations):
            new_scores = np.ones(n) * (1 - damping) / n

            for i in range(n):
                out_degree = np.sum(graph[i])
                if out_degree > 0:
                    for j in range(n):
                        new_scores[j] += damping * graph[i][j] / out_degree * scores[i]

            scores = new_scores

        return scores.tolist()


class LexRankSummarizer:
    """Summarization using LexRank (eigenvector centrality).

    Similar to TextRank but uses eigenvector centrality instead of PageRank.
    """

    def __init__(self) -> None:
        """Initialize summarizer."""
        self.similarity_calc = SentenceSimilarityCalculator()

    def summarize(self, sentences: list[Sentence], summary_length: int = 3) -> list[Sentence]:
        """Summarize using LexRank.

        Args:
            sentences: Input sentences.
            summary_length: Number of sentences in summary.

        Returns:
            Summary sentences.
        """
        if len(sentences) <= summary_length:
            return sentences

        sentence_texts = [s.text for s in sentences]
        similarity_matrix = self._build_similarity_matrix(sentence_texts)

        # Use power iteration for eigenvector
        scores = self._eigenvector_centrality(similarity_matrix)

        # Select top sentences
        top_indices = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)[:summary_length]

        top_indices.sort()
        return [sentences[i] for i in top_indices]

    def _build_similarity_matrix(self, sentences: list[str]) -> np.ndarray:
        """Build normalized similarity matrix."""
        n = len(sentences)
        matrix = np.zeros((n, n))

        tfidf_vectors = [self.similarity_calc.calculate_tfidf(s, sentences) for s in sentences]

        for i in range(n):
            for j in range(n):
                if i != j:
                    matrix[i][j] = self.similarity_calc.cosine_similarity(tfidf_vectors[i], tfidf_vectors[j])

        # Normalize rows
        for i in range(n):
            row_sum = np.sum(matrix[i])
            if row_sum > 0:
                matrix[i] /= row_sum

        return matrix

    def _eigenvector_centrality(self, matrix: np.ndarray, iterations: int = 20) -> list[float]:
        """Calculate eigenvector centrality."""
        n = matrix.shape[0]
        vector = np.ones(n) / n

        for _ in range(iterations):
            vector = matrix.T @ vector
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector /= norm

        return vector.tolist()


class LSASummarizer:
    """Summarization using Latent Semantic Analysis (LSA).

    Decomposes term-sentence matrix using SVD and selects
    representative sentences.
    """

    def summarize(self, sentences: list[Sentence], summary_length: int = 3) -> list[Sentence]:
        """Summarize using LSA.

        Args:
            sentences: Input sentences.
            summary_length: Number of sentences.

        Returns:
            Summary sentences.
        """
        if len(sentences) <= summary_length:
            return sentences

        # Build term-sentence matrix
        matrix = self._build_term_matrix(sentences)

        if matrix.shape[1] == 0:
            return sentences[:summary_length]

        # SVD decomposition
        try:
            u, s, vt = np.linalg.svd(matrix, full_matrices=False)
        except (np.linalg.LinAlgError, ValueError):
            return sentences[:summary_length]

        # Use first k singular values
        k = min(3, len(s) - 1)
        if k < 1:
            k = 1

        # Score sentences by their magnitude in first k components
        scores = np.linalg.norm(vt[:k, :], axis=0)

        top_indices = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)[:summary_length]

        top_indices.sort()
        return [sentences[i] for i in top_indices]

    def _build_term_matrix(self, sentences: list[Sentence]) -> np.ndarray:
        """Build term-frequency matrix.

        Args:
            sentences: Input sentences.

        Returns:
            Term-sentence matrix (terms x sentences).
        """
        # Collect all words
        vocab: set[str] = set()
        sentence_words: list[list[str]] = []

        for sentence in sentences:
            words = sentence.text.lower().split()
            sentence_words.append(words)
            vocab.update(words)

        vocab_list = sorted(vocab)
        vocab_index = {word: i for i, word in enumerate(vocab_list)}

        # Build matrix
        matrix = np.zeros((len(vocab_list), len(sentences)))

        for j, words in enumerate(sentence_words):
            for word in words:
                if word in vocab_index:
                    matrix[vocab_index[word], j] += 1.0

        return matrix


class DocumentSummarizer:
    """High-level document summarization interface."""

    def __init__(self, method: str = "textrank") -> None:
        """Initialize summarizer.

        Args:
            method: "textrank", "lexrank", or "lsa".
        """
        self.method = method

        if method == "textrank":
            self.summarizer = TextRankSummarizer()
        elif method == "lexrank":
            self.summarizer = LexRankSummarizer()
        elif method == "lsa":
            self.summarizer = LSASummarizer()
        else:
            raise ValueError(f"Unknown method: {method}")

    def summarize(self, document: Document, summary_ratio: float = 0.3) -> str:
        """Summarize document.

        Args:
            document: Document to summarize.
            summary_ratio: Ratio of summary to original (0-1).

        Returns:
            Summary text.
        """
        # Extract sentences from document
        sentences: list[Sentence] = []
        for page in document.pages:
            for block in page.text_blocks:
                for para in block.paragraphs:
                    sentences.extend(para.sentences)

        if not sentences:
            return ""

        # Calculate target summary length
        summary_length = max(1, int(len(sentences) * summary_ratio))

        # Summarize
        summary_sentences = self.summarizer.summarize(sentences, summary_length)

        return " ".join(s.text for s in summary_sentences)
