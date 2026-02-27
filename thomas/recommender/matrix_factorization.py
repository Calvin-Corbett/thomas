"""
Matrix factorization algorithms for collaborative filtering.

This module implements Alternating Least Squares (ALS) and Stochastic Gradient Descent (SGD)
for low-rank matrix factorization of user-item ratings matrices.
"""

import math
import random

from thomas.recommender._exceptions import ColdStartError, InsufficientDataError
from thomas.recommender._types import Rating, Recommendation, RecommenderConfig


class MatrixFactorization:
    """Base class for matrix factorization recommenders."""

    def __init__(self, config: RecommenderConfig | None = None) -> None:
        """Initialize matrix factorization recommender.

        Args:
            config: Recommender configuration.
        """
        self.config = config or RecommenderConfig()
        self.config.validate()

        # Random seed for reproducibility
        random.seed(self.config.random_seed)

        self.ratings: list[Rating] = []
        self.user_factors: dict[str, list[float]] = {}
        self.item_factors: dict[str, list[float]] = {}
        self.user_biases: dict[str, float] = {}
        self.item_biases: dict[str, float] = {}
        self.global_bias: float = 0.0
        self.is_trained: bool = False

    def add_rating(self, rating: Rating) -> None:
        """Add a rating to the system.

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

    def _get_user_ratings(self, user_id: str) -> dict[str, float]:
        """Get all ratings for a user.

        Args:
            user_id: User identifier.

        Returns:
            Dictionary mapping item_id to rating score.
        """
        return {r.item_id: r.score for r in self.ratings if r.user_id == user_id}

    def _get_item_ratings(self, item_id: str) -> dict[str, float]:
        """Get all ratings for an item.

        Args:
            item_id: Item identifier.

        Returns:
            Dictionary mapping user_id to rating score.
        """
        return {r.user_id: r.score for r in self.ratings if r.item_id == item_id}

    def _get_all_users(self) -> set[str]:
        """Get all users in the system.

        Returns:
            Set of user IDs.
        """
        return {r.user_id for r in self.ratings}

    def _get_all_items(self) -> set[str]:
        """Get all items in the system.

        Returns:
            Set of item IDs.
        """
        return {r.item_id for r in self.ratings}

    def _initialize_factors(self) -> None:
        """Initialize user and item factor vectors randomly."""
        all_users = self._get_all_users()
        all_items = self._get_all_items()

        # Initialize factor vectors with small random values
        for user_id in all_users:
            self.user_factors[user_id] = [random.gauss(0, 0.01) for _ in range(self.config.latent_factors)]
            self.user_biases[user_id] = 0.0

        for item_id in all_items:
            self.item_factors[item_id] = [random.gauss(0, 0.01) for _ in range(self.config.latent_factors)]
            self.item_biases[item_id] = 0.0

        # Compute global mean bias
        if self.ratings:
            self.global_bias = sum(r.score for r in self.ratings) / len(self.ratings)

    def _dot_product(self, user_factors: list[float], item_factors: list[float]) -> float:
        """Compute dot product of two vectors.

        Args:
            user_factors: User factor vector.
            item_factors: Item factor vector.

        Returns:
            Dot product value.
        """
        return sum(u * i for u, i in zip(user_factors, item_factors))

    def _compute_rmse(self) -> float:
        """Compute root mean squared error on current ratings.

        Returns:
            RMSE value.
        """
        if not self.ratings:
            return 0.0

        total_error = 0.0
        for rating in self.ratings:
            pred = self.predict_rating(rating.user_id, rating.item_id)
            if pred is not None:
                total_error += (rating.score - pred) ** 2

        return math.sqrt(total_error / len(self.ratings))

    def predict_rating(self, user_id: str, item_id: str) -> float | None:
        """Predict a rating using learned factors.

        Args:
            user_id: User identifier.
            item_id: Item identifier.

        Returns:
            Predicted rating or None if user/item not in training data.
        """
        if user_id not in self.user_factors or item_id not in self.item_factors:
            return None

        # Prediction = global_bias + user_bias + item_bias + dot(user_factors, item_factors)
        pred = self.global_bias
        pred += self.user_biases.get(user_id, 0.0)
        pred += self.item_biases.get(item_id, 0.0)
        pred += self._dot_product(self.user_factors[user_id], self.item_factors[item_id])

        return pred

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
            ColdStartError: If user is not in training data.
        """
        if not self.is_trained:
            raise ValueError("Model not trained yet. Call fit() first.")

        if user_id not in self.user_factors:
            raise ColdStartError("user", user_id, "Not in training data")

        user_ratings = self._get_user_ratings(user_id)
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
                    explanation="Predicted from matrix factorization",
                    algorithm=self.__class__.__name__,
                )
                recommendations.append(rec)

        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations[:n]


class ALSFactorizer(MatrixFactorization):
    """Alternating Least Squares matrix factorization.

    ALS alternates between fixing user factors and solving for item factors,
    then fixing item factors and solving for user factors.
    """

    def fit(self) -> None:
        """Train the model using ALS algorithm."""
        if not self.ratings:
            raise InsufficientDataError(1, 0, "ratings")

        self._initialize_factors()

        prev_rmse = float("inf")

        for iteration in range(self.config.iterations):
            # Fix item factors, optimize user factors
            self._optimize_users()

            # Fix user factors, optimize item factors
            self._optimize_items()

            # Check convergence
            rmse = self._compute_rmse()
            improvement = prev_rmse - rmse

            if improvement < self.config.convergence_threshold:
                break

            prev_rmse = rmse

        self.is_trained = True

    def _optimize_users(self) -> None:
        """Optimize user factors (fixing item factors)."""
        all_users = self._get_all_users()

        for user_id in all_users:
            user_ratings = self._get_user_ratings(user_id)
            if not user_ratings:
                continue

            # Build matrix A and vector b for least squares
            A = [[0.0] * self.config.latent_factors for _ in range(self.config.latent_factors)]
            b = [0.0] * self.config.latent_factors

            for item_id, rating in user_ratings.items():
                item_factors = self.item_factors[item_id]

                # A += item_factors^T * item_factors
                for i in range(self.config.latent_factors):
                    for j in range(self.config.latent_factors):
                        A[i][j] += item_factors[i] * item_factors[j]

                # Add regularization to diagonal
                A[i][i] += self.config.regularization

                # b += item_factors * rating
                residual = rating - self.global_bias - self.item_biases.get(item_id, 0.0)
                for i in range(self.config.latent_factors):
                    b[i] += item_factors[i] * residual

            # Solve A * x = b using Gaussian elimination
            self.user_factors[user_id] = self._solve_linear_system(A, b)

    def _optimize_items(self) -> None:
        """Optimize item factors (fixing user factors)."""
        all_items = self._get_all_items()

        for item_id in all_items:
            item_ratings = self._get_item_ratings(item_id)
            if not item_ratings:
                continue

            A = [[0.0] * self.config.latent_factors for _ in range(self.config.latent_factors)]
            b = [0.0] * self.config.latent_factors

            for user_id, rating in item_ratings.items():
                user_factors = self.user_factors[user_id]

                for i in range(self.config.latent_factors):
                    for j in range(self.config.latent_factors):
                        A[i][j] += user_factors[i] * user_factors[j]

                    A[i][i] += self.config.regularization

                    residual = rating - self.global_bias - self.user_biases.get(user_id, 0.0)
                    b[i] += user_factors[i] * residual

            self.item_factors[item_id] = self._solve_linear_system(A, b)

    def _solve_linear_system(self, A: list[list[float]], b: list[float]) -> list[float]:
        """Solve linear system Ax = b using Gaussian elimination.

        Args:
            A: Coefficient matrix.
            b: Right-hand side vector.

        Returns:
            Solution vector x.
        """
        n = len(A)
        # Create augmented matrix
        aug = [A[i] + [b[i]] for i in range(n)]

        # Forward elimination
        for i in range(n):
            # Find pivot
            max_row = i
            for k in range(i + 1, n):
                if abs(aug[k][i]) > abs(aug[max_row][i]):
                    max_row = k
            aug[i], aug[max_row] = aug[max_row], aug[i]

            # Make all rows below this one 0 in current column
            if abs(aug[i][i]) > 1e-10:
                for k in range(i + 1, n):
                    c = aug[k][i] / aug[i][i]
                    for j in range(i, n + 1):
                        aug[k][j] -= c * aug[i][j]

        # Back substitution
        x = [0.0] * n
        for i in range(n - 1, -1, -1):
            x[i] = aug[i][n]
            for j in range(i + 1, n):
                x[i] -= aug[i][j] * x[j]
            if abs(aug[i][i]) > 1e-10:
                x[i] /= aug[i][i]

        return x


class SGDFactorizer(MatrixFactorization):
    """Stochastic Gradient Descent matrix factorization.

    SGD updates factors based on individual rating errors using gradient descent.
    """

    def fit(self) -> None:
        """Train the model using SGD algorithm."""
        if not self.ratings:
            raise InsufficientDataError(1, 0, "ratings")

        self._initialize_factors()

        prev_rmse = float("inf")

        for iteration in range(self.config.iterations):
            # Shuffle ratings
            shuffled_ratings = self.ratings.copy()
            random.shuffle(shuffled_ratings)

            # Process each rating
            for rating in shuffled_ratings:
                user_id = rating.user_id
                item_id = rating.item_id
                actual = rating.score

                # Compute prediction and error
                pred = self.predict_rating(user_id, item_id)
                if pred is None:
                    continue

                error = actual - pred

                # Update biases
                self.user_biases[user_id] += (
                    self.config.learning_rate * error - self.config.regularization * self.user_biases[user_id]
                )
                self.item_biases[item_id] += (
                    self.config.learning_rate * error - self.config.regularization * self.item_biases[item_id]
                )

                # Update factors using gradient
                user_factors = self.user_factors[user_id]
                item_factors = self.item_factors[item_id]

                for f in range(self.config.latent_factors):
                    user_grad = error * item_factors[f] - self.config.regularization * user_factors[f]
                    item_grad = error * user_factors[f] - self.config.regularization * item_factors[f]

                    user_factors[f] += self.config.learning_rate * user_grad
                    item_factors[f] += self.config.learning_rate * item_grad

            # Check convergence
            rmse = self._compute_rmse()
            improvement = prev_rmse - rmse

            if improvement < self.config.convergence_threshold:
                break

            prev_rmse = rmse

        self.is_trained = True
