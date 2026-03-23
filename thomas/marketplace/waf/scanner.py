"""
Vulnerability Scanner Detection

Detects automated vulnerability scanning tools and suspicious scanning patterns.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

from thomas.marketplace.waf._types import HTTPRequest, RuleAction


class ScannerDetector:
    """
    Detects vulnerability scanning attempts.

    Features:
    - User-agent analysis for known scanner signatures
    - Request pattern analysis
    - Sequential path enumeration detection
    - Parameter fuzzing detection
    - Honeypot path triggers
    - Scanner fingerprinting
    - Auto-ban on detection
    """

    # Known scanner user-agent signatures
    SCANNER_SIGNATURES = [
        "acunetix",
        "nessus",
        "openvas",
        "burp",
        "nikto",
        "masscan",
        "sqlmap",
        "metasploit",
        "nmap",
        "zap",
        "qualys",
        "tenable",
        "fortify",
        "checkmarx",
        "coverity",
        "veracode",
    ]

    # Honeypot paths that indicate scanning
    HONEYPOT_PATHS = [
        "/admin",
        "/wp-admin",
        "/administrator",
        ".env",
        "/.env",
        "/.git",
        "/.git/config",
        "/.gitignore",
        "/config.php",
        "/web.config",
        "/.aws",
        "/.aws/credentials",
        "/.ssh",
        "/.ssh/id_rsa",
        "/database.yml",
        "/config/database.yml",
        "/.env.local",
    ]

    def __init__(self) -> None:
        """Initialize scanner detector."""
        self.request_history: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
        self.detected_scanners: set[str] = set()
        self.honeypot_triggers: dict[str, int] = defaultdict(int)
        self.auto_ban_threshold: int = 3
        self.logger = logging.getLogger(__name__)

    def is_scanner(self, request: HTTPRequest) -> tuple[bool, str]:
        """
        Detect if request is from vulnerability scanner.

        Args:
            request: HTTP request

        Returns:
            Tuple of (is_scanner, scanner_type)
        """
        # Check user-agent
        user_agent = request.user_agent.lower()

        for signature in self.SCANNER_SIGNATURES:
            if signature in user_agent:
                self.detected_scanners.add(request.client_ip)
                self.logger.warning(f"Scanner detected from {request.client_ip}: {signature}")
                return (True, signature)

        # Check for suspicious patterns
        is_pattern_scan = self._detect_scanning_pattern(request)
        if is_pattern_scan:
            return (True, "pattern_scan")

        # Check for honeypot path access
        if self._is_honeypot_path(request):
            self.honeypot_triggers[request.client_ip] += 1
            if self.honeypot_triggers[request.client_ip] >= self.auto_ban_threshold:
                self.detected_scanners.add(request.client_ip)
                self.logger.warning(f"Scanner auto-detected from {request.client_ip} via honeypot triggers")
                return (True, "honeypot_trigger")

        return (False, "")

    def _detect_scanning_pattern(self, request: HTTPRequest) -> bool:
        """
        Detect scanning patterns in requests.

        Args:
            request: HTTP request

        Returns:
            True if scanning pattern detected
        """
        ip = request.client_ip

        # Record request
        self.request_history[ip].append((datetime.utcnow(), request.path))

        # Clean old entries (older than 5 minutes)
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        self.request_history[ip] = [(ts, path) for ts, path in self.request_history[ip] if ts > cutoff]

        # Check for high request rate on different paths
        if len(self.request_history[ip]) > 20:
            # Check if paths are different
            paths = [path for _, path in self.request_history[ip]]
            unique_paths = set(paths)

            if len(unique_paths) > 15:
                # Likely path enumeration scanning
                self.logger.warning(
                    f"Path enumeration scanning detected from {ip}: {len(unique_paths)} unique paths in 5 minutes"
                )
                return True

        # Check for parameter fuzzing patterns
        if len(self.request_history[ip]) > 10:
            for _, path in self.request_history[ip]:
                # Look for patterns like ?param=<test>, ?param=<test2>, etc.
                if re.search(r"\?.*=.*[0-9]{3,}", path):
                    if self._has_fuzzing_pattern(paths):
                        self.logger.warning(f"Parameter fuzzing detected from {ip}")
                        return True

        return False

    def _has_fuzzing_pattern(self, paths: list[str]) -> bool:
        """
        Check if paths show fuzzing patterns.

        Args:
            paths: List of request paths

        Returns:
            True if fuzzing pattern detected
        """
        # Simple pattern: multiple requests with similar structure but different parameter values
        param_patterns = defaultdict(int)

        for path in paths:
            # Extract parameter pattern (remove values)
            pattern = re.sub(r"=\d+", "=*", path)
            pattern = re.sub(r"=\w+", "=*", pattern)
            param_patterns[pattern] += 1

        # If many requests follow same parameter pattern with different values
        for pattern, count in param_patterns.items():
            if count > 5:
                return True

        return False

    def _is_honeypot_path(self, request: HTTPRequest) -> bool:
        """
        Check if request accesses honeypot path.

        Args:
            request: HTTP request

        Returns:
            True if honeypot path accessed
        """
        path = request.path.lower()

        for honeypot in self.HONEYPOT_PATHS:
            if path.endswith(honeypot.lower()):
                self.logger.info(f"Honeypot path accessed from {request.client_ip}: {honeypot}")
                return True

        return False

    def get_scanner_action(self, request: HTTPRequest) -> tuple[RuleAction, str]:
        """
        Get recommended action for scanner detection.

        Args:
            request: HTTP request

        Returns:
            Tuple of (action, reason)
        """
        is_scan, scan_type = self.is_scanner(request)

        if not is_scan:
            return (RuleAction.ALLOW, "")

        if scan_type == "honeypot_trigger":
            return (
                RuleAction.BLOCK,
                f"Honeypot access detected ({self.honeypot_triggers[request.client_ip]} attempts)",
            )

        if scan_type in ["acunetix", "nessus", "openvas", "burp"]:
            return (
                RuleAction.BLOCK,
                f"Known vulnerability scanner detected: {scan_type}",
            )

        if scan_type == "pattern_scan":
            return (
                RuleAction.CHALLENGE,
                "Suspicious scanning pattern detected",
            )

        return (
            RuleAction.LOG,
            f"Potential scanner detected: {scan_type}",
        )

    def fingerprint_scanner(self, request: HTTPRequest) -> dict[str, str]:
        """
        Fingerprint scanner based on request characteristics.

        Args:
            request: HTTP request

        Returns:
            Dictionary with scanner fingerprint info
        """
        fingerprint = {
            "user_agent": request.user_agent,
            "method": request.method,
            "headers": ",".join(request.headers.keys()),
        }

        # Try to identify specific scanner
        user_agent_lower = request.user_agent.lower()

        for signature in self.SCANNER_SIGNATURES:
            if signature in user_agent_lower:
                fingerprint["identified_scanner"] = signature
                break

        # Check for unusual headers
        suspicious_headers = []
        for header_name in request.headers.keys():
            if header_name.lower() in [
                "x-scanner",
                "x-burp-request-id",
                "x-acunetix",
            ]:
                suspicious_headers.append(header_name)

        if suspicious_headers:
            fingerprint["suspicious_headers"] = ",".join(suspicious_headers)

        return fingerprint

    def is_detected_scanner(self, ip_address: str) -> bool:
        """
        Check if IP has been identified as scanner.

        Args:
            ip_address: IP address

        Returns:
            True if detected scanner, False otherwise
        """
        return ip_address in self.detected_scanners

    def add_detected_scanner(self, ip_address: str) -> None:
        """
        Manually mark IP as scanner.

        Args:
            ip_address: IP address to mark
        """
        self.detected_scanners.add(ip_address)

    def remove_detected_scanner(self, ip_address: str) -> None:
        """
        Remove IP from detected scanners.

        Args:
            ip_address: IP address to remove
        """
        self.detected_scanners.discard(ip_address)

    def get_stats(self) -> dict[str, int]:
        """
        Get scanner detection statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            "detected_scanners": len(self.detected_scanners),
            "ips_under_observation": len(self.request_history),
            "honeypot_triggers_total": sum(self.honeypot_triggers.values()),
        }
