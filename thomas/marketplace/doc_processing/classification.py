"""Document classification and analysis.

Implements TF-IDF feature extraction, Naive Bayes classification,
fingerprinting, language detection, and reading level estimation.
"""

import math
from collections import Counter

from thomas.marketplace.doc_processing._types import LanguageCode


class TFIDFFeatureExtractor:
    """Extract TF-IDF features from documents."""

    def __init__(self) -> None:
        """Initialize extractor."""
        self.vocabulary: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.doc_count = 0

    def fit(self, documents: list[str]) -> None:
        """Fit IDF values on documents.

        Args:
            documents: List of document texts.
        """
        self.doc_count = len(documents)
        doc_frequencies: dict[str, int] = {}

        # Build vocabulary and document frequencies
        for doc in documents:
            words = set(doc.lower().split())
            for word in words:
                doc_frequencies[word] = doc_frequencies.get(word, 0) + 1

        # Calculate IDF
        for word, freq in doc_frequencies.items():
            self.idf[word] = math.log(self.doc_count / freq)

        # Build vocabulary
        self.vocabulary = {word: i for i, word in enumerate(self.idf.keys())}

    def transform(self, text: str) -> dict[str, float]:
        """Transform document to TF-IDF vector.

        Args:
            text: Document text.

        Returns:
            Dictionary of word -> TF-IDF value.
        """
        words = text.lower().split()
        word_freq = Counter(words)

        # Calculate TF
        tf: dict[str, float] = {}
        for word, freq in word_freq.items():
            tf[word] = freq / len(words) if words else 0.0

        # Calculate TF-IDF
        tfidf: dict[str, float] = {}
        for word, tf_val in tf.items():
            idf_val = self.idf.get(word, 0.0)
            tfidf[word] = tf_val * idf_val

        return tfidf


class NaiveBayesClassifier:
    """Multinomial Naive Bayes document classifier with Laplace smoothing."""

    def __init__(self, alpha: float = 1.0) -> None:
        """Initialize classifier.

        Args:
            alpha: Laplace smoothing parameter.
        """
        self.alpha = alpha
        self.class_priors: dict[str, float] = {}
        self.class_word_freq: dict[str, dict[str, int]] = {}
        self.vocabulary: set = set()
        self.classes: list[str] = []

    def fit(self, texts: list[str], labels: list[str]) -> None:
        """Train classifier.

        Args:
            texts: List of document texts.
            labels: List of corresponding labels.
        """
        self.classes = list(set(labels))

        # Count class frequencies
        class_counts = Counter(labels)
        total_docs = len(texts)

        for cls in self.classes:
            self.class_priors[cls] = class_counts[cls] / total_docs
            self.class_word_freq[cls] = Counter()

        # Count word frequencies per class
        for text, label in zip(texts, labels):
            words = text.lower().split()
            self.vocabulary.update(words)

            for word in words:
                self.class_word_freq[label][word] += 1

    def predict(self, text: str) -> str:
        """Predict class for text.

        Args:
            text: Text to classify.

        Returns:
            Predicted class label.
        """
        probs = self.predict_proba(text)
        if not probs:
            return self.classes[0] if self.classes else ""

        return max(probs, key=probs.get)

    def predict_proba(self, text: str) -> dict[str, float]:
        """Get class probabilities for text.

        Args:
            text: Text to classify.

        Returns:
            Dictionary of class -> probability.
        """
        words = text.lower().split()
        probs: dict[str, float] = {}

        for cls in self.classes:
            # Start with class prior
            prob = math.log(self.class_priors.get(cls, 0.0001))

            word_freq = self.class_word_freq.get(cls, Counter())
            total_words = sum(word_freq.values())

            # Add word likelihoods (with Laplace smoothing)
            for word in words:
                word_count = word_freq.get(word, 0)
                # P(word|class) = (count + alpha) / (total + alpha * vocab_size)
                likelihood = (word_count + self.alpha) / (total_words + self.alpha * len(self.vocabulary))
                prob += math.log(likelihood + 1e-10)

            probs[cls] = prob

        # Convert log probabilities to probabilities
        if probs:
            max_prob = max(probs.values())
            for cls in probs:
                probs[cls] = math.exp(probs[cls] - max_prob)

            # Normalize
            total = sum(probs.values())
            if total > 0:
                for cls in probs:
                    probs[cls] /= total

        return probs


class SimHashFingerprinter:
    """Generate document fingerprints using SimHash for near-duplicate detection."""

    @staticmethod
    def compute_fingerprint(text: str, hash_size: int = 64) -> int:
        """Compute SimHash fingerprint for document.

        Args:
            text: Document text.
            hash_size: Size of hash in bits.

        Returns:
            Integer fingerprint.
        """
        words = text.lower().split()
        vector = [0] * hash_size

        for word in words:
            # Simple hash of word (normally would use cryptographic hash)
            h = hash(word)

            for i in range(hash_size):
                if (h >> i) & 1:
                    vector[i] += 1
                else:
                    vector[i] -= 1

        # Convert to binary
        fingerprint = 0
        for i in range(hash_size):
            if vector[i] > 0:
                fingerprint |= 1 << i

        return fingerprint

    @staticmethod
    def hamming_distance(fp1: int, fp2: int) -> int:
        """Calculate Hamming distance between fingerprints.

        Args:
            fp1: First fingerprint.
            fp2: Second fingerprint.

        Returns:
            Hamming distance (number of differing bits).
        """
        xor = fp1 ^ fp2
        distance = 0
        while xor:
            distance += xor & 1
            xor >>= 1
        return distance

    @staticmethod
    def similarity(fp1: int, fp2: int, hash_size: int = 64) -> float:
        """Calculate similarity between fingerprints.

        Args:
            fp1: First fingerprint.
            fp2: Second fingerprint.
            hash_size: Size of hash.

        Returns:
            Similarity 0-1 (higher = more similar).
        """
        distance = SimHashFingerprinter.hamming_distance(fp1, fp2)
        return 1.0 - (distance / hash_size)


class LanguageDetector:
    """Detect document language using character n-gram profiles."""

    # Simple language profiles (character trigram frequencies)
    LANGUAGE_PROFILES: dict[str, dict[str, float]] = {
        "en": {
            "the": 0.045,
            "and": 0.038,
            "ing": 0.035,
            "ion": 0.025,
            "tion": 0.022,
            " th": 0.020,
            " an": 0.018,
        },
        "es": {
            "que": 0.048,
            " de": 0.040,
            " la": 0.038,
            "ión": 0.028,
            " en": 0.026,
            "nte": 0.024,
            "ent": 0.022,
        },
        "fr": {
            " de": 0.050,
            " la": 0.042,
            "ent": 0.038,
            " et": 0.036,
            "ion": 0.032,
            "que": 0.028,
            " le": 0.026,
        },
        "de": {
            "sch": 0.042,
            "hen": 0.038,
            "ich": 0.035,
            "der": 0.032,
            "cht": 0.028,
            "nge": 0.025,
            "ige": 0.023,
        },
    }

    @staticmethod
    def detect(text: str) -> LanguageCode | None:
        """Detect language of text.

        Args:
            text: Text to analyze.

        Returns:
            LanguageCode or None if undetected.
        """
        if not text or len(text) < 50:
            return None

        # Extract character trigrams
        text_lower = text.lower()
        trigrams: Counter = Counter()

        for i in range(len(text_lower) - 2):
            trigrams[text_lower[i : i + 3]] += 1

        # Normalize
        total = sum(trigrams.values())
        if total == 0:
            return None

        trigram_freq = {t: count / total for t, count in trigrams.items()}

        # Score each language
        scores: dict[str, float] = {}

        for lang, profile in LanguageDetector.LANGUAGE_PROFILES.items():
            score = 0.0
            for trigram, freq in profile.items():
                if trigram in trigram_freq:
                    # Rank-order statistics similarity
                    score += abs(trigram_freq[trigram] - freq)

            scores[lang] = -score  # Negative because we want max similarity

        # Find best match
        best_lang = min(scores, key=scores.get)

        return LanguageCode(best_lang) if best_lang else None


class GenreClassifier:
    """Classify documents as formal, informal, technical, or legal."""

    @staticmethod
    def classify(text: str) -> str:
        """Classify document genre.

        Args:
            text: Document text.

        Returns:
            Genre: "formal", "informal", "technical", or "legal".
        """
        words = text.lower().split()

        # Count indicators
        formal_words = len([w for w in words if w in ["furthermore", "moreover", "therefore", "hereby", "thereof"]])

        informal_words = len([w for w in words if w in ["gonna", "wanna", "kinda", "awesome", "cool"]])

        tech_words = len([w for w in words if w in ["algorithm", "function", "database", "api", "software"]])

        legal_words = len([w for w in words if w in ["whereas", "thereto", "herein", "thereof", "notwithstanding"]])

        # Classify based on highest indicator count
        scores = {
            "formal": formal_words,
            "informal": informal_words,
            "technical": tech_words,
            "legal": legal_words,
        }

        return max(scores, key=scores.get)


class ReadingLevelEstimator:
    """Estimate document reading level using Flesch-Kincaid and Gunning Fog."""

    @staticmethod
    def flesch_kincaid_grade(text: str) -> float:
        """Calculate Flesch-Kincaid grade level.

        Args:
            text: Document text.

        Returns:
            Grade level (e.g., 8.5 = 8th-9th grade).
        """
        sentences = text.split(".")
        words = text.split()
        syllables = 0

        if not sentences or not words:
            return 0.0

        # Simple syllable estimation
        for word in words:
            syllables += ReadingLevelEstimator._count_syllables(word)

        # Flesch-Kincaid formula
        grade = 0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59

        return max(0.0, grade)

    @staticmethod
    def gunning_fog_index(text: str) -> float:
        """Calculate Gunning Fog index.

        Args:
            text: Document text.

        Returns:
            Grade level equivalent.
        """
        sentences = text.split(".")
        words = text.split()

        if not sentences or not words:
            return 0.0

        # Count complex words (3+ syllables)
        complex_words = 0
        for word in words:
            if ReadingLevelEstimator._count_syllables(word) >= 3:
                complex_words += 1

        # Gunning Fog formula
        index = 0.4 * ((len(words) / len(sentences)) + 100 * (complex_words / len(words)))

        return max(0.0, index)

    @staticmethod
    def _count_syllables(word: str) -> int:
        """Estimate syllable count in word.

        Args:
            word: Word to analyze.

        Returns:
            Estimated syllable count.
        """
        word = word.lower()
        count = 0
        vowels = "aeiouy"
        previous_was_vowel = False

        for char in word:
            is_vowel = char in vowels
            if is_vowel and not previous_was_vowel:
                count += 1
            previous_was_vowel = is_vowel

        # Adjust for silent e
        if word.endswith("e"):
            count -= 1

        return max(1, count)


class DocumentClassifier:
    """High-level document classification interface."""

    def __init__(self) -> None:
        """Initialize classifier."""
        self.naive_bayes = NaiveBayesClassifier()
        self.trained = False

    def train(self, documents: list[str], labels: list[str]) -> None:
        """Train classifier.

        Args:
            documents: Training documents.
            labels: Corresponding labels.
        """
        self.naive_bayes.fit(documents, labels)
        self.trained = True

    def classify(self, text: str) -> dict[str, any]:
        """Classify document.

        Args:
            text: Document to classify.

        Returns:
            Dictionary with classification results.
        """
        result: dict[str, any] = {
            "class": None,
            "probabilities": {},
            "genre": GenreClassifier.classify(text),
            "language": LanguageDetector.detect(text),
            "reading_level": ReadingLevelEstimator.flesch_kincaid_grade(text),
            "fingerprint": SimHashFingerprinter.compute_fingerprint(text),
        }

        if self.trained:
            result["probabilities"] = self.naive_bayes.predict_proba(text)
            result["class"] = self.naive_bayes.predict(text)

        return result
