"""SIEM (Security Information and Event Management) module.

A comprehensive security analytics and event management system with detection,
correlation, incident management, and automated response capabilities.
"""

from thomas.siem._exceptions import (
    CollectorException,
    CorrelationException,
    DetectionException,
    IncidentException,
    SIEMException,
)
from thomas.siem._types import (
    Alert,
    Asset,
    EventCategory,
    EventSeverity,
    Incident,
    Indicator,
    Investigation,
    Rule,
    SecurityEvent,
    ThreatIntel,
    Timeline,
    Vulnerability,
)

__version__ = "0.1.0"

__all__ = [
    "SecurityEvent",
    "EventSeverity",
    "EventCategory",
    "Alert",
    "Rule",
    "Indicator",
    "ThreatIntel",
    "Asset",
    "Vulnerability",
    "Incident",
    "Investigation",
    "Timeline",
    "SIEMException",
    "CollectorException",
    "CorrelationException",
    "DetectionException",
    "IncidentException",
]
