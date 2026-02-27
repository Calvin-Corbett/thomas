"""
Tests for intent classification module.
"""

import unittest

from thomas.nlu._exceptions import ClassificationError
from thomas.nlu.intent import IntentClassifier


class TestIntentClassifier(unittest.TestCase):
    """Tests for intent classifier."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.classifier = IntentClassifier()

        # Training examples
        self.train_examples = [
            ("I'd like to book a flight", "book_flight"),
            ("I want to reserve a ticket", "book_flight"),
            ("Can I book a hotel room?", "book_hotel"),
            ("I need a room for tonight", "book_hotel"),
            ("What's the weather today?", "check_weather"),
            ("Will it rain tomorrow?", "check_weather"),
            ("Tell me about the weather", "check_weather"),
        ]

    def test_training(self) -> None:
        """Test classifier training."""
        self.classifier.train(self.train_examples)

        self.assertTrue(self.classifier.is_trained)
        self.assertGreater(len(self.classifier.intent_vocabulary), 0)

    def test_classification_after_training(self) -> None:
        """Test classification after training."""
        self.classifier.train(self.train_examples)

        result = self.classifier.classify("I want to book a flight")

        self.assertIsNotNone(result)
        self.assertIn(result.top_label, self.classifier.intent_vocabulary)

    def test_single_intent(self) -> None:
        """Test single intent classification."""
        self.classifier.train(self.train_examples)

        result = self.classifier.classify("Book me a flight", multi_intent=False)

        self.assertEqual(len(result.predictions), 1)

    def test_multi_intent(self) -> None:
        """Test multi-intent classification."""
        self.classifier.train(self.train_examples)

        result = self.classifier.classify("Book a flight and check weather", multi_intent=True)

        # Should have multiple intents
        self.assertGreater(len(result.predictions), 0)

    def test_confidence_scores(self) -> None:
        """Test that confidence scores are valid."""
        self.classifier.train(self.train_examples)

        result = self.classifier.classify("Book a flight")

        # Confidence should be in [0, 1]
        self.assertGreaterEqual(result.top_confidence, 0.0)
        self.assertLessEqual(result.top_confidence, 1.0)

    def test_untrained_classifier_error(self) -> None:
        """Test error when using untrained classifier."""
        with self.assertRaises(ClassificationError):
            self.classifier.classify("test")

    def test_empty_text_error(self) -> None:
        """Test error on empty text."""
        self.classifier.train(self.train_examples)

        with self.assertRaises(ClassificationError):
            self.classifier.classify("")

    def test_sorted_predictions(self) -> None:
        """Test that predictions are sorted by confidence."""
        self.classifier.train(self.train_examples)

        result = self.classifier.classify("Book a flight")

        # Predictions should be sorted descending by confidence
        sorted_preds = result.get_sorted_predictions()
        for i in range(len(sorted_preds) - 1):
            self.assertGreaterEqual(sorted_preds[i][1], sorted_preds[i + 1][1])

    def test_intent_vocabulary(self) -> None:
        """Test that intent vocabulary is built correctly."""
        self.classifier.train(self.train_examples)

        expected_intents = {"book_flight", "book_hotel", "check_weather"}
        self.assertEqual(self.classifier.intent_vocabulary, expected_intents)

    def test_feature_extraction(self) -> None:
        """Test feature extraction."""
        features = self.classifier._extract_features("I want to book a flight")

        self.assertGreater(len(features), 0)
        self.assertIn("want", features)
        self.assertIn("book", features)

    def test_idf_computation(self) -> None:
        """Test IDF computation."""
        self.classifier.train(self.train_examples)

        # IDF should be computed
        self.assertGreater(len(self.classifier.idf), 0)

    def test_prototype_building(self) -> None:
        """Test prototype network building."""
        self.classifier.train(self.train_examples)

        # Prototypes should be built
        self.assertGreater(len(self.classifier.prototypes), 0)

    def test_hierarchy_setup(self) -> None:
        """Test intent hierarchy."""
        self.classifier.train(self.train_examples)

        # Set up hierarchy
        hierarchy = {"book_flight": None, "book_hotel": None, "check_weather": None, "book_accommodation": "book_hotel"}
        self.classifier.set_intent_hierarchy(hierarchy)

        # Get hierarchy
        path = self.classifier.get_intent_hierarchy("book_accommodation")
        self.assertIn("book_hotel", path)

    def test_hierarchical_classification(self) -> None:
        """Test classification with hierarchy."""
        self.classifier.train(self.train_examples)

        hierarchy = {"book_flight": "book_travel", "book_hotel": "book_travel", "check_weather": "get_info"}
        self.classifier.set_intent_hierarchy(hierarchy)

        intent, conf, hierarchy_path = self.classifier.classify_with_hierarchy("Book a flight")

        self.assertIsNotNone(intent)
        self.assertGreater(len(hierarchy_path), 0)


class TestIntentClassifierEdgeCases(unittest.TestCase):
    """Test edge cases for intent classifier."""

    def test_single_training_example(self) -> None:
        """Test training with single example."""
        classifier = IntentClassifier()
        classifier.train([("book a flight", "book_flight")])

        result = classifier.classify("book flight")
        self.assertEqual(result.top_label, "book_flight")

    def test_many_intents(self) -> None:
        """Test with many different intents."""
        classifier = IntentClassifier()

        examples = [(f"text for intent {i}", f"intent_{i}") for i in range(20)]
        classifier.train(examples)

        self.assertEqual(len(classifier.intent_vocabulary), 20)

    def test_similar_intents(self) -> None:
        """Test classification with very similar intents."""
        classifier = IntentClassifier()

        examples = [
            ("book a flight", "book_flight"),
            ("reserve a flight", "book_flight"),
            ("book a train", "book_train"),
            ("reserve a train", "book_train"),
        ]
        classifier.train(examples)

        result = classifier.classify("book a flight")
        self.assertEqual(result.top_label, "book_flight")

    def test_very_short_text(self) -> None:
        """Test classification on very short text."""
        classifier = IntentClassifier()
        classifier.train(
            [
                ("book flight", "book_flight"),
                ("book hotel", "book_hotel"),
            ]
        )

        result = classifier.classify("book")
        self.assertIsNotNone(result)

    def test_long_text(self) -> None:
        """Test classification on longer text."""
        classifier = IntentClassifier()
        classifier.train(
            [
                ("book flight", "book_flight"),
            ]
        )

        long_text = "I would like to book a flight please " * 10
        result = classifier.classify(long_text)

        self.assertIsNotNone(result)

    def test_oov_words(self) -> None:
        """Test classification with out-of-vocabulary words."""
        classifier = IntentClassifier()
        classifier.train(
            [
                ("book flight", "book_flight"),
            ]
        )

        result = classifier.classify("xyzabc defgh")
        self.assertIsNotNone(result)

    def test_case_insensitivity(self) -> None:
        """Test case-insensitive classification."""
        classifier = IntentClassifier()
        classifier.train(
            [
                ("book flight", "book_flight"),
            ]
        )

        result1 = classifier.classify("BOOK FLIGHT")
        result2 = classifier.classify("Book Flight")

        self.assertEqual(result1.top_label, result2.top_label)


class TestIntentClassifierProbabilities(unittest.TestCase):
    """Test probability calculations."""

    def test_probability_sum(self) -> None:
        """Test that probabilities sum to approximately 1."""
        classifier = IntentClassifier()
        classifier.train(
            [
                ("book flight", "book_flight"),
                ("book hotel", "book_hotel"),
                ("check weather", "check_weather"),
            ]
        )

        result = classifier.classify("book")

        total = sum(result.predictions.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_confidence_calibration(self) -> None:
        """Test confidence calibration."""
        classifier = IntentClassifier()
        classifier.train(
            [
                ("book flight", "book_flight"),
                ("book hotel", "book_hotel"),
            ]
        )

        result = classifier.classify("book flight")

        # Top confidence should be calibrated
        self.assertGreater(result.top_confidence, 0.3)
        self.assertLess(result.top_confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
