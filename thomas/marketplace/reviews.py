"""Review system with authenticity scoring, moderation, and sentiment analysis."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from thomas.marketplace._exceptions import (
    ReviewException,
    ReviewNotFoundError,
    UnverifiedPurchaseReview,
)
from thomas.marketplace._types import (
    Review,
)


@dataclass
class AggregateRating:
    """Aggregate rating with Bayesian smoothing."""

    listing_id: str
    average_rating: Decimal
    review_count: int
    rating_distribution: dict[int, int]
    bayesian_average: Decimal


class AuthenticityScorer:
    """Score review authenticity based on multiple factors."""

    MIN_ACCOUNT_AGE_DAYS: int = 7
    MIN_REVIEW_LENGTH: int = 10
    MAX_REVIEW_LENGTH: int = 5000

    @staticmethod
    def calculate_score(
        review: Review,
        account_age_days: int,
        helpful_votes: int,
        total_votes: int,
    ) -> Decimal:
        """Calculate authenticity score 0-100.

        Factors:
        - Verified purchase (40%)
        - Account age (20%)
        - Review length (20%)
        - Helpful votes (20%)

        Args:
            review: Review to score.
            account_age_days: Days since account creation.
            helpful_votes: Helpful votes on review.
            total_votes: Total votes on review.

        Returns:
            Authenticity score 0-100.
        """
        score = Decimal("0")

        # Verified purchase (40%)
        purchase_score = Decimal("40") if review.is_verified_purchase else Decimal("0")
        score += purchase_score

        # Account age (20%)
        if account_age_days >= AuthenticityScorer.MIN_ACCOUNT_AGE_DAYS:
            age_score = Decimal("20")
        else:
            age_score = Decimal(max(0, 20 * account_age_days / AuthenticityScorer.MIN_ACCOUNT_AGE_DAYS))
        score += age_score

        # Review length (20%)
        review_len = len(review.text)
        if AuthenticityScorer.MIN_REVIEW_LENGTH <= review_len <= AuthenticityScorer.MAX_REVIEW_LENGTH:
            length_score = Decimal("20")
        else:
            length_score = Decimal("0")
        score += length_score

        # Helpful votes (20%)
        if total_votes > 0:
            helpfulness = Decimal(helpful_votes) / Decimal(total_votes)
            helpful_score = Decimal("20") * helpfulness
        else:
            helpful_score = Decimal("0")
        score += helpful_score

        return score


class SentimentAnalyzer:
    """Analyze review text sentiment (simplified)."""

    POSITIVE_WORDS: list[str] = [
        "excellent",
        "great",
        "amazing",
        "love",
        "perfect",
        "wonderful",
        "fantastic",
        "best",
        "highly",
        "recommend",
        "satisfied",
        "happy",
    ]

    NEGATIVE_WORDS: list[str] = [
        "terrible",
        "awful",
        "hate",
        "worst",
        "broken",
        "defective",
        "poor",
        "bad",
        "disappointing",
        "waste",
        "regret",
        "never",
        "useless",
    ]

    @staticmethod
    def analyze(text: str) -> Decimal:
        """Analyze review sentiment.

        Returns score -1 to 1 where negative is negative, positive is positive.

        Args:
            text: Review text.

        Returns:
            Sentiment score -100 to 100.
        """
        text_lower = text.lower()
        words = text_lower.split()

        positive_count = sum(1 for word in words if word in SentimentAnalyzer.POSITIVE_WORDS)
        negative_count = sum(1 for word in words if word in SentimentAnalyzer.NEGATIVE_WORDS)

        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words == 0:
            return Decimal("0")

        sentiment = (positive_count - negative_count) / total_sentiment_words
        return Decimal(str(sentiment * 100))


class ReviewModerator:
    """Review moderation with auto-approve and manual queue."""

    AUTO_APPROVE_THRESHOLD: Decimal = Decimal("70")

    def __init__(self) -> None:
        """Initialize review moderator."""
        self._pending_reviews: dict[str, Review] = {}
        self._approved_reviews: dict[str, Review] = {}
        self._rejected_reviews: dict[str, Review] = {}

    def submit_review(self, review: Review, is_verified_purchase: bool) -> tuple[bool, str]:
        """Submit review for moderation.

        Args:
            review: Review to moderate.
            is_verified_purchase: Whether purchase is verified.

        Returns:
            Tuple of (approved, reason).

        Raises:
            UnverifiedPurchaseReview: If not verified purchase.
        """
        review.is_verified_purchase = is_verified_purchase

        if not is_verified_purchase:
            raise UnverifiedPurchaseReview()

        # Calculate authenticity score
        review.authenticity_score = AuthenticityScorer.calculate_score(
            review,
            account_age_days=30,  # Stub
            helpful_votes=0,
            total_votes=0,
        )

        # Calculate sentiment
        review.sentiment_score = SentimentAnalyzer.analyze(review.text)

        # Auto-approve if high authenticity
        if review.authenticity_score >= self.AUTO_APPROVE_THRESHOLD:
            self._approved_reviews[review.id] = review
            return True, "Auto-approved"

        # Queue for manual review
        self._pending_reviews[review.id] = review
        return False, "Pending manual review"

    def approve_review(self, review_id: str) -> Review:
        """Manually approve pending review.

        Args:
            review_id: Review identifier.

        Returns:
            Approved review.

        Raises:
            ReviewException: If review not pending.
        """
        if review_id not in self._pending_reviews:
            raise ReviewException(f"Review not pending: {review_id}")

        review = self._pending_reviews.pop(review_id)
        self._approved_reviews[review_id] = review
        return review

    def reject_review(self, review_id: str, reason: str = "") -> Review:
        """Reject pending review.

        Args:
            review_id: Review identifier.
            reason: Rejection reason.

        Returns:
            Rejected review.

        Raises:
            ReviewException: If review not pending.
        """
        if review_id not in self._pending_reviews:
            raise ReviewException(f"Review not pending: {review_id}")

        review = self._pending_reviews.pop(review_id)
        self._rejected_reviews[review_id] = review
        return review

    def get_pending_reviews(self) -> list[Review]:
        """Get all reviews pending moderation.

        Returns:
            List of pending reviews.
        """
        return list(self._pending_reviews.values())


class RatingAggregator:
    """Calculate aggregate ratings with Bayesian smoothing."""

    BAYESIAN_CONFIDENCE: int = 5  # Minimum reviews for full confidence

    @staticmethod
    def calculate_aggregate(reviews: list[Review]) -> AggregateRating:
        """Calculate aggregate rating from reviews.

        Uses Bayesian averaging to handle low review counts.

        Args:
            reviews: List of reviews.

        Returns:
            Aggregate rating.
        """
        if not reviews:
            return AggregateRating(
                listing_id="",
                average_rating=Decimal("0"),
                review_count=0,
                rating_distribution={},
                bayesian_average=Decimal("0"),
            )

        listing_id = reviews[0].listing_id
        review_count = len(reviews)

        # Distribution
        distribution: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        total_rating = Decimal("0")

        for review in reviews:
            distribution[review.rating] += 1
            total_rating += Decimal(review.rating)

        # Simple average
        average = total_rating / Decimal(review_count) if review_count > 0 else Decimal("0")

        # Bayesian average: smooths toward 3.0 for low review counts
        confidence = min(review_count / RatingAggregator.BAYESIAN_CONFIDENCE, 1.0)
        bayesian = Decimal("3.0") * Decimal(str(1 - confidence)) + average * Decimal(str(confidence))

        return AggregateRating(
            listing_id=listing_id,
            average_rating=average,
            review_count=review_count,
            rating_distribution=distribution,
            bayesian_average=bayesian,
        )


class ReviewRegistry:
    """In-memory review registry with moderation and aggregation."""

    def __init__(self) -> None:
        """Initialize review registry."""
        self._reviews: dict[str, Review] = {}
        self._listing_reviews: dict[str, list[str]] = {}
        self._moderator = ReviewModerator()
        self._helpful_votes: dict[str, int] = {}

    def submit_review(
        self,
        listing_id: str,
        vendor_id: str,
        buyer_id: str,
        rating: int,
        title: str,
        text: str,
        is_verified_purchase: bool,
    ) -> Review:
        """Submit review for a listing.

        Args:
            listing_id: Listing identifier.
            vendor_id: Vendor identifier.
            buyer_id: Buyer identifier.
            rating: Star rating 1-5.
            title: Review title.
            text: Review text.
            is_verified_purchase: Whether purchase verified.

        Returns:
            Created review (pending moderation).

        Raises:
            UnverifiedPurchaseReview: If not verified purchase.
        """
        review_id = f"review_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        review = Review(
            id=review_id,
            listing_id=listing_id,
            vendor_id=vendor_id,
            buyer_id=buyer_id,
            rating=rating,
            title=title,
            text=text,
            created_at=now,
            updated_at=now,
            is_verified_purchase=is_verified_purchase,
        )

        # Submit for moderation
        approved, reason = self._moderator.submit_review(review, is_verified_purchase)

        # Store review
        self._reviews[review_id] = review
        if listing_id not in self._listing_reviews:
            self._listing_reviews[listing_id] = []
        self._listing_reviews[listing_id].append(review_id)

        return review

    def get_review(self, review_id: str) -> Review:
        """Get review by ID.

        Args:
            review_id: Review identifier.

        Returns:
            Review object.

        Raises:
            ReviewNotFoundError: If review not found.
        """
        review = self._reviews.get(review_id)
        if not review:
            raise ReviewNotFoundError(review_id)
        return review

    def list_listing_reviews(self, listing_id: str, limit: int = 10) -> list[Review]:
        """List reviews for a listing.

        Args:
            listing_id: Listing identifier.
            limit: Maximum reviews to return.

        Returns:
            List of reviews for listing.
        """
        review_ids = self._listing_reviews.get(listing_id, [])
        reviews = [self._reviews[rid] for rid in review_ids if rid in self._reviews]
        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return reviews[:limit]

    def vote_helpful(self, review_id: str) -> int:
        """Mark review as helpful.

        Args:
            review_id: Review identifier.

        Returns:
            Updated helpful vote count.

        Raises:
            ReviewNotFoundError: If review not found.
        """
        review = self.get_review(review_id)
        review.helpfulness_votes += 1
        self._helpful_votes[review_id] = review.helpfulness_votes
        return review.helpfulness_votes

    def add_vendor_response(self, review_id: str, response_text: str) -> Review:
        """Add vendor response to review.

        Args:
            review_id: Review identifier.
            response_text: Vendor response.

        Returns:
            Updated review.

        Raises:
            ReviewNotFoundError: If review not found.
        """
        review = self.get_review(review_id)
        review.vendor_response = response_text
        review.vendor_response_at = datetime.utcnow()
        return review

    def get_listing_aggregate_rating(self, listing_id: str) -> AggregateRating:
        """Get aggregate rating for listing.

        Args:
            listing_id: Listing identifier.

        Returns:
            Aggregate rating with Bayesian smoothing.
        """
        review_ids = self._listing_reviews.get(listing_id, [])
        reviews = [self._reviews[rid] for rid in review_ids if rid in self._reviews]
        return RatingAggregator.calculate_aggregate(reviews)

    def get_trending_reviews(self, limit: int = 5) -> list[Review]:
        """Get most helpful reviews across marketplace.

        Args:
            limit: Maximum reviews to return.

        Returns:
            List of trending reviews.
        """
        all_reviews = list(self._reviews.values())
        all_reviews.sort(key=lambda r: r.helpfulness_votes, reverse=True)
        return all_reviews[:limit]
