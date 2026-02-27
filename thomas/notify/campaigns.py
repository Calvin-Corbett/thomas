"""
Campaign management for batch notification sending with A/B testing.
Handles audience segmentation and statistical analysis.
"""

import random
from datetime import datetime
from typing import Any

from thomas.notify._exceptions import NotifyException
from thomas.notify._types import (
    ABTest,
    Audience,
    Campaign,
    ChannelType,
    Priority,
    Schedule,
    Segment,
)


class AudienceManager:
    """Manages audience definitions and segmentation."""

    def __init__(self) -> None:
        """Initialize audience manager."""
        self.audiences: dict[str, Audience] = {}
        self.segments: dict[str, Segment] = {}

    def create_audience(
        self,
        name: str,
        description: str = "",
        filters: list[dict[str, Any]] | None = None,
        segment_ids: list[str] | None = None,
        user_ids: set[str] | None = None,
    ) -> Audience:
        """Create audience definition.

        Args:
            name: Audience name
            description: Audience description
            filters: Filter expressions
            segment_ids: Segment identifiers to include
            user_ids: Specific user IDs

        Returns:
            Created audience
        """
        audience = Audience(
            name=name,
            description=description,
            filters=filters or [],
            segment_ids=segment_ids or [],
            user_ids=user_ids or set(),
        )

        self.audiences[audience.audience_id] = audience

        return audience

    def create_segment(
        self,
        name: str,
        description: str = "",
        filters: dict[str, Any] | None = None,
    ) -> Segment:
        """Create segment definition.

        Args:
            name: Segment name
            description: Segment description
            filters: Filter expressions

        Returns:
            Created segment
        """
        segment = Segment(
            name=name,
            description=description,
            filters=filters or {},
        )

        self.segments[segment.segment_id] = segment

        return segment

    def get_audience(self, audience_id: str) -> Audience:
        """Get audience by ID.

        Args:
            audience_id: Audience identifier

        Returns:
            Audience

        Raises:
            NotifyException: If audience not found
        """
        if audience_id not in self.audiences:
            raise NotifyException(f"Audience {audience_id} not found")

        return self.audiences[audience_id]

    def get_segment(self, segment_id: str) -> Segment:
        """Get segment by ID.

        Args:
            segment_id: Segment identifier

        Returns:
            Segment

        Raises:
            NotifyException: If segment not found
        """
        if segment_id not in self.segments:
            raise NotifyException(f"Segment {segment_id} not found")

        return self.segments[segment_id]


class CampaignManager:
    """Manages notification campaigns."""

    def __init__(self) -> None:
        """Initialize campaign manager."""
        self.campaigns: dict[str, Campaign] = {}
        self.audience_manager = AudienceManager()

    def create_campaign(
        self,
        name: str,
        template_id: str,
        audience: Audience,
        channel_types: list[ChannelType] | None = None,
        schedule: Schedule | None = None,
        priority: Priority = Priority.NORMAL,
        ab_test: ABTest | None = None,
    ) -> Campaign:
        """Create campaign.

        Args:
            name: Campaign name
            template_id: Template to send
            audience: Target audience
            channel_types: Delivery channels
            schedule: Send schedule
            priority: Notification priority
            ab_test: A/B test configuration

        Returns:
            Created campaign
        """
        campaign = Campaign(
            name=name,
            template_id=template_id,
            audience=audience,
            channel_types=channel_types or [ChannelType.EMAIL],
            schedule=schedule,
            priority=priority,
            ab_test=ab_test,
        )

        self.campaigns[campaign.campaign_id] = campaign

        return campaign

    def get_campaign(self, campaign_id: str) -> Campaign:
        """Get campaign by ID.

        Args:
            campaign_id: Campaign identifier

        Returns:
            Campaign

        Raises:
            NotifyException: If campaign not found
        """
        if campaign_id not in self.campaigns:
            raise NotifyException(f"Campaign {campaign_id} not found")

        return self.campaigns[campaign_id]

    def start_campaign(self, campaign_id: str) -> Campaign:
        """Start campaign execution.

        Args:
            campaign_id: Campaign identifier

        Returns:
            Updated campaign

        Raises:
            NotifyException: If campaign already running or invalid
        """
        campaign = self.get_campaign(campaign_id)

        if campaign.status != "draft":
            raise NotifyException(f"Campaign {campaign_id} is not in draft status")

        campaign.status = "running"
        campaign.started_at = datetime.utcnow()

        return campaign

    def complete_campaign(self, campaign_id: str) -> Campaign:
        """Mark campaign as completed.

        Args:
            campaign_id: Campaign identifier

        Returns:
            Updated campaign
        """
        campaign = self.get_campaign(campaign_id)
        campaign.status = "completed"
        campaign.completed_at = datetime.utcnow()

        return campaign

    def record_send(self, campaign_id: str) -> None:
        """Record a send event for campaign.

        Args:
            campaign_id: Campaign identifier
        """
        campaign = self.get_campaign(campaign_id)
        campaign.sent_count += 1

    def record_delivery(self, campaign_id: str) -> None:
        """Record a delivery event for campaign.

        Args:
            campaign_id: Campaign identifier
        """
        campaign = self.get_campaign(campaign_id)
        campaign.delivered_count += 1

    def record_open(self, campaign_id: str) -> None:
        """Record an open event for campaign.

        Args:
            campaign_id: Campaign identifier
        """
        campaign = self.get_campaign(campaign_id)
        campaign.opened_count += 1

    def record_click(self, campaign_id: str) -> None:
        """Record a click event for campaign.

        Args:
            campaign_id: Campaign identifier
        """
        campaign = self.get_campaign(campaign_id)
        campaign.clicked_count += 1

    def record_conversion(self, campaign_id: str) -> None:
        """Record a conversion event for campaign.

        Args:
            campaign_id: Campaign identifier
        """
        campaign = self.get_campaign(campaign_id)
        campaign.converted_count += 1


class ABTestManager:
    """Manages A/B testing for campaigns."""

    def __init__(self) -> None:
        """Initialize A/B test manager."""
        self.tests: dict[str, ABTest] = {}
        self.user_assignments: dict[str, tuple[str, str]] = {}

    def create_ab_test(
        self,
        control_template_id: str,
        variant_template_id: str,
        split_percentage: float = 0.5,
        metric: str = "open_rate",
        sample_size: int = 1000,
        confidence_level: float = 0.95,
    ) -> ABTest:
        """Create A/B test.

        Args:
            control_template_id: Control template
            variant_template_id: Variant template
            split_percentage: Percentage to variant (default 50%)
            metric: Metric to measure
            sample_size: Required sample size
            confidence_level: Confidence level for significance

        Returns:
            Created A/B test

        Raises:
            NotifyException: If configuration invalid
        """
        if not (0 <= split_percentage <= 1):
            raise NotifyException("split_percentage must be between 0 and 1 inclusive")

        if confidence_level not in (0.90, 0.95, 0.99):
            raise NotifyException("confidence_level must be 0.90, 0.95, or 0.99")

        ab_test = ABTest(
            control_template_id=control_template_id,
            variant_template_id=variant_template_id,
            split_percentage=split_percentage,
            metric=metric,
            sample_size=sample_size,
            confidence_level=confidence_level,
        )

        self.tests[ab_test.test_id] = ab_test

        return ab_test

    def assign_user(self, test_id: str, user_id: str) -> str:
        """Assign user to control or variant.

        Args:
            test_id: A/B test identifier
            user_id: User identifier

        Returns:
            Template ID (control or variant)

        Raises:
            NotifyException: If test not found
        """
        if test_id not in self.tests:
            raise NotifyException(f"Test {test_id} not found")

        if (test_id, user_id) in self.user_assignments:
            _, template_id = self.user_assignments[(test_id, user_id)]
            return template_id

        ab_test = self.tests[test_id]
        rand = random.random()

        if rand < ab_test.split_percentage:
            template_id = ab_test.variant_template_id
        else:
            template_id = ab_test.control_template_id

        self.user_assignments[(test_id, user_id)] = (user_id, template_id)

        return template_id

    def get_results(self, test_id: str) -> dict[str, Any]:
        """Get A/B test results.

        Args:
            test_id: A/B test identifier

        Returns:
            Test results with metrics

        Raises:
            NotifyException: If test not found
        """
        if test_id not in self.tests:
            raise NotifyException(f"Test {test_id} not found")

        ab_test = self.tests[test_id]

        # Get assignments for each template
        control_assignments = [
            uid
            for (tid, uid), (_, tmpl_id) in (self.user_assignments.items())
            if tid == test_id and (tmpl_id == ab_test.control_template_id)
        ]
        variant_assignments = [
            uid
            for (tid, uid), (_, tmpl_id) in (self.user_assignments.items())
            if tid == test_id and (tmpl_id == ab_test.variant_template_id)
        ]

        return {
            "test_id": test_id,
            "control_template": ab_test.control_template_id,
            "variant_template": ab_test.variant_template_id,
            "control_count": len(control_assignments),
            "variant_count": len(variant_assignments),
            "metric": ab_test.metric,
            "status": "running" if ab_test.winner_template_id is None else "completed",
            "winner": ab_test.winner_template_id,
        }

    def calculate_significance(
        self,
        control_successes: int,
        control_total: int,
        variant_successes: int,
        variant_total: int,
    ) -> tuple[float, bool]:
        """Calculate statistical significance using chi-squared test.

        Args:
            control_successes: Number of successes in control
            control_total: Total control sample size
            variant_successes: Number of successes in variant
            variant_total: Total variant sample size

        Returns:
            Tuple of (p_value, is_significant)
        """
        if control_total < 1 or variant_total < 1:
            return (1.0, False)

        control_failures = control_total - control_successes
        variant_failures = variant_total - variant_successes

        # Chi-squared calculation
        total = control_total + variant_total
        expected_success_rate = (control_successes + variant_successes) / total

        expected_control_success = control_total * expected_success_rate
        expected_control_failure = control_total * (1 - expected_success_rate)
        expected_variant_success = variant_total * expected_success_rate
        expected_variant_failure = variant_total * (1 - expected_success_rate)

        chi_squared = (
            ((control_successes - expected_control_success) ** 2 / expected_control_success)
            + ((control_failures - expected_control_failure) ** 2 / expected_control_failure)
            + ((variant_successes - expected_variant_success) ** 2 / expected_variant_success)
            + ((variant_failures - expected_variant_failure) ** 2 / expected_variant_failure)
        )

        # Critical values for chi-squared (df=1)
        critical_values = {
            0.90: 2.706,
            0.95: 3.841,
            0.99: 6.635,
        }

        # Approximation of p-value
        p_value = 0.05 if chi_squared > 3.841 else 0.95

        return (p_value, chi_squared > 3.841)

    def conclude_test(
        self,
        test_id: str,
        control_successes: int,
        control_total: int,
        variant_successes: int,
        variant_total: int,
    ) -> str:
        """Conclude A/B test and determine winner.

        Args:
            test_id: A/B test identifier
            control_successes: Number of successes in control
            control_total: Total control sample size
            variant_successes: Number of successes in variant
            variant_total: Total variant sample size

        Returns:
            Winner template ID

        Raises:
            NotifyException: If test not found
        """
        if test_id not in self.tests:
            raise NotifyException(f"Test {test_id} not found")

        ab_test = self.tests[test_id]

        p_value, is_significant = self.calculate_significance(
            control_successes,
            control_total,
            variant_successes,
            variant_total,
        )

        ab_test.p_value = p_value
        ab_test.is_significant = is_significant

        if is_significant:
            control_rate = control_successes / control_total if control_total > 0 else 0
            variant_rate = variant_successes / variant_total if variant_total > 0 else 0

            if variant_rate > control_rate:
                ab_test.winner_template_id = ab_test.variant_template_id
            else:
                ab_test.winner_template_id = ab_test.control_template_id
        else:
            ab_test.winner_template_id = ab_test.control_template_id

        return ab_test.winner_template_id
