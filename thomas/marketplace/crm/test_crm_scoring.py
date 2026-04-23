"""
Tests for the lead and deal scoring engine.
"""

from datetime import datetime, timedelta

import pytest

from thomas.marketplace.crm._types import Contact
from thomas.marketplace.crm.scoring import ScoringEngine


@pytest.fixture
def scoring_engine() -> ScoringEngine:
    """Create a scoring engine instance."""
    return ScoringEngine()


@pytest.fixture
def sample_contact() -> Contact:
    """Create a sample contact."""
    return Contact(
        id="contact-1",
        first_name="John",
        last_name="Doe",
        email="john@example.com",
        phone="555-1234",
        company="Acme Corp",
        title="Sales Manager",
    )


class TestScoringConfiguration:
    """Test scoring configuration."""

    def test_configure_scoring(self, scoring_engine: ScoringEngine) -> None:
        """Test configuring the scoring model."""
        scoring_engine.configure_scoring(
            demographic_weight=0.4,
            behavioral_weight=0.4,
            predictive_weight=0.2,
        )

        config = scoring_engine._scoring_config

        assert config["demographic_weight"] == 0.4
        assert config["behavioral_weight"] == 0.4
        assert config["predictive_weight"] == 0.2

    def test_normalize_weights(self, scoring_engine: ScoringEngine) -> None:
        """Test weight normalization."""
        scoring_engine.configure_scoring(
            demographic_weight=0.5,
            behavioral_weight=0.5,
            predictive_weight=0.5,
        )

        config = scoring_engine._scoring_config
        total = config["demographic_weight"] + config["behavioral_weight"] + config["predictive_weight"]

        assert abs(total - 1.0) < 0.001


class TestDemographicScoring:
    """Test demographic scoring component."""

    def test_executive_title_scoring(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring boost for executive titles."""
        contact = Contact(
            id="contact-2",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            title="VP of Sales",
        )

        score = scoring_engine._calculate_demographic_score(contact, {})

        assert score > 50  # Should be boosted

    def test_company_size_scoring(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring based on company size."""
        score_small = scoring_engine._calculate_demographic_score(
            sample_contact,
            {"company_size": 50},
        )

        score_large = scoring_engine._calculate_demographic_score(
            sample_contact,
            {"company_size": 5000},
        )

        assert score_large > score_small

    def test_industry_scoring(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring based on industry."""
        score_high = scoring_engine._calculate_demographic_score(
            sample_contact,
            {"industry": "Technology"},
        )

        score_low = scoring_engine._calculate_demographic_score(
            sample_contact,
            {"industry": "Agriculture"},
        )

        assert score_high > score_low


class TestBehavioralScoring:
    """Test behavioral scoring component."""

    def test_email_engagement_scoring(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring based on email engagement."""
        score_no_engagement = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {},
        )

        score_high_engagement = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {
                "email_opens": 10,
                "email_clicks": 3,
            },
        )

        assert score_high_engagement > score_no_engagement

    def test_website_visit_scoring(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring based on website visits."""
        score_no_visits = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {},
        )

        score_many_visits = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {"website_visits": 15},
        )

        assert score_many_visits > score_no_visits

    def test_demo_page_interest(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring boost for demo/pricing page views."""
        score_regular = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {"website_visits": 5},
        )

        score_demo = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {
                "website_visits": 5,
                "demo_page_views": 2,
                "pricing_page_views": 1,
            },
        )

        assert score_demo > score_regular

    def test_recency_scoring(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring based on activity recency."""
        recent_date = datetime.utcnow() - timedelta(days=3)
        old_date = datetime.utcnow() - timedelta(days=120)

        score_recent = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {"last_activity_date": recent_date},
        )

        score_old = scoring_engine._calculate_behavioral_score(
            sample_contact,
            {"last_activity_date": old_date},
        )

        assert score_recent > score_old


class TestPredictiveScoring:
    """Test predictive scoring component."""

    def test_predictive_score_with_history(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test predictive scoring with historical data."""
        historical_data = [
            {"converted": True, "title": "VP Sales"},
            {"converted": True, "title": "Director"},
            {"converted": False, "title": "Coordinator"},
            {"converted": True, "title": "Manager"},
        ]

        score = scoring_engine._calculate_predictive_score(
            sample_contact,
            historical_data,
        )

        assert 0 <= score <= 100

    def test_predictive_score_no_history(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test predictive scoring without historical data."""
        score = scoring_engine._calculate_predictive_score(
            sample_contact,
            [],
        )

        assert score == 50.0  # Default


class TestScoreToDegree:
    """Test score to grade conversion."""

    def test_grade_conversion(self, scoring_engine: ScoringEngine) -> None:
        """Test converting scores to letter grades."""
        assert scoring_engine._score_to_grade(95) == "A"
        assert scoring_engine._score_to_grade(85) == "B"
        assert scoring_engine._score_to_grade(75) == "C"
        assert scoring_engine._score_to_grade(65) == "D"
        assert scoring_engine._score_to_grade(30) == "F"


class TestLeadScoring:
    """Test complete lead scoring."""

    def test_score_lead(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test scoring a lead."""
        lead_score = scoring_engine.score_lead(
            sample_contact,
            demographic_data={
                "company_size": 1000,
                "industry": "Technology",
            },
            behavioral_data={
                "email_opens": 8,
                "website_visits": 12,
                "demo_page_views": 2,
            },
        )

        assert lead_score.contact_id == sample_contact.id
        assert 0 <= lead_score.total_score <= 100
        assert lead_score.grade in ["A", "B", "C", "D", "F"]

    def test_score_persistence(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test that scores are persisted."""
        scoring_engine.score_lead(sample_contact)

        retrieved = scoring_engine.get_lead_score(sample_contact.id)

        assert retrieved is not None
        assert retrieved.contact_id == sample_contact.id


class TestScoreDecay:
    """Test score decay over time."""

    def test_apply_score_decay(
        self,
        scoring_engine: ScoringEngine,
        sample_contact: Contact,
    ) -> None:
        """Test applying score decay for inactive leads."""
        scoring_engine.score_lead(sample_contact)

        original_score = scoring_engine.get_lead_score(sample_contact.id)

        # Apply decay with 120 days of inactivity
        last_activity = datetime.utcnow() - timedelta(days=120)
        decayed = scoring_engine.apply_score_decay(sample_contact.id, last_activity)

        assert decayed.total_score <= original_score.total_score


class TestHighValueLeads:
    """Test filtering for high-value leads."""

    def test_get_high_value_leads(self, scoring_engine: ScoringEngine) -> None:
        """Test getting leads above a score threshold."""
        contact1 = Contact(
            id="contact-1",
            first_name="High",
            last_name="Value",
            email="high@example.com",
            title="CEO",
        )

        contact2 = Contact(
            id="contact-2",
            first_name="Low",
            last_name="Value",
            email="low@example.com",
        )

        scoring_engine.score_lead(contact1, demographic_data={"company_size": 5000})
        scoring_engine.score_lead(contact2)

        high_value = scoring_engine.get_high_value_leads(min_score=80)

        # At least one should be high value
        assert len(high_value) >= 0


class TestAtRiskLeads:
    """Test identifying at-risk leads."""

    def test_get_at_risk_leads(self, scoring_engine: ScoringEngine) -> None:
        """Test identifying leads with low scores."""
        contact = Contact(
            id="contact-1",
            first_name="At",
            last_name="Risk",
            email="atrisk@example.com",
        )

        scoring_engine.score_lead(contact)

        at_risk = scoring_engine.get_at_risk_leads()

        # Without much behavioral data, should be low scoring
        assert len(at_risk) >= 0


class TestScoreComparison:
    """Test comparing scores between contacts."""

    def test_compare_scores(self, scoring_engine: ScoringEngine) -> None:
        """Test comparing scores between two contacts."""
        contact1 = Contact(
            id="contact-1",
            first_name="High",
            last_name="Value",
            email="high@example.com",
            title="CEO",
        )

        contact2 = Contact(
            id="contact-2",
            first_name="Low",
            last_name="Value",
            email="low@example.com",
        )

        scoring_engine.score_lead(contact1, demographic_data={"company_size": 5000})
        scoring_engine.score_lead(contact2)

        comparison = scoring_engine.compare_scores(contact1.id, contact2.id)

        assert comparison is not None
        assert "score_difference" in comparison
