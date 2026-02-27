"""
Email filtering implementation.

Supports Sieve-like filter rules with header/content matching,
spam scoring using Bayesian analysis, and filter execution.
"""

import re
from dataclasses import dataclass
from enum import Enum

from thomas.email_protocol._types import EmailMessage


class FilterAction(str, Enum):
    """Filter actions."""

    KEEP = "keep"
    DISCARD = "discard"
    FILEINTO = "fileinto"
    REDIRECT = "redirect"
    MARK_READ = "mark_read"
    ADD_FLAG = "add_flag"
    REMOVE_FLAG = "remove_flag"


@dataclass
class FilterRule:
    """Represents a single filter rule.

    Attributes:
        name: Rule name
        conditions: List of conditions (all must match)
        action: Action to perform
        action_target: Target for action (folder, email, etc.)
        enabled: Whether rule is enabled
        priority: Rule priority (lower = higher priority)
    """

    name: str
    conditions: list[dict[str, any]]
    action: FilterAction
    action_target: str | None = None
    enabled: bool = True
    priority: int = 100

    def matches(self, message: EmailMessage) -> bool:
        """Check if message matches all conditions.

        Args:
            message: Message to test

        Returns:
            True if all conditions match
        """
        return all(self._evaluate_condition(cond, message) for cond in self.conditions)

    def _evaluate_condition(self, condition: dict[str, any], message: EmailMessage) -> bool:
        """Evaluate a single condition.

        Args:
            condition: Condition to evaluate
            message: Message to test

        Returns:
            True if condition matches
        """
        test_type = condition.get("type")

        if test_type == "from":
            if not message.envelope.from_addr:
                return False
            return condition.get("value").lower() in message.envelope.from_addr.address.lower()

        elif test_type == "to":
            to_addrs = [addr.address.lower() for addr in message.envelope.to_addrs]
            return any(condition.get("value").lower() in addr for addr in to_addrs)

        elif test_type == "subject":
            return condition.get("value").lower() in message.envelope.subject.lower()

        elif test_type == "body":
            text_body = message.text_body or ""
            return condition.get("value").lower() in text_body.lower()

        elif test_type == "header":
            header_name = condition.get("header", "").lower()
            if header_name in message.headers:
                values = message.headers[header_name]
                if isinstance(values, list):
                    return any(condition.get("value").lower() in v.lower() for v in values)
                return condition.get("value").lower() in values.lower()

        elif test_type == "size":
            operator = condition.get("operator", "==")
            size_bytes = condition.get("value", 0)
            if operator == ">":
                return message.size > size_bytes
            elif operator == "<":
                return message.size < size_bytes
            elif operator == "==":
                return message.size == size_bytes

        return True


class FilterEngine:
    """Email filter execution engine."""

    def __init__(self) -> None:
        """Initialize filter engine."""
        self.rules: list[FilterRule] = []
        self.results: dict[str, list[str]] = {
            "keep": [],
            "discard": [],
            "fileinto": {},
            "redirect": {},
        }

    def add_rule(self, rule: FilterRule) -> None:
        """Add a filter rule.

        Args:
            rule: Filter rule to add
        """
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority)

    def remove_rule(self, rule_name: str) -> None:
        """Remove a filter rule by name.

        Args:
            rule_name: Name of rule to remove
        """
        self.rules = [r for r in self.rules if r.name != rule_name]

    def execute(self, message: EmailMessage) -> dict[str, any]:
        """Execute filters on a message.

        Args:
            message: Message to filter

        Returns:
            Dictionary with action and target
        """
        for rule in self.rules:
            if not rule.enabled:
                continue

            if rule.matches(message):
                return {
                    "action": rule.action,
                    "target": rule.action_target,
                    "rule": rule.name,
                }

        return {"action": FilterAction.KEEP, "target": None, "rule": None}

    def import_sieve_rules(self, sieve_text: str) -> list[FilterRule]:
        """Parse Sieve-like filter syntax.

        Args:
            sieve_text: Sieve filter script

        Returns:
            List of parsed FilterRule objects
        """
        rules = []

        lines = sieve_text.strip().split("\n")
        current_rule = None
        rule_conditions = []
        rule_action = None

        for line in lines:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if line.startswith("if"):
                if current_rule and rule_action:
                    rule = FilterRule(
                        name=current_rule,
                        conditions=rule_conditions,
                        action=rule_action[0],
                        action_target=rule_action[1],
                    )
                    rules.append(rule)

                current_rule = "rule"
                rule_conditions = []
                rule_action = None

                condition_match = re.search(r"if\s+(.*?)\s+then", line)
                if condition_match:
                    condition_str = condition_match.group(1)
                    rule_conditions.extend(self._parse_condition(condition_str))

            elif "then" in line:
                action_match = re.search(r"then\s+(\w+)(?:\s+['\"]([^'\"]+)['\"])?", line)
                if action_match:
                    action_name = action_match.group(1).lower()
                    action_target = action_match.group(2)

                    try:
                        action = FilterAction[action_name.upper()]
                        rule_action = (action, action_target)
                    except KeyError:
                        pass

        if current_rule and rule_action:
            rule = FilterRule(
                name=current_rule,
                conditions=rule_conditions,
                action=rule_action[0],
                action_target=rule_action[1],
            )
            rules.append(rule)

        return rules

    def _parse_condition(self, condition_str: str) -> list[dict[str, any]]:
        """Parse condition syntax.

        Args:
            condition_str: Condition string

        Returns:
            List of condition dictionaries
        """
        conditions = []

        patterns = [
            (
                r'header\s+"([^"]+)"\s+contains\s+"([^"]+)"',
                lambda m: {
                    "type": "header",
                    "header": m.group(1),
                    "value": m.group(2),
                },
            ),
            (
                r'from\s+contains\s+"([^"]+)"',
                lambda m: {
                    "type": "from",
                    "value": m.group(1),
                },
            ),
            (
                r'subject\s+contains\s+"([^"]+)"',
                lambda m: {
                    "type": "subject",
                    "value": m.group(1),
                },
            ),
        ]

        for pattern, extractor in patterns:
            for match in re.finditer(pattern, condition_str):
                conditions.append(extractor(match))

        return conditions


class BayesianSpamFilter:
    """Bayesian spam classification filter."""

    def __init__(self, spam_threshold: float = 0.5) -> None:
        """Initialize spam filter.

        Args:
            spam_threshold: Probability threshold for spam (0.0-1.0)
        """
        self.spam_threshold = spam_threshold
        self.spam_words: dict[str, float] = {}
        self.ham_words: dict[str, float] = {}
        self.total_spam = 0
        self.total_ham = 0

    def train(self, message: EmailMessage, is_spam: bool) -> None:
        """Train filter with a message.

        Args:
            message: Message to train on
            is_spam: Whether message is spam
        """
        words = self._extract_words(message)

        if is_spam:
            self.total_spam += 1
            for word in words:
                self.spam_words[word] = self.spam_words.get(word, 0) + 1
        else:
            self.total_ham += 1
            for word in words:
                self.ham_words[word] = self.ham_words.get(word, 0) + 1

    def score(self, message: EmailMessage) -> float:
        """Calculate spam score for message (0.0 = ham, 1.0 = spam).

        Args:
            message: Message to score

        Returns:
            Spam probability (0.0-1.0)
        """
        words = self._extract_words(message)

        if not words:
            return 0.5

        probabilities = []

        for word in set(words):
            spam_count = self.spam_words.get(word, 0)
            ham_count = self.ham_words.get(word, 0)

            spam_prob = self._robinson_combining(spam_count, ham_count)
            probabilities.append(spam_prob)

        if not probabilities:
            return 0.5

        return self._combine_probabilities(probabilities)

    def is_spam(self, message: EmailMessage) -> bool:
        """Classify message as spam.

        Args:
            message: Message to classify

        Returns:
            True if message is spam
        """
        return self.score(message) >= self.spam_threshold

    def _extract_words(self, message: EmailMessage) -> list[str]:
        """Extract words from message for analysis.

        Args:
            message: Message to analyze

        Returns:
            List of words
        """
        text_parts = [
            message.envelope.subject or "",
            message.text_body or "",
        ]

        if message.envelope.from_addr:
            text_parts.append(message.envelope.from_addr.address)

        full_text = " ".join(text_parts).lower()

        words = re.findall(r"\b[a-z]{3,}\b", full_text)
        return words

    def _robinson_combining(self, spam_count: int, ham_count: int) -> float:
        """Calculate Robinson probability for a word.

        Args:
            spam_count: Count in spam messages
            ham_count: Count in ham messages

        Returns:
            Probability (0.0-1.0)
        """
        spam_freq = spam_count / max(self.total_spam, 1)
        ham_freq = ham_count / max(self.total_ham, 1)

        if spam_freq + ham_freq == 0:
            return 0.5

        return spam_freq / (spam_freq + ham_freq)

    def _combine_probabilities(self, probabilities: list[float]) -> float:
        """Combine individual word probabilities using Robinson's method.

        Args:
            probabilities: List of word probabilities

        Returns:
            Combined probability (0.0-1.0)
        """
        if not probabilities:
            return 0.5

        inv_chi2 = self._inverse_chi2(probabilities)

        numerator = inv_chi2
        denominator = inv_chi2 + self._inverse_chi2([1 - p for p in probabilities])

        if denominator == 0:
            return 0.5

        return numerator / denominator

    def _inverse_chi2(self, probabilities: list[float]) -> float:
        """Calculate inverse chi-squared value.

        Args:
            probabilities: List of probabilities

        Returns:
            Chi-squared value
        """
        if not probabilities:
            return 0.0

        import math

        log_sum = sum(math.log(max(p, 0.001)) for p in probabilities)
        return -2.0 * log_sum
