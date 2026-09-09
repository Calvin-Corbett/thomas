"""
Thomas Supply Chain Management and Logistics Optimization Module.

A comprehensive supply chain management system providing inventory optimization,
demand forecasting, logistics planning, procurement management, warehouse
operations, production scheduling, transportation optimization, network design,
and supply chain analytics.

Modules:
    _types: Core data types and domain models
    _exceptions: Custom exception classes
    inventory: Inventory management (ABC/XYZ, EOQ, reorder points, valuation)
    demand: Demand forecasting (exponential smoothing, Croston's method, Bass model)
    logistics: Logistics optimization (VRP, time windows, last-mile, consolidation)
    procurement: Procurement (supplier scoring, RFQ, spend analysis, TCO)
    warehouse: Warehouse operations (slotting, pick paths, wave planning, dock scheduling)
    production: Production planning (MRP, capacity planning, job scheduling, lot sizing)
    transportation: Transportation (mode selection, rates, bin packing, tracking)
    network: Network design (facility location, network flow, make-vs-buy, disruption risk)
    analytics: Supply chain analytics (KPIs, bullwhip, landed cost, risk assessment)

Example:
    >>> from thomas.supply_chain import inventory, demand, logistics
    >>> from thomas.supply_chain._types import SKU, Product, Warehouse
    >>> from uuid import UUID
    >>>
    >>> # Create SKU and inventory manager
    >>> sku = SKU(code="PROD001", product_id=UUID(int=0))
    >>> inv_mgr = inventory.InventoryManager()
    >>>
    >>> # Calculate Economic Order Quantity
    >>> eoq = inv_mgr.calculate_eoq(
    ...     sku=sku,
    ...     annual_demand=1000,
    ...     order_cost=50,
    ...     holding_cost_per_unit=2
    ... )
    >>> print(f"EOQ: {eoq.economic_order_quantity} units")
"""

from thomas.supply_chain._exceptions import (
    AnalyticsException,
    BottleneckException,
    CapacityException,
    DataValidationException,
    DemandForecastException,
    FacilityLocationException,
    InsufficientHistoricalDataException,
    InsufficientInventoryException,
    InvalidForecastMethodException,
    InvalidInventoryValuationException,
    InvalidReturnException,
    InvalidRouteException,
    InvalidShipmentException,
    InvalidSlottingException,
    InvalidSupplierException,
    InvalidTransportationProblemException,
    InventoryCycleCountException,
    InventoryException,
    LeadTimeViolationException,
    LogisticsException,
    MaterialShortageException,
    NetworkException,
    NetworkFlowException,
    ProcurementException,
    ProductionException,
    QualityException,
    QualityInspectionFailedException,
    ReturnException,
    SupplyChainException,
    TimeWindowViolationException,
    TransportationException,
    WarehouseCapacityException,
    WarehouseException,
)
from thomas.supply_chain._types import (
    # Core types
    SKU,
    BillOfMaterials,
    BOMComponent,
    CostBreakdown,
    DemandForecast,
    DemandPattern,
    InventoryClassification,
    InventoryLevel,
    InventoryValuationMethod,
    MaterialRequirement,
    OrderLineItem,
    OrderStatus,
    Product,
    ProductionOrder,
    ProductionOrderStatus,
    PurchaseOrder,
    QualityInspection,
    QualityStatus,
    ReturnReason,
    ReturnRequest,
    Route,
    RouteStop,
    Shipment,
    ShipmentLineItem,
    ShipmentStatus,
    Supplier,
    # Enumerations
    TransportMode,
    Warehouse,
)
from thomas.supply_chain.analytics import (
    BullwhipMetrics,
    KPIDashboard,
    RiskHeatMap,
    ScenarioAnalysis,
    SupplyChainAnalytics,
    SupplyChainEdge,
    SupplyChainNode,
    TotalLandedCost,
)
from thomas.supply_chain.demand import (
    BassModel,
    DemandDecomposition,
    DemandForecaster,
    ForecastAccuracy,
)
from thomas.supply_chain.inventory import (
    ABCClassification,
    EOQResult,
    InventoryManager,
    InventorySnapshot,
    ReorderPoint,
    ReviewPolicyResult,
    XYZClassification,
)
from thomas.supply_chain.logistics import (
    ConsolidationPlan,
    Location,
    LogisticsOptimizer,
    RoutingResult,
    Vehicle,
)
from thomas.supply_chain.network import (
    DisruptionAnalysis,
    Facility,
    FacilityLocationResult,
    LocationCost,
    MakeVsBuyAnalysis,
    MinCostFlow,
    MultiPeriodPlan,
    NearshoreOffshoreAnalysis,
    NetworkDesigner,
    NetworkFlow,
    RiskScenario,
)
from thomas.supply_chain.procurement import (
    ContractTerms,
    LeadTimeAnalysis,
    ProcurementManager,
    RFQResponse,
    SpendAnalysis,
    SupplierScore,
    TotalCostOfOwnership,
)
from thomas.supply_chain.production import (
    BottleneckAnalysis,
    CapacityRequirement,
    JobSchedule,
    LotSizingResult,
    MRPExplosion,
    OperationSchedule,
    ProductionPlanner,
    WIPStatus,
)
from thomas.supply_chain.transportation import (
    CarrierOption,
    CarrierSelection,
    Container,
    FreightRate,
    Item,
    ShipmentState,
    TransportationAllocation,
    TransportationOptimizer,
    TransportationProblemResult,
)
from thomas.supply_chain.warehouse import (
    DockSchedule,
    LaborPlan,
    PickPath,
    PutAwayInstruction,
    SlotAssignment,
    StorageZone,
    WarehouseOptimizer,
    Wave,
)

__version__ = "1.0.0"
__author__ = "Claude"
__all__ = [
    # Enumerations
    "TransportMode",
    "InventoryValuationMethod",
    "OrderStatus",
    "ShipmentStatus",
    "QualityStatus",
    "ReturnReason",
    "ProductionOrderStatus",
    "InventoryClassification",
    "DemandPattern",
    # Core types
    "SKU",
    "Product",
    "Warehouse",
    "Supplier",
    "InventoryLevel",
    "DemandForecast",
    "PurchaseOrder",
    "OrderLineItem",
    "Shipment",
    "ShipmentLineItem",
    "Route",
    "RouteStop",
    "BillOfMaterials",
    "BOMComponent",
    "ProductionOrder",
    "MaterialRequirement",
    "QualityInspection",
    "ReturnRequest",
    "CostBreakdown",
    # Exceptions
    "SupplyChainException",
    "InventoryException",
    "InsufficientInventoryException",
    "InvalidInventoryValuationException",
    "InventoryCycleCountException",
    "DemandForecastException",
    "InsufficientHistoricalDataException",
    "InvalidForecastMethodException",
    "LogisticsException",
    "InvalidRouteException",
    "CapacityException",
    "TimeWindowViolationException",
    "ProcurementException",
    "InvalidSupplierException",
    "LeadTimeViolationException",
    "WarehouseException",
    "WarehouseCapacityException",
    "InvalidSlottingException",
    "ProductionException",
    "MaterialShortageException",
    "BottleneckException",
    "TransportationException",
    "InvalidTransportationProblemException",
    "InvalidShipmentException",
    "NetworkException",
    "FacilityLocationException",
    "NetworkFlowException",
    "QualityException",
    "QualityInspectionFailedException",
    "ReturnException",
    "InvalidReturnException",
    "AnalyticsException",
    "DataValidationException",
    # Managers/Optimizers
    "InventoryManager",
    "DemandForecaster",
    "LogisticsOptimizer",
    "ProcurementManager",
    "WarehouseOptimizer",
    "ProductionPlanner",
    "TransportationOptimizer",
    "NetworkDesigner",
    "SupplyChainAnalytics",
    # Result types
    "EOQResult",
    "ReorderPoint",
    "ReviewPolicyResult",
    "ABCClassification",
    "XYZClassification",
    "InventorySnapshot",
    "ForecastAccuracy",
    "DemandDecomposition",
    "BassModel",
    "Location",
    "Vehicle",
    "RoutingResult",
    "ConsolidationPlan",
    "SupplierScore",
    "RFQResponse",
    "ContractTerms",
    "SpendAnalysis",
    "LeadTimeAnalysis",
    "TotalCostOfOwnership",
    "SlotAssignment",
    "PickPath",
    "Wave",
    "DockSchedule",
    "PutAwayInstruction",
    "StorageZone",
    "LaborPlan",
    "MRPExplosion",
    "CapacityRequirement",
    "JobSchedule",
    "OperationSchedule",
    "BottleneckAnalysis",
    "LotSizingResult",
    "WIPStatus",
    "TransportationAllocation",
    "TransportationProblemResult",
    "CarrierOption",
    "CarrierSelection",
    "FreightRate",
    "Container",
    "Item",
    "ShipmentState",
    "Facility",
    "FacilityLocationResult",
    "NetworkFlow",
    "MinCostFlow",
    "MakeVsBuyAnalysis",
    "LocationCost",
    "NearshoreOffshoreAnalysis",
    "MultiPeriodPlan",
    "RiskScenario",
    "DisruptionAnalysis",
    "KPIDashboard",
    "BullwhipMetrics",
    "TotalLandedCost",
    "SupplyChainNode",
    "SupplyChainEdge",
    "RiskHeatMap",
    "ScenarioAnalysis",
]
