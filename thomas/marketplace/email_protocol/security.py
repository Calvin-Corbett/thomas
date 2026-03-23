"""
Email security implementations.

Provides SPF checking, DKIM signing basics, DMARC evaluation,
phishing detection, and attachment risk analysis.
"""

import base64
import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from thomas.marketplace.email_protocol._types import Attachment, EmailMessage


class SPFResult(str, Enum):
    """SPF check result."""

    PASS = "pass"
    FAIL = "fail"
    SOFTFAIL = "softfail"
    NEUTRAL = "neutral"
    NONE = "none"
    TEMPERROR = "temperror"
    PERMERROR = "permerror"


class DMARCResult(str, Enum):
    """DMARC check result."""

    PASS = "pass"
    FAIL = "fail"
    NEUTRAL = "neutral"
    NONE = "none"


@dataclass
class SPFRecord:
    """Represents parsed SPF record.

    Attributes:
        domain: Domain the record is for
        mechanisms: List of SPF mechanisms
        default_policy: Default policy (pass/fail)
    """

    domain: str
    mechanisms: list[dict[str, str]]
    default_policy: SPFResult = SPFResult.NEUTRAL


@dataclass
class AuthenticationResult:
    """Email authentication check result.

    Attributes:
        spf_result: SPF check result
        dkim_result: DKIM check result
        dmarc_result: DMARC check result
        summary: Overall assessment
    """

    spf_result: SPFResult = SPFResult.NONE
    dkim_result: str | None = None
    dmarc_result: DMARCResult = DMARCResult.NONE
    summary: str = ""


class SPFChecker:
    """SPF (Sender Policy Framework) implementation."""

    @staticmethod
    def parse_spf_record(spf_text: str) -> SPFRecord:
        """Parse SPF TXT record.

        Format: "v=spf1 ip4:192.168.0.0/24 include:example.com -all"

        Args:
            spf_text: SPF record text

        Returns:
            Parsed SPFRecord
        """
        parts = spf_text.split()
        domain = ""
        mechanisms = []
        default_policy = SPFResult.NEUTRAL

        for part in parts:
            if part.startswith("v="):
                continue

            qualifier = "+"
            if part[0] in ("+-~?"):
                qualifier = part[0]
                part = part[1:]

            if ":" in part:
                mechanism_type, mechanism_value = part.split(":", 1)
            else:
                mechanism_type = part
                mechanism_value = ""

            if mechanism_type == "all":
                default_policy = SPFResult.PASS if qualifier == "+" else SPFResult.FAIL

            mechanisms.append(
                {
                    "type": mechanism_type,
                    "value": mechanism_value,
                    "qualifier": qualifier,
                }
            )

        return SPFRecord(domain, mechanisms, default_policy)

    @staticmethod
    def check_spf(
        sender_ip: str,
        sender_domain: str,
        spf_record: SPFRecord | None,
    ) -> SPFResult:
        """Check if sender IP passes SPF policy.

        Args:
            sender_ip: IP address of sender
            sender_domain: Domain in From header
            spf_record: Parsed SPF record

        Returns:
            SPF check result
        """
        if not spf_record:
            return SPFResult.NONE

        for mechanism in spf_record.mechanisms:
            mech_type = mechanism["type"]
            mech_value = mechanism["value"]
            qualifier = mechanism["qualifier"]

            if mech_type == "ip4":
                if SPFChecker._ip_in_cidr(sender_ip, mech_value):
                    return SPFResult.PASS if qualifier == "+" else SPFResult.FAIL

            elif mech_type == "ip6":
                if SPFChecker._ipv6_in_cidr(sender_ip, mech_value):
                    return SPFResult.PASS if qualifier == "+" else SPFResult.FAIL

            elif mech_type == "mx":
                if SPFChecker._check_mx_match(sender_domain, mech_value):
                    return SPFResult.PASS if qualifier == "+" else SPFResult.FAIL

            elif mech_type == "a":
                if SPFChecker._check_a_record(sender_domain, sender_ip):
                    return SPFResult.PASS if qualifier == "+" else SPFResult.FAIL

            elif mech_type == "include":
                return SPFResult.PASS if qualifier == "+" else SPFResult.FAIL

        return spf_record.default_policy

    @staticmethod
    def _ip_in_cidr(ip: str, cidr: str) -> bool:
        """Check if IP is in CIDR range."""
        try:
            import ipaddress

            ip_obj = ipaddress.IPv4Address(ip)
            network = ipaddress.IPv4Network(cidr, strict=False)
            return ip_obj in network
        except ImportError:
            return False

    @staticmethod
    def _ipv6_in_cidr(ip: str, cidr: str) -> bool:
        """Check if IPv6 is in CIDR range."""
        try:
            import ipaddress

            ip_obj = ipaddress.IPv6Address(ip)
            network = ipaddress.IPv6Network(cidr, strict=False)
            return ip_obj in network
        except ImportError:
            return False

    @staticmethod
    def _check_mx_match(domain: str, mx_pattern: str) -> bool:
        """Check if domain MX matches pattern (simulated)."""
        return mx_pattern == "" or mx_pattern in domain

    @staticmethod
    def _check_a_record(domain: str, sender_ip: str) -> bool:
        """Check if sender IP matches domain A record (simulated)."""
        return True


class DKIMSigner:
    """DKIM (DomainKeys Identified Mail) signing."""

    @staticmethod
    def canonicalize_headers(headers: dict[str, str], mode: str = "relaxed") -> str:
        """Canonicalize headers for DKIM signature.

        Args:
            headers: Header dictionary
            mode: Canonicalization mode (simple or relaxed)

        Returns:
            Canonicalized header string
        """
        canonical = []

        for name, value in headers.items():
            if mode == "relaxed":
                name = name.lower().strip()
                value = re.sub(r"\s+", " ", value.strip())
            else:
                name = name.lower()

            canonical.append(f"{name}:{value}")

        if mode == "relaxed":
            return "\r\n".join(canonical) + "\r\n"
        return "\r\n".join(canonical)

    @staticmethod
    def canonicalize_body(body: str, mode: str = "relaxed") -> str:
        """Canonicalize body for DKIM signature.

        Args:
            body: Message body
            mode: Canonicalization mode

        Returns:
            Canonicalized body
        """
        if mode == "relaxed":
            lines = body.split("\r\n")
            lines = [re.sub(r"\s+$", "", line) for line in lines]
            lines = [line for line in lines if line.strip()]
            return "\r\n".join(lines) + "\r\n"
        return body

    @staticmethod
    def generate_signature_base(
        headers: dict[str, str],
        body: str,
        domain: str,
        selector: str,
    ) -> str:
        """Generate data to be signed.

        Args:
            headers: Email headers
            body: Email body
            domain: Signing domain
            selector: DKIM selector

        Returns:
            Base64 encoded signature (simulated)
        """
        canonical_headers = DKIMSigner.canonicalize_headers(headers)
        canonical_body = DKIMSigner.canonicalize_body(body)

        data_to_sign = canonical_headers + canonical_body

        signature = hashlib.sha256(data_to_sign.encode()).digest()
        return base64.b64encode(signature).decode()


class DMARCEvaluator:
    """DMARC (Domain-based Message Authentication) policy evaluation."""

    @staticmethod
    def parse_dmarc_policy(dmarc_record: str) -> dict[str, str]:
        """Parse DMARC policy record.

        Format: "v=DMARC1; p=quarantine; rua=mailto:reports@example.com"

        Args:
            dmarc_record: DMARC policy text

        Returns:
            Dictionary of policy tags
        """
        policy = {
            "version": "DMARC1",
            "policy": "none",
            "subdomain_policy": None,
            "alignment": "relaxed",
            "dkim_alignment": "relaxed",
            "spf_alignment": "relaxed",
            "percentage": "100",
        }

        parts = dmarc_record.split(";")
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip().lower()
                value = value.strip()

                if key == "v":
                    policy["version"] = value
                elif key == "p":
                    policy["policy"] = value
                elif key == "sp":
                    policy["subdomain_policy"] = value
                elif key == "adkim":
                    policy["dkim_alignment"] = value
                elif key == "aspf":
                    policy["spf_alignment"] = value
                elif key == "pct":
                    policy["percentage"] = value

        return policy

    @staticmethod
    def evaluate_dmarc(
        dkim_pass: bool,
        spf_pass: bool,
        dkim_aligned: bool,
        spf_aligned: bool,
        policy: dict[str, str],
    ) -> DMARCResult:
        """Evaluate DMARC policy.

        Args:
            dkim_pass: Whether DKIM passed
            spf_pass: Whether SPF passed
            dkim_aligned: Whether DKIM is aligned
            spf_aligned: Whether SPF is aligned
            policy: DMARC policy

        Returns:
            DMARC evaluation result
        """
        alignment_mode = policy.get("alignment", "relaxed")

        dkim_aligned = dkim_pass and (alignment_mode == "relaxed" or dkim_aligned)
        spf_aligned = spf_pass and (alignment_mode == "relaxed" or spf_aligned)

        if dkim_aligned or spf_aligned:
            return DMARCResult.PASS

        return DMARCResult.FAIL


class PhishingDetector:
    """Phishing email detection."""

    def __init__(self) -> None:
        """Initialize phishing detector."""
        self.suspicious_domains: set[str] = {
            "gmail.com",
            "yahoo.com",
            "outlook.com",
            "aol.com",
            "protonmail.com",
            "tutanota.com",
        }

    def detect_phishing_urls(self, message: EmailMessage) -> list[str]:
        """Find potentially phishing URLs in message.

        Args:
            message: Message to analyze

        Returns:
            List of suspicious URLs
        """
        suspicious = []

        body = message.text_body or ""
        html_body = message.html_body or ""

        full_text = body + html_body

        urls = re.findall(r"https?://[^\s<>\"]+", full_text)

        for url in urls:
            if self._is_suspicious_url(url, message):
                suspicious.append(url)

        return suspicious

    def _is_suspicious_url(self, url: str, message: EmailMessage) -> bool:
        """Check if URL is suspicious.

        Args:
            url: URL to check
            message: Message context

        Returns:
            True if URL appears suspicious
        """
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            if not message.envelope.from_addr:
                return False

            sender_domain = message.envelope.from_addr.address.split("@")[1].lower()

            if domain != sender_domain and self._is_homograph(domain, sender_domain):
                return True

            if any(domain == sus_domain for sus_domain in self.suspicious_domains):
                return True

            if parsed.scheme == "http" and domain.endswith(".com"):
                return True

        except ImportError:
            pass

        return False

    @staticmethod
    def _is_homograph(url_domain: str, sender_domain: str) -> bool:
        """Check if domains are homographs (visually similar).

        Args:
            url_domain: Domain in URL
            sender_domain: Domain in sender address

        Returns:
            True if domains appear to be homographs
        """
        if url_domain == sender_domain:
            return False

        url_parts = url_domain.split(".")
        sender_parts = sender_domain.split(".")

        if len(url_parts) != len(sender_parts):
            return False

        similarity_count = sum(1 for u, s in zip(url_parts, sender_parts) if u[0] == s[0] and u[-1] == s[-1])

        return similarity_count >= len(url_parts) - 1


class AttachmentAnalyzer:
    """Analyze attachments for security risks."""

    DANGEROUS_EXTENSIONS = {
        ".exe",
        ".com",
        ".bat",
        ".cmd",
        ".scr",
        ".vbs",
        ".js",
        ".jar",
        ".zip",
        ".rar",
        ".7z",
        ".dll",
        ".sys",
    }

    SUSPICIOUS_EXTENSIONS = {
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".pdf",
        ".rtf",
        ".txt",
        ".html",
    }

    @staticmethod
    def analyze_attachment(attachment: Attachment) -> dict[str, any]:
        """Analyze attachment for risks.

        Args:
            attachment: Attachment to analyze

        Returns:
            Dictionary with risk assessment
        """
        filename = attachment.filename.lower()
        _, ext = filename.rsplit(".", 1) if "." in filename else ("", "")
        ext = "." + ext if ext else ""

        risk_score = 0
        warnings = []

        if ext in AttachmentAnalyzer.DANGEROUS_EXTENSIONS:
            risk_score += 100
            warnings.append(f"Dangerous file type: {ext}")

        if ext in AttachmentAnalyzer.SUSPICIOUS_EXTENSIONS:
            risk_score += 30
            warnings.append(f"Potentially suspicious file type: {ext}")

        if attachment.size > 10 * 1024 * 1024:
            risk_score += 10
            warnings.append("Large file size (>10 MB)")

        if len(filename) > 100:
            risk_score += 5
            warnings.append("Suspiciously long filename")

        return {
            "risk_score": min(risk_score, 100),
            "is_dangerous": risk_score >= 100,
            "warnings": warnings,
            "recommendation": AttachmentAnalyzer._get_recommendation(risk_score),
        }

    @staticmethod
    def _get_recommendation(risk_score: int) -> str:
        """Get recommendation based on risk score.

        Args:
            risk_score: Risk score (0-100+)

        Returns:
            Recommendation string
        """
        if risk_score >= 100:
            return "Do not open - likely malicious"
        elif risk_score >= 30:
            return "Be cautious - verify sender and content"
        elif risk_score >= 10:
            return "Low risk - safe to open"
        else:
            return "No known risks"
