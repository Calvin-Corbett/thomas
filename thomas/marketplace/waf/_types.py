"""
WAF Type Definitions and Data Classes

Core data structures for the WAF system including request representation,
rule definitions, and configuration objects.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from re import Pattern


class RuleAction(Enum):
    """Enumeration of possible rule actions."""

    ALLOW = "allow"
    BLOCK = "block"
    LOG = "log"
    CHALLENGE = "challenge"
    REDIRECT = "redirect"


class ThreatLevel(Enum):
    """Threat level classification."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class HTTPRequest:
    """
    Represents an HTTP request for WAF evaluation.

    Attributes:
        method: HTTP method (GET, POST, etc.)
        path: Request path URI
        headers: HTTP headers dictionary
        body: Request body bytes
        client_ip: Client IP address
        query_params: Query string parameters
        cookies: Cookie dictionary
        timestamp: Request timestamp
        session_id: Optional session identifier
        user_id: Optional user identifier
    """

    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    client_ip: str
    query_params: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    session_id: str | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        """Validate request data."""
        if not self.method or not isinstance(self.method, str):
            raise ValueError("Invalid HTTP method")
        if not self.path or not isinstance(self.path, str):
            raise ValueError("Invalid path")
        if not isinstance(self.headers, dict):
            raise ValueError("Headers must be a dictionary")
        if not isinstance(self.body, bytes):
            raise ValueError("Body must be bytes")
        if not self.client_ip or not isinstance(self.client_ip, str):
            raise ValueError("Invalid client IP")

    def get_header(self, name: str, default: str = "") -> str:
        """
        Get header value case-insensitively.

        Args:
            name: Header name
            default: Default value if not found

        Returns:
            Header value or default
        """
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default

    @property
    def full_path(self) -> str:
        """Get full request path with query string."""
        if self.query_params:
            params = "&".join(f"{k}={v}" for k, v in self.query_params.items())
            return f"{self.path}?{params}"
        return self.path

    @property
    def content_length(self) -> int:
        """Get content length from headers."""
        try:
            return int(self.get_header("content-length", "0"))
        except ValueError:
            return 0

    @property
    def content_type(self) -> str:
        """Get content type from headers."""
        return self.get_header("content-type", "")

    @property
    def user_agent(self) -> str:
        """Get user agent from headers."""
        return self.get_header("user-agent", "")


@dataclass
class RuleMatch:
    """
    Represents a matched rule result.

    Attributes:
        rule_id: Rule identifier
        rule_name: Rule name
        matched_pattern: Pattern that matched
        matched_value: Value that matched pattern
        severity: Threat level
        action: Action to take
        confidence: Confidence score (0-1)
        timestamp: When rule matched
    """

    rule_id: str
    rule_name: str
    matched_pattern: str
    matched_value: str
    severity: ThreatLevel
    action: RuleAction
    confidence: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Validate match data."""
        if not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")


@dataclass
class WAFRule:
    """
    Represents a WAF rule for request filtering.

    Attributes:
        id: Unique rule identifier
        name: Rule name
        pattern: Regex pattern to match against
        action: Action to take when rule matches
        severity: Threat level
        category: Rule category (SQL injection, XSS, etc.)
        enabled: Whether rule is enabled
        priority: Rule priority (lower = higher priority)
        variables: Request variables to check against pattern
        transformations: List of transformations to apply
    """

    id: str
    name: str
    pattern: str
    action: RuleAction
    severity: ThreatLevel
    category: str
    enabled: bool = True
    priority: int = 100
    variables: list[str] = field(default_factory=lambda: ["ARGS|REQUEST_URI|BODY"])
    transformations: list[str] = field(default_factory=list)

    _compiled_pattern: Pattern[str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Compile regex pattern."""
        try:
            self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

    def matches(self, value: str) -> bool:
        """
        Check if rule pattern matches value.

        Args:
            value: Value to match against

        Returns:
            True if pattern matches, False otherwise
        """
        if not self._compiled_pattern or not value:
            return False
        return bool(self._compiled_pattern.search(value))

    def get_match_groups(self, value: str) -> tuple:
        """
        Get regex match groups.

        Args:
            value: Value to match against

        Returns:
            Match groups tuple
        """
        if not self._compiled_pattern:
            return ()
        match = self._compiled_pattern.search(value)
        return match.groups() if match else ()


@dataclass
class GeoLocation:
    """
    Geographic location information.

    Attributes:
        country_code: ISO 3166-1 alpha-2 country code
        city: City name
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        is_vpn: Whether IP is detected as VPN
        is_proxy: Whether IP is detected as proxy
        is_tor: Whether IP is Tor exit node
    """

    country_code: str
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_vpn: bool = False
    is_proxy: bool = False
    is_tor: bool = False


@dataclass
class IPReputation:
    """
    IP address reputation information.

    Attributes:
        ip_address: IP address
        reputation_score: Reputation score (0-100, higher = worse)
        threat_types: List of threat types associated
        last_seen: Timestamp of last activity
        ban_until: Timestamp when ban expires (None if not banned)
        abuse_count: Number of abuses reported
    """

    ip_address: str
    reputation_score: int = 0
    threat_types: list[str] = field(default_factory=list)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    ban_until: datetime | None = None
    abuse_count: int = 0

    def __post_init__(self) -> None:
        """Validate reputation score."""
        if not 0 <= self.reputation_score <= 100:
            raise ValueError("Reputation score must be between 0 and 100")

    def is_banned(self) -> bool:
        """Check if IP is currently banned."""
        if self.ban_until is None:
            return False
        return datetime.utcnow() < self.ban_until

    def add_threat_type(self, threat_type: str) -> None:
        """Add threat type if not already present."""
        if threat_type not in self.threat_types:
            self.threat_types.append(threat_type)


@dataclass
class RateLimitConfig:
    """
    Rate limiting configuration.

    Attributes:
        requests_per_second: Maximum requests per second
        requests_per_minute: Maximum requests per minute
        requests_per_hour: Maximum requests per hour
        burst_size: Allowed burst size
        window_size: Sliding window size in seconds
        whitelist_ips: IPs exempt from rate limiting
        whitelist_paths: Paths exempt from rate limiting
        graduated_response: Enable graduated response (log->challenge->block)
    """

    requests_per_second: int = 100
    requests_per_minute: int = 1000
    requests_per_hour: int = 10000
    burst_size: int = 10
    window_size: int = 60
    whitelist_ips: set[str] = field(default_factory=set)
    whitelist_paths: set[str] = field(default_factory=set)
    graduated_response: bool = True


@dataclass
class WAFConfig:
    """
    WAF configuration.

    Attributes:
        enable_rate_limiting: Enable rate limiting
        enable_bot_detection: Enable bot detection
        enable_geo_blocking: Enable geo-blocking
        enable_scanner_detection: Enable scanner detection
        enable_anomaly_scoring: Enable anomaly scoring
        paranoia_level: Paranoia level 1-4
        block_threshold: Anomaly score threshold to block
        challenge_threshold: Anomaly score threshold to challenge
        log_requests: Log all requests
        log_level: Logging level
        whitelist_ips: IPs exempt from all checks
        rate_limit_config: Rate limiting configuration
    """

    enable_rate_limiting: bool = True
    enable_bot_detection: bool = True
    enable_geo_blocking: bool = False
    enable_scanner_detection: bool = True
    enable_anomaly_scoring: bool = True
    paranoia_level: int = 1
    block_threshold: int = 100
    challenge_threshold: int = 75
    log_requests: bool = True
    log_level: str = "INFO"
    whitelist_ips: set[str] = field(default_factory=set)
    rate_limit_config: RateLimitConfig = field(default_factory=RateLimitConfig)

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not 1 <= self.paranoia_level <= 4:
            raise ValueError("Paranoia level must be between 1 and 4")
        if self.block_threshold < self.challenge_threshold:
            raise ValueError("Block threshold must be >= challenge threshold")
