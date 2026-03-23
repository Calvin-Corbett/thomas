"""Exception types for SIEM module.

Provides specific exception classes for various SIEM operations.
"""


class SIEMException(Exception):
    """Base exception for all SIEM errors."""

    pass


class CollectorException(SIEMException):
    """Exception raised during log collection operations."""

    pass


class ParsingException(CollectorException):
    """Exception raised when parsing log entries."""

    pass


class EnrichmentException(CollectorException):
    """Exception raised during event enrichment."""

    pass


class SourceHealthException(CollectorException):
    """Exception raised for source health monitoring issues."""

    pass


class CorrelationException(SIEMException):
    """Exception raised during event correlation."""

    pass


class RuleEngineException(CorrelationException):
    """Exception raised by the correlation rule engine."""

    pass


class StateManagementException(CorrelationException):
    """Exception raised for state management issues."""

    pass


class DetectionException(SIEMException):
    """Exception raised during threat detection."""

    pass


class SignatureMatchException(DetectionException):
    """Exception raised during signature matching."""

    pass


class AnomalyDetectionException(DetectionException):
    """Exception raised during anomaly detection."""

    pass


class BruteForceDetectionException(DetectionException):
    """Exception raised during brute force detection."""

    pass


class IncidentException(SIEMException):
    """Exception raised during incident management."""

    pass


class IncidentCreationException(IncidentException):
    """Exception raised when creating incidents."""

    pass


class ForensicsException(SIEMException):
    """Exception raised during forensic analysis."""

    pass


class TimelineException(ForensicsException):
    """Exception raised during timeline reconstruction."""

    pass


class HashAnalysisException(ForensicsException):
    """Exception raised during hash analysis."""

    pass


class ThreatIntelException(SIEMException):
    """Exception raised for threat intelligence operations."""

    pass


class IOCManagementException(ThreatIntelException):
    """Exception raised for IOC management."""

    pass


class ComplianceException(SIEMException):
    """Exception raised during compliance monitoring."""

    pass


class ResponseException(SIEMException):
    """Exception raised during automated response operations."""

    pass


class PlaybookException(ResponseException):
    """Exception raised during playbook execution."""

    pass
