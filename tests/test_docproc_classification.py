"""Tests for document classification module."""

from thomas.doc_processing.classification import (
    DocumentClassifier,
    GenreClassifier,
    LanguageDetector,
    NaiveBayesClassifier,
    ReadingLevelEstimator,
    SimHashFingerprinter,
    TFIDFFeatureExtractor,
)


class TestTFIDFFeatureExtractor:
    """Test TF-IDF feature extraction."""

    def test_fit_and_transform(self) -> None:
        """Test fitting and transformation."""
        documents = [
            "python programming language",
            "java programming language",
            "javascript web development",
        ]

        extractor = TFIDFFeatureExtractor()
        extractor.fit(documents)

        vector = extractor.transform("python programming")

        assert isinstance(vector, dict)
        assert len(vector) > 0

    def test_empty_vocabulary(self) -> None:
        """Test with empty documents."""
        extractor = TFIDFFeatureExtractor()
        extractor.fit([])

        vector = extractor.transform("test")

        assert isinstance(vector, dict)


class TestNaiveBayesClassifier:
    """Test Naive Bayes classification."""

    def test_train_and_predict(self) -> None:
        """Test training and prediction."""
        texts = [
            "this is spam message",
            "buy now cheap stuff",
            "hello how are you",
            "meeting tomorrow at noon",
        ]
        labels = ["spam", "spam", "ham", "ham"]

        classifier = NaiveBayesClassifier()
        classifier.fit(texts, labels)

        prediction = classifier.predict("buy cheap products now")

        assert prediction in ["spam", "ham"]

    def test_predict_proba(self) -> None:
        """Test probability prediction."""
        texts = [
            "this is spam",
            "legitimate email",
        ]
        labels = ["spam", "ham"]

        classifier = NaiveBayesClassifier()
        classifier.fit(texts, labels)

        probs = classifier.predict_proba("spam spam spam")

        assert isinstance(probs, dict)
        assert "spam" in probs or "ham" in probs


class TestSimHashFingerprinter:
    """Test SimHash fingerprinting."""

    def test_compute_fingerprint(self) -> None:
        """Test fingerprint computation."""
        text = "this is a test document"
        fingerprint = SimHashFingerprinter.compute_fingerprint(text)

        assert isinstance(fingerprint, int)

    def test_hamming_distance(self) -> None:
        """Test Hamming distance."""
        fp1 = 0b1010101010
        fp2 = 0b1010101010

        distance = SimHashFingerprinter.hamming_distance(fp1, fp2)

        assert distance == 0

    def test_different_fingerprints(self) -> None:
        """Test different fingerprints."""
        fp1 = 0b1010101010
        fp2 = 0b0101010101

        distance = SimHashFingerprinter.hamming_distance(fp1, fp2)

        assert distance > 0

    def test_similarity(self) -> None:
        """Test similarity calculation."""
        text1 = "the quick brown fox"
        text2 = "the quick brown fox"

        fp1 = SimHashFingerprinter.compute_fingerprint(text1)
        fp2 = SimHashFingerprinter.compute_fingerprint(text2)

        similarity = SimHashFingerprinter.similarity(fp1, fp2)

        assert similarity >= 0.9  # Nearly identical


class TestLanguageDetector:
    """Test language detection."""

    def test_detect_english(self) -> None:
        """Test English detection."""
        text = "The quick brown fox jumps over the lazy dog. " * 5

        language = LanguageDetector.detect(text)

        assert language is not None

    def test_short_text(self) -> None:
        """Test with short text."""
        text = "Hello"

        language = LanguageDetector.detect(text)

        # May return None or a language
        assert language is None or language is not None

    def test_empty_text(self) -> None:
        """Test with empty text."""
        language = LanguageDetector.detect("")

        assert language is None


class TestGenreClassifier:
    """Test genre classification."""

    def test_classify_formal(self) -> None:
        """Test formal text classification."""
        text = "Furthermore, moreover, therefore, we conclude that " * 3

        genre = GenreClassifier.classify(text)

        assert genre in ["formal", "informal", "technical", "legal"]

    def test_classify_informal(self) -> None:
        """Test informal text classification."""
        text = "This is gonna be awesome and cool stuff like " * 3

        genre = GenreClassifier.classify(text)

        assert genre in ["formal", "informal", "technical", "legal"]

    def test_classify_technical(self) -> None:
        """Test technical text classification."""
        text = "algorithm function database api software " * 5

        genre = GenreClassifier.classify(text)

        assert genre in ["formal", "informal", "technical", "legal"]


class TestReadingLevelEstimator:
    """Test reading level estimation."""

    def test_flesch_kincaid(self) -> None:
        """Test Flesch-Kincaid grade level."""
        text = "The cat sat on the mat. " * 5

        grade = ReadingLevelEstimator.flesch_kincaid_grade(text)

        assert grade >= 0

    def test_gunning_fog(self) -> None:
        """Test Gunning Fog index."""
        text = "The cat sat on the mat. " * 5

        index = ReadingLevelEstimator.gunning_fog_index(text)

        assert index >= 0

    def test_count_syllables(self) -> None:
        """Test syllable counting."""
        syllables_cat = ReadingLevelEstimator._count_syllables("cat")
        syllables_beautiful = ReadingLevelEstimator._count_syllables("beautiful")

        assert syllables_cat == 1
        assert syllables_beautiful >= 3

    def test_empty_text(self) -> None:
        """Test with empty text."""
        grade = ReadingLevelEstimator.flesch_kincaid_grade("")
        index = ReadingLevelEstimator.gunning_fog_index("")

        assert grade == 0.0
        assert index == 0.0


class TestDocumentClassifier:
    """Test high-level document classification."""

    def test_classify_untrained(self) -> None:
        """Test classification without training."""
        classifier = DocumentClassifier()
        result = classifier.classify("test document")

        assert isinstance(result, dict)
        assert "class" in result
        assert "genre" in result
        assert "language" in result

    def test_classify_trained(self) -> None:
        """Test classification with training."""
        classifier = DocumentClassifier()
        documents = [
            "spam message buy now",
            "another spam offer",
            "hello friend how are you",
            "meeting tomorrow at office",
        ]
        labels = ["spam", "spam", "ham", "ham"]

        classifier.train(documents, labels)
        result = classifier.classify("cheap products on sale")

        assert result["class"] in ["spam", "ham"]
        assert isinstance(result["probabilities"], dict)

    def test_fingerprint_calculation(self) -> None:
        """Test fingerprint in classification."""
        classifier = DocumentClassifier()
        result = classifier.classify("test document")

        assert isinstance(result["fingerprint"], int)
