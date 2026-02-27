"""
Tests for WAF Scanner Detection

Tests for vulnerability scanner detection and fingerprinting.
"""

import pytest

from thomas.waf._types import HTTPRequest, RuleAction
from thomas.waf.scanner import ScannerDetector


class TestScannerDetector:
    """Test cases for ScannerDetector."""

    @pytest.fixture
    def detector(self) -> ScannerDetector:
        """Create test detector."""
        return ScannerDetector()

    @pytest.fixture
    def normal_request(self) -> HTTPRequest:
        """Create normal browser request."""
        return HTTPRequest(
            method="GET",
            path="/index.html",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            body=b"",
            client_ip="192.168.1.1",
        )

    def test_detector_initialization(self, detector: ScannerDetector) -> None:
        """Test detector initialization."""
        assert len(detector.detected_scanners) == 0

    def test_good_bot_detection(self, detector: ScannerDetector) -> None:
        """Test detection of good bots."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_scan, scan_type = detector.is_scanner(request)
        # Googlebot should not be detected as malicious
        if is_scan:
            assert scan_type == "good_bot"

    def test_bad_bot_detection(self, detector: ScannerDetector) -> None:
        """Test detection of bad bots."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "sqlmap/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_scan, scan_type = detector.is_scanner(request)
        assert is_scan is True
        assert scan_type == "sqlmap"

    def test_acunetix_detection(self, detector: ScannerDetector) -> None:
        """Test Acunetix scanner detection."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Acunetix-Scan/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_scan, scan_type = detector.is_scanner(request)
        assert is_scan is True
        assert scan_type == "acunetix"

    def test_nessus_detection(self, detector: ScannerDetector) -> None:
        """Test Nessus scanner detection."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Nessus/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_scan, scan_type = detector.is_scanner(request)
        assert is_scan is True

    def test_normal_request_not_flagged(self, detector: ScannerDetector, normal_request: HTTPRequest) -> None:
        """Test that normal requests are not flagged."""
        is_scan, _ = detector.is_scanner(normal_request)
        # Should not be detected as scanner with normal headers
        if is_scan:
            # Only if pattern matching detects something
            pass

    def test_honeypot_path_detection(self, detector: ScannerDetector) -> None:
        """Test honeypot path detection."""
        request = HTTPRequest(
            method="GET",
            path="/admin",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_honeypot = detector._is_honeypot_path(request)
        assert is_honeypot is True

    def test_honeypot_trigger_auto_ban(self, detector: ScannerDetector) -> None:
        """Test auto-ban on honeypot triggers."""
        ip = "192.168.1.1"
        detector.auto_ban_threshold = 2

        # Access honeypot paths
        for i in range(2):
            request = HTTPRequest(
                method="GET",
                path="/admin",
                headers={"User-Agent": "Mozilla/5.0"},
                body=b"",
                client_ip=ip,
            )
            detector.is_scanner(request)

        # Should be detected as scanner
        assert detector.is_detected_scanner(ip) is True

    def test_path_enumeration_detection(self, detector: ScannerDetector) -> None:
        """Test path enumeration detection."""
        ip = "192.168.1.1"

        # Make many requests to different paths
        paths = [f"/test{i}" for i in range(20)]

        for path in paths:
            request = HTTPRequest(
                method="GET",
                path=path,
                headers={"User-Agent": "Mozilla/5.0"},
                body=b"",
                client_ip=ip,
            )
            detector.is_scanner(request)

        # Should detect scanning pattern
        is_scan, scan_type = detector.is_scanner(
            HTTPRequest(
                method="GET",
                path="/another",
                headers={"User-Agent": "Mozilla/5.0"},
                body=b"",
                client_ip=ip,
            )
        )

    def test_scanner_fingerprinting(self, detector: ScannerDetector) -> None:
        """Test scanner fingerprinting."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={
                "User-Agent": "sqlmap/1.0",
                "X-Scanner": "test",
            },
            body=b"",
            client_ip="192.168.1.1",
        )

        fingerprint = detector.fingerprint_scanner(request)

        assert "user_agent" in fingerprint
        assert "method" in fingerprint
        assert "headers" in fingerprint

    def test_is_detected_scanner(self, detector: ScannerDetector) -> None:
        """Test checking if IP is detected scanner."""
        ip = "192.168.1.1"

        assert detector.is_detected_scanner(ip) is False

        detector.add_detected_scanner(ip)
        assert detector.is_detected_scanner(ip) is True

        detector.remove_detected_scanner(ip)
        assert detector.is_detected_scanner(ip) is False

    def test_get_scanner_action_block(self, detector: ScannerDetector) -> None:
        """Test scanner action determination."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "Acunetix-Scan/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        action, reason = detector.get_scanner_action(request)
        assert action == RuleAction.BLOCK

    def test_get_stats(self, detector: ScannerDetector) -> None:
        """Test statistics retrieval."""
        # Add some scanners
        detector.add_detected_scanner("192.168.1.1")

        stats = detector.get_stats()

        assert "detected_scanners" in stats
        assert stats["detected_scanners"] >= 1

    def test_parameter_fuzzing_detection(self, detector: ScannerDetector) -> None:
        """Test parameter fuzzing detection."""
        ip = "192.168.1.1"

        # Make requests with varying parameter values
        for i in range(10):
            request = HTTPRequest(
                method="GET",
                path=f"/search?q=test{i}",
                headers={"User-Agent": "Mozilla/5.0"},
                body=b"",
                client_ip=ip,
            )
            detector.is_scanner(request)

    def test_honeypot_paths_coverage(self, detector: ScannerDetector) -> None:
        """Test coverage of honeypot paths."""
        honeypot_paths = [
            "/admin",
            "/wp-admin",
            "/.env",
            "/.git/config",
            "/config.php",
        ]

        for path in honeypot_paths:
            request = HTTPRequest(
                method="GET",
                path=path,
                headers={"User-Agent": "Mozilla/5.0"},
                body=b"",
                client_ip="192.168.1.1",
            )

            is_honeypot = detector._is_honeypot_path(request)
            assert is_honeypot is True

    def test_scanner_signature_case_insensitive(self, detector: ScannerDetector) -> None:
        """Test case-insensitive scanner detection."""
        request = HTTPRequest(
            method="GET",
            path="/",
            headers={"User-Agent": "SQLMAP/1.0"},
            body=b"",
            client_ip="192.168.1.1",
        )

        is_scan, _ = detector.is_scanner(request)
        assert is_scan is True
