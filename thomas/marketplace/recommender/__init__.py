"""
Thomas Recommender Module - A complete recommendation system with multiple algorithms.

This module provides collaborative filtering, matrix factorization, content-based filtering,
and hybrid recommendation strategies with comprehensive evaluation tools.
"""

from thomas.marketplace.recommender._exceptions import (
    ColdStartError,
    InsufficientDataError,
    RecommenderError,
)
from thomas.marketplace.recommender._types import (
    FeatureVector,
    InteractionType,
    ItemProfile,
    Rating,
    Recommendation,
    RecommenderConfig,
    SimilarityMetric,
    UserProfile,
)
from thomas.marketplace.recommender.cold_start import ColdStartHandler
from thomas.marketplace.recommender.collaborative import (
    CollaborativeFilter,
    ItemBasedCF,
    UserBasedCF,
)
from thomas.marketplace.recommender.content_based import ContentBasedRecommender
from thomas.marketplace.recommender.evaluation import (
    PrecisionRecall,
    RankingMetrics,
    RatingMetrics,
    RecommenderEvaluator,
)
from thomas.marketplace.recommender.matrix_factorization import (
    ALSFactorizer,
    MatrixFactorization,
    SGDFactorizer,
)
from thomas.marketplace.recommender.pipeline import RecommendationPipeline
from thomas.marketplace.recommender.session_based import SessionBasedRecommender
from thomas.marketplace.recommender.similarity import (
    SimilarityComputer,
    cosine_similarity,
    euclidean_similarity,
    jaccard_similarity,
    pearson_correlation,
)

__version__ = "0.1.0"

__all__ = [
    # Types
    "InteractionType",
    "Rating",
    "Recommendation",
    "RecommenderConfig",
    "SimilarityMetric",
    "UserProfile",
    "ItemProfile",
    "FeatureVector",
    # Exceptions
    "RecommenderError",
    "ColdStartError",
    "InsufficientDataError",
    # Collaborative Filtering
    "CollaborativeFilter",
    "UserBasedCF",
    "ItemBasedCF",
    # Matrix Factorization
    "MatrixFactorization",
    "ALSFactorizer",
    "SGDFactorizer",
    # Content-based
    "ContentBasedRecommender",
    # Similarity
    "SimilarityComputer",
    "cosine_similarity",
    "pearson_correlation",
    "jaccard_similarity",
    "euclidean_similarity",
    # Evaluation
    "RecommenderEvaluator",
    "PrecisionRecall",
    "RankingMetrics",
    "RatingMetrics",
    # Cold Start
    "ColdStartHandler",
    # Session-based
    "SessionBasedRecommender",
    # Pipeline
    "RecommendationPipeline",
]
