"""Product reviews and ratings management."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4


class ReviewStatus(str):
    """Review moderation status."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Review:
    """Product review."""

    id: str
    product_id: str
    reviewer_id: str
    rating: int
    title: str
    text: str
    verified_purchase: bool = False
    status: str = ReviewStatus.PENDING
    helpful_votes: int = 0
    unhelpful_votes: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    images: list[str] = field(default_factory=list)

    def is_approved(self) -> bool:
        """Check if review is approved."""
        return self.status == ReviewStatus.APPROVED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "product_id": self.product_id,
            "reviewer_id": self.reviewer_id,
            "rating": self.rating,
            "title": self.title,
            "text": self.text,
            "verified_purchase": self.verified_purchase,
            "status": self.status,
            "helpful_votes": self.helpful_votes,
            "unhelpful_votes": self.unhelpful_votes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "images": self.images,
        }


class ReviewManager:
    """Manage product reviews and ratings."""

    def __init__(self) -> None:
        """Initialize review manager."""
        self.reviews: dict[str, Review] = {}
        self.product_ratings: dict[str, dict[str, Any]] = {}
        self.reviewer_profiles: dict[str, dict[str, Any]] = {}
        self.helpful_votes: dict[str, set[str]] = {}  # review_id -> set of user_ids
        self.unhelpful_votes: dict[str, set[str]] = {}

    def submit_review(
        self,
        product_id: str,
        reviewer_id: str,
        rating: int,
        title: str,
        text: str,
        verified_purchase: bool = False,
        images: list[str] | None = None,
    ) -> Review:
        """Submit product review.

        Args:
            product_id: Product ID
            reviewer_id: Reviewer user ID
            rating: Rating 1-5
            title: Review title
            text: Review text
            verified_purchase: Whether purchase verified
            images: Optional review images

        Returns:
            Created review

        Raises:
            ValueError: If rating invalid
        """
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be 1-5")

        if not title or not text:
            raise ValueError("Title and text required")

        review_id = str(uuid4())
        review = Review(
            id=review_id,
            product_id=product_id,
            reviewer_id=reviewer_id,
            rating=rating,
            title=title,
            text=text,
            verified_purchase=verified_purchase,
            images=images or [],
        )

        self.reviews[review_id] = review
        self._update_product_rating(product_id)
        self._update_reviewer_profile(reviewer_id)

        return review

    def approve_review(self, review_id: str) -> Review:
        """Approve review for display.

        Args:
            review_id: Review ID

        Returns:
            Approved review

        Raises:
            ValueError: If review not found
        """
        review = self.reviews.get(review_id)
        if not review:
            raise ValueError(f"Review {review_id} not found")

        review.status = ReviewStatus.APPROVED
        review.updated_at = datetime.utcnow()
        self._update_product_rating(review.product_id)

        return review

    def reject_review(self, review_id: str, reason: str = "") -> Review:
        """Reject review.

        Args:
            review_id: Review ID
            reason: Rejection reason

        Returns:
            Rejected review

        Raises:
            ValueError: If review not found
        """
        review = self.reviews.get(review_id)
        if not review:
            raise ValueError(f"Review {review_id} not found")

        review.status = ReviewStatus.REJECTED
        review.updated_at = datetime.utcnow()
        self._update_product_rating(review.product_id)

        return review

    def mark_helpful(self, review_id: str, user_id: str) -> int:
        """Mark review as helpful.

        Args:
            review_id: Review ID
            user_id: User marking helpful

        Returns:
            Updated helpful count
        """
        if review_id not in self.helpful_votes:
            self.helpful_votes[review_id] = set()

        if user_id not in self.helpful_votes[review_id]:
            self.helpful_votes[review_id].add(user_id)

            review = self.reviews.get(review_id)
            if review:
                review.helpful_votes = len(self.helpful_votes[review_id])
                review.updated_at = datetime.utcnow()

        return self.helpful_votes[review_id].__len__()

    def mark_unhelpful(self, review_id: str, user_id: str) -> int:
        """Mark review as unhelpful.

        Args:
            review_id: Review ID
            user_id: User marking unhelpful

        Returns:
            Updated unhelpful count
        """
        if review_id not in self.unhelpful_votes:
            self.unhelpful_votes[review_id] = set()

        if user_id not in self.unhelpful_votes[review_id]:
            self.unhelpful_votes[review_id].add(user_id)

            review = self.reviews.get(review_id)
            if review:
                review.unhelpful_votes = len(self.unhelpful_votes[review_id])
                review.updated_at = datetime.utcnow()

        return self.unhelpful_votes[review_id].__len__()

    def get_product_reviews(
        self,
        product_id: str,
        approved_only: bool = True,
        sort_by: str = "helpful",
    ) -> list[Review]:
        """Get reviews for product.

        Args:
            product_id: Product ID
            approved_only: Only return approved reviews
            sort_by: Sort by "helpful", "newest", "rating_high", "rating_low"

        Returns:
            List of reviews
        """
        reviews = [
            r for r in self.reviews.values() if r.product_id == product_id and (not approved_only or r.is_approved())
        ]

        # Sort
        if sort_by == "helpful":
            reviews.sort(key=lambda r: r.helpful_votes, reverse=True)
        elif sort_by == "newest":
            reviews.sort(key=lambda r: r.created_at, reverse=True)
        elif sort_by == "rating_high":
            reviews.sort(key=lambda r: r.rating, reverse=True)
        elif sort_by == "rating_low":
            reviews.sort(key=lambda r: r.rating)

        return reviews

    def get_average_rating(self, product_id: str) -> Decimal:
        """Get average product rating.

        Args:
            product_id: Product ID

        Returns:
            Average rating 0-5
        """
        ratings = self.product_ratings.get(product_id, {})
        return ratings.get("average", Decimal("0"))

    def get_rating_distribution(self, product_id: str) -> dict[int, int]:
        """Get rating distribution for product.

        Args:
            product_id: Product ID

        Returns:
            Dict of {rating: count}
        """
        ratings = self.product_ratings.get(product_id, {})
        return ratings.get("distribution", {1: 0, 2: 0, 3: 0, 4: 0, 5: 0})

    def _update_product_rating(self, product_id: str) -> None:
        """Recalculate product rating.

        Args:
            product_id: Product ID
        """
        reviews = [r for r in self.reviews.values() if r.product_id == product_id and r.is_approved()]

        if not reviews:
            self.product_ratings[product_id] = {
                "average": Decimal("0"),
                "count": 0,
                "distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            }
            return

        # Calculate average
        total_rating = sum(r.rating for r in reviews)
        average = Decimal(total_rating) / Decimal(len(reviews))

        # Distribution
        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for review in reviews:
            distribution[review.rating] += 1

        self.product_ratings[product_id] = {
            "average": average.quantize(Decimal("0.01")),
            "count": len(reviews),
            "distribution": distribution,
        }

    def _update_reviewer_profile(self, reviewer_id: str) -> None:
        """Update reviewer profile.

        Args:
            reviewer_id: Reviewer ID
        """
        reviews = [r for r in self.reviews.values() if r.reviewer_id == reviewer_id]

        if not reviews:
            self.reviewer_profiles[reviewer_id] = {
                "review_count": 0,
                "average_rating": Decimal("0"),
                "verified_purchase_count": 0,
            }
            return

        verified_count = sum(1 for r in reviews if r.verified_purchase)
        avg_rating = Decimal(sum(r.rating for r in reviews)) / Decimal(len(reviews))

        self.reviewer_profiles[reviewer_id] = {
            "review_count": len(reviews),
            "average_rating": avg_rating.quantize(Decimal("0.01")),
            "verified_purchase_count": verified_count,
        }

    def get_reviewer_profile(self, reviewer_id: str) -> dict[str, Any]:
        """Get reviewer profile.

        Args:
            reviewer_id: Reviewer ID

        Returns:
            Reviewer profile
        """
        return self.reviewer_profiles.get(
            reviewer_id,
            {
                "review_count": 0,
                "average_rating": Decimal("0"),
                "verified_purchase_count": 0,
            },
        )

    def search_reviews(
        self,
        product_id: str | None = None,
        min_rating: int | None = None,
        max_rating: int | None = None,
        verified_only: bool = False,
        query: str | None = None,
    ) -> list[Review]:
        """Search reviews with filters.

        Args:
            product_id: Filter by product
            min_rating: Minimum rating
            max_rating: Maximum rating
            verified_only: Only verified purchases
            query: Text search query

        Returns:
            Matching reviews
        """
        results = list(self.reviews.values())

        if product_id:
            results = [r for r in results if r.product_id == product_id]

        if min_rating:
            results = [r for r in results if r.rating >= min_rating]

        if max_rating:
            results = [r for r in results if r.rating <= max_rating]

        if verified_only:
            results = [r for r in results if r.verified_purchase]

        if query:
            query_lower = query.lower()
            results = [r for r in results if query_lower in r.title.lower() or query_lower in r.text.lower()]

        return results

    def get_review_statistics(self, product_id: str) -> dict[str, Any]:
        """Get detailed review statistics.

        Args:
            product_id: Product ID

        Returns:
            Review statistics
        """
        reviews = [r for r in self.reviews.values() if r.product_id == product_id and r.is_approved()]

        if not reviews:
            return {
                "total_reviews": 0,
                "average_rating": Decimal("0"),
                "rating_distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                "verified_purchase_percentage": 0,
                "helpful_votes_total": 0,
            }

        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for review in reviews:
            distribution[review.rating] += 1

        verified_count = sum(1 for r in reviews if r.verified_purchase)
        helpful_total = sum(r.helpful_votes for r in reviews)
        average = Decimal(sum(r.rating for r in reviews)) / Decimal(len(reviews))

        return {
            "total_reviews": len(reviews),
            "average_rating": average.quantize(Decimal("0.01")),
            "rating_distribution": distribution,
            "verified_purchase_percentage": int((verified_count / len(reviews)) * 100),
            "helpful_votes_total": helpful_total,
        }
