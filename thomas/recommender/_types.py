"""
Core type definitions for the recommender system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class InteractionType(Enum):
    """Types of user interactions with items."""

    VIEW = "view"
    CLICK = "click"
    PURCHASE = "purchase"
    RATE = "rate"


class SimilarityMetric(Enum):
    """Available similarity metrics for recommendations."""

    COSINE = "cosine"
    PEARSON = "pearson"
    JACCARD = "jaccard"
    EUCLIDEAN = "euclidean"
    ADJUSTED_COSINE = "adjusted_cosine"
    HAMMING = "hamming"


@dataclass
class Rating:
    """Represents a user's rating of an item.

    Attributes:
        user_id: Unique identifier for the user.
        item_id: Unique identifier for the item.
        score: Rating score (typically 0-5 or 0-10).
        timestamp: When the rating was given.
        interaction_type: Type of interaction (view, click, purchase, rate).
    """

    user_id: str
    item_id: str
    score: float
    timestamp: datetime
    interaction_type: InteractionType = InteractionType.RATE

    def __post_init__(self) -> None:
        """Validate rating score is positive."""
        if self.score < 0:
            raise ValueError(f"Rating score must be non-negative, got {self.score}")


@dataclass
class FeatureVector:
    """Represents a sparse feature vector.

    Attributes:
        features: Dictionary mapping feature names to values.
        norm: L2 norm of the vector (cached for efficiency).
    """

    features: dict[str, float] = field(default_factory=dict)
    norm: float | None = None

    def compute_norm(self) -> float:
        """Compute L2 norm of the feature vector.

        Returns:
            The L2 norm of the vector.
        """
        if self.norm is not None:
            return self.norm
        self.norm = sum(v**2 for v in self.features.values()) ** 0.5
        return self.norm

    def add_feature(self, name: str, value: float) -> None:
        """Add or update a feature.

        Args:
            name: Feature name.
            value: Feature value.
        """
        self.features[name] = value
        self.norm = None  # Invalidate cached norm

    def get_feature(self, name: str, default: float = 0.0) -> float:
        """Get a feature value safely.

        Args:
            name: Feature name.
            default: Default value if feature doesn't exist.

        Returns:
            The feature value or default.
        """
        return self.features.get(name, default)

    def dimension(self) -> int:
        """Get the number of features.

        Returns:
            Number of non-zero features.
        """
        return len(self.features)


@dataclass
class UserProfile:
    """Represents a user's profile for recommendations.

    Attributes:
        user_id: Unique user identifier.
        feature_vector: User's feature vector (from rated items).
        ratings: List of all user's ratings.
        metadata: Additional user metadata (age, location, etc).
        created_at: When the profile was created.
    """

    user_id: str
    feature_vector: FeatureVector = field(default_factory=FeatureVector)
    ratings: list[Rating] = field(default_factory=list)
    metadata: dict[str, any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def rating_count(self) -> int:
        """Get number of ratings given by user.

        Returns:
            Count of ratings.
        """
        return len(self.ratings)

    def average_rating(self) -> float:
        """Calculate average rating score for user.

        Returns:
            Average rating score, or 0 if no ratings.
        """
        if not self.ratings:
            return 0.0
        return sum(r.score for r in self.ratings) / len(self.ratings)

    def get_rated_items(self) -> dict[str, float]:
        """Get all items rated by user with scores.

        Returns:
            Mapping of item_id to rating score.
        """
        return {r.item_id: r.score for r in self.ratings}


@dataclass
class ItemProfile:
    """Represents an item's profile for recommendations.

    Attributes:
        item_id: Unique item identifier.
        feature_vector: Item's feature vector (from metadata/description).
        ratings: List of user ratings for this item.
        metadata: Item attributes (title, category, genres, tags).
        created_at: When the item was added.
    """

    item_id: str
    feature_vector: FeatureVector = field(default_factory=FeatureVector)
    ratings: list[Rating] = field(default_factory=list)
    metadata: dict[str, any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def rating_count(self) -> int:
        """Get number of ratings for this item.

        Returns:
            Count of ratings.
        """
        return len(self.ratings)

    def average_rating(self) -> float:
        """Calculate average rating for item.

        Returns:
            Average rating score, or 0 if no ratings.
        """
        if not self.ratings:
            return 0.0
        return sum(r.score for r in self.ratings) / len(self.ratings)

    def popularity(self) -> int:
        """Get popularity as number of interactions.

        Returns:
            Number of ratings/interactions.
        """
        return len(self.ratings)


@dataclass
class Recommendation:
    """Represents a recommendation for a user.

    Attributes:
        item_id: The recommended item.
        score: Recommendation score (higher is better).
        explanation: Human-readable explanation for the recommendation.
        confidence: Confidence in the recommendation (0-1).
        algorithm: Name of algorithm that generated it.
    """

    item_id: str
    score: float
    explanation: str = ""
    confidence: float = 1.0
    algorithm: str = "unknown"

    def __lt__(self, other: "Recommendation") -> bool:
        """Compare recommendations by score (descending).

        Args:
            other: Another recommendation.

        Returns:
            True if this recommendation scores lower.
        """
        return self.score < other.score

    def __le__(self, other: "Recommendation") -> bool:
        """Compare recommendations by score (descending).

        Args:
            other: Another recommendation.

        Returns:
            True if this recommendation scores lower or equal.
        """
        return self.score <= other.score


@dataclass
class RecommenderConfig:
    """Configuration for recommender systems.

    Attributes:
        k: Number of neighbors to use (for collaborative filtering).
        similarity_metric: Metric for computing similarity.
        min_ratings: Minimum ratings needed for recommendation.
        latent_factors: Number of latent factors (for matrix factorization).
        learning_rate: Learning rate for training algorithms.
        regularization: Regularization parameter (L2).
        iterations: Number of training iterations.
        convergence_threshold: Stop training when improvement below this.
        random_seed: Random seed for reproducibility.
    """

    k: int = 10
    similarity_metric: SimilarityMetric = SimilarityMetric.COSINE
    min_ratings: int = 2
    latent_factors: int = 20
    learning_rate: float = 0.01
    regularization: float = 0.01
    iterations: int = 100
    convergence_threshold: float = 1e-5
    random_seed: int = 42

    def validate(self) -> None:
        """Validate configuration parameters.

        Raises:
            ValueError: If any parameter is invalid.
        """
        if self.k < 1:
            raise ValueError(f"k must be >= 1, got {self.k}")
        if self.min_ratings < 0:
            raise ValueError(f"min_ratings must be >= 0, got {self.min_ratings}")
        if self.latent_factors < 1:
            raise ValueError(f"latent_factors must be >= 1, got {self.latent_factors}")
        if not (0 < self.learning_rate < 1):
            raise ValueError(f"learning_rate must be in (0, 1), got {self.learning_rate}")
        if self.regularization < 0:
            raise ValueError(f"regularization must be >= 0, got {self.regularization}")
        if self.iterations < 1:
            raise ValueError(f"iterations must be >= 1, got {self.iterations}")
        if self.convergence_threshold < 0:
            raise ValueError(f"convergence_threshold must be >= 0, got {self.convergence_threshold}")
