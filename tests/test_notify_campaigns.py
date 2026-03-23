"""
Tests for campaign management and A/B testing.
"""

import pytest

from thomas.notify._exceptions import NotifyException
from thomas.notify._types import (
    ChannelType,
    Priority,
)
from thomas.notify.campaigns import (
    ABTestManager,
    AudienceManager,
    CampaignManager,
)


class TestAudienceManager:
    """Tests for audience management."""

    def test_create_audience(self) -> None:
        """Test audience creation."""
        manager = AudienceManager()

        audience = manager.create_audience(
            name="Premium Users",
            description="Users with premium subscription",
            filters=[{"subscription": "premium"}],
        )

        assert audience.name == "Premium Users"
        assert audience.audience_id is not None

    def test_create_segment(self) -> None:
        """Test segment creation."""
        manager = AudienceManager()

        segment = manager.create_segment(
            name="Active Users",
            description="Users active in last 30 days",
            filters={"days_since_active": {"$lt": 30}},
        )

        assert segment.name == "Active Users"
        assert segment.segment_id is not None

    def test_get_audience(self) -> None:
        """Test retrieving audience."""
        manager = AudienceManager()

        audience = manager.create_audience(name="Test Audience")
        retrieved = manager.get_audience(audience.audience_id)

        assert retrieved.name == "Test Audience"

    def test_get_nonexistent_audience_raises(self) -> None:
        """Test getting nonexistent audience raises."""
        manager = AudienceManager()

        with pytest.raises(NotifyException):
            manager.get_audience("nonexistent")


class TestCampaignManager:
    """Tests for campaign management."""

    def test_create_campaign(self) -> None:
        """Test campaign creation."""
        manager = CampaignManager()

        audience = manager.audience_manager.create_audience(name="Test Audience")

        campaign = manager.create_campaign(
            name="Test Campaign",
            template_id="t1",
            audience=audience,
            channel_types=[ChannelType.EMAIL],
            priority=Priority.NORMAL,
        )

        assert campaign.name == "Test Campaign"
        assert campaign.status == "draft"

    def test_start_campaign(self) -> None:
        """Test starting campaign."""
        manager = CampaignManager()

        audience = manager.audience_manager.create_audience(name="Test Audience")

        campaign = manager.create_campaign(
            name="Test Campaign",
            template_id="t1",
            audience=audience,
        )

        started = manager.start_campaign(campaign.campaign_id)

        assert started.status == "running"
        assert started.started_at is not None

    def test_start_non_draft_campaign_raises(self) -> None:
        """Test starting non-draft campaign raises."""
        manager = CampaignManager()

        audience = manager.audience_manager.create_audience(name="Test Audience")

        campaign = manager.create_campaign(
            name="Test Campaign",
            template_id="t1",
            audience=audience,
        )

        manager.start_campaign(campaign.campaign_id)

        with pytest.raises(NotifyException):
            manager.start_campaign(campaign.campaign_id)

    def test_record_campaign_metrics(self) -> None:
        """Test recording campaign metrics."""
        manager = CampaignManager()

        audience = manager.audience_manager.create_audience(name="Test Audience")

        campaign = manager.create_campaign(
            name="Test Campaign",
            template_id="t1",
            audience=audience,
        )

        manager.record_send(campaign.campaign_id)
        manager.record_delivery(campaign.campaign_id)
        manager.record_open(campaign.campaign_id)
        manager.record_click(campaign.campaign_id)
        manager.record_conversion(campaign.campaign_id)

        campaign = manager.get_campaign(campaign.campaign_id)

        assert campaign.sent_count == 1
        assert campaign.delivered_count == 1
        assert campaign.opened_count == 1
        assert campaign.clicked_count == 1
        assert campaign.converted_count == 1

    def test_campaign_metrics_calculation(self) -> None:
        """Test campaign metric calculations."""
        manager = CampaignManager()

        audience = manager.audience_manager.create_audience(name="Test Audience")

        campaign = manager.create_campaign(
            name="Test Campaign",
            template_id="t1",
            audience=audience,
        )

        for _ in range(100):
            manager.record_send(campaign.campaign_id)

        for _ in range(90):
            manager.record_delivery(campaign.campaign_id)

        campaign = manager.get_campaign(campaign.campaign_id)

        assert campaign.get_delivery_rate() == 0.9


class TestABTestManager:
    """Tests for A/B testing."""

    def test_create_ab_test(self) -> None:
        """Test A/B test creation."""
        manager = ABTestManager()

        test = manager.create_ab_test(
            control_template_id="t1",
            variant_template_id="t2",
            split_percentage=0.5,
            sample_size=1000,
        )

        assert test.control_template_id == "t1"
        assert test.variant_template_id == "t2"

    def test_invalid_split_percentage_raises(self) -> None:
        """Test invalid split percentage raises."""
        manager = ABTestManager()

        with pytest.raises(NotifyException):
            manager.create_ab_test(
                control_template_id="t1",
                variant_template_id="t2",
                split_percentage=1.5,
            )

    def test_assign_user_to_control(self) -> None:
        """Test user assignment to control."""
        manager = ABTestManager()

        test = manager.create_ab_test(
            control_template_id="t1",
            variant_template_id="t2",
            split_percentage=0.0,  # All control
        )

        template_id = manager.assign_user(test.test_id, "user1")

        assert template_id == "t1"

    def test_assign_user_to_variant(self) -> None:
        """Test user assignment to variant."""
        manager = ABTestManager()

        test = manager.create_ab_test(
            control_template_id="t1",
            variant_template_id="t2",
            split_percentage=1.0,  # All variant
        )

        template_id = manager.assign_user(test.test_id, "user1")

        assert template_id == "t2"

    def test_consistent_user_assignment(self) -> None:
        """Test user gets same assignment consistently."""
        manager = ABTestManager()

        test = manager.create_ab_test(
            control_template_id="t1",
            variant_template_id="t2",
            split_percentage=0.5,
        )

        template1 = manager.assign_user(test.test_id, "user1")
        template2 = manager.assign_user(test.test_id, "user1")

        assert template1 == template2

    def test_calculate_significance(self) -> None:
        """Test statistical significance calculation."""
        manager = ABTestManager()

        # Large difference
        p_value, is_significant = manager.calculate_significance(
            control_successes=50,
            control_total=100,
            variant_successes=80,
            variant_total=100,
        )

        assert is_significant is True

    def test_conclude_test_declares_winner(self) -> None:
        """Test test conclusion determines winner."""
        manager = ABTestManager()

        test = manager.create_ab_test(
            control_template_id="t1",
            variant_template_id="t2",
        )

        winner = manager.conclude_test(
            test_id=test.test_id,
            control_successes=50,
            control_total=100,
            variant_successes=75,
            variant_total=100,
        )

        assert winner in ["t1", "t2"]

        test = manager.tests[test.test_id]
        assert test.winner_template_id is not None
