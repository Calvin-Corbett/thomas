"""
Anomaly Scoring Module

Calculate anomaly scores for requests based on rule matches,
threat levels, and paranoia settings.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from thomas.waf._types import RuleMatch, ThreatLevel


class AnomalyScorer:
    """
    Calculates anomaly scores for requests.

    Features:
    - Score aggregation based on rule severity
    - Paranoia level adjustments (1-4)
    - Inbound/outbound score thresholds
    - Score history tracking
    - Explanation of score components
    """

    # Base scores by severity
    SEVERITY_SCORES = {
        ThreatLevel.LOW.value: 5,
        ThreatLevel.MEDIUM.value: 15,
        ThreatLevel.HIGH.value: 30,
        ThreatLevel.CRITICAL.value: 50,
    }

    # Paranoia level multipliers
    PARANOIA_MULTIPLIERS = {
        1: 1.0,
        2: 1.5,
        3: 2.0,
        4: 3.0,
    }

    def __init__(self, paranoia_level: int = 1) -> None:
        """
        Initialize anomaly scorer.

        Args:
            paranoia_level: Paranoia level 1-4 (1=low, 4=maximum)
        """
        if not 1 <= paranoia_level <= 4:
            raise ValueError("Paranoia level must be between 1 and 4")

        self.paranoia_level = paranoia_level
        self.inbound_threshold = 100
        self.outbound_threshold = 100
        self.score_history: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
        self.logger = logging.getLogger(__name__)

    def calculate_inbound_score(self, matches: list[RuleMatch]) -> tuple[int, dict[str, int]]:
        """
        Calculate inbound anomaly score.

        Args:
            matches: List of matched rules

        Returns:
            Tuple of (total_score, scores_by_category)
        """
        scores_by_category: dict[str, int] = defaultdict(int)
        total_score = 0

        for match in matches:
            # Get base score
            base_score = self.SEVERITY_SCORES.get(match.severity.value, 10)

            # Apply paranoia multiplier
            adjusted_score = int(base_score * self.PARANOIA_MULTIPLIERS[self.paranoia_level])

            scores_by_category[match.severity.name] += adjusted_score
            total_score += adjusted_score

        return (total_score, dict(scores_by_category))

    def calculate_outbound_score(self, response_headers: dict[str, str], response_body: bytes) -> tuple[int, list[str]]:
        """
        Calculate outbound anomaly score (response analysis).

        Args:
            response_headers: Response headers
            response_body: Response body

        Returns:
            Tuple of (score, findings)
        """
        score = 0
        findings: list[str] = []

        # Check for sensitive information in response
        body_str = response_body.decode("utf-8", errors="ignore").lower()

        if "password" in body_str or "secret" in body_str:
            score += 10
            findings.append("Potential sensitive data in response")

        if "error" in body_str and "sql" in body_str:
            score += 15
            findings.append("SQL error message leaked")

        if "stack trace" in body_str or "traceback" in body_str:
            score += 10
            findings.append("Stack trace/debug info leaked")

        # Check for suspicious headers
        if "server" in response_headers:
            server = response_headers["server"].lower()
            if "apache" in server or "nginx" in server:
                # Information disclosure is minor
                score += 3

        return (score, findings)

    def is_inbound_anomaly(self, inbound_score: int) -> bool:
        """
        Check if inbound score exceeds threshold.

        Args:
            inbound_score: Inbound anomaly score

        Returns:
            True if anomaly detected
        """
        return inbound_score >= self.inbound_threshold

    def is_outbound_anomaly(self, outbound_score: int) -> bool:
        """
        Check if outbound score exceeds threshold.

        Args:
            outbound_score: Outbound anomaly score

        Returns:
            True if anomaly detected
        """
        return outbound_score >= self.outbound_threshold

    def get_score_explanation(self, matches: list[RuleMatch]) -> dict[str, any]:
        """
        Get detailed explanation of anomaly score.

        Args:
            matches: List of matched rules

        Returns:
            Dictionary with score breakdown
        """
        explanation = {
            "paranoia_level": self.paranoia_level,
            "paranoia_multiplier": self.PARANOIA_MULTIPLIERS[self.paranoia_level],
            "matches": [],
            "total_score": 0,
        }

        for match in matches:
            base_score = self.SEVERITY_SCORES.get(match.severity.value, 10)
            adjusted_score = int(base_score * self.PARANOIA_MULTIPLIERS[self.paranoia_level])

            explanation["matches"].append(
                {
                    "rule_id": match.rule_id,
                    "rule_name": match.rule_name,
                    "severity": match.severity.name,
                    "base_score": base_score,
                    "adjusted_score": adjusted_score,
                }
            )

            explanation["total_score"] += adjusted_score

        return explanation

    def track_score(self, ip_address: str, score: int) -> None:
        """
        Track score for IP address over time.

        Args:
            ip_address: IP address
            score: Anomaly score
        """
        now = datetime.utcnow()
        self.score_history[ip_address].append((now, score))

        # Keep only last 1000 entries per IP
        if len(self.score_history[ip_address]) > 1000:
            self.score_history[ip_address] = self.score_history[ip_address][-1000:]

    def get_average_score(self, ip_address: str, minutes: int = 60) -> float:
        """
        Get average score for IP over time period.

        Args:
            ip_address: IP address
            minutes: Time window in minutes

        Returns:
            Average score
        """
        if ip_address not in self.score_history:
            return 0.0

        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        recent = [score for ts, score in self.score_history[ip_address] if ts > cutoff]

        if not recent:
            return 0.0

        return sum(recent) / len(recent)

    def get_max_score(self, ip_address: str, minutes: int = 60) -> int:
        """
        Get maximum score for IP over time period.

        Args:
            ip_address: IP address
            minutes: Time window in minutes

        Returns:
            Maximum score
        """
        if ip_address not in self.score_history:
            return 0

        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        recent = [score for ts, score in self.score_history[ip_address] if ts > cutoff]

        return max(recent) if recent else 0

    def set_paranoia_level(self, level: int) -> None:
        """
        Set paranoia level.

        Args:
            level: Paranoia level 1-4
        """
        if not 1 <= level <= 4:
            raise ValueError("Paranoia level must be between 1 and 4")

        self.paranoia_level = level
        self.logger.info(f"Paranoia level set to {level}")

    def set_thresholds(self, inbound: int = 100, outbound: int = 100) -> None:
        """
        Set anomaly score thresholds.

        Args:
            inbound: Inbound threshold
            outbound: Outbound threshold
        """
        if inbound <= 0 or outbound <= 0:
            raise ValueError("Thresholds must be positive")

        self.inbound_threshold = inbound
        self.outbound_threshold = outbound

    def cleanup_history(self, older_than_hours: int = 24) -> int:
        """
        Clean up old score history.

        Args:
            older_than_hours: Remove entries older than this

        Returns:
            Number of entries removed
        """
        count = 0
        cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)

        for ip_address in list(self.score_history.keys()):
            old_len = len(self.score_history[ip_address])
            self.score_history[ip_address] = [
                (ts, score) for ts, score in self.score_history[ip_address] if ts > cutoff
            ]
            count += old_len - len(self.score_history[ip_address])

            # Remove IP if no more history
            if not self.score_history[ip_address]:
                del self.score_history[ip_address]

        return count

    def get_stats(self) -> dict[str, int]:
        """
        Get scorer statistics.

        Returns:
            Statistics dictionary
        """
        total_entries = sum(len(v) for v in self.score_history.values())

        return {
            "ips_tracked": len(self.score_history),
            "total_score_entries": total_entries,
            "inbound_threshold": self.inbound_threshold,
            "outbound_threshold": self.outbound_threshold,
            "paranoia_level": self.paranoia_level,
        }
