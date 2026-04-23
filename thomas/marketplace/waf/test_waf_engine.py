"""
Tests for WAF Engine

Tests for core WAF evaluation logic, rule matching, and scoring.
"""

import pytest

from thomas.marketplace.waf._types import (
    HTTPRequest,
    RuleAction,
    ThreatLevel,
    WAFConfig,
    WAFRule,
)
from thomas.marketplace.waf.engine import WAFEngine


class TestWAFEngine:
    """Test cases for WAFEngine."""

    @pytest.fixture
    def config(self) -> WAFConfig:
        """Create test config."""
        return WAFConfig(
            enable_rate_limiting=False,
            enable_bot_detection=False,
            paranoia_level=1,
            block_threshold=100,
            challenge_threshold=75,
        )

    @pytest.fixture
    def engine(self, config: WAFConfig) -> WAFEngine:
        """Create test engine."""
        return WAFEngine(config)

    @pytest.fixture
    def test_request(self) -> HTTPRequest:
        """Create test request."""
        return HTTPRequest(
            method="GET",
            path="/test",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
            query_params={"id": "123"},
        )

    def test_engine_initialization(self, engine: WAFEngine) -> None:
        """Test engine initialization."""
        assert engine.get_rules_count() == 0
        assert engine.statistics.total_requests == 0

    def test_add_single_rule(self, engine: WAFEngine) -> None:
        """Test adding a single rule."""
        rule = WAFRule(
            id="test_001",
            name="Test Rule",
            pattern="test",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="Test",
        )

        engine.add_rule(rule)
        assert engine.get_rules_count() == 1

    def test_add_multiple_rules(self, engine: WAFEngine) -> None:
        """Test adding multiple rules."""
        rules = [
            WAFRule(
                id=f"test_{i:03d}",
                name=f"Test Rule {i}",
                pattern=f"pattern{i}",
                action=RuleAction.BLOCK,
                severity=ThreatLevel.MEDIUM,
                category="Test",
            )
            for i in range(5)
        ]

        engine.add_rules(rules)
        assert engine.get_rules_count() == 5

    def test_remove_rule(self, engine: WAFEngine) -> None:
        """Test removing a rule."""
        rule = WAFRule(
            id="test_001",
            name="Test Rule",
            pattern="test",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="Test",
        )

        engine.add_rule(rule)
        assert engine.get_rules_count() == 1

        removed = engine.remove_rule("test_001")
        assert removed is True
        assert engine.get_rules_count() == 0

    def test_rule_matching(self, engine: WAFEngine, test_request: HTTPRequest) -> None:
        """Test rule matching."""
        rule = WAFRule(
            id="sql_001",
            name="SQL Injection",
            pattern=r"union.*select",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="SQL Injection",
        )

        engine.add_rule(rule)

        # Request with SQL injection
        request = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
            query_params={"q": "UNION SELECT * FROM users"},
        )

        action, matches, score = engine.evaluate(request)
        assert action == RuleAction.BLOCK
        assert len(matches) == 1
        assert score > 0

    def test_rule_no_match(self, engine: WAFEngine, test_request: HTTPRequest) -> None:
        """Test when rule doesn't match."""
        rule = WAFRule(
            id="sql_001",
            name="SQL Injection",
            pattern=r"union.*select",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="SQL Injection",
        )

        engine.add_rule(rule)

        # Clean request
        request = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
            query_params={"q": "normal search"},
        )

        action, matches, score = engine.evaluate(request)
        assert action == RuleAction.ALLOW
        assert len(matches) == 0

    def test_whitelist_bypass(self, engine: WAFEngine) -> None:
        """Test IP whitelist bypass."""
        rule = WAFRule(
            id="sql_001",
            name="SQL Injection",
            pattern=r"union.*select",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="SQL Injection",
        )

        engine.add_rule(rule)
        engine.add_bypass_whitelist("192.168.1.1")

        # Request from whitelisted IP with SQL injection
        request = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
            query_params={"q": "UNION SELECT * FROM users"},
        )

        action, matches, score = engine.evaluate(request)
        assert action == RuleAction.ALLOW
        assert len(matches) == 0

    def test_rule_priority_ordering(self, engine: WAFEngine) -> None:
        """Test rule priority ordering."""
        rule1 = WAFRule(
            id="rule_1",
            name="Rule 1",
            pattern="test",
            action=RuleAction.LOG,
            severity=ThreatLevel.LOW,
            category="Test",
            priority=100,
        )

        rule2 = WAFRule(
            id="rule_2",
            name="Rule 2",
            pattern="test",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="Test",
            priority=10,
        )

        engine.add_rule(rule1)
        engine.add_rule(rule2)

        # Rule 2 (priority 10) should come first
        assert engine.rules[0].id == "rule_2"
        assert engine.rules[1].id == "rule_1"

    def test_statistics_tracking(self, engine: WAFEngine) -> None:
        """Test statistics tracking."""
        rule = WAFRule(
            id="test_001",
            name="Test Rule",
            pattern="attack",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="Test",
        )

        engine.add_rule(rule)

        # Good request
        good_request = HTTPRequest(
            method="GET",
            path="/test",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        action, _, _ = engine.evaluate(good_request)
        assert action == RuleAction.ALLOW

        # Attack request
        bad_request = HTTPRequest(
            method="GET",
            path="/test",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.2",
            query_params={"q": "attack"},
        )

        action, _, _ = engine.evaluate(bad_request)
        assert action == RuleAction.BLOCK

        stats = engine.get_statistics()
        assert stats.total_requests == 2
        assert stats.allowed_requests == 1
        assert stats.blocked_requests == 1

    def test_anomaly_score_calculation(self, engine: WAFEngine) -> None:
        """Test anomaly score calculation."""
        rule1 = WAFRule(
            id="test_001",
            name="Test Rule 1",
            pattern="attack",
            action=RuleAction.LOG,
            severity=ThreatLevel.MEDIUM,
            category="Test",
        )

        rule2 = WAFRule(
            id="test_002",
            name="Test Rule 2",
            pattern="malicious",
            action=RuleAction.LOG,
            severity=ThreatLevel.HIGH,
            category="Test",
        )

        engine.add_rule(rule1)
        engine.add_rule(rule2)

        request = HTTPRequest(
            method="GET",
            path="/test",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"attack malicious content",
            client_ip="192.168.1.1",
        )

        action, matches, score = engine.evaluate(request)
        assert len(matches) == 2
        assert score > 0

    def test_get_rule_by_id(self, engine: WAFEngine) -> None:
        """Test retrieving rule by ID."""
        rule = WAFRule(
            id="test_001",
            name="Test Rule",
            pattern="test",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="Test",
        )

        engine.add_rule(rule)

        retrieved = engine.get_rule_by_id("test_001")
        assert retrieved is not None
        assert retrieved.name == "Test Rule"

        not_found = engine.get_rule_by_id("nonexistent")
        assert not_found is None

    def test_transformation_application(self, engine: WAFEngine) -> None:
        """Test transformation application."""
        rule = WAFRule(
            id="xss_001",
            name="XSS Detection",
            pattern=r"<script",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="XSS",
            transformations=["htmlDecode"],
        )

        engine.add_rule(rule)

        # HTML encoded script tag
        request = HTTPRequest(
            method="POST",
            path="/comment",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=b"comment=%3Cscript%3Ealert(1)%3C%2Fscript%3E",
            client_ip="192.168.1.1",
        )

        action, matches, _ = engine.evaluate(request)
        assert action == RuleAction.BLOCK

    def test_statistics_reset(self, engine: WAFEngine) -> None:
        """Test statistics reset."""
        rule = WAFRule(
            id="test_001",
            name="Test Rule",
            pattern="test",
            action=RuleAction.BLOCK,
            severity=ThreatLevel.HIGH,
            category="Test",
        )

        engine.add_rule(rule)

        request = HTTPRequest(
            method="GET",
            path="/test",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        engine.evaluate(request)
        assert engine.statistics.total_requests == 1

        engine.reset_statistics()
        assert engine.statistics.total_requests == 0
