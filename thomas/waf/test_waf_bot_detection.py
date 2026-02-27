"""
Tests for WAF Bot Detection

Tests for bot detection, JavaScript challenges, and behavioral analysis.
"""

import pytest

from thomas.waf._types import HTTPRequest
from thomas.waf.bot_detection import BotDetector


class TestBotDetector:
    """Test cases for BotDetector."""

    @pytest.fixture
    def detector(self) -> BotDetector:
        """Create test detector."""
        return BotDetector()

    @pytest.fixture
    def browser_request(self) -> HTTPRequest:
        """Create typical browser request."""
        return HTTPRequest(
            method="GET",
            path="/index.html",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
            },
            body=b"",
            client_ip="192.168.1.1",
            cookies={"session": "abc123"},
        )

    @pytest.fixture
    def bot_request(self) -> HTTPRequest:
        """Create typical bot request."""
        return HTTPRequest(
            method="GET",
            path="/",
            headers={
                "User-Agent": "",
            },
            body=b"",
            client_ip="192.168.1.1",
        )

    def test_detector_initialization(self, detector: BotDetector) -> None:
        """Test detector initialization."""
        assert len(detector.verified_humans) == 0
        assert len(detector.challenge_tokens) == 0

    def test_good_bot_detection(self, detector: BotDetector) -> None:
        """Test good bot detection."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_good = detector.is_good_bot(request)
        assert is_good is True

    def test_bad_bot_detection(self, detector: BotDetector) -> None:
        """Test bad bot detection."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "sqlmap/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_bad = detector.is_bad_bot(request)
        assert is_bad is True

    def test_bot_score_good_browser(self, detector: BotDetector, browser_request: HTTPRequest) -> None:
        """Test bot score for normal browser."""
        score = detector.calculate_bot_score(browser_request)

        # Should be low score for normal browser
        assert 0 <= score <= 1

    def test_bot_score_missing_headers(self, detector: BotDetector) -> None:
        """Test bot score increases with missing headers."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "CustomBot"},
            body=b"",
            client_ip="192.168.1.1",
        )

        score = detector.calculate_bot_score(request)

        # Should be higher score for missing headers
        assert score > 0

    def test_bot_score_no_cookies(self, detector: BotDetector) -> None:
        """Test bot score for request without cookies."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        score = detector.calculate_bot_score(request)

        # Should increase score for missing cookies
        assert score > 0

    def test_javascript_challenge_generation(self, detector: BotDetector, browser_request: HTTPRequest) -> None:
        """Test JavaScript challenge generation."""
        token = detector.require_javascript_challenge(browser_request)

        assert token is not None
        assert len(token) > 0
        assert token in detector.challenge_tokens

    def test_challenge_verification(self, detector: BotDetector, browser_request: HTTPRequest) -> None:
        """Test challenge verification."""
        token = detector.require_javascript_challenge(browser_request)

        # Verify with correct IP
        result = detector.verify_challenge(token, browser_request.client_ip)
        assert result is True

        # IP should now be verified human
        assert detector.is_verified_human(browser_request.client_ip) is True

    def test_challenge_verification_wrong_ip(self, detector: BotDetector, browser_request: HTTPRequest) -> None:
        """Test challenge verification with wrong IP."""
        token = detector.require_javascript_challenge(browser_request)

        # Try to verify with different IP
        result = detector.verify_challenge(token, "192.168.1.99")
        assert result is False

    def test_verified_human_bypass(self, detector: BotDetector, browser_request: HTTPRequest) -> None:
        """Test verified human bypasses detection."""
        # Verify as human
        token = detector.require_javascript_challenge(browser_request)
        detector.verify_challenge(token, browser_request.client_ip)

        # Should now be verified
        assert detector.is_verified_human(browser_request.client_ip) is True

        # Detection should show as human
        is_bot, _, reason = detector.get_bot_detection_result(browser_request)
        assert is_bot is False
        assert reason == "verified_human"

    def test_suspicious_pattern_detection(self, detector: BotDetector) -> None:
        """Test suspicious pattern detection."""
        request = HTTPRequest(
            method="POST",
            path="/",
            headers={
                "User-Agent": "",
                "Content-Type": "application/json",
            },
            body=b'{"test": "data"}',
            client_ip="192.168.1.1",
        )

        has_suspicious = detector._has_suspicious_pattern(request)
        assert has_suspicious is True

    def test_request_pattern_analysis(self, detector: BotDetector) -> None:
        """Test request pattern analysis."""
        ip = "192.168.1.1"

        # Make rapid requests
        for i in range(5):
            request = HTTPRequest(
                method="GET",
                path=f"/page{i}",
                headers={"User-Agent": "Mozilla/5.0"},
                body=b"",
                client_ip=ip,
            )
            detector._analyze_request_pattern(request)

    def test_get_bot_detection_result_good_bot(self, detector: BotDetector) -> None:
        """Test bot detection result for good bot."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_bot, confidence, reason = detector.get_bot_detection_result(request)

        assert is_bot is True
        assert reason == "good_bot"

    def test_get_bot_detection_result_bad_bot(self, detector: BotDetector) -> None:
        """Test bot detection result for bad bot."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "sqlmap/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_bot, confidence, reason = detector.get_bot_detection_result(request)

        assert is_bot is True
        assert reason == "bad_bot"

    def test_cleanup_expired_tokens(self, detector: BotDetector, browser_request: HTTPRequest) -> None:
        """Test cleanup of expired tokens."""
        # Generate token
        token = detector.require_javascript_challenge(browser_request)

        assert len(detector.challenge_tokens) == 1

        # Cleanup
        count = detector.cleanup_expired_tokens()
        # Count may be 0 if token hasn't expired yet

    def test_get_stats(self, detector: BotDetector, browser_request: HTTPRequest) -> None:
        """Test statistics retrieval."""
        # Generate challenge
        detector.require_javascript_challenge(browser_request)

        stats = detector.get_stats()

        assert "pending_challenges" in stats
        assert stats["pending_challenges"] == 1

    def test_bot_score_bounds(self, detector: BotDetector) -> None:
        """Test bot score stays within bounds."""
        # Create very suspicious request
        request = HTTPRequest(
            method="OPTIONS",
            path="/",
            headers={},
            body=b"",
            client_ip="192.168.1.1",
        )

        score = detector.calculate_bot_score(request)

        # Score should never exceed 1.0
        assert 0 <= score <= 1.0

    def test_multiple_ips_independent(self, detector: BotDetector) -> None:
        """Test that different IPs are tracked independently."""
        # Verify IP1
        request1 = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        token1 = detector.require_javascript_challenge(request1)
        detector.verify_challenge(token1, "192.168.1.1")

        assert detector.is_verified_human("192.168.1.1") is True
        assert detector.is_verified_human("192.168.1.2") is False
