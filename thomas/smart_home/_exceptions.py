"""Custom exceptions for the smart home system."""


class SmartHomeException(Exception):
    """Base exception for smart home system."""

    pass


class DeviceError(SmartHomeException):
    """Raised when a device operation fails."""

    pass


class DeviceOfflineError(DeviceError):
    """Raised when trying to communicate with an offline device."""

    def __init__(self, device_id: str) -> None:
        """Initialize with device ID."""
        super().__init__(f"Device {device_id} is offline")
        self.device_id = device_id


class DeviceNotFoundError(DeviceError):
    """Raised when a device is not found."""

    def __init__(self, device_id: str) -> None:
        """Initialize with device ID."""
        super().__init__(f"Device {device_id} not found")
        self.device_id = device_id


class InvalidCapabilityError(DeviceError):
    """Raised when accessing an unsupported capability."""

    def __init__(self, device_id: str, capability: str) -> None:
        """Initialize with device and capability."""
        super().__init__(f"Device {device_id} does not support {capability}")
        self.device_id = device_id
        self.capability = capability


class PairingError(DeviceError):
    """Raised when device pairing fails."""

    pass


class FirmwareUpdateError(DeviceError):
    """Raised when firmware update fails."""

    pass


class ProtocolError(SmartHomeException):
    """Raised when protocol operations fail."""

    pass


class ConnectionError(ProtocolError):
    """Raised when unable to connect via protocol."""

    pass


class MessageRoutingError(ProtocolError):
    """Raised when message routing fails."""

    pass


class BridgeError(ProtocolError):
    """Raised when protocol bridging fails."""

    pass


class SerializationError(ProtocolError):
    """Raised when message serialization fails."""

    pass


class AutomationError(SmartHomeException):
    """Raised when automation operations fail."""

    pass


class TriggerError(AutomationError):
    """Raised when trigger evaluation fails."""

    pass


class ConditionError(AutomationError):
    """Raised when condition evaluation fails."""

    pass


class ActionError(AutomationError):
    """Raised when action execution fails."""

    pass


class ConflictError(AutomationError):
    """Raised when automation conflicts are detected."""

    pass


class SecurityError(SmartHomeException):
    """Raised for security-related errors."""

    pass


class AlarmError(SecurityError):
    """Raised when alarm operations fail."""

    pass


class SensorError(SecurityError):
    """Raised for sensor-related security errors."""

    pass


class AccessDeniedError(SecurityError):
    """Raised when access is denied."""

    def __init__(self, reason: str = "Access denied") -> None:
        """Initialize with reason."""
        super().__init__(reason)


class SceneError(SmartHomeException):
    """Raised when scene operations fail."""

    pass


class SceneNotFoundError(SceneError):
    """Raised when a scene is not found."""

    def __init__(self, scene_id: str) -> None:
        """Initialize with scene ID."""
        super().__init__(f"Scene {scene_id} not found")
        self.scene_id = scene_id


class ClimateError(SmartHomeException):
    """Raised for climate control errors."""

    pass


class ThermostatError(ClimateError):
    """Raised for thermostat operations."""

    pass


class LightingError(SmartHomeException):
    """Raised for lighting control errors."""

    pass


class ColorConversionError(LightingError):
    """Raised when color conversion fails."""

    pass


class EnergyError(SmartHomeException):
    """Raised for energy management errors."""

    pass


class VoiceError(SmartHomeException):
    """Raised for voice control errors."""

    pass


class IntentParsingError(VoiceError):
    """Raised when voice intent parsing fails."""

    pass


class CommandDisambiguationError(VoiceError):
    """Raised when command is ambiguous."""

    pass


class CommandExecutionError(VoiceError):
    """Raised when voice command execution fails."""

    pass


class ConfigurationError(SmartHomeException):
    """Raised for configuration errors."""

    pass


class ValidationError(SmartHomeException):
    """Raised for validation errors."""

    pass
