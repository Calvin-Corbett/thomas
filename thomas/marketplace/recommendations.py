"""Recommendation engine with collaborative filtering and trending products."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from thomas.marketplace._types import Listing, ListingState


@dataclass
class RecommendationScore:
    """Recommendation with score and reason."""

    listing_id: str
    score: Decimal
    reason: str
    rank: int


class CollaborativeFiltering:
    """Item-based collaborative filtering using cosine similarity."""

    def __init__(self) -> None:
        """Initialize collaborative filtering."""
        self._user_purchases: dict[str, set[str]] = {}
        self._listing_vectors: dict[str, dict[str, int]] = {}

    def record_purchase(self, user_id: str, listing_id: str) -> None:
        """Record user purchase for recommendations.

        Args:
            user_id: User identifier.
            listing_id: Listing identifier.
        """
        if user_id not in self._user_purchases:
            self._user_purchases[user_id] = set()

        self._user_purchases[user_id].add(listing_id)

        # Update listing vectors
        if listing_id not in self._listing_vectors:
            self._listing_vectors[listing_id] = {}

        for user_listing in self._user_purchases[user_id]:
            if user_listing != listing_id:
                self._listing_vectors[listing_id][user_listing] = (
                    self._listing_vectors[listing_id].get(user_listing, 0) + 1
                )

    def record_view(self, user_id: str, listing_id: str) -> None:
        """Record user view for recommendations.

        Args:
            user_id: User identifier.
            listing_id: Listing identifier.
        """
        if user_id not in self._user_purchases:
            self._user_purchases[user_id] = set()

        # Lighter weight than purchase
        self._user_purchases[user_id].add(listing_id)

    def get_recommendations(self, user_id: str, limit: int = 5) -> list[tuple[str, Decimal]]:
        """Get item-based collaborative filtering recommendations.

        Args:
            user_id: User identifier.
            limit: Maximum recommendations.

        Returns:
            List of (listing_id, similarity_score) tuples.
        """
        if user_id not in self._user_purchases:
            return []

        user_items = self._user_purchases[user_id]
        recommendations: dict[str, Decimal] = {}

        # For each item user viewed/purchased
        for item in user_items:
            if item not in self._listing_vectors:
                continue

            # Get similar items from vector
            similarities = self._listing_vectors[item]
            for similar_item, count in similarities.items():
                if similar_item not in user_items:
                    score = Decimal(str(count / (1 + len(user_items))))
                    recommendations[similar_item] = recommendations.get(similar_item, Decimal("0")) + score

        # Sort by score
        sorted_recs = sorted(recommendations.items(), key=lambda x: x[1], reverse=True)
        return sorted_recs[:limit]

    @staticmethod
    def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> Decimal:
        """Calculate cosine similarity between vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Similarity score 0-1.
        """
        all_keys = set(vec1.keys()) | set(vec2.keys())
        if not all_keys:
            return Decimal("0")

        dot_product = sum(vec1.get(key, 0) * vec2.get(key, 0) for key in all_keys)

        norm1 = math.sqrt(sum(v**2 for v in vec1.values())) or 1
        norm2 = math.sqrt(sum(v**2 for v in vec2.values())) or 1

        similarity = dot_product / (norm1 * norm2) if norm1 and norm2 else 0
        return Decimal(str(similarity))


class TrendingProductsEngine:
    """Identify trending products using velocity with time decay."""

    VELOCITY_WINDOW_DAYS: int = 7
    TIME_DECAY_FACTOR: float = 0.9  # Decay for older events

    def __init__(self) -> None:
        """Initialize trending engine."""
        self._view_timestamps: dict[str, list[datetime]] = {}
        self._purchase_timestamps: dict[str, list[datetime]] = {}

    def record_view(self, listing_id: str, timestamp: datetime | None = None) -> None:
        """Record product view for trending.

        Args:
            listing_id: Listing identifier.
            timestamp: View timestamp.
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        if listing_id not in self._view_timestamps:
            self._view_timestamps[listing_id] = []

        self._view_timestamps[listing_id].append(timestamp)

    def record_purchase(self, listing_id: str, timestamp: datetime | None = None) -> None:
        """Record product purchase for trending.

        Args:
            listing_id: Listing identifier.
            timestamp: Purchase timestamp.
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        if listing_id not in self._purchase_timestamps:
            self._purchase_timestamps[listing_id] = []

        self._purchase_timestamps[listing_id].append(timestamp)

    def get_trending(self, limit: int = 10) -> list[tuple[str, Decimal]]:
        """Get trending products based on velocity and time decay.

        Args:
            limit: Maximum products to return.

        Returns:
            List of (listing_id, trend_score) tuples.
        """
        now = datetime.utcnow()
        window_start = now - timedelta(days=self.VELOCITY_WINDOW_DAYS)

        trending: dict[str, Decimal] = {}

        # Score views
        for listing_id, timestamps in self._view_timestamps.items():
            recent_views = [ts for ts in timestamps if ts >= window_start]

            if recent_views:
                # Apply time decay - more recent = higher score
                view_score = Decimal("0")
                for ts in recent_views:
                    age_days = (now - ts).days
                    decay = Decimal(str(self.TIME_DECAY_FACTOR**age_days))
                    view_score += decay

                trending[listing_id] = trending.get(listing_id, Decimal("0")) + view_score

        # Score purchases (heavier weight)
        for listing_id, timestamps in self._purchase_timestamps.items():
            recent_purchases = [ts for ts in timestamps if ts >= window_start]

            if recent_purchases:
                purchase_score = Decimal("0")
                for ts in recent_purchases:
                    age_days = (now - ts).days
                    decay = Decimal(str(self.TIME_DECAY_FACTOR**age_days))
                    purchase_score += decay * Decimal("5")  # 5x weight

                trending[listing_id] = trending.get(listing_id, Decimal("0")) + purchase_score

        # Sort by score
        sorted_trending = sorted(trending.items(), key=lambda x: x[1], reverse=True)
        return sorted_trending[:limit]


class FrequentlyBoughtTogether:
    """Find frequently bought together using association rules."""

    MIN_SUPPORT: float = 0.02  # Minimum 2% co-occurrence
    MIN_CONFIDENCE: float = 0.3  # Minimum 30% conditional probability

    def __init__(self) -> None:
        """Initialize FBT engine."""
        self._order_items: list[set[str]] = []
        self._co_occurrence: dict[tuple[str, str], int] = {}

    def record_order(self, listing_ids: list[str]) -> None:
        """Record order contents for association rules.

        Args:
            listing_ids: Listings in order.
        """
        items_set = set(listing_ids)
        self._order_items.append(items_set)

        # Update co-occurrence matrix
        for i, item1 in enumerate(listing_ids):
            for item2 in listing_ids[i + 1 :]:
                key = tuple(sorted([item1, item2]))
                self._co_occurrence[key] = self._co_occurrence.get(key, 0) + 1

    def get_related_items(self, listing_id: str, limit: int = 5) -> list[tuple[str, Decimal]]:
        """Get frequently bought together recommendations.

        Args:
            listing_id: Listing to find related items for.
            limit: Maximum recommendations.

        Returns:
            List of (related_listing_id, confidence) tuples.
        """
        total_orders = len(self._order_items)
        if total_orders == 0:
            return []

        # Find orders containing this listing
        orders_with_item = [items for items in self._order_items if listing_id in items]

        if not orders_with_item:
            return []

        support_threshold = int(total_orders * self.MIN_SUPPORT)

        # Calculate association rules
        related: dict[str, Decimal] = {}

        for co_key, count in self._co_occurrence.items():
            # Check if this pair involves our listing
            if listing_id not in co_key:
                continue

            if count < support_threshold:
                continue

            # Calculate confidence: P(item2 | item1)
            other_item = co_key[0] if co_key[1] == listing_id else co_key[1]
            confidence = Decimal(count) / Decimal(len(orders_with_item))

            if confidence >= Decimal(str(self.MIN_CONFIDENCE)):
                related[other_item] = confidence

        # Sort by confidence
        sorted_related = sorted(related.items(), key=lambda x: x[1], reverse=True)
        return sorted_related[:limit]


class RecommendationEngine:
    """Unified recommendation engine combining multiple algorithms."""

    def __init__(self) -> None:
        """Initialize recommendation engine."""
        self._collab = CollaborativeFiltering()
        self._trending = TrendingProductsEngine()
        self._fbt = FrequentlyBoughtTogether()
        self._listings: dict[str, Listing] = {}

    def index_listing(self, listing: Listing) -> None:
        """Index listing for recommendations.

        Args:
            listing: Listing to index.
        """
        self._listings[listing.id] = listing

    def record_view(self, user_id: str, listing_id: str) -> None:
        """Record user view event.

        Args:
            user_id: User identifier.
            listing_id: Listing identifier.
        """
        self._collab.record_view(user_id, listing_id)
        self._trending.record_view(listing_id)

    def record_purchase(self, user_id: str, listing_ids: list[str]) -> None:
        """Record purchase event.

        Args:
            user_id: User identifier.
            listing_ids: Listings purchased.
        """
        for listing_id in listing_ids:
            self._collab.record_purchase(user_id, listing_id)
            self._trending.record_purchase(listing_id)

        self._fbt.record_order(listing_ids)

    def get_personalized_recommendations(self, user_id: str, limit: int = 10) -> list[RecommendationScore]:
        """Get personalized recommendations for user.

        Args:
            user_id: User identifier.
            limit: Maximum recommendations.

        Returns:
            Ranked recommendations with reasons.
        """
        recommendations: dict[str, tuple[Decimal, str]] = {}

        # Collaborative filtering
        collab_recs = self._collab.get_recommendations(user_id, limit * 2)
        for listing_id, score in collab_recs:
            recommendations[listing_id] = (
                Decimal(str(score)) * Decimal("0.4"),
                "Users who viewed this also viewed",
            )

        # Trending products
        trending = self._trending.get_trending(limit * 2)
        for listing_id, score in trending:
            if listing_id in recommendations:
                recommendations[listing_id] = (
                    recommendations[listing_id][0] + score * Decimal("0.3"),
                    recommendations[listing_id][1],
                )
            else:
                recommendations[listing_id] = (
                    score * Decimal("0.3"),
                    "Trending now",
                )

        # Sort by score
        sorted_recs = sorted(recommendations.items(), key=lambda x: x[1][0], reverse=True)

        results = []
        for rank, (listing_id, (score, reason)) in enumerate(sorted_recs[:limit]):
            results.append(
                RecommendationScore(
                    listing_id=listing_id,
                    score=score,
                    reason=reason,
                    rank=rank + 1,
                )
            )

        return results

    def get_cross_sell_recommendations(self, listing_id: str, limit: int = 5) -> list[RecommendationScore]:
        """Get cross-sell recommendations (frequently bought together).

        Args:
            listing_id: Base listing.
            limit: Maximum recommendations.

        Returns:
            Cross-sell recommendations.
        """
        fbt_recs = self._fbt.get_related_items(listing_id, limit)

        results = []
        for rank, (related_id, confidence) in enumerate(fbt_recs):
            results.append(
                RecommendationScore(
                    listing_id=related_id,
                    score=confidence * Decimal("100"),
                    reason="Frequently bought together",
                    rank=rank + 1,
                )
            )

        return results

    def get_homepage_recommendations(
        self, user_id: str | None = None, limit: int = 20
    ) -> dict[str, list[RecommendationScore]]:
        """Get homepage personalized recommendations.

        Combines personalized, trending, and seasonal recommendations.

        Args:
            user_id: User identifier for personalization.
            limit: Total recommendations.

        Returns:
            Dict with "personalized", "trending", "new" sections.
        """
        recommendations = {
            "personalized": [],
            "trending": [],
            "new": [],
        }

        if user_id:
            personalized = self.get_personalized_recommendations(user_id, limit // 3)
            recommendations["personalized"] = personalized

        # Trending
        trending = self._trending.get_trending(limit // 3)
        for rank, (listing_id, score) in enumerate(trending):
            recommendations["trending"].append(
                RecommendationScore(
                    listing_id=listing_id,
                    score=score,
                    reason="Trending this week",
                    rank=rank + 1,
                )
            )

        # New listings (stub)
        new_listings = [l for l in self._listings.values() if l.state == ListingState.PUBLISHED]
        new_listings.sort(key=lambda l: l.created_at, reverse=True)

        for rank, listing in enumerate(new_listings[: limit // 3]):
            recommendations["new"].append(
                RecommendationScore(
                    listing_id=listing.id,
                    score=Decimal("50"),
                    reason="Just added",
                    rank=rank + 1,
                )
            )

        return recommendations
