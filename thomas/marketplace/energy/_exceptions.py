"""
Custom exceptions for the energy module.

Provides specific exception types for various error conditions in energy
systems simulation and operation.
"""


class EnergyModuleException(Exception):
    """Base exception for all energy module errors."""

    pass


class GridOverloadError(EnergyModuleException):
    """Raised when grid power flow exceeds line or equipment capacity."""

    def __init__(
        self,
        line_id: str,
        current_mw: float,
        capacity_mw: float,
        percentage_excess: float = None,
    ) -> None:
        self.line_id = line_id
        self.current_mw = current_mw
        self.capacity_mw = capacity_mw
        self.percentage_excess = percentage_excess or ((current_mw / capacity_mw - 1) * 100)

        message = (
            f"Grid line {line_id} overloaded: {current_mw:.1f} MW "
            f"exceeds {capacity_mw:.1f} MW capacity ({self.percentage_excess:.1f}% over)"
        )
        super().__init__(message)


class StorageDepletedError(EnergyModuleException):
    """Raised when energy storage cannot provide requested power."""

    def __init__(
        self,
        storage_id: str,
        requested_mw: float,
        available_mw: float,
        soc: float,
    ) -> None:
        self.storage_id = storage_id
        self.requested_mw = requested_mw
        self.available_mw = available_mw
        self.soc = soc

        message = (
            f"Storage {storage_id} insufficient: requested {requested_mw:.1f} MW, "
            f"available {available_mw:.1f} MW (SOC: {soc:.1%})"
        )
        super().__init__(message)


class GenerationShortfallError(EnergyModuleException):
    """Raised when generation cannot meet demand."""

    def __init__(
        self,
        demand_mw: float,
        available_mw: float,
        shortfall_mw: float,
        timestamp: str = None,
    ) -> None:
        self.demand_mw = demand_mw
        self.available_mw = available_mw
        self.shortfall_mw = shortfall_mw
        self.timestamp = timestamp

        time_str = f" at {timestamp}" if timestamp else ""
        message = (
            f"Generation shortfall{time_str}: demand {demand_mw:.1f} MW, "
            f"available {available_mw:.1f} MW, shortfall {shortfall_mw:.1f} MW"
        )
        super().__init__(message)


class FrequencyDeviationError(EnergyModuleException):
    """Raised when grid frequency deviates beyond safe limits."""

    def __init__(
        self,
        current_frequency: float,
        nominal_frequency: float = 60.0,
        threshold: float = 0.2,
    ) -> None:
        self.current_frequency = current_frequency
        self.nominal_frequency = nominal_frequency
        self.deviation = current_frequency - nominal_frequency
        self.threshold = threshold

        message = (
            f"Frequency deviation: {current_frequency:.2f} Hz "
            f"(nominal {nominal_frequency:.1f} Hz), "
            f"deviation {self.deviation:.2f} Hz exceeds threshold ±{threshold:.2f} Hz"
        )
        super().__init__(message)


class VoltageViolationError(EnergyModuleException):
    """Raised when bus voltage is outside acceptable range."""

    def __init__(
        self,
        bus_id: int,
        voltage_pu: float,
        min_voltage: float = 0.95,
        max_voltage: float = 1.05,
    ) -> None:
        self.bus_id = bus_id
        self.voltage_pu = voltage_pu
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage

        message = (
            f"Voltage violation at bus {bus_id}: {voltage_pu:.3f} p.u. "
            f"outside [{min_voltage:.2f}, {max_voltage:.2f}] p.u."
        )
        super().__init__(message)


class NoFeasibleSolutionError(EnergyModuleException):
    """Raised when optimization has no feasible solution."""

    def __init__(self, reason: str = None) -> None:
        self.reason = reason
        message = "No feasible solution found"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class ConvergenceError(EnergyModuleException):
    """Raised when power flow or optimization fails to converge."""

    def __init__(
        self,
        iterations: int,
        tolerance: float,
        final_error: float,
        algorithm: str = None,
    ) -> None:
        self.iterations = iterations
        self.tolerance = tolerance
        self.final_error = final_error
        self.algorithm = algorithm

        algo_str = f" ({algorithm})" if algorithm else ""
        message = (
            f"Failed to converge{algo_str} after {iterations} iterations: "
            f"error {final_error:.2e} > tolerance {tolerance:.2e}"
        )
        super().__init__(message)


class InvalidModelError(EnergyModuleException):
    """Raised when model parameters or configuration is invalid."""

    def __init__(self, component: str, issue: str) -> None:
        self.component = component
        self.issue = issue
        message = f"Invalid {component} model: {issue}"
        super().__init__(message)


class DataError(EnergyModuleException):
    """Raised when input data is malformed or invalid."""

    def __init__(self, data_type: str, issue: str) -> None:
        self.data_type = data_type
        self.issue = issue
        message = f"Data error in {data_type}: {issue}"
        super().__init__(message)


class ConstraintViolationError(EnergyModuleException):
    """Raised when operational constraint is violated."""

    def __init__(self, plant_id: str, constraint: str, value: float, limit: float) -> None:
        self.plant_id = plant_id
        self.constraint = constraint
        self.value = value
        self.limit = limit

        message = f"Constraint violation in plant {plant_id}: {constraint} {value:.2f} exceeds limit {limit:.2f}"
        super().__init__(message)


class MarketError(EnergyModuleException):
    """Raised when market operation encounters an error."""

    def __init__(self, issue: str) -> None:
        self.issue = issue
        message = f"Market error: {issue}"
        super().__init__(message)


class ForecastingError(EnergyModuleException):
    """Raised when forecasting operation fails."""

    def __init__(self, forecast_type: str, reason: str) -> None:
        self.forecast_type = forecast_type
        self.reason = reason
        message = f"Forecasting error ({forecast_type}): {reason}"
        super().__init__(message)
