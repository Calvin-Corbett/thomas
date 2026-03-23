"""
Content-based filtering recommendation algorithms.

Uses item features and metadata to make recommendations based on item similarity
to items the user has previously rated highly.
"""

import math

from thomas.marketplace.recommender._exceptions import ColdStartError
from thomas.marketplace.recommender._types import Rating, Recommendation, RecommenderConfig
from thomas.marketplace.recommender.similarity import cosine_similarity


class TFIDFVectorizer:
    """TF-IDF feature extraction for text descriptions."""

    def __init__(self) -> None:
        """Initialize TF-IDF vectorizer."""
        self.idf: dict[str, float] = {}
        self.vocabulary: set[str] = set()

    def build_vocabulary(self, documents: list[str]) -> None:
        """Build vocabulary and compute IDF values.

        Args:
            documents: List of text documents.
        """
        # Count document frequencies
        doc_freq: dict[str, int] = {}
        num_docs = len(documents)

        for doc in documents:
            words = set(self._tokenize(doc))
            for word in words:
                doc_freq[word] = doc_freq.get(word, 0) + 1
                self.vocabulary.add(word)

        # Compute IDF
        for word, freq in doc_freq.items():
            self.idf[word] = math.log(num_docs / (1 + freq))

    def vectorize(self, document: str) -> dict[str, float]:
        """Convert document to TF-IDF vector.

        Args:
            document: Text document to vectorize.

        Returns:
            Dictionary mapping words to TF-IDF scores.
        """
        words = self._tokenize(document)
        tf: dict[str, int] = {}

        # Count word frequencies
        for word in words:
            tf[word] = tf.get(word, 0) + 1

        # Compute TF-IDF
        vector = {}
        for word, count in tf.items():
            if word in self.idf:
                tf_score = count / len(words) if words else 0
                vector[word] = tf_score * self.idf[word]

        return vector

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into words.

        Args:
            text: Text to tokenize.

        Returns:
            List of words.
        """
        # Simple tokenization: lowercase and split on whitespace
        return text.lower().split()


class ContentBasedRecommender:
    """Content-based filtering using item features.

    Recommends items based on similarity to items the user has rated highly.
    Uses TF-IDF vectorization for text features and manual feature vectors.
    """

    def __init__(self, config: RecommenderConfig | None = None) -> None:
        """Initialize content-based recommender.

        Args:
            config: Recommender configuration.
        """
        self.config = config or RecommenderConfig()
        self.config.validate()

        self.ratings: list[Rating] = []
        self.item_features: dict[str, dict[str, float]] = {}
        self.user_profiles: dict[str, dict[str, float]] = {}
        self.vectorizer = TFIDFVectorizer()

    def add_rating(self, rating: Rating) -> None:
        """Add a rating.

        Args:
            rating: Rating to add.
        """
        self.ratings.append(rating)

    def add_ratings(self, ratings: list[Rating]) -> None:
        """Add multiple ratings.

        Args:
            ratings: List of ratings to add.
        """
        self.ratings.extend(ratings)

    def add_item_features(self, item_id: str, features: dict[str, float]) -> None:
        """Add feature vector for an item.

        Args:
            item_id: Item identifier.
            features: Feature vector as dictionary.
        """
        self.item_features[item_id] = features

    def add_item_description(self, item_id: str, description: str) -> None:
        """Add text description for an item.

        Args:
            item_id: Item identifier.
            description: Text description of item.
        """
        vector = self.vectorizer.vectorize(description)
        if item_id in self.item_features:
            self.item_features[item_id].update(vector)
        else:
            self.item_features[item_id] = vector

    def _get_user_ratings(self, user_id: str) -> dict[str, float]:
        """Get all ratings for a user.

        Args:
            user_id: User identifier.

        Returns:
            Dictionary mapping item_id to rating score.
        """
        return {r.item_id: r.score for r in self.ratings if r.user_id == user_id}

    def _get_all_items(self) -> set[str]:
        """Get all items with features.

        Returns:
            Set of item IDs.
        """
        return set(self.item_features.keys())

    def _build_user_profile(self, user_id: str) -> dict[str, float]:
        """Build a user profile from their rated items.

        User profile is weighted average of features of items they rated highly.

        Args:
            user_id: User identifier.

        Returns:
            User profile as feature vector.
        """
        user_ratings = self._get_user_ratings(user_id)
        if not user_ratings:
            return {}

        profile: dict[str, float] = {}
        total_weight = 0.0

        for item_id, rating in user_ratings.items():
            if item_id not in self.item_features:
                continue

            weight = rating  # Use rating as weight
            total_weight += weight

            item_features = self.item_features[item_id]
            for feature, value in item_features.items():
                profile[feature] = profile.get(feature, 0.0) + weight * value

        # Normalize
        if total_weight > 0:
            profile = {f: v / total_weight for f, v in profile.items()}

        return profile

    def build_user_profiles(self) -> None:
        """Build profiles for all users."""
        all_users = {r.user_id for r in self.ratings}
        for user_id in all_users:
            self.user_profiles[user_id] = self._build_user_profile(user_id)

    def get_user_profile(self, user_id: str) -> dict[str, float]:
        """Get or build user profile.

        Args:
            user_id: User identifier.

        Returns:
            User profile as feature vector.
        """
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = self._build_user_profile(user_id)
        return self.user_profiles[user_id]

    def predict_rating(self, user_id: str, item_id: str) -> float | None:
        """Predict a rating based on content similarity.

        Prediction = cosine_similarity(user_profile, item_features).

        Args:
            user_id: User identifier.
            item_id: Item identifier.

        Returns:
            Predicted rating or None if prediction not possible.
        """
        user_profile = self.get_user_profile(user_id)
        if not user_profile or item_id not in self.item_features:
            return None

        item_features = self.item_features[item_id]
        similarity = cosine_similarity(user_profile, item_features)

        # Scale similarity to rating scale (assuming 0-5)
        return similarity * 5.0

    def recommend(
        self,
        user_id: str,
        n: int = 10,
        exclude_rated: bool = True,
    ) -> list[Recommendation]:
        """Get top-N recommendations for a user.

        Args:
            user_id: User to recommend for.
            n: Number of recommendations.
            exclude_rated: If True, don't recommend already-rated items.

        Returns:
            List of recommendations sorted by score.

        Raises:
            ColdStartError: If user has no rating history.
        """
        user_ratings = self._get_user_ratings(user_id)
        if not user_ratings:
            raise ColdStartError("user", user_id, "No rating history")

        all_items = self._get_all_items()
        if exclude_rated:
            all_items = all_items - set(user_ratings.keys())

        recommendations: list[Recommendation] = []
        for item_id in all_items:
            pred_rating = self.predict_rating(user_id, item_id)
            if pred_rating is not None and pred_rating > 0:
                rec = Recommendation(
                    item_id=item_id,
                    score=pred_rating,
                    explanation="Content-based similarity match",
                    algorithm="ContentBased",
                )
                recommendations.append(rec)

        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations[:n]

    def recommend_by_item(
        self,
        item_id: str,
        n: int = 10,
        exclude_item: bool = True,
    ) -> list[Recommendation]:
        """Get items similar to a given item.

        Args:
            item_id: Reference item.
            n: Number of recommendations.
            exclude_item: If True, don't recommend the reference item.

        Returns:
            List of recommendations for similar items.
        """
        if item_id not in self.item_features:
            raise ValueError(f"Item {item_id} not found")

        ref_features = self.item_features[item_id]
        all_items = self._get_all_items()

        if exclude_item:
            all_items = all_items - {item_id}

        recommendations: list[Recommendation] = []
        for other_item in all_items:
            other_features = self.item_features[other_item]
            similarity = cosine_similarity(ref_features, other_features)

            if similarity > 0:
                rec = Recommendation(
                    item_id=other_item,
                    score=similarity,
                    explanation=f"Similar to {item_id}",
                    algorithm="ContentBased",
                )
                recommendations.append(rec)

        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations[:n]
