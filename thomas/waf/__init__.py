"""
Web Application Firewall (WAF) Module

A comprehensive WAF implementation with rule-based request filtering,
rate limiting, bot detection, and anomaly scoring.
"""

from thomas.waf._exceptions import (
    ConfigurationException,
    RateLimitException,
    RuleParseException,
    WAFException,
)
from thomas.waf._types import (
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
from thomas.waf.anomaly import AnomalyScorer
from thomas.waf.bot_detection import BotDetector
from thomas.waf.engine import WAFEngine, WAFStatistics
from thomas.waf.geo import GeoIPManager
from thomas.waf.ip_reputation import IPReputationManager
from thomas.waf.logging import WAFLogger
from thomas.waf.modsecurity import ModSecurityParser
from thomas.waf.rate_limiter import RateLimiter
from thomas.waf.rules import BuiltInRules
from thomas.waf.scanner import ScannerDetector

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
