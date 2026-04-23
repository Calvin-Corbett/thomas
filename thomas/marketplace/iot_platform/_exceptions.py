"""
Custom exceptions for the IoT platform.

Defines all exception types used throughout the IoT platform
for error handling and reporting.
"""


class IoTException(Exception):
    """Base exception for all IoT platform errors."""

    pass


class DeviceNotFoundError(IoTException):
    """Raised when a device cannot be found in the registry."""

    pass


class InvalidDeviceError(IoTException):
    """Raised when device data or configuration is invalid."""

    pass


class DuplicateDeviceError(IoTException):
    """Raised when attempting to register a device that already exists."""

    pass


class TelemetryError(IoTException):
    """Raised when telemetry ingestion or processing fails."""

    pass


class InvalidRuleError(IoTException):
    """Raised when rule definition or evaluation fails."""

    pass


class CommandError(IoTException):
    """Raised when command execution fails."""

    pass


class MQTTError(IoTException):
    """Raised when MQTT operations fail."""

    pass


class OTAError(IoTException):
    """Raised when firmware update operations fail."""

    pass
