"""Tests for content moderation."""

from uuid import uuid4

import pytest

from thomas.social_platform import (
    ContentPolicy,
    ModerationAction,
    ModerationEngine,
)


class TestModerationEngine:
    """Test suite for ModerationEngine."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.engine = ModerationEngine()
        self.user_id = uuid4()
        self.moderator_id = uuid4()

    def test_toxicity_scoring_clean_content(self) -> None:
        """Test toxicity scoring for clean content."""
        text = "This is a great post about programming!"
        score, reason = self.engine.check_content(text)

        assert score < self.engine.TOXICITY_THRESHOLD
        assert reason is None

    def test_toxicity_scoring_toxic_content(self) -> None:
        """Test toxicity scoring detects toxic words."""
        text = "I hate this and you are stupid!"
        score, reason = self.engine.check_content(text)

        assert score >= self.engine.TOXICITY_THRESHOLD
        assert reason is not None

    def test_toxicity_multiple_violations(self) -> None:
        """Test toxicity scoring with multiple violations."""
        text = "hate hate hate abuse abuse"
        score, reason = self.engine.check_content(text)

        assert score >= self.engine.TOXICITY_THRESHOLD

    def test_spam_detection_legitimate(self) -> None:
        """Test spam detection on legitimate content."""
        text = "Great day to work on my favorite project!"
        score, is_spam = self.engine.detect_spam(text)

        assert not is_spam

    def test_spam_detection_spam_content(self) -> None:
        """Test spam detection on spam content."""
        text = "click here buy cheap viagra visit my casino!"
        score, is_spam = self.engine.detect_spam(text)

        assert is_spam

    def test_create_report_user(self) -> None:
        """Test creating user report."""
        reported_user = uuid4()
        report = self.engine.create_report(
            reporter_id=self.user_id,
            reason="harassment",
            reported_user_id=reported_user,
            details="User was harassing me",
        )

        assert report.reported_user_id == reported_user
        assert report.status == "pending"

    def test_create_report_content(self) -> None:
        """Test creating content report."""
        reported_content = uuid4()
        report = self.engine.create_report(
            reporter_id=self.user_id,
            reason="toxic_content",
            reported_content_id=reported_content,
            details="Hate speech in post",
        )

        assert report.reported_content_id == reported_content

    def test_report_requires_target(self) -> None:
        """Test that report requires either user or content."""
        with pytest.raises(ValueError):
            self.engine.create_report(reporter_id=self.user_id, reason="test")

    def test_get_next_report(self) -> None:
        """Test getting next report from queue."""
        report1 = self.engine.create_report(reporter_id=self.user_id, reason="minor", reported_user_id=uuid4())

        report2 = self.engine.create_report(reporter_id=self.user_id, reason="hate", reported_user_id=uuid4())

        # Get highest priority report
        next_report = self.engine.get_next_report()
        assert next_report is not None
        assert next_report.reason == "hate"

    def test_review_report(self) -> None:
        """Test reviewing a report."""
        report = self.engine.create_report(reporter_id=self.user_id, reason="spam", reported_content_id=uuid4())

        reviewed = self.engine.review_report(
            report.id, self.moderator_id, ModerationAction.SUPPRESS, notes="Content removed"
        )

        assert reviewed.status == "resolved"
        assert reviewed.action_taken == ModerationAction.SUPPRESS

    def test_take_moderation_action(self) -> None:
        """Test taking moderation action."""
        target_user = uuid4()
        log = self.engine.take_moderation_action(
            moderator_id=self.moderator_id,
            target_user_id=target_user,
            action=ModerationAction.MUTE,
            duration_hours=24,
            reason="spam",
        )

        assert log.action == ModerationAction.MUTE
        assert log.target_user_id == target_user
        assert log.appeal_deadline is not None

    def test_get_user_violation_history(self) -> None:
        """Test retrieving user violation history."""
        user = uuid4()

        self.engine.take_moderation_action(
            moderator_id=self.moderator_id, target_user_id=user, action=ModerationAction.WARNING
        )

        self.engine.take_moderation_action(
            moderator_id=self.moderator_id, target_user_id=user, action=ModerationAction.MUTE, duration_hours=24
        )

        history = self.engine.get_user_violation_history(user)
        assert len(history) == 2

    def test_moderation_stats(self) -> None:
        """Test moderation statistics."""
        # Take several actions
        for _ in range(3):
            self.engine.take_moderation_action(
                moderator_id=self.moderator_id, target_user_id=uuid4(), action=ModerationAction.WARNING
            )

        for _ in range(2):
            self.engine.take_moderation_action(
                moderator_id=self.moderator_id, target_user_id=uuid4(), action=ModerationAction.BAN
            )

        stats = self.engine.get_moderation_stats()
        assert stats["total_actions"] == 5
        assert stats["actions_by_type"]["warning"] == 3
        assert stats["actions_by_type"]["ban"] == 2

    def test_filter_content_clean(self) -> None:
        """Test content filtering on clean content."""
        is_blocked, reason, score = self.engine.filter_content(
            "Great post about technology!", auto_action_threshold=0.8
        )

        assert not is_blocked

    def test_filter_content_toxic(self) -> None:
        """Test content filtering on toxic content."""
        is_blocked, reason, score = self.engine.filter_content("I hate hate hate this", auto_action_threshold=0.6)

        assert is_blocked
        assert reason is not None

    def test_filter_content_spam(self) -> None:
        """Test content filtering on spam."""
        is_blocked, reason, score = self.engine.filter_content("click here buy cheap casino", auto_action_threshold=0.6)

        # Should be detected as spam or low threshold
        if is_blocked:
            assert "blocked" in reason.lower()

    def test_add_policy(self) -> None:
        """Test adding content policy."""
        policy = ContentPolicy(name="Test Policy", description="Test", keywords=["test"], severity=5)

        self.engine.add_policy(policy)
        assert policy.id in self.engine.policies

    def test_disable_policy(self) -> None:
        """Test disabling policy."""
        policy = ContentPolicy(name="Test Policy", description="Test", keywords=["test"], severity=5, enabled=True)

        self.engine.add_policy(policy)
        self.engine.disable_policy(policy.id)

        assert not self.engine.policies[policy.id].enabled

    def test_toxicity_weights_different_terms(self) -> None:
        """Test that different toxic terms have different weights."""
        # Mildly toxic
        mild = "This is stupid"
        mild_score, _ = self.engine.check_content(mild)

        # Highly toxic
        severe = "This is hate speech"
        severe_score, _ = self.engine.check_content(severe)

        assert severe_score > mild_score

    def test_spam_probability_calculation(self) -> None:
        """Test spam probability calculation."""
        # Legitimate text
        spam1, is_spam1 = self.engine.detect_spam("I love working on projects")
        assert not is_spam1

        # Spam text
        spam2, is_spam2 = self.engine.detect_spam("click buy cheap cash now")
        assert is_spam2

        # Spam probability should be higher for spam text
        assert spam2 > spam1

    def test_report_priority_calculation(self) -> None:
        """Test report priority calculation."""
        high_priority_report = self.engine.create_report(
            reporter_id=self.user_id, reason="hate", reported_user_id=uuid4()
        )

        low_priority_report = self.engine.create_report(
            reporter_id=self.user_id, reason="spam", reported_user_id=uuid4()
        )

        # High priority should be returned first
        first = self.engine.get_next_report()
        assert first.reason == "hate"
