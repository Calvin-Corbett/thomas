"""
Supply chain management custom exceptions.

This module defines exception classes for various supply chain operations
and error conditions.
"""


class SupplyChainException(Exception):
    """Base exception for supply chain module."""

    pass


class InventoryException(SupplyChainException):
    """Base exception for inventory operations."""

    pass


class InsufficientInventoryException(InventoryException):
    """Raised when there is insufficient inventory to fulfill a request."""

    def __init__(self, sku: str, warehouse_id: str, requested: int, available: int) -> None:
        self.sku = sku
        self.warehouse_id = warehouse_id
        self.requested = requested
        self.available = available
        message = (
            f"Insufficient inventory for SKU {sku} at warehouse {warehouse_id}. "
            f"Requested: {requested}, Available: {available}"
        )
        super().__init__(message)


class InvalidInventoryValuationException(InventoryException):
    """Raised when inventory valuation method is invalid."""

    pass


class InventoryCycleCountException(InventoryException):
    """Raised during inventory cycle counting errors."""

    pass


class DemandForecastException(SupplyChainException):
    """Base exception for demand forecasting."""

    pass


class InsufficientHistoricalDataException(DemandForecastException):
    """Raised when there is insufficient historical data for forecasting."""

    def __init__(self, sku: str, min_periods: int, available: int) -> None:
        self.sku = sku
        self.min_periods = min_periods
        self.available = available
        message = f"Insufficient historical data for SKU {sku}. Required: {min_periods} periods, Available: {available}"
        super().__init__(message)


class InvalidForecastMethodException(DemandForecastException):
    """Raised when forecast method is not supported."""

    def __init__(self, method: str) -> None:
        self.method = method
        message = f"Unsupported forecast method: {method}"
        super().__init__(message)


class LogisticsException(SupplyChainException):
    """Base exception for logistics operations."""

    pass


class InvalidRouteException(LogisticsException):
    """Raised when route is invalid or cannot be optimized."""

    pass


class CapacityException(LogisticsException):
    """Raised when vehicle or route capacity is exceeded."""

    def __init__(self, resource: str, capacity: float, required: float) -> None:
        self.resource = resource
        self.capacity = capacity
        self.required = required
        message = f"Capacity exceeded for {resource}. Capacity: {capacity}, Required: {required}"
        super().__init__(message)


class TimeWindowViolationException(LogisticsException):
    """Raised when time window constraint is violated."""

    pass


class ProcurementException(SupplyChainException):
    """Base exception for procurement operations."""

    pass


class InvalidSupplierException(ProcurementException):
    """Raised when supplier is invalid or not approved."""

    def __init__(self, supplier_id: str) -> None:
        self.supplier_id = supplier_id
        message = f"Invalid or inactive supplier: {supplier_id}"
        super().__init__(message)


class LeadTimeViolationException(ProcurementException):
    """Raised when lead time requirements cannot be met."""

    pass


class WarehouseException(SupplyChainException):
    """Base exception for warehouse operations."""

    pass


class WarehouseCapacityException(WarehouseException):
    """Raised when warehouse capacity is exceeded."""

    def __init__(self, warehouse_id: str, current: float, capacity: float) -> None:
        self.warehouse_id = warehouse_id
        self.current = current
        self.capacity = capacity
        message = f"Warehouse {warehouse_id} capacity exceeded. Current: {current}, Capacity: {capacity}"
        super().__init__(message)


class InvalidSlottingException(WarehouseException):
    """Raised when slotting assignment is invalid."""

    pass


class ProductionException(SupplyChainException):
    """Base exception for production operations."""

    pass


class MaterialShortageException(ProductionException):
    """Raised when required materials are not available."""

    def __init__(self, sku: str, required: int, available: int) -> None:
        self.sku = sku
        self.required = required
        self.available = available
        message = f"Material shortage for SKU {sku}. Required: {required}, Available: {available}"
        super().__init__(message)


class BottleneckException(ProductionException):
    """Raised when production bottleneck is detected."""

    def __init__(self, resource: str, utilization: float) -> None:
        self.resource = resource
        self.utilization = utilization
        message = f"Production bottleneck detected at {resource} ({utilization}% utilized)"
        super().__init__(message)


class TransportationException(SupplyChainException):
    """Base exception for transportation operations."""

    pass


class InvalidTransportationProblemException(TransportationException):
    """Raised when transportation problem is infeasible."""

    pass


class InvalidShipmentException(TransportationException):
    """Raised when shipment is invalid."""

    pass


class NetworkException(SupplyChainException):
    """Base exception for supply chain network operations."""

    pass


class FacilityLocationException(NetworkException):
    """Raised when facility location problem cannot be solved."""

    pass


class NetworkFlowException(NetworkException):
    """Raised when network flow optimization fails."""

    pass


class QualityException(SupplyChainException):
    """Base exception for quality operations."""

    pass


class QualityInspectionFailedException(QualityException):
    """Raised when quality inspection fails."""

    def __init__(self, batch_number: str, defect_rate: float) -> None:
        self.batch_number = batch_number
        self.defect_rate = defect_rate
        message = f"Quality inspection failed for batch {batch_number}. Defect rate: {defect_rate}%"
        super().__init__(message)


class ReturnException(SupplyChainException):
    """Base exception for return operations."""

    pass


class InvalidReturnException(ReturnException):
    """Raised when return request is invalid."""

    pass


class AnalyticsException(SupplyChainException):
    """Base exception for analytics operations."""

    pass


class DataValidationException(SupplyChainException):
    """Raised when input data validation fails."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        message = f"Data validation failed for field '{field}': {reason}"
        super().__init__(message)
