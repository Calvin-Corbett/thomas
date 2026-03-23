"""Content moderation and safety enforcement.

This module implements automated content filtering, toxicity scoring,
spam detection using Bayesian classification, report management,
moderation actions, and audit logging.
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta
from heapq import heappop, heappush
from uuid import UUID

from ._types import ContentPolicy, ModerationAction, ModerationLog, Report


class ModerationEngine:
    """Content moderation and policy enforcement.

    Attributes:
        policies: Content policies
        moderation_log: Log of moderation actions
        report_queue: Priority queue of reports
        user_flags: Track user violation history
        spam_features: Training data for spam detection
    """

    # Toxicity thresholds
    TOXICITY_THRESHOLD = 0.7
    SPAM_THRESHOLD = 0.6

    def __init__(self) -> None:
        """Initialize moderation engine."""
        self.policies: dict[UUID, ContentPolicy] = {}
        self.moderation_log: list[ModerationLog] = []
        self.report_queue: list[tuple[int, Report]] = []  # Priority queue
        self.user_flags: dict[UUID, list[ModerationLog]] = defaultdict(list)
        self.spam_features: dict[str, dict[str, int]] = {"spam": defaultdict(int), "ham": defaultdict(int)}

        # Initialize default policies
        self._init_default_policies()
        self._train_spam_classifier()

    def _init_default_policies(self) -> None:
        """Initialize default content policies."""
        toxic_policy = ContentPolicy(
            name="Toxic Language",
            description="Content containing hate speech, slurs, or abuse",
            keywords=["hate", "abuse", "slur"],
            severity=8,
            action=ModerationAction.SUPPRESS,
            enabled=True,
        )
        self.policies[toxic_policy.id] = toxic_policy

        spam_policy = ContentPolicy(
            name="Spam",
            description="Repetitive unwanted content",
            keywords=["spam", "promotional"],
            severity=5,
            action=ModerationAction.SUPPRESS,
            enabled=True,
        )
        self.policies[spam_policy.id] = spam_policy

    def _train_spam_classifier(self) -> None:
        """Train spam classifier with typical spam features."""
        # Spam features
        spam_features = [
            "click",
            "buy",
            "cheap",
            "free",
            "visit",
            "link",
            "earn",
            "money",
            "bitcoin",
            "casino",
            "lottery",
            "viagra",
            "pharmacy",
            "alert",
            "urgent",
        ]
        for feature in spam_features:
            self.spam_features["spam"][feature] = 5

        # Ham (legitimate) features
        ham_features = ["think", "people", "time", "life", "day", "work", "good", "great", "thanks", "love", "amazing"]
        for feature in ham_features:
            self.spam_features["ham"][feature] = 5

    def check_content(self, content: str) -> tuple[float, str | None]:
        """Check content for toxicity.

        Args:
            content: Text content to check

        Returns:
            Tuple of (toxicity_score, violation_reason)
        """
        toxicity_score = self._calculate_toxicity_score(content)

        if toxicity_score >= self.TOXICITY_THRESHOLD:
            return toxicity_score, "Toxic content detected"

        return toxicity_score, None

    def _calculate_toxicity_score(self, text: str) -> float:
        """Calculate toxicity score for text.

        Rule-based scoring with weighted toxic terms.

        Args:
            text: Text to analyze

        Returns:
            Score from 0.0 to 1.0
        """
        toxic_words = {
            "hate": 0.9,
            "kill": 0.85,
            "die": 0.8,
            "abuse": 0.85,
            "stupid": 0.5,
            "idiot": 0.6,
            "racist": 0.95,
            "sexist": 0.9,
        }

        text_lower = text.lower()
        total_score = 0.0
        max_possible = 0.0

        for word, score in toxic_words.items():
            # Count occurrences
            count = len(re.findall(r"\b" + re.escape(word) + r"\b", text_lower))
            if count > 0:
                total_score += min(count * score, 1.0)
                max_possible += 1.0

        if max_possible == 0:
            return 0.0

        return min(total_score / max_possible, 1.0)

    def detect_spam(self, text: str) -> tuple[float, bool]:
        """Detect spam using Bayesian classifier.

        Args:
            text: Text to analyze

        Returns:
            Tuple of (spam_probability, is_spam)
        """
        spam_prob = self._calculate_spam_probability(text)
        is_spam = spam_prob >= self.SPAM_THRESHOLD

        return spam_prob, is_spam

    def _calculate_spam_probability(self, text: str) -> float:
        """Calculate spam probability using Bayes theorem.

        Args:
            text: Text to analyze

        Returns:
            Probability of being spam (0.0 to 1.0)
        """
        tokens = text.lower().split()

        # Prior probabilities
        p_spam = 0.1
        p_ham = 0.9

        # Calculate likelihoods
        p_text_given_spam = 1.0
        p_text_given_ham = 1.0

        for token in tokens:
            spam_count = self.spam_features["spam"].get(token, 0)
            ham_count = self.spam_features["ham"].get(token, 0)

            spam_total = sum(self.spam_features["spam"].values())
            ham_total = sum(self.spam_features["ham"].values())

            # Laplace smoothing
            p_token_spam = (spam_count + 1) / (spam_total + 2)
            p_token_ham = (ham_count + 1) / (ham_total + 2)

            p_text_given_spam *= p_token_spam
            p_text_given_ham *= p_token_ham

        # Bayes theorem
        p_spam_given_text = (p_text_given_spam * p_spam) / (p_text_given_spam * p_spam + p_text_given_ham * p_ham)

        return p_spam_given_text

    def create_report(
        self,
        reporter_id: UUID,
        reason: str,
        reported_user_id: UUID | None = None,
        reported_content_id: UUID | None = None,
        details: str = "",
    ) -> Report:
        """Create a content/user report.

        Args:
            reporter_id: User making report
            reason: Reason for report
            reported_user_id: ID of reported user (optional)
            reported_content_id: ID of reported content (optional)
            details: Additional details

        Returns:
            Report object
        """
        if not reported_user_id and not reported_content_id:
            raise ValueError("Must report either user or content")

        report = Report(
            reporter_id=reporter_id,
            reported_user_id=reported_user_id,
            reported_content_id=reported_content_id,
            reason=reason,
            details=details,
            created_at=datetime.utcnow(),
            status="pending",
        )

        # Add to priority queue (based on severity)
        priority = self._calculate_report_priority(report)
        heappush(self.report_queue, (-priority, report))

        return report

    def _calculate_report_priority(self, report: Report) -> float:
        """Calculate report priority.

        Args:
            report: Report to prioritize

        Returns:
            Priority score (higher = more urgent)
        """
        priority = 0.0

        # Higher priority for certain reasons
        if report.reason.lower() in ["hate", "violence", "abuse"]:
            priority += 10.0
        elif report.reason.lower() in ["spam", "scam"]:
            priority += 5.0

        # Higher priority for repeat reporters
        report_age = (datetime.utcnow() - report.created_at).total_seconds()
        priority *= max(1.0, 100.0 / (report_age + 1))

        return priority

    def get_next_report(self) -> Report | None:
        """Get next report from priority queue.

        Returns:
            Next report or None if queue empty
        """
        while self.report_queue:
            _, report = heappop(self.report_queue)
            if report.status == "pending":
                return report
        return None

    def review_report(
        self, report_id: UUID, moderator_id: UUID, action: ModerationAction | None = None, notes: str = ""
    ) -> Report:
        """Review and resolve a report.

        Args:
            report_id: Report ID
            moderator_id: Moderator user ID
            action: Moderation action to take
            notes: Moderator notes

        Returns:
            Updated Report

        Raises:
            ValueError: If report not found
        """
        # Find report in queue
        report = None
        for priority, r in self.report_queue:
            if r.id == report_id:
                report = r
                break

        if not report:
            raise ValueError(f"Report {report_id} not found")

        if action:
            report.action_taken = action
            report.status = "resolved"
        else:
            report.status = "dismissed"

        report.moderator_notes = notes

        # Log action
        log = ModerationLog(
            moderator_id=moderator_id,
            target_user_id=report.reported_user_id,
            target_content_id=report.reported_content_id,
            action=action or ModerationAction.WARNING,
            reason=report.reason,
            notes=notes,
            created_at=datetime.utcnow(),
        )

        self.moderation_log.append(log)

        if report.reported_user_id:
            self.user_flags[report.reported_user_id].append(log)

        return report

    def take_moderation_action(
        self,
        moderator_id: UUID,
        target_user_id: UUID | None = None,
        target_content_id: UUID | None = None,
        action: ModerationAction = ModerationAction.WARNING,
        duration_hours: int | None = None,
        reason: str = "",
    ) -> ModerationLog:
        """Take moderation action against user or content.

        Args:
            moderator_id: Moderator user ID
            target_user_id: User being moderated
            target_content_id: Content being moderated
            action: Action to take
            duration_hours: Duration of action (for mutes/bans)
            reason: Reason for action

        Returns:
            ModerationLog entry
        """
        log = ModerationLog(
            moderator_id=moderator_id,
            target_user_id=target_user_id,
            target_content_id=target_content_id,
            action=action,
            duration_hours=duration_hours,
            reason=reason,
            created_at=datetime.utcnow(),
        )

        # Set appeal deadline (30 days from action)
        if action in [ModerationAction.MUTE, ModerationAction.BAN]:
            log.appeal_deadline = datetime.utcnow() + timedelta(days=30)

        self.moderation_log.append(log)

        if target_user_id:
            self.user_flags[target_user_id].append(log)

        return log

    def get_user_violation_history(self, user_id: UUID) -> list[ModerationLog]:
        """Get user's violation history.

        Args:
            user_id: User ID

        Returns:
            List of moderation logs for user
        """
        return self.user_flags.get(user_id, [])

    def get_moderation_stats(self) -> dict[str, int]:
        """Get moderation statistics.

        Returns:
            Dictionary with stats
        """
        actions = defaultdict(int)
        for log in self.moderation_log:
            actions[log.action.value] += 1

        return {
            "total_actions": len(self.moderation_log),
            "pending_reports": sum(1 for _, r in self.report_queue if r.status == "pending"),
            "actions_by_type": dict(actions),
        }

    def filter_content(self, content: str, auto_action_threshold: float = 0.8) -> tuple[bool, str | None, float]:
        """Filter content automatically.

        Args:
            content: Content to filter
            auto_action_threshold: Threshold for automatic action

        Returns:
            Tuple of (is_blocked, reason, score)
        """
        toxicity_score, toxicity_reason = self.check_content(content)
        spam_score, is_spam = self.detect_spam(content)

        if toxicity_score >= auto_action_threshold:
            return True, "Toxic content blocked", toxicity_score

        if is_spam and spam_score >= 0.8:
            return True, "Spam blocked", spam_score

        return False, None, max(toxicity_score, spam_score)

    def add_policy(self, policy: ContentPolicy) -> None:
        """Add content policy.

        Args:
            policy: ContentPolicy to add
        """
        self.policies[policy.id] = policy

    def disable_policy(self, policy_id: UUID) -> None:
        """Disable a policy.

        Args:
            policy_id: Policy ID to disable
        """
        if policy_id in self.policies:
            self.policies[policy_id].enabled = False

    def get_content_for_review(self, limit: int = 10) -> list[tuple[str, float]]:
        """Get content flagged for manual review.

        Args:
            limit: Maximum items to return

        Returns:
            List of (content_id, toxicity_score) tuples
        """
        # This would query content with scores between thresholds
        # For now, returning empty as we'd need actual content store
        return []
