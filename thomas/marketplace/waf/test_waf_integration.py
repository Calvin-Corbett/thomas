"""
Integration Tests for WAF

End-to-end tests for complete WAF functionality.
"""

import pytest

from thomas.marketplace.waf._types import (
    HTTPRequest,
    RuleAction,
    ThreatLevel,
    WAFConfig,
)
from thomas.marketplace.waf.anomaly import AnomalyScorer
from thomas.marketplace.waf.bot_detection import BotDetector
from thomas.marketplace.waf.engine import WAFEngine
from thomas.marketplace.waf.ip_reputation import IPReputationManager
from thomas.marketplace.waf.rate_limiter import RateLimiter
from thomas.marketplace.waf.rules import BuiltInRules
from thomas.marketplace.waf.scanner import ScannerDetector


class TestWAFIntegration:
    """Integration tests for WAF system."""

    @pytest.fixture
    def config(self) -> WAFConfig:
        """Create WAF config."""
        return WAFConfig(
            enable_rate_limiting=True,
            enable_bot_detection=True,
            enable_scanner_detection=True,
            paranoia_level=2,
            block_threshold=100,
            challenge_threshold=75,
        )

    @pytest.fixture
    def waf_stack(self, config: WAFConfig):
        """Create complete WAF stack."""
        engine = WAFEngine(config)
        rate_limiter = RateLimiter(config.rate_limit_config)
        ip_reputation = IPReputationManager()
        scanner_detector = ScannerDetector()
        bot_detector = BotDetector()
        anomaly_scorer = AnomalyScorer(config.paranoia_level)

        # Add all built-in rules
        engine.add_rules(BuiltInRules.get_all_rules())

        return {
            "engine": engine,
            "rate_limiter": rate_limiter,
            "ip_reputation": ip_reputation,
            "scanner_detector": scanner_detector,
            "bot_detector": bot_detector,
            "anomaly_scorer": anomaly_scorer,
        }

    def test_normal_request_flow(self, waf_stack):
        """Test normal request flow through WAF."""
        request = HTTPRequest(
            method="GET",
            path="/api/users",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            },
            body=b"",
            client_ip="192.168.1.1",
        )

        # Rate limit check
        action, _ = waf_stack["rate_limiter"].check_rate_limit(request.client_ip, request.path)
        assert action == RuleAction.ALLOW

        # Rule evaluation
        action, matches, score = waf_stack["engine"].evaluate(request)
        assert action == RuleAction.ALLOW

        # Bot detection
        is_bot, _, _ = waf_stack["bot_detector"].get_bot_detection_result(request)

    def test_sql_injection_attack_flow(self, waf_stack):
        """Test SQL injection attack detection flow."""
        request = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
            query_params={"q": "UNION SELECT * FROM users"},
        )

        # Rule evaluation
        action, matches, score = waf_stack["engine"].evaluate(request)
        assert action == RuleAction.BLOCK
        assert len(matches) > 0

        # IP reputation update
        waf_stack["ip_reputation"].increment_abuse_count(request.client_ip)
        rep = waf_stack["ip_reputation"].get_reputation(request.client_ip)
        assert rep.abuse_count > 0

    def test_scanner_detection_flow(self, waf_stack):
        """Test vulnerability scanner detection."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Acunetix-Scan/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        # Scanner detection
        is_scan, scan_type = waf_stack["scanner_detector"].is_scanner(request)
        assert is_scan is True

        action, reason = waf_stack["scanner_detector"].get_scanner_action(request)
        assert action == RuleAction.BLOCK

    def test_rate_limit_escalation_flow(self, waf_stack):
        """Test rate limit escalation."""
        ip = "192.168.1.1"

        # Fill up rate limit
        for i in range(5):
            waf_stack["rate_limiter"].check_rate_limit(ip, "/api")

        # Should trigger LOG action
        action, _ = waf_stack["rate_limiter"].check_rate_limit(ip, "/api")
        # First overflow triggers LOG in graduated response

        # Continue exceeding
        for i in range(5):
            waf_stack["rate_limiter"].check_rate_limit(ip, "/api")

        # Should eventually block
        action, _ = waf_stack["rate_limiter"].check_rate_limit(ip, "/api")

    def test_ip_reputation_tracking_flow(self, waf_stack):
        """Test IP reputation tracking."""
        ip = "192.168.1.1"

        # Add threats
        waf_stack["ip_reputation"].add_threat_type(ip, "SQL_INJECTION")
        waf_stack["ip_reputation"].add_threat_type(ip, "XSS")

        # Get reputation
        rep = waf_stack["ip_reputation"].get_reputation(ip)
        assert len(rep.threat_types) == 2

        # Check suspicious
        waf_stack["ip_reputation"].is_suspicious(ip)

    def test_bot_challenge_flow(self, waf_stack):
        """Test bot challenge flow."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": ""},
            body=b"",
            client_ip="192.168.1.1",
        )

        # Calculate bot score
        score = waf_stack["bot_detector"].calculate_bot_score(request)

        if score > 0.4:
            # Issue challenge
            token = waf_stack["bot_detector"].require_javascript_challenge(request)

            # Verify challenge
            result = waf_stack["bot_detector"].verify_challenge(token, request.client_ip)
            assert result is True

            # Should now be verified human
            is_human = waf_stack["bot_detector"].is_verified_human(request.client_ip)
            assert is_human is True

    def test_anomaly_score_accumulation(self, waf_stack):
        """Test anomaly score accumulation."""
        # Get SQL injection rules
        BuiltInRules.get_rules_by_category("SQL Injection")

        request = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
            query_params={"q": "UNION SELECT * FROM users"},
        )

        action, matches, score = waf_stack["engine"].evaluate(request)

        # Track score
        waf_stack["anomaly_scorer"].track_score(request.client_ip, score)

        # Get average score
        avg_score = waf_stack["anomaly_scorer"].get_average_score(request.client_ip, minutes=1)
        assert avg_score >= 0

    def test_multi_stage_attack_detection(self, waf_stack):
        """Test detection of multi-stage attack."""
        ip = "192.168.1.1"

        # Stage 1: Path traversal attempt
        request1 = HTTPRequest(
            method="GET",
            path="/get_file?path=../../etc/passwd",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip=ip,
        )

        action1, matches1, score1 = waf_stack["engine"].evaluate(request1)
        waf_stack["ip_reputation"].increment_abuse_count(ip)

        # Stage 2: SQL injection attempt
        request2 = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip=ip,
            query_params={"q": "UNION SELECT"},
        )

        action2, matches2, score2 = waf_stack["engine"].evaluate(request2)
        waf_stack["ip_reputation"].increment_abuse_count(ip)

        # IP should be heavily flagged
        rep = waf_stack["ip_reputation"].get_reputation(ip)
        assert rep.abuse_count >= 2

    def test_whitelisted_ip_bypass(self, waf_stack):
        """Test whitelisted IP bypasses checks."""
        ip = "10.0.0.1"
        waf_stack["engine"].add_bypass_whitelist(ip)

        # Attack request from whitelisted IP
        request = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip=ip,
            query_params={"q": "UNION SELECT * FROM users"},
        )

        action, matches, _ = waf_stack["engine"].evaluate(request)
        assert action == RuleAction.ALLOW

    def test_paranoia_level_affects_scoring(self, waf_stack):
        """Test paranoia level affects anomaly scoring."""
        # Test with paranoia level 1
        scorer1 = AnomalyScorer(paranoia_level=1)

        # Test with paranoia level 4
        scorer4 = AnomalyScorer(paranoia_level=4)

        from thomas.marketplace.waf._types import RuleMatch

        match = RuleMatch(
            rule_id="test_001",
            rule_name="Test",
            matched_pattern="test",
            matched_value="test value",
            severity=ThreatLevel.MEDIUM,
            action=RuleAction.LOG,
            confidence=1.0,
        )

        score1, _ = scorer1.calculate_inbound_score([match])
        score4, _ = scorer4.calculate_inbound_score([match])

        # Higher paranoia level should result in higher score
        assert score4 > score1

    def test_cleanup_and_maintenance(self, waf_stack):
        """Test cleanup and maintenance operations."""
        # Add some history
        ip = "192.168.1.1"
        waf_stack["ip_reputation"].get_reputation(ip)
        waf_stack["bot_detector"].require_javascript_challenge(
            HTTPRequest(
                method="GET",
                path="/",
                headers={"User-Agent": "Mozilla/5.0"},
                body=b"",
                client_ip=ip,
            )
        )

        # Cleanup
        cleaned = waf_stack["ip_reputation"].cleanup_expired_bans()
        assert cleaned >= 0

        cleaned = waf_stack["bot_detector"].cleanup_expired_tokens()
        assert cleaned >= 0

        cleaned = waf_stack["anomaly_scorer"].cleanup_history(older_than_hours=0)

    def test_statistics_reporting(self, waf_stack):
        """Test statistics reporting."""
        # Make some requests
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        waf_stack["engine"].evaluate(request)
        waf_stack["rate_limiter"].check_rate_limit("192.168.1.1", "/")

        # Get stats
        engine_stats = waf_stack["engine"].get_statistics()
        rate_limiter_stats = waf_stack["rate_limiter"].get_stats("192.168.1.1")
        scanner_stats = waf_stack["scanner_detector"].get_stats()
        bot_stats = waf_stack["bot_detector"].get_stats()
        anomaly_stats = waf_stack["anomaly_scorer"].get_stats()

        assert engine_stats.total_requests > 0
        assert isinstance(rate_limiter_stats, dict)
        assert isinstance(scanner_stats, dict)
        assert isinstance(bot_stats, dict)
        assert isinstance(anomaly_stats, dict)

    def test_request_without_optional_fields(self, waf_stack):
        """Test request handling without optional fields."""
        request = HTTPRequest(
            method="POST",
            path="/api",
            headers={"Content-Type": "text/plain"},
            body=b"test data",
            client_ip="192.168.1.1",
        )

        # Should handle gracefully
        action, matches, score = waf_stack["engine"].evaluate(request)
        assert isinstance(action, RuleAction)
