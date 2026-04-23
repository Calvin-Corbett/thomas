"""
Web Application Firewall (WAF) Module

A comprehensive WAF implementation with rule-based request filtering,
rate limiting, bot detection, and anomaly scoring.
"""

from thomas.marketplace.waf._exceptions import (
    ConfigurationException,
    RateLimitException,
    RuleParseException,
    WAFException,
)
from thomas.marketplace.waf._types import (
    GeoLocation,
    HTTPRequest,
    IPReputation,
    RateLimitConfig,
    RuleAction,
    RuleMatch,
    ThreatLevel,
    WAFConfig,
    WAFRule,
)
from thomas.marketplace.waf.anomaly import AnomalyScorer
from thomas.marketplace.waf.bot_detection import BotDetector
from thomas.marketplace.waf.engine import WAFEngine, WAFStatistics
from thomas.marketplace.waf.geo import GeoIPManager
from thomas.marketplace.waf.ip_reputation import IPReputationManager
from thomas.marketplace.waf.logging import WAFLogger
from thomas.marketplace.waf.modsecurity import ModSecurityParser
from thomas.marketplace.waf.rate_limiter import RateLimiter
from thomas.marketplace.waf.rules import BuiltInRules
from thomas.marketplace.waf.scanner import ScannerDetector

__version__ = "1.0.0"
__all__ = [
    "HTTPRequest",
    "RuleAction",
    "WAFRule",
    "RuleMatch",
    "WAFConfig",
    "ThreatLevel",
    "IPReputation",
    "RateLimitConfig",
    "GeoLocation",
    "WAFException",
    "RuleParseException",
    "ConfigurationException",
    "RateLimitException",
    "WAFEngine",
    "WAFStatistics",
    "BuiltInRules",
    "IPReputationManager",
    "RateLimiter",
    "ScannerDetector",
    "ModSecurityParser",
    "GeoIPManager",
    "WAFLogger",
    "BotDetector",
    "AnomalyScorer",
]
