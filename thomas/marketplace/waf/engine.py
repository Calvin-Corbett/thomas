"""
WAF Engine

Core WAF engine for evaluating requests against rules.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from thomas.marketplace.waf._exceptions import WAFException
from thomas.marketplace.waf._types import (
    HTTPRequest,
    RuleAction,
    RuleMatch,
    WAFConfig,
    WAFRule,
)


@dataclass
class WAFStatistics:
    """WAF engine statistics."""

    total_requests: int = 0
    blocked_requests: int = 0
    challenged_requests: int = 0
    allowed_requests: int = 0
    logged_requests: int = 0
    rules_triggered: int = 0
    avg_processing_time_ms: float = 0.0
    last_reset: datetime = field(default_factory=datetime.utcnow)

    def reset(self) -> None:
        """Reset statistics."""
        self.total_requests = 0
        self.blocked_requests = 0
        self.challenged_requests = 0
        self.allowed_requests = 0
        self.logged_requests = 0
        self.rules_triggered = 0
        self.avg_processing_time_ms = 0.0
        self.last_reset = datetime.utcnow()


class WAFEngine:
    """
    Main WAF engine for request evaluation.

    Evaluates HTTP requests against configured rules with support for:
    - Rule priority ordering
    - Short-circuit blocking
    - Match accumulation and scoring
    - Request/response logging
    - Action execution
    - Bypass whitelisting
    - Custom rule chains
    """

    def __init__(self, config: WAFConfig) -> None:
        """
        Initialize WAF engine.

        Args:
            config: WAF configuration
        """
        self.config = config
        self.rules: list[WAFRule] = []
        self.whitelist_ips: set[str] = config.whitelist_ips.copy()
        self.bypass_rules: dict[str, list[str]] = defaultdict(list)
        self.rule_chains: dict[str, list[str]] = defaultdict(list)
        self.statistics = WAFStatistics()
        self.logger = logging.getLogger(__name__)

    def add_rule(self, rule: WAFRule) -> None:
        """
        Add a rule to the engine.

        Args:
            rule: WAFRule to add
        """
        if rule.enabled:
            self.rules.append(rule)
            self._sort_rules()

    def add_rules(self, rules: list[WAFRule]) -> None:
        """
        Add multiple rules to the engine.

        Args:
            rules: List of WAFRule objects
        """
        for rule in rules:
            self.add_rule(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """
        Remove a rule by ID.

        Args:
            rule_id: Rule ID to remove

        Returns:
            True if rule was removed, False if not found
        """
        original_len = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) < original_len

    def add_bypass_whitelist(self, ip_address: str) -> None:
        """
        Add IP to bypass whitelist.

        Args:
            ip_address: IP address to whitelist
        """
        self.whitelist_ips.add(ip_address)

    def add_rule_chain(self, chain_id: str, rule_ids: list[str]) -> None:
        """
        Define a rule chain (sequential rules).

        Args:
            chain_id: Chain identifier
            rule_ids: List of rule IDs in chain order
        """
        self.rule_chains[chain_id] = rule_ids

    def evaluate(self, request: HTTPRequest) -> tuple[RuleAction, list[RuleMatch], int]:
        """
        Evaluate request against all rules.

        Args:
            request: HTTP request to evaluate

        Returns:
            Tuple of (action, matched_rules, anomaly_score)

        Raises:
            WAFException: If evaluation fails
        """
        start_time = datetime.utcnow()

        try:
            self.statistics.total_requests += 1

            # Check IP whitelist
            if request.client_ip in self.whitelist_ips:
                self.statistics.allowed_requests += 1
                return (RuleAction.ALLOW, [], 0)

            matches: list[RuleMatch] = []
            anomaly_score = 0

            # Evaluate all enabled rules
            for rule in self.rules:
                if not rule.enabled:
                    continue

                rule_matches = self._evaluate_rule(request, rule)
                if rule_matches:
                    matches.extend(rule_matches)
                    anomaly_score += self._calculate_rule_score(rule)

                    # Short-circuit on block action
                    if rule.action == RuleAction.BLOCK:
                        self.statistics.blocked_requests += 1
                        self.statistics.rules_triggered += len(matches)
                        self._update_processing_time(start_time)
                        return (RuleAction.BLOCK, matches, anomaly_score)

            # Determine action based on accumulated matches and scores
            action = self._determine_action(anomaly_score, matches)

            # Update statistics
            if action == RuleAction.BLOCK:
                self.statistics.blocked_requests += 1
            elif action == RuleAction.CHALLENGE:
                self.statistics.challenged_requests += 1
            elif action == RuleAction.LOG:
                self.statistics.logged_requests += 1
            else:
                self.statistics.allowed_requests += 1

            if matches:
                self.statistics.rules_triggered += len(matches)

            self._update_processing_time(start_time)
            return (action, matches, anomaly_score)

        except Exception as e:
            self.logger.error(f"Error evaluating request: {e}")
            raise WAFException(f"Request evaluation failed: {e}")

    def _evaluate_rule(self, request: HTTPRequest, rule: WAFRule) -> list[RuleMatch]:
        """
        Evaluate a single rule against a request.

        Args:
            request: HTTP request
            rule: WAFRule to evaluate

        Returns:
            List of RuleMatch objects
        """
        matches: list[RuleMatch] = []

        try:
            # Build list of values to check based on variables
            values_to_check = self._get_values_to_check(request, rule.variables)

            # Apply transformations
            transformed_values = []
            for value in values_to_check:
                transformed = self._apply_transformations(value, rule.transformations)
                transformed_values.append(transformed)

            # Check if rule pattern matches any value
            for original_value, transformed_value in zip(values_to_check, transformed_values):
                if rule.matches(transformed_value):
                    match = RuleMatch(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        matched_pattern=rule.pattern,
                        matched_value=original_value[:100],  # Truncate for logging
                        severity=rule.severity,
                        action=rule.action,
                        confidence=1.0,
                    )
                    matches.append(match)
                    break  # Only record one match per rule

        except Exception as e:
            self.logger.warning(f"Error evaluating rule {rule.id}: {e}")

        return matches

    def _get_values_to_check(self, request: HTTPRequest, variables: list[str]) -> list[str]:
        """
        Extract values to check from request based on variables.

        Args:
            request: HTTP request
            variables: Variable names (e.g., ARGS, REQUEST_URI, BODY)

        Returns:
            List of values to check
        """
        values: list[str] = []

        for var in variables:
            if "ARGS" in var:
                # Check query parameters
                values.extend(request.query_params.values())
                # Check POST parameters (from body)
                if request.body:
                    values.append(request.body.decode("utf-8", errors="ignore"))

            if "REQUEST_URI" in var:
                values.append(request.full_path)

            if "BODY" in var and request.body:
                values.append(request.body.decode("utf-8", errors="ignore"))

            if "HEADERS" in var:
                values.extend(request.headers.values())

            if "COOKIES" in var:
                values.extend(request.cookies.values())

            if "METHOD" in var:
                values.append(request.method)

        return [v for v in values if v]  # Filter empty values

    def _apply_transformations(self, value: str, transformations: list[str]) -> str:
        """
        Apply transformations to a value.

        Args:
            value: Value to transform
            transformations: List of transformation names

        Returns:
            Transformed value
        """
        result = value

        for transform in transformations:
            if transform == "lowercase":
                result = result.lower()
            elif transform == "uppercase":
                result = result.upper()
            elif transform == "trim":
                result = result.strip()
            elif transform == "urlDecode":
                try:
                    from urllib.parse import unquote

                    result = unquote(result)
                except Exception:
                    pass
            elif transform == "htmlDecode":
                try:
                    from html import unescape

                    result = unescape(result)
                except Exception:
                    pass
            elif transform == "base64Decode":
                try:
                    import base64

                    result = base64.b64decode(result).decode("utf-8", errors="ignore")
                except Exception:
                    pass

        return result

    def _calculate_rule_score(self, rule: WAFRule) -> int:
        """
        Calculate anomaly score for a rule match.

        Args:
            rule: Matched rule

        Returns:
            Anomaly score
        """
        base_scores = {
            1: 5,  # LOW
            2: 15,  # MEDIUM
            3: 30,  # HIGH
            4: 50,  # CRITICAL
        }
        return base_scores.get(rule.severity.value, 10)

    def _determine_action(self, anomaly_score: int, matches: list[RuleMatch]) -> RuleAction:
        """
        Determine action based on anomaly score and matches.

        Args:
            anomaly_score: Accumulated anomaly score
            matches: List of matched rules

        Returns:
            RuleAction to take
        """
        if not matches:
            return RuleAction.ALLOW

        # Check for any BLOCK actions
        for match in matches:
            if match.action == RuleAction.BLOCK:
                return RuleAction.BLOCK

        # Check anomaly score thresholds
        if anomaly_score >= self.config.block_threshold:
            return RuleAction.BLOCK

        if anomaly_score >= self.config.challenge_threshold:
            return RuleAction.CHALLENGE

        # Check for any LOG actions
        for match in matches:
            if match.action == RuleAction.LOG:
                return RuleAction.LOG

        return RuleAction.ALLOW

    def _sort_rules(self) -> None:
        """Sort rules by priority (lower priority value = higher priority)."""
        self.rules.sort(key=lambda r: r.priority)

    def _update_processing_time(self, start_time: datetime) -> None:
        """Update average processing time."""
        elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        if self.statistics.total_requests == 1:
            self.statistics.avg_processing_time_ms = elapsed_ms
        else:
            # Exponential moving average
            alpha = 0.1
            self.statistics.avg_processing_time_ms = (
                alpha * elapsed_ms + (1 - alpha) * self.statistics.avg_processing_time_ms
            )

    def get_statistics(self) -> WAFStatistics:
        """
        Get current WAF statistics.

        Returns:
            WAFStatistics object
        """
        return self.statistics

    def reset_statistics(self) -> None:
        """Reset all statistics."""
        self.statistics.reset()

    def get_rules_count(self) -> int:
        """
        Get total number of enabled rules.

        Returns:
            Number of enabled rules
        """
        return len(self.rules)

    def get_rule_by_id(self, rule_id: str) -> WAFRule | None:
        """
        Get a rule by ID.

        Args:
            rule_id: Rule ID to find

        Returns:
            WAFRule object or None if not found
        """
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None
