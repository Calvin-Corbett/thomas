"""
Bot Detection Module

Detect automated bots using JavaScript challenges, CAPTCHA triggers,
behavioral analysis, and bot signature detection.
"""

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from thomas.marketplace.waf._types import HTTPRequest


class BotDetector:
    """
    Detects and manages bot traffic.

    Features:
    - JavaScript challenge generation
    - CAPTCHA trigger logic
    - Known bot signature detection
    - Behavioral analysis
    - Good bot whitelist
    - Bot score calculation
    - Request pattern analysis
    """

    # Known good bot signatures
    GOOD_BOTS = [
        "googlebot",
        "bingbot",
        "slurp",
        "duckduckgo",
        "baiduspider",
        "yandex",
        "facebot",
        "twitterbot",
        "slrpbot",
        "linkedinbot",
        "whatsapp",
        "skype",
        "telegram",
    ]

    # Known bad bot signatures
    BAD_BOTS = [
        "sqlmap",
        "nikto",
        "nmap",
        "masscan",
        "nessus",
        "qualys",
        "acunetix",
        "burpsuite",
        "zap",
        "metasploit",
    ]

    def __init__(self) -> None:
        """Initialize bot detector."""
        self.challenge_tokens: dict[str, tuple[datetime, str]] = {}
        self.challenge_attempts: dict[str, int] = defaultdict(int)
        self.verified_humans: dict[str, datetime] = {}
        self.verified_bots: dict[str, str] = {}
        self.request_patterns: dict[str, list[dict]] = defaultdict(list)
        self.logger = logging.getLogger(__name__)

    def is_good_bot(self, request: HTTPRequest) -> bool:
        """
        Check if request is from known good bot.

        Args:
            request: HTTP request

        Returns:
            True if known good bot
        """
        user_agent = request.user_agent.lower()

        for bot_sig in self.GOOD_BOTS:
            if bot_sig in user_agent:
                return True

        return False

    def is_bad_bot(self, request: HTTPRequest) -> bool:
        """
        Check if request is from known bad bot.

        Args:
            request: HTTP request

        Returns:
            True if known bad bot
        """
        user_agent = request.user_agent.lower()

        for bot_sig in self.BAD_BOTS:
            if bot_sig in user_agent:
                return True

        return False

    def calculate_bot_score(self, request: HTTPRequest) -> float:
        """
        Calculate bot likelihood score (0-1, higher = more likely bot).

        Args:
            request: HTTP request

        Returns:
            Bot score
        """
        score = 0.0

        # Check user-agent
        user_agent = request.user_agent.lower()

        if not user_agent:
            score += 0.3

        if self.is_good_bot(request):
            return 0.0

        if self.is_bad_bot(request):
            return 1.0

        # Check for missing headers
        if not request.get_header("accept"):
            score += 0.15

        if not request.get_header("accept-language"):
            score += 0.15

        if not request.get_header("accept-encoding"):
            score += 0.15

        # Check for referer
        referer = request.get_header("referer")
        if not referer:
            score += 0.1

        # Check for cookies
        if not request.cookies:
            score += 0.15

        # Check for suspicious patterns
        if self._has_suspicious_pattern(request):
            score += 0.2

        # Check request history pattern
        pattern_score = self._analyze_request_pattern(request)
        score += pattern_score * 0.3

        return min(score, 1.0)

    def _has_suspicious_pattern(self, request: HTTPRequest) -> bool:
        """
        Check for suspicious request patterns.

        Args:
            request: HTTP request

        Returns:
            True if suspicious pattern detected
        """
        # Empty user-agent combined with other indicators
        if not request.user_agent:
            if not request.cookies:
                return True

        # Unusual HTTP methods for browser
        if request.method not in ["GET", "POST", "HEAD", "OPTIONS"]:
            return True

        # Content-type mismatch for GET request
        if request.method == "GET" and request.content_type:
            if request.content_type.startswith("application/json"):
                return True

        # Very large body for GET request
        if request.method == "GET" and request.content_length > 1000:
            return True

        return False

    def _analyze_request_pattern(self, request: HTTPRequest) -> float:
        """
        Analyze request patterns to detect bots.

        Args:
            request: HTTP request

        Returns:
            Pattern anomaly score (0-1)
        """
        ip = request.client_ip

        # Record request
        self.request_patterns[ip].append(
            {
                "timestamp": datetime.utcnow(),
                "path": request.path,
                "method": request.method,
            }
        )

        # Keep only last 100 requests
        if len(self.request_patterns[ip]) > 100:
            self.request_patterns[ip] = self.request_patterns[ip][-100:]

        pattern = self.request_patterns[ip]

        # Check for rapid sequential requests
        if len(pattern) > 5:
            recent = pattern[-5:]
            timestamps = [r["timestamp"] for r in recent]

            # Calculate average time between requests
            time_diffs = []
            for i in range(len(timestamps) - 1):
                diff = (timestamps[i + 1] - timestamps[i]).total_seconds()
                time_diffs.append(diff)

            if time_diffs:
                avg_diff = sum(time_diffs) / len(time_diffs)
                # Less than 100ms average between requests = likely bot
                if avg_diff < 0.1:
                    return 0.8

                # Less than 500ms = suspicious
                if avg_diff < 0.5:
                    return 0.3

        # Check for path enumeration
        if len(pattern) > 10:
            recent_paths = [r["path"] for r in pattern[-10:]]
            unique_paths = set(recent_paths)

            # Many unique paths in short time = likely scanner
            if len(unique_paths) > 8:
                return 0.6

        return 0.0

    def require_javascript_challenge(self, request: HTTPRequest) -> str:
        """
        Generate JavaScript challenge token.

        Args:
            request: HTTP request

        Returns:
            Challenge token
        """
        challenge_data = f"{request.client_ip}:{datetime.utcnow().isoformat()}"
        token = hashlib.sha256(challenge_data.encode()).hexdigest()

        self.challenge_tokens[token] = (
            datetime.utcnow() + timedelta(minutes=15),
            request.client_ip,
        )

        self.logger.info(f"JavaScript challenge issued to {request.client_ip}: {token}")

        return token

    def verify_challenge(self, token: str, ip_address: str) -> bool:
        """
        Verify challenge token.

        Args:
            token: Challenge token
            ip_address: IP address

        Returns:
            True if valid
        """
        if token not in self.challenge_tokens:
            return False

        expiry, stored_ip = self.challenge_tokens[token]

        # Check expiry
        if datetime.utcnow() > expiry:
            del self.challenge_tokens[token]
            return False

        # Check IP matches
        if stored_ip != ip_address:
            return False

        # Mark as verified human
        del self.challenge_tokens[token]
        self.verified_humans[ip_address] = datetime.utcnow() + timedelta(hours=24)

        self.logger.info(f"Challenge verified for {ip_address}")

        return True

    def is_verified_human(self, ip_address: str) -> bool:
        """
        Check if IP has passed challenge.

        Args:
            ip_address: IP address

        Returns:
            True if verified human
        """
        if ip_address not in self.verified_humans:
            return False

        expiry = self.verified_humans[ip_address]

        if datetime.utcnow() > expiry:
            del self.verified_humans[ip_address]
            return False

        return True

    def get_bot_detection_result(self, request: HTTPRequest) -> tuple[bool, float, str]:
        """
        Get comprehensive bot detection result.

        Args:
            request: HTTP request

        Returns:
            Tuple of (is_bot, confidence, reason)
        """
        # Check verified human
        if self.is_verified_human(request.client_ip):
            return (False, 0.0, "verified_human")

        # Check good bots
        if self.is_good_bot(request):
            return (True, 1.0, "good_bot")

        # Check bad bots
        if self.is_bad_bot(request):
            return (True, 1.0, "bad_bot")

        # Calculate score
        score = self.calculate_bot_score(request)

        if score > 0.8:
            return (True, score, "high_bot_score")

        if score > 0.6:
            return (True, score, "medium_bot_score")

        if score > 0.4:
            return (False, score, "suspicious_but_allowed")

        return (False, score, "likely_human")

    def cleanup_expired_tokens(self) -> int:
        """
        Clean up expired challenge tokens.

        Returns:
            Number of tokens removed
        """
        count = 0
        expired = []

        for token, (expiry, _) in self.challenge_tokens.items():
            if datetime.utcnow() > expiry:
                expired.append(token)
                count += 1

        for token in expired:
            del self.challenge_tokens[token]

        return count

    def get_stats(self) -> dict[str, int]:
        """
        Get bot detection statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "pending_challenges": len(self.challenge_tokens),
            "verified_humans": len(self.verified_humans),
            "monitored_ips": len(self.request_patterns),
        }
