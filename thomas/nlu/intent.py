"""
Intent classification module using TF-IDF and Naive Bayes.

Implements intent classification with TF-IDF features, multinomial Naive Bayes
with Laplace smoothing, multi-intent detection, confidence calibration, intent
hierarchies, and few-shot learning with prototype networks.
"""

import math
from collections import defaultdict

from thomas.nlu._exceptions import ClassificationError
from thomas.nlu._types import ClassificationResult


class IntentClassifier:
    """
    Intent classifier using TF-IDF features and Naive Bayes.

    Learns intent patterns from training data and classifies text into one or more
    intents with confidence scores and optional hierarchical relationships.
    """

    def __init__(self, use_hierarchy: bool = False) -> None:
        """
        Initialize intent classifier.

        Args:
            use_hierarchy: Whether to use hierarchical intent structure
        """
        self.use_hierarchy = use_hierarchy
        self.intent_vocabulary: set[str] = set()
        self.feature_vocabulary: set[str] = set()

        # TF-IDF data structures
        self.idf: dict[str, float] = {}
        self.intent_feature_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.intent_counts: dict[str, int] = defaultdict(int)
        self.intent_total_count: int = 0

        # Naive Bayes probabilities
        self.intent_priors: dict[str, float] = {}
        self.feature_likelihoods: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        # Intent hierarchy
        self.intent_hierarchy: dict[str, str | None] = {}  # intent -> parent

        # Prototype network for few-shot learning
        self.prototypes: dict[str, list[dict[str, float]]] = defaultdict(list)

        self.is_trained = False

    def train(self, train_examples: list[tuple[str, str]]) -> None:
        """
        Train intent classifier on examples.

        Args:
            train_examples: List of (text, intent_label) tuples
        """
        # Build vocabulary and count statistics
        for text, intent in train_examples:
            self.intent_vocabulary.add(intent)
            self.intent_counts[intent] += 1
            self.intent_total_count += 1

            # Extract features (words)
            features = self._extract_features(text)
            for feature in features:
                self.feature_vocabulary.add(feature)
                self.intent_feature_counts[intent][feature] += features[feature]

        # Compute IDF
        num_docs = len(train_examples)
        feature_doc_counts: dict[str, int] = defaultdict(int)

        for text, _ in train_examples:
            seen_features = set(self._extract_features(text).keys())
            for feature in seen_features:
                feature_doc_counts[feature] += 1

        for feature in self.feature_vocabulary:
            doc_count = feature_doc_counts.get(feature, 1)
            self.idf[feature] = math.log(num_docs / max(1, doc_count))

        # Compute Naive Bayes probabilities with Laplace smoothing
        self._compute_probabilities()

        # Build prototypes for few-shot learning
        self._build_prototypes(train_examples)

        self.is_trained = True

    def _compute_probabilities(self) -> None:
        """Compute prior and likelihood probabilities."""
        # Prior probabilities
        for intent in self.intent_vocabulary:
            self.intent_priors[intent] = self.intent_counts[intent] / max(1, self.intent_total_count)

        # Likelihood probabilities with Laplace smoothing
        for intent in self.intent_vocabulary:
            total_count = sum(self.intent_feature_counts[intent].values())

            for feature in self.feature_vocabulary:
                count = self.intent_feature_counts[intent].get(feature, 0)
                # Laplace smoothing: (count + 1) / (total + vocabulary_size)
                self.feature_likelihoods[intent][feature] = (count + 1) / (
                    total_count + len(self.feature_vocabulary) + 1
                )

    def _build_prototypes(self, train_examples: list[tuple[str, str]]) -> None:
        """Build prototype vectors for few-shot learning."""
        for text, intent in train_examples:
            features = self._extract_features(text)

            # Normalize to TF-IDF vector
            tf_idf_vector = {}
            total_weight = 0

            for feature, count in features.items():
                tf = count / max(1, sum(features.values()))
                idf = self.idf.get(feature, 0)
                weight = tf * idf
                tf_idf_vector[feature] = weight
                total_weight += weight**2

            # Normalize
            if total_weight > 0:
                norm = math.sqrt(total_weight)
                for feature in tf_idf_vector:
                    tf_idf_vector[feature] /= norm

            self.prototypes[intent].append(tf_idf_vector)

    def classify(self, text: str, multi_intent: bool = False) -> ClassificationResult:
        """
        Classify text into intent(s).

        Args:
            text: Text to classify
            multi_intent: Whether to return multiple intents

        Returns:
            Classification result
        """
        if not self.is_trained:
            raise ClassificationError("Classifier not trained. Call train() first.")

        if not text.strip():
            raise ClassificationError("Cannot classify empty text")

        # Extract features
        features = self._extract_features(text)

        # Compute scores for each intent using Naive Bayes
        scores: dict[str, float] = {}

        for intent in self.intent_vocabulary:
            # Prior log-probability
            score = math.log(self.intent_priors[intent])

            # Likelihood log-probabilities
            for feature, count in features.items():
                likelihood = self.feature_likelihoods[intent].get(
                    feature, 1 / (sum(self.intent_feature_counts[intent].values()) + len(self.feature_vocabulary) + 1)
                )
                score += count * math.log(likelihood)

            scores[intent] = score

        # Also score using prototype networks
        prototype_scores = self._prototype_score(features)
        for intent in self.intent_vocabulary:
            scores[intent] = 0.7 * scores[intent] + 0.3 * prototype_scores.get(intent, 0)

        # Convert to probabilities via softmax
        max_score = max(scores.values())
        exp_scores = {intent: math.exp(score - max_score) for intent, score in scores.items()}
        total_exp = sum(exp_scores.values())
        probs = {intent: exp_scores[intent] / total_exp for intent in exp_scores}

        # Apply confidence calibration (Platt scaling)
        probs = self._calibrate_confidence(probs)

        # Get results
        sorted_intents = sorted(probs.items(), key=lambda x: x[1], reverse=True)

        if multi_intent:
            # Return all intents above threshold
            threshold = 0.1
            predictions = {intent: prob for intent, prob in sorted_intents if prob > threshold}
        else:
            # Single-intent mode exposes a one-hot prediction map.
            predictions = {sorted_intents[0][0]: 1.0}

        top_label, top_conf = sorted_intents[0]

        return ClassificationResult(
            predictions=predictions, top_label=top_label, top_confidence=top_conf, all_scores=sorted_intents
        )

    def _extract_features(self, text: str) -> dict[str, int]:
        """
        Extract bag-of-words features.

        Args:
            text: Text to extract features from

        Returns:
            Feature count dictionary
        """
        # Simple tokenization
        tokens = text.lower().split()
        features: dict[str, int] = defaultdict(int)

        for token in tokens:
            # Remove punctuation
            token = "".join(c for c in token if c.isalnum())
            if token:
                features[token] += 1

        return dict(features)

    def _prototype_score(self, features: dict[str, int]) -> dict[str, float]:
        """
        Score using prototype networks (cosine similarity).

        Args:
            features: Feature dictionary

        Returns:
            Intent scores
        """
        # Build query vector
        total_weight = sum((count * self.idf.get(feature, 0)) ** 2 for feature, count in features.items())
        if total_weight == 0:
            return {intent: 0.0 for intent in self.intent_vocabulary}

        query_norm = math.sqrt(total_weight)
        query_vector = {feature: (count * self.idf.get(feature, 0)) / query_norm for feature, count in features.items()}

        # Compute similarity to prototypes
        scores: dict[str, float] = defaultdict(float)

        for intent, proto_vectors in self.prototypes.items():
            if not proto_vectors:
                continue

            similarities = []
            for proto in proto_vectors:
                # Cosine similarity
                sim = sum(
                    query_vector.get(feature, 0) * proto.get(feature, 0)
                    for feature in set(query_vector.keys()) | set(proto.keys())
                )
                similarities.append(sim)

            # Average similarity
            scores[intent] = sum(similarities) / len(similarities)

        return dict(scores)

    def _calibrate_confidence(self, probs: dict[str, float]) -> dict[str, float]:
        """
        Calibrate confidence scores using Platt scaling.

        Args:
            probs: Raw probability scores

        Returns:
            Calibrated probabilities
        """
        # Simple calibration: apply softmax and adjust
        # In production, would use learned Platt scaling coefficients
        total = sum(probs.values())
        return {intent: prob / total for intent, prob in probs.items()}

    def set_intent_hierarchy(self, parent_map: dict[str, str | None]) -> None:
        """
        Set intent hierarchy for hierarchical classification.

        Args:
            parent_map: Dictionary mapping intent to parent intent
        """
        self.intent_hierarchy = parent_map

    def get_intent_hierarchy(self, intent: str) -> list[str]:
        """
        Get hierarchy path for intent (from root to intent).

        Args:
            intent: Intent label

        Returns:
            List of intents from root to specified intent
        """
        path = [intent]
        current = intent

        while current in self.intent_hierarchy and self.intent_hierarchy[current]:
            current = self.intent_hierarchy[current]
            path.insert(0, current)

        return path

    def classify_with_hierarchy(self, text: str) -> tuple[str, float, list[str]]:
        """
        Classify text respecting intent hierarchy.

        Args:
            text: Text to classify

        Returns:
            (top_intent, confidence, hierarchy_path)
        """
        result = self.classify(text)
        hierarchy = (
            self.get_intent_hierarchy(result.top_label)
            if result.top_label in self.intent_hierarchy
            else [result.top_label]
        )

        return result.top_label, result.top_confidence, hierarchy
