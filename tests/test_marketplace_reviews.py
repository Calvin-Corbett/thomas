"""Tests for review system module."""

from datetime import datetime
from decimal import Decimal

import pytest

from thomas.marketplace._exceptions import UnverifiedPurchaseReview
from thomas.marketplace._types import Review
from thomas.marketplace.reviews import (
    AuthenticityScorer,
    RatingAggregator,
    ReviewModerator,
    ReviewRegistry,
    SentimentAnalyzer,
)


class TestAuthenticityScorer:
    """Test review authenticity scoring."""

    def test_score_verified_purchase(self) -> None:
        """Test authenticity score for verified purchase."""
        review = Review(
            id="review_1",
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Great product!",
            text="This product is absolutely amazing and well worth the price.",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_verified_purchase=True,
        )

        score = AuthenticityScorer.calculate_score(
            review,
            account_age_days=30,
            helpful_votes=10,
            total_votes=12,
        )

        assert score > Decimal("50")

    def test_score_unverified_purchase(self) -> None:
        """Test authenticity score for unverified purchase."""
        review = Review(
            id="review_1",
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Great product!",
            text="This product is absolutely amazing and well worth the price.",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_verified_purchase=False,
        )

        score = AuthenticityScorer.calculate_score(
            review,
            account_age_days=30,
            helpful_votes=10,
            total_votes=12,
        )

        assert score < Decimal("80")


class TestSentimentAnalyzer:
    """Test sentiment analysis."""

    def test_positive_sentiment(self) -> None:
        """Test positive sentiment detection."""
        text = "I absolutely love this product! It's excellent and amazing!"

        sentiment = SentimentAnalyzer.analyze(text)
        assert sentiment > Decimal("0")

    def test_negative_sentiment(self) -> None:
        """Test negative sentiment detection."""
        text = "Terrible product! Awful quality, very disappointed."

        sentiment = SentimentAnalyzer.analyze(text)
        assert sentiment < Decimal("0")

    def test_neutral_sentiment(self) -> None:
        """Test neutral sentiment."""
        text = "This is a product."

        sentiment = SentimentAnalyzer.analyze(text)
        assert sentiment == Decimal("0")


class TestRatingAggregator:
    """Test rating aggregation."""

    def test_aggregate_multiple_reviews(self) -> None:
        """Test aggregating multiple reviews."""
        reviews = [
            Review(
                id="review_1",
                listing_id="listing_1",
                vendor_id="vendor_1",
                buyer_id="buyer_1",
                rating=5,
                title="Excellent!",
                text="Great product",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                is_verified_purchase=True,
            ),
            Review(
                id="review_2",
                listing_id="listing_1",
                vendor_id="vendor_1",
                buyer_id="buyer_2",
                rating=4,
                title="Good",
                text="Pretty good",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                is_verified_purchase=True,
            ),
            Review(
                id="review_3",
                listing_id="listing_1",
                vendor_id="vendor_1",
                buyer_id="buyer_3",
                rating=3,
                title="Okay",
                text="It's okay",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                is_verified_purchase=True,
            ),
        ]

        aggregate = RatingAggregator.calculate_aggregate(reviews)

        assert aggregate.review_count == 3
        assert aggregate.average_rating == Decimal("4")
        assert aggregate.rating_distribution[5] == 1
        assert aggregate.rating_distribution[4] == 1
        assert aggregate.rating_distribution[3] == 1

    def test_bayesian_smoothing_low_count(self) -> None:
        """Test Bayesian smoothing with low review count."""
        reviews = [
            Review(
                id="review_1",
                listing_id="listing_1",
                vendor_id="vendor_1",
                buyer_id="buyer_1",
                rating=5,
                title="Perfect!",
                text="Perfect product",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                is_verified_purchase=True,
            ),
        ]

        aggregate = RatingAggregator.calculate_aggregate(reviews)

        # Bayesian should pull down from 5.0 toward 3.0
        assert aggregate.bayesian_average < Decimal("5.0")
        assert aggregate.bayesian_average > Decimal("3.0")

    def test_empty_reviews(self) -> None:
        """Test aggregating empty review list."""
        aggregate = RatingAggregator.calculate_aggregate([])

        assert aggregate.review_count == 0
        assert aggregate.average_rating == Decimal("0")


class TestReviewModerator:
    """Test review moderation."""

    def test_submit_verified_purchase(self) -> None:
        """Test submitting verified purchase review."""
        moderator = ReviewModerator()

        review = Review(
            id="review_1",
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Great!",
            text="This is an excellent product that I really enjoyed using.",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_verified_purchase=False,
        )

        approved, reason = moderator.submit_review(review, True)
        assert approved

    def test_submit_unverified_purchase(self) -> None:
        """Test submitting unverified purchase review."""
        moderator = ReviewModerator()

        review = Review(
            id="review_1",
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Great!",
            text="This is an excellent product.",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_verified_purchase=False,
        )

        with pytest.raises(UnverifiedPurchaseReview):
            moderator.submit_review(review, False)

    def test_approve_pending_review(self) -> None:
        """Test manually approving pending review."""
        moderator = ReviewModerator()

        review = Review(
            id="review_1",
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=3,
            title="Okay",
            text="Not bad",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_verified_purchase=False,
        )

        moderator.submit_review(review, True)
        approved = moderator.approve_review("review_1")

        assert approved.id == "review_1"

    def test_reject_pending_review(self) -> None:
        """Test rejecting pending review."""
        moderator = ReviewModerator()

        review = Review(
            id="review_1",
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=3,
            title="Okay",
            text="Not bad",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_verified_purchase=False,
        )

        moderator.submit_review(review, True)
        rejected = moderator.reject_review("review_1", "Spam")

        assert rejected.id == "review_1"


class TestReviewRegistry:
    """Test review registry operations."""

    def test_submit_review(self) -> None:
        """Test submitting review."""
        registry = ReviewRegistry()

        review = registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Excellent!",
            text="This is a great product that exceeded my expectations.",
            is_verified_purchase=True,
        )

        assert review.rating == 5
        assert review.is_verified_purchase

    def test_get_review(self) -> None:
        """Test retrieving review."""
        registry = ReviewRegistry()

        review = registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=4,
            title="Good",
            text="Pretty good product",
            is_verified_purchase=True,
        )

        retrieved = registry.get_review(review.id)
        assert retrieved.id == review.id

    def test_list_listing_reviews(self) -> None:
        """Test listing reviews for a listing."""
        registry = ReviewRegistry()

        registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Excellent!",
            text="Great product",
            is_verified_purchase=True,
        )

        registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_2",
            rating=4,
            title="Good",
            text="Pretty good",
            is_verified_purchase=True,
        )

        registry.submit_review(
            listing_id="listing_2",
            vendor_id="vendor_1",
            buyer_id="buyer_3",
            rating=3,
            title="Okay",
            text="It's okay",
            is_verified_purchase=True,
        )

        listing1_reviews = registry.list_listing_reviews("listing_1")
        assert len(listing1_reviews) == 2

        listing2_reviews = registry.list_listing_reviews("listing_2")
        assert len(listing2_reviews) == 1

    def test_vote_helpful(self) -> None:
        """Test marking review as helpful."""
        registry = ReviewRegistry()

        review = registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Great!",
            text="Excellent product",
            is_verified_purchase=True,
        )

        votes1 = registry.vote_helpful(review.id)
        votes2 = registry.vote_helpful(review.id)

        assert votes1 == 1
        assert votes2 == 2

    def test_add_vendor_response(self) -> None:
        """Test adding vendor response to review."""
        registry = ReviewRegistry()

        review = registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=4,
            title="Good",
            text="Good product",
            is_verified_purchase=True,
        )

        updated = registry.add_vendor_response(review.id, "Thank you for the review!")

        assert updated.vendor_response == "Thank you for the review!"
        assert updated.vendor_response_at is not None

    def test_get_listing_aggregate_rating(self) -> None:
        """Test getting aggregate rating for listing."""
        registry = ReviewRegistry()

        registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_1",
            rating=5,
            title="Excellent!",
            text="Great product",
            is_verified_purchase=True,
        )

        registry.submit_review(
            listing_id="listing_1",
            vendor_id="vendor_1",
            buyer_id="buyer_2",
            rating=3,
            title="Okay",
            text="It's okay",
            is_verified_purchase=True,
        )

        aggregate = registry.get_listing_aggregate_rating("listing_1")

        assert aggregate.review_count == 2
        assert aggregate.average_rating == Decimal("4")
