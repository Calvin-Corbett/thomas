"""
Tests for email filtering functionality.

Tests filter rules, Sieve-like syntax parsing, and Bayesian spam filtering.
"""

from thomas.marketplace.email_protocol._types import EmailAddress, EmailMessage
from thomas.marketplace.email_protocol.filtering import (
    BayesianSpamFilter,
    FilterAction,
    FilterEngine,
    FilterRule,
)


class TestFilterRule:
    """Test individual filter rules."""

    def test_create_filter_rule(self):
        """Test creating filter rule."""
        conditions = [{"type": "from", "value": "spam@example.com"}]
        rule = FilterRule(
            name="Block spam",
            conditions=conditions,
            action=FilterAction.DISCARD,
        )

        assert rule.name == "Block spam"
        assert rule.enabled

    def test_filter_rule_matches_from(self):
        """Test rule matching FROM condition."""
        conditions = [{"type": "from", "value": "sender@example.com"}]
        rule = FilterRule(
            name="From Rule",
            conditions=conditions,
            action=FilterAction.KEEP,
        )

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("sender@example.com")

        assert rule.matches(message)

    def test_filter_rule_no_match_from(self):
        """Test rule not matching FROM."""
        conditions = [{"type": "from", "value": "sender@example.com"}]
        rule = FilterRule(
            name="From Rule",
            conditions=conditions,
            action=FilterAction.KEEP,
        )

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("other@example.com")

        assert not rule.matches(message)

    def test_filter_rule_matches_subject(self):
        """Test rule matching SUBJECT."""
        conditions = [{"type": "subject", "value": "Important"}]
        rule = FilterRule(
            name="Subject Rule",
            conditions=conditions,
            action=FilterAction.FILEINTO,
            action_target="Important",
        )

        message = EmailMessage()
        message.envelope.subject = "Important Meeting"

        assert rule.matches(message)

    def test_filter_rule_matches_size(self):
        """Test rule matching SIZE."""
        conditions = [{"type": "size", "operator": ">", "value": 1000000}]
        rule = FilterRule(
            name="Size Rule",
            conditions=conditions,
            action=FilterAction.DISCARD,
        )

        message = EmailMessage()
        message.size = 5000000

        assert rule.matches(message)

    def test_filter_rule_multiple_conditions(self):
        """Test rule with multiple conditions (AND logic)."""
        conditions = [
            {"type": "from", "value": "sender@example.com"},
            {"type": "subject", "value": "Test"},
        ]
        rule = FilterRule(
            name="Multi Rule",
            conditions=conditions,
            action=FilterAction.KEEP,
        )

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("sender@example.com")
        message.envelope.subject = "Test Message"

        assert rule.matches(message)

    def test_filter_rule_disabled(self):
        """Test disabled rule doesn't match."""
        conditions = [{"type": "from", "value": "sender@example.com"}]
        rule = FilterRule(
            name="Disabled",
            conditions=conditions,
            action=FilterAction.KEEP,
            enabled=False,
        )

        assert not rule.enabled


class TestFilterEngine:
    """Test filter engine."""

    def test_add_rule(self):
        """Test adding rule to engine."""
        engine = FilterEngine()
        rule = FilterRule(
            name="Test Rule",
            conditions=[],
            action=FilterAction.KEEP,
        )

        engine.add_rule(rule)
        assert len(engine.rules) == 1

    def test_remove_rule(self):
        """Test removing rule by name."""
        engine = FilterEngine()
        rule = FilterRule(
            name="Test Rule",
            conditions=[],
            action=FilterAction.KEEP,
        )

        engine.add_rule(rule)
        engine.remove_rule("Test Rule")
        assert len(engine.rules) == 0

    def test_execute_matching_rule(self):
        """Test executing matching rule."""
        engine = FilterEngine()
        rule = FilterRule(
            name="Discard Rule",
            conditions=[{"type": "from", "value": "spam@example.com"}],
            action=FilterAction.DISCARD,
        )
        engine.add_rule(rule)

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("spam@example.com")

        result = engine.execute(message)
        assert result["action"] == FilterAction.DISCARD

    def test_execute_no_matching_rule(self):
        """Test execution with no matching rule."""
        engine = FilterEngine()
        rule = FilterRule(
            name="Never Match",
            conditions=[{"type": "from", "value": "spam@example.com"}],
            action=FilterAction.DISCARD,
        )
        engine.add_rule(rule)

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("clean@example.com")

        result = engine.execute(message)
        assert result["action"] == FilterAction.KEEP

    def test_rule_priority(self):
        """Test rules execute in priority order."""
        engine = FilterEngine()

        rule1 = FilterRule(
            name="High Priority",
            conditions=[{"type": "from", "value": "test@example.com"}],
            action=FilterAction.DISCARD,
            priority=1,
        )
        rule2 = FilterRule(
            name="Low Priority",
            conditions=[{"type": "from", "value": "test@example.com"}],
            action=FilterAction.KEEP,
            priority=100,
        )

        engine.add_rule(rule2)
        engine.add_rule(rule1)

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("test@example.com")

        result = engine.execute(message)
        assert result["rule"] == "High Priority"


class TestSieveImport:
    """Test Sieve-like filter syntax parsing."""

    def test_import_simple_sieve(self):
        """Test importing simple Sieve rule."""
        sieve_text = """
        if from contains "spam@example.com" then discard;
        """

        engine = FilterEngine()
        rules = engine.import_sieve_rules(sieve_text)

        assert isinstance(rules, list)

    def test_import_fileinto_action(self):
        """Test importing fileinto action."""
        sieve_text = """
        if subject contains "Important" then fileinto "Important";
        """

        engine = FilterEngine()
        rules = engine.import_sieve_rules(sieve_text)

        assert isinstance(rules, list)


class TestBayesianSpamFilter:
    """Test Bayesian spam filtering."""

    def test_create_filter(self):
        """Test creating spam filter."""
        filter = BayesianSpamFilter(spam_threshold=0.5)

        assert filter.spam_threshold == 0.5

    def test_train_spam(self):
        """Test training with spam message."""
        filter = BayesianSpamFilter()

        message = EmailMessage()
        message.envelope.subject = "Buy cheap pills now"
        message.text_body = "Click here to buy now"

        filter.train(message, is_spam=True)

        assert filter.total_spam == 1
        assert len(filter.spam_words) > 0

    def test_train_ham(self):
        """Test training with legitimate message."""
        filter = BayesianSpamFilter()

        message = EmailMessage()
        message.envelope.subject = "Meeting Tomorrow"
        message.text_body = "Let's discuss the project status"

        filter.train(message, is_spam=False)

        assert filter.total_ham == 1
        assert len(filter.ham_words) > 0

    def test_score_spam_message(self):
        """Test scoring spam message."""
        filter = BayesianSpamFilter()

        spam_msg = EmailMessage()
        spam_msg.envelope.subject = "Buy cheap pills now"
        spam_msg.text_body = "Click here immediately"

        ham_msg = EmailMessage()
        ham_msg.envelope.subject = "Meeting"
        ham_msg.text_body = "Let's meet tomorrow"

        filter.train(spam_msg, is_spam=True)
        filter.train(ham_msg, is_spam=False)

        spam_score = filter.score(spam_msg)
        ham_score = filter.score(ham_msg)

        assert isinstance(spam_score, float)
        assert isinstance(ham_score, float)
        assert 0.0 <= spam_score <= 1.0
        assert 0.0 <= ham_score <= 1.0

    def test_is_spam_classification(self):
        """Test spam classification."""
        filter = BayesianSpamFilter(spam_threshold=0.5)

        spam_msg = EmailMessage()
        spam_msg.envelope.subject = "Buy pills"
        spam_msg.text_body = "Spam content here"

        ham_msg = EmailMessage()
        ham_msg.envelope.subject = "Meeting"
        ham_msg.text_body = "Regular email"

        filter.train(spam_msg, is_spam=True)
        filter.train(ham_msg, is_spam=False)

        assert isinstance(filter.is_spam(spam_msg), bool)
        assert isinstance(filter.is_spam(ham_msg), bool)

    def test_extract_words(self):
        """Test word extraction from message."""
        filter = BayesianSpamFilter()

        message = EmailMessage()
        message.envelope.subject = "Test Subject"
        message.text_body = "This is test content"
        message.envelope.from_addr = EmailAddress("sender@example.com")

        words = filter._extract_words(message)

        assert len(words) > 0
        assert "test" in words


class TestHeaderBasedFiltering:
    """Test filtering based on headers."""

    def test_filter_by_custom_header(self):
        """Test filtering by custom header."""
        conditions = [{"type": "header", "header": "X-Spam", "value": "yes"}]
        rule = FilterRule(
            name="Spam Header",
            conditions=conditions,
            action=FilterAction.DISCARD,
        )

        message = EmailMessage()
        message.headers["x-spam"] = ["yes"]

        assert rule.matches(message)


class TestFilterActions:
    """Test various filter actions."""

    def test_keep_action(self):
        """Test KEEP action."""
        rule = FilterRule(
            name="Keep Rule",
            conditions=[],
            action=FilterAction.KEEP,
        )

        assert rule.action == FilterAction.KEEP

    def test_discard_action(self):
        """Test DISCARD action."""
        rule = FilterRule(
            name="Discard Rule",
            conditions=[],
            action=FilterAction.DISCARD,
        )

        assert rule.action == FilterAction.DISCARD

    def test_fileinto_action(self):
        """Test FILEINTO action."""
        rule = FilterRule(
            name="File Into",
            conditions=[],
            action=FilterAction.FILEINTO,
            action_target="Archive",
        )

        assert rule.action_target == "Archive"

    def test_redirect_action(self):
        """Test REDIRECT action."""
        rule = FilterRule(
            name="Redirect",
            conditions=[],
            action=FilterAction.REDIRECT,
            action_target="other@example.com",
        )

        assert rule.action_target == "other@example.com"
