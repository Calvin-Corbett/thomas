"""
Custom exceptions for the telecommunications network module.

Provides domain-specific exceptions for various network operations.
"""


class TelecomError(Exception):
    """Base exception for all telecom module errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class NoSignalError(TelecomError):
    """Raised when a subscriber has no signal in a cell."""

    def __init__(self, msisdn: str, cell_id: str, signal_dbm: float) -> None:
        self.msisdn = msisdn
        self.cell_id = cell_id
        self.signal_dbm = signal_dbm
        message = f"Subscriber {msisdn} has no signal in cell {cell_id} (signal: {signal_dbm} dBm)"
        super().__init__(message)


class InterferenceError(TelecomError):
    """Raised when interference levels exceed acceptable thresholds."""

    def __init__(self, frequency_mhz: float, interference_dbm: float, threshold_dbm: float) -> None:
        self.frequency_mhz = frequency_mhz
        self.interference_dbm = interference_dbm
        self.threshold_dbm = threshold_dbm
        message = (
            f"Interference on frequency {frequency_mhz} MHz exceeds threshold: "
            f"{interference_dbm} dBm > {threshold_dbm} dBm"
        )
        super().__init__(message)


class HandoverFailedError(TelecomError):
    """Raised when a handover operation fails."""

    def __init__(self, msisdn: str, source_cell: str, target_cell: str, reason: str) -> None:
        self.msisdn = msisdn
        self.source_cell = source_cell
        self.target_cell = target_cell
        self.reason = reason
        message = f"Handover failed for subscriber {msisdn} from {source_cell} to {target_cell}: {reason}"
        super().__init__(message)


class BillingError(TelecomError):
    """Raised when a billing operation fails."""

    def __init__(self, msisdn: str, reason: str) -> None:
        self.msisdn = msisdn
        self.reason = reason
        message = f"Billing error for subscriber {msisdn}: {reason}"
        super().__init__(message)


class SpectrumError(TelecomError):
    """Raised when spectrum allocation or management fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProtocolError(TelecomError):
    """Raised when protocol operation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ResourceAllocationError(TelecomError):
    """Raised when resource allocation fails."""

    def __init__(self, resource_type: str, requested: float, available: float) -> None:
        self.resource_type = resource_type
        self.requested = requested
        self.available = available
        message = f"Cannot allocate {resource_type}: requested {requested}, available {available}"
        super().__init__(message)


class QoSViolationError(TelecomError):
    """Raised when QoS requirements cannot be met."""

    def __init__(self, qos_param: str, required: float, achieved: float) -> None:
        self.qos_param = qos_param
        self.required = required
        self.achieved = achieved
        message = f"QoS violation for {qos_param}: required {required}, achieved {achieved}"
        super().__init__(message)


class SubscriberNotFoundError(TelecomError):
    """Raised when a subscriber cannot be found."""

    def __init__(self, msisdn: str) -> None:
        self.msisdn = msisdn
        message = f"Subscriber not found: {msisdn}"
        super().__init__(message)


class InvalidConfigurationError(TelecomError):
    """Raised when configuration is invalid."""

    def __init__(self, parameter: str, value: str, reason: str) -> None:
        self.parameter = parameter
        self.value = value
        self.reason = reason
        message = f"Invalid configuration for {parameter}={value}: {reason}"
        super().__init__(message)


class CoverageError(TelecomError):
    """Raised when coverage is insufficient."""

    def __init__(self, location: str, message: str) -> None:
        self.location = location
        super().__init__(f"Coverage error at {location}: {message}")


class RoamingError(TelecomError):
    """Raised when roaming operation fails."""

    def __init__(self, msisdn: str, home_network: str, visited_network: str) -> None:
        self.msisdn = msisdn
        self.home_network = home_network
        self.visited_network = visited_network
        message = f"Roaming error for subscriber {msisdn} from {home_network} to {visited_network}"
        super().__init__(message)


__all__ = [
    "TelecomError",
    "NoSignalError",
    "InterferenceError",
    "HandoverFailedError",
    "BillingError",
    "SpectrumError",
    "ProtocolError",
    "ResourceAllocationError",
    "QoSViolationError",
    "SubscriberNotFoundError",
    "InvalidConfigurationError",
    "CoverageError",
    "RoamingError",
]
