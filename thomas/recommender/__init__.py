"""
Thomas Recommender Module - A complete recommendation system with multiple algorithms.

This module provides collaborative filtering, matrix factorization, content-based filtering,
and hybrid recommendation strategies with comprehensive evaluation tools.
"""

from thomas.recommender._exceptions import (
    ColdStartError,
    InsufficientDataError,
    RecommenderError,
)
from thomas.recommender._types import (
    FeatureVector,
    InteractionType,
    ItemProfile,
    Rating,
    Recommendation,
    RecommenderConfig,
    SimilarityMetric,
    UserProfile,
)
from thomas.recommender.cold_start import ColdStartHandler
from thomas.recommender.collaborative import (
    CollaborativeFilter,
    ItemBasedCF,
    UserBasedCF,
)
from thomas.recommender.content_based import ContentBasedRecommender
from thomas.recommender.evaluation import (
    PrecisionRecall,
    RankingMetrics,
    RatingMetrics,
    RecommenderEvaluator,
)
from thomas.recommender.matrix_factorization import (
    ALSFactorizer,
    MatrixFactorization,
    SGDFactorizer,
)
from thomas.recommender.pipeline import RecommendationPipeline
from thomas.recommender.session_based import SessionBasedRecommender
from thomas.recommender.similarity import (
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
