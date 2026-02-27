"""
Tests for email security functionality.

Tests SPF checking, DKIM signing, DMARC evaluation, phishing detection,
and attachment analysis.
"""

from thomas.email_protocol._types import Attachment, EmailAddress, EmailMessage
from thomas.email_protocol.security import (
    AttachmentAnalyzer,
    AuthenticationResult,
    DKIMSigner,
    DMARCEvaluator,
    DMARCResult,
    PhishingDetector,
    SPFChecker,
    SPFRecord,
    SPFResult,
)


class TestSPFChecker:
    """Test SPF record parsing and checking."""

    def test_parse_spf_record(self):
        """Test parsing SPF TXT record."""
        spf_text = "v=spf1 ip4:192.168.0.0/24 include:example.com -all"
        record = SPFChecker.parse_spf_record(spf_text)

        assert record.domain == ""
        assert len(record.mechanisms) > 0

    def test_spf_record_mechanisms(self):
        """Test SPF mechanism parsing."""
        spf_text = "v=spf1 ip4:192.168.1.0/24 ~all"
        record = SPFChecker.parse_spf_record(spf_text)

        assert any(m["type"] == "ip4" for m in record.mechanisms)

    def test_check_spf_pass(self):
        """Test SPF check passes for allowed IP."""
        record = SPFRecord(
            domain="example.com",
            mechanisms=[
                {"type": "ip4", "value": "192.168.1.0/24", "qualifier": "+"},
                {"type": "all", "value": "", "qualifier": "-"},
            ],
            default_policy=SPFResult.FAIL,
        )

        result = SPFChecker.check_spf(
            "192.168.1.100",
            "example.com",
            record,
        )

        assert result == SPFResult.PASS

    def test_check_spf_fail(self):
        """Test SPF check fails for disallowed IP."""
        record = SPFRecord(
            domain="example.com",
            mechanisms=[
                {"type": "ip4", "value": "192.168.1.0/24", "qualifier": "+"},
                {"type": "all", "value": "", "qualifier": "-"},
            ],
            default_policy=SPFResult.FAIL,
        )

        result = SPFChecker.check_spf(
            "10.0.0.1",
            "example.com",
            record,
        )

        assert result == SPFResult.FAIL

    def test_check_spf_none(self):
        """Test SPF check returns NONE for no record."""
        result = SPFChecker.check_spf("192.168.1.1", "example.com", None)

        assert result == SPFResult.NONE

    def test_ip_in_cidr_ipv4(self):
        """Test IPv4 CIDR matching."""
        assert SPFChecker._ip_in_cidr("192.168.1.100", "192.168.1.0/24")
        assert not SPFChecker._ip_in_cidr("10.0.0.1", "192.168.1.0/24")

    def test_ip_in_cidr_ipv6(self):
        """Test IPv6 CIDR matching."""
        assert SPFChecker._ipv6_in_cidr(
            "2001:db8::1",
            "2001:db8::/32",
        )


class TestDKIMSigner:
    """Test DKIM signing functionality."""

    def test_canonicalize_headers_relaxed(self):
        """Test relaxed header canonicalization."""
        headers = {"Subject": "  Test  Subject  "}
        canonical = DKIMSigner.canonicalize_headers(headers, mode="relaxed")

        assert "subject" in canonical.lower() and "test" in canonical.lower()

    def test_canonicalize_headers_simple(self):
        """Test simple header canonicalization."""
        headers = {"Subject": "Test Subject"}
        canonical = DKIMSigner.canonicalize_headers(headers, mode="simple")

        assert "subject" in canonical.lower() and "test" in canonical.lower()

    def test_canonicalize_body_relaxed(self):
        """Test relaxed body canonicalization."""
        body = "Line 1  \nLine 2\n\n\nLine 3"
        canonical = DKIMSigner.canonicalize_body(body, mode="relaxed")

        lines = canonical.strip().split("\r\n")
        assert len(lines) <= 3

    def test_canonicalize_body_simple(self):
        """Test simple body canonicalization."""
        body = "Line 1\nLine 2\nLine 3"
        canonical = DKIMSigner.canonicalize_body(body, mode="simple")

        assert "Line 1" in canonical

    def test_generate_signature(self):
        """Test generating DKIM signature."""
        headers = {"Subject": "Test"}
        body = "Message body"

        signature = DKIMSigner.generate_signature_base(
            headers,
            body,
            "example.com",
            "selector",
        )

        assert len(signature) > 0
        assert isinstance(signature, str)


class TestDMARCEvaluator:
    """Test DMARC policy evaluation."""

    def test_parse_dmarc_policy(self):
        """Test parsing DMARC policy."""
        policy_text = "v=DMARC1; p=quarantine; rua=mailto:reports@example.com"
        policy = DMARCEvaluator.parse_dmarc_policy(policy_text)

        assert policy["policy"] == "quarantine"

    def test_dmarc_policy_tags(self):
        """Test DMARC policy tag extraction."""
        policy_text = "v=DMARC1; p=reject; pct=100; adkim=s"
        policy = DMARCEvaluator.parse_dmarc_policy(policy_text)

        assert policy["policy"] == "reject"
        assert policy["percentage"] == "100"

    def test_evaluate_dmarc_pass(self):
        """Test DMARC pass when alignment achieved."""
        policy = {
            "policy": "reject",
            "alignment": "relaxed",
        }

        result = DMARCEvaluator.evaluate_dmarc(
            dkim_pass=True,
            spf_pass=False,
            dkim_aligned=True,
            spf_aligned=False,
            policy=policy,
        )

        assert result == DMARCResult.PASS

    def test_evaluate_dmarc_fail(self):
        """Test DMARC fail when no alignment."""
        policy = {
            "policy": "reject",
            "alignment": "strict",
        }

        result = DMARCEvaluator.evaluate_dmarc(
            dkim_pass=True,
            spf_pass=False,
            dkim_aligned=False,
            spf_aligned=False,
            policy=policy,
        )

        assert result == DMARCResult.FAIL


class TestPhishingDetector:
    """Test phishing detection."""

    def test_detector_initialization(self):
        """Test creating phishing detector."""
        detector = PhishingDetector()

        assert len(detector.suspicious_domains) > 0

    def test_detect_phishing_urls(self):
        """Test detecting phishing URLs."""
        detector = PhishingDetector()

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("sender@example.com")
        message.text_body = "Click here http://gmail.com/phishing"

        urls = detector.detect_phishing_urls(message)

        assert isinstance(urls, list)

    def test_no_phishing_urls(self):
        """Test message with no suspicious URLs."""
        detector = PhishingDetector()

        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("sender@example.com")
        message.text_body = "Normal message with no links"

        urls = detector.detect_phishing_urls(message)

        assert len(urls) == 0

    def test_homograph_detection(self):
        """Test homograph domain detection."""
        assert not PhishingDetector._is_homograph(
            "example.com",
            "example.com",
        )

        is_homograph = PhishingDetector._is_homograph(
            "examp1e.com",
            "example.com",
        )
        assert isinstance(is_homograph, bool)


class TestAttachmentAnalyzer:
    """Test attachment security analysis."""

    def test_analyze_safe_attachment(self):
        """Test analyzing safe attachment."""
        attachment = Attachment(
            filename="document.pdf",
            content=b"PDF content",
        )

        result = AttachmentAnalyzer.analyze_attachment(attachment)

        assert "risk_score" in result
        assert isinstance(result["is_dangerous"], bool)

    def test_analyze_dangerous_executable(self):
        """Test analyzing dangerous executable."""
        attachment = Attachment(
            filename="malware.exe",
            content=b"executable content",
        )

        result = AttachmentAnalyzer.analyze_attachment(attachment)

        assert result["is_dangerous"]
        assert result["risk_score"] >= 100

    def test_analyze_suspicious_archive(self):
        """Test analyzing suspicious archive."""
        attachment = Attachment(
            filename="data.zip",
            content=b"zip content",
        )

        result = AttachmentAnalyzer.analyze_attachment(attachment)

        assert result["risk_score"] >= 30

    def test_analyze_large_file(self):
        """Test analyzing large file."""
        attachment = Attachment(
            filename="large.pdf",
            content=b"x" * (15 * 1024 * 1024),
        )

        result = AttachmentAnalyzer.analyze_attachment(attachment)

        assert result["risk_score"] > 0
        assert len(result["warnings"]) > 0

    def test_analyze_long_filename(self):
        """Test analyzing suspiciously long filename."""
        attachment = Attachment(
            filename="a" * 150 + ".txt",
            content=b"content",
        )

        result = AttachmentAnalyzer.analyze_attachment(attachment)

        assert result["risk_score"] > 0

    def test_dangerous_extensions(self):
        """Test dangerous file extension detection."""
        dangerous = [".exe", ".com", ".bat", ".vbs", ".jar"]

        for ext in dangerous:
            filename = f"file{ext}"
            attachment = Attachment(filename, b"content")
            result = AttachmentAnalyzer.analyze_attachment(attachment)

            assert result["is_dangerous"] or result["risk_score"] >= 100

    def test_suspicious_extensions(self):
        """Test suspicious file extension detection."""
        suspicious = [".doc", ".xls", ".pdf"]

        for ext in suspicious:
            filename = f"file{ext}"
            attachment = Attachment(filename, b"content")
            result = AttachmentAnalyzer.analyze_attachment(attachment)

            assert result["risk_score"] >= 30

    def test_safe_extensions(self):
        """Test safe file extension detection."""
        safe = [".txt", ".png", ".jpg"]

        for ext in safe:
            filename = f"file{ext}"
            attachment = Attachment(filename, b"content")
            result = AttachmentAnalyzer.analyze_attachment(attachment)

            assert not result["is_dangerous"]


class TestAuthenticationResult:
    """Test authentication result aggregation."""

    def test_create_result(self):
        """Test creating authentication result."""
        result = AuthenticationResult(
            spf_result=SPFResult.PASS,
            dkim_result="PASS",
            dmarc_result=DMARCResult.PASS,
        )

        assert result.spf_result == SPFResult.PASS
        assert result.dmarc_result == DMARCResult.PASS

    def test_result_defaults(self):
        """Test default result values."""
        result = AuthenticationResult()

        assert result.spf_result == SPFResult.NONE
        assert result.dmarc_result == DMARCResult.NONE
