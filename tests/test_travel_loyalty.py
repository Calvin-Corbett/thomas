"""Tests for loyalty program module."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.travel._exceptions import InsufficientPointsError, LoyaltyError
from thomas.travel._types import Loyalty, LoyaltyTier
from thomas.travel.loyalty import (
    EliteBenefitsManager,
    LoyaltyAnalytics,
    PartnerEarningBurning,
    PointsAccrual,
    PointsExpiryTracking,
    PointsRedemption,
    TierManagement,
)


@pytest.fixture
def sample_loyalty_member():
    """Create sample loyalty member."""
    return Loyalty(
        member_id="LY123456",
        member_name="John Doe",
        tier=LoyaltyTier.GOLD,
        points_balance=50000,
        qualifying_points=45000,
        segments_flown=60,
        miles_flown=250000,
    )


@pytest.fixture
def points_accrual():
    """Create points accrual engine."""
    return PointsAccrual()


@pytest.fixture
def tier_management():
    """Create tier management engine."""
    return TierManagement()


@pytest.fixture
def points_redemption():
    """Create points redemption engine."""
    return PointsRedemption()


@pytest.fixture
def benefits_manager():
    """Create elite benefits manager."""
    return EliteBenefitsManager()


@pytest.fixture
def partner_earning():
    """Create partner earning/burning engine."""
    engine = PartnerEarningBurning()
    engine.add_partner("HOTEL001", "Premier Hotels", 0.5)
    engine.add_partner("CAR001", "Elite Rentals", 0.75)
    return engine


@pytest.fixture
def expiry_tracking():
    """Create points expiry tracker."""
    return PointsExpiryTracking()


@pytest.fixture
def loyalty_analytics():
    """Create loyalty analytics."""
    return LoyaltyAnalytics()


class TestPointsAccrual:
    """Test points earning and accrual."""

    def test_calculate_points_standard_tier(self, points_accrual):
        """Test points calculation for standard tier."""
        points = points_accrual.calculate_points_earned(Decimal("100"), LoyaltyTier.STANDARD, "domestic_flight")

        assert points == 100  # 1x multiplier

    def test_calculate_points_gold_tier(self, points_accrual):
        """Test points calculation for gold tier."""
        points = points_accrual.calculate_points_earned(Decimal("100"), LoyaltyTier.GOLD, "domestic_flight")

        assert points > 100  # Gold gets multiplier

    def test_calculate_points_international_bonus(self, points_accrual):
        """Test international flight bonus."""
        domestic = points_accrual.calculate_points_earned(Decimal("100"), LoyaltyTier.STANDARD, "domestic_flight")

        international = points_accrual.calculate_points_earned(
            Decimal("100"), LoyaltyTier.STANDARD, "international_flight"
        )

        assert international > domestic

    def test_calculate_points_promotional_bonus(self, points_accrual):
        """Test promotional bonus multiplier."""
        normal = points_accrual.calculate_points_earned(
            Decimal("100"), LoyaltyTier.STANDARD, "domestic_flight", is_promotional=False
        )

        promotional = points_accrual.calculate_points_earned(
            Decimal("100"), LoyaltyTier.STANDARD, "domestic_flight", is_promotional=True
        )

        assert promotional > normal

    def test_record_earning(self, points_accrual):
        """Test recording earning transaction."""
        record = points_accrual.record_earning("LY123456", 1500, "Flight AA100")

        assert record["points"] == 1500
        assert record["source"] == "Flight AA100"

    def test_get_earning_history(self, points_accrual):
        """Test retrieving earning history."""
        points_accrual.record_earning("LY123456", 1500, "Flight 1")
        points_accrual.record_earning("LY123456", 2000, "Flight 2")

        history = points_accrual.get_earning_history("LY123456")
        assert len(history) == 2


class TestTierManagement:
    """Test tier progression."""

    def test_determine_tier_standard(self, tier_management):
        """Test determining standard tier."""
        tier = tier_management.determine_tier(5000, 5)
        assert tier == LoyaltyTier.STANDARD

    def test_determine_tier_silver(self, tier_management):
        """Test determining silver tier."""
        tier = tier_management.determine_tier(25000, 0)
        assert tier == LoyaltyTier.SILVER

    def test_determine_tier_gold(self, tier_management):
        """Test determining gold tier."""
        tier = tier_management.determine_tier(50000, 0)
        assert tier == LoyaltyTier.GOLD

    def test_determine_tier_platinum(self, tier_management):
        """Test determining platinum tier."""
        tier = tier_management.determine_tier(100000, 0)
        assert tier == LoyaltyTier.PLATINUM

    def test_determine_tier_by_segments(self, tier_management):
        """Test determining tier by segments flown."""
        tier = tier_management.determine_tier(0, 50)
        assert tier == LoyaltyTier.GOLD

    def test_process_tier_change(self, tier_management):
        """Test processing tier upgrade."""
        change = tier_management.process_tier_change("LY123456", LoyaltyTier.SILVER, LoyaltyTier.GOLD)

        assert change["old_tier"] == LoyaltyTier.SILVER
        assert change["new_tier"] == LoyaltyTier.GOLD
        assert change["tier_expiry"] is not None

    def test_calculate_elite_benefits_platinum(self, tier_management):
        """Test benefits for platinum tier."""
        benefits = tier_management.calculate_elite_benefits(LoyaltyTier.PLATINUM)

        assert benefits["lounge_access"] is True
        assert benefits["priority_boarding"] is True
        assert benefits["concierge_service"] is True


class TestPointsRedemption:
    """Test points redemption."""

    def test_get_award_price(self, points_redemption):
        """Test getting award price."""
        price = points_redemption.get_award_price("domestic_economy")
        assert price > 0

    def test_redeem_points(self, points_redemption):
        """Test redeeming points for award."""
        redemption = points_redemption.redeem_points("LY123456", 25000, "domestic_economy", 25000)

        assert redemption["award_type"] == "domestic_economy"
        assert redemption["confirmation_number"] is not None

    def test_redeem_insufficient_points(self, points_redemption):
        """Test error when redeeming with insufficient points."""
        with pytest.raises(InsufficientPointsError):
            points_redemption.redeem_points(
                "LY123456",
                25000,
                "domestic_economy",
                10000,  # Not enough
            )

    def test_get_redemption_history(self, points_redemption):
        """Test retrieving redemption history."""
        points_redemption.redeem_points("LY123456", 25000, "domestic_economy", 25000)

        history = points_redemption.get_redemption_history("LY123456")
        assert len(history) == 1


class TestEliteBenefits:
    """Test elite benefits."""

    def test_grant_priority_boarding(self, benefits_manager):
        """Test granting priority boarding."""
        result = benefits_manager.grant_priority_boarding("LY123456", "AA100")
        assert result is True

    def test_grant_lounge_access(self, benefits_manager):
        """Test granting lounge access."""
        access = benefits_manager.grant_lounge_access("LY123456", "JFK_LOUNGE", num_guests=1)

        assert access["lounge_id"] == "JFK_LOUNGE"
        assert access["complimentary_guests"] == 1

    def test_process_seat_upgrade(self, benefits_manager):
        """Test automatic seat upgrade."""
        upgrade = benefits_manager.process_seat_upgrade("LY123456", "ABC123", "economy", "business")

        assert upgrade["from_class"] == "economy"
        assert upgrade["to_class"] == "business"

    def test_get_lounge_access(self, benefits_manager):
        """Test retrieving lounge access."""
        benefits_manager.grant_lounge_access("LY123456", "JFK_LOUNGE")

        lounges = benefits_manager.get_lounge_access("LY123456")
        assert "JFK_LOUNGE" in lounges


class TestPartnerEarningBurning:
    """Test partner program."""

    def test_add_partner(self, partner_earning):
        """Test adding partner program."""
        partner_earning.add_partner("PART001", "Partner Airlines", 0.8)

    def test_transfer_points(self, partner_earning):
        """Test transferring points to partner."""
        transfer = partner_earning.transfer_points("LY123456", "HOTEL001", 1000)

        assert transfer["points_transferred"] == 1000
        assert transfer["partner_points_received"] > 0  # Converted

    def test_transfer_invalid_partner(self, partner_earning):
        """Test error transferring to invalid partner."""
        with pytest.raises(LoyaltyError):
            partner_earning.transfer_points("LY123456", "INVALID", 1000)

    def test_get_transfer_history(self, partner_earning):
        """Test retrieving transfer history."""
        partner_earning.transfer_points("LY123456", "HOTEL001", 1000)

        history = partner_earning.get_transfer_history("LY123456")
        assert len(history) == 1


class TestPointsExpiry:
    """Test points expiry tracking."""

    def test_set_expiry_date(self, expiry_tracking):
        """Test setting points expiry."""
        expiry = datetime.now() + timedelta(days=365)
        expiry_tracking.set_expiry_date("LY123456", expiry)

        retrieved = expiry_tracking.get_expiry_date("LY123456")
        assert retrieved == expiry

    def test_calculate_expiry_date(self, expiry_tracking):
        """Test calculating expiry date."""
        last_activity = datetime.now()
        expiry = expiry_tracking.calculate_expiry_date(last_activity)

        expected = last_activity + timedelta(days=365 * 3)
        assert expiry == expected


class TestLoyaltyAnalytics:
    """Test loyalty analytics."""

    def test_calculate_lifetime_value(self, loyalty_analytics):
        """Test calculating member lifetime value."""
        ltv = loyalty_analytics.calculate_lifetime_value("LY123456", Decimal("10000"), 5, LoyaltyTier.PLATINUM)

        assert ltv > Decimal("10000")  # Enhanced by tier

    def test_record_metrics(self, loyalty_analytics):
        """Test recording member metrics."""
        metrics = {
            "total_spending": Decimal("50000"),
            "trips": 25,
            "avg_trip_value": Decimal("2000"),
        }

        loyalty_analytics.record_metrics("LY123456", metrics)

        retrieved = loyalty_analytics.get_metrics("LY123456")
        assert retrieved["total_spending"] == Decimal("50000")


class TestLoyaltyIntegration:
    """Integration tests for loyalty program."""

    def test_complete_loyalty_journey(self, points_accrual, tier_management, benefits_manager):
        """Test complete loyalty program journey."""
        # Earn points
        points = points_accrual.calculate_points_earned(
            Decimal("500"), LoyaltyTier.STANDARD, "international_flight", is_promotional=True
        )
        points_accrual.record_earning("LY123456", points, "Transatlantic Flight")

        # Determine tier based on spending
        tier = tier_management.determine_tier(100000, 50)
        tier_change = tier_management.process_tier_change("LY123456", LoyaltyTier.STANDARD, tier)

        # Get tier benefits
        benefits = tier_management.calculate_elite_benefits(tier_change["new_tier"])

        assert benefits["lounge_access"] is True
        assert points > 500
