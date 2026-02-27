"""
Supply chain type definitions and data structures.

This module defines comprehensive types for supply chain management including
products, warehouses, suppliers, orders, shipments, and various operational entities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4


class TransportMode(Enum):
    """Enumeration of transportation modes."""

    TRUCK = "truck"
    RAIL = "rail"
    SHIP = "ship"
    AIR = "air"
    PIPELINE = "pipeline"
    BARGE = "barge"


class InventoryValuationMethod(Enum):
    """Inventory valuation methods."""

    FIFO = "fifo"
    LIFO = "lifo"
    WEIGHTED_AVERAGE = "weighted_average"
    STANDARD_COST = "standard_cost"


class OrderStatus(Enum):
    """Purchase order status."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ShipmentStatus(Enum):
    """Shipment status tracking."""

    CREATED = "created"
    PICKED = "picked"
    PACKED = "packed"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    RETURNED = "returned"


class QualityStatus(Enum):
    """Quality inspection status."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    CONDITIONAL = "conditional"


class ReturnReason(Enum):
    """Reasons for product returns."""

    DEFECTIVE = "defective"
    WRONG_ITEM = "wrong_item"
    DAMAGED = "damaged"
    NOT_AS_DESCRIBED = "not_as_described"
    CUSTOMER_CHANGE_MIND = "customer_change_mind"
    EXCESS_STOCK = "excess_stock"


class ProductionOrderStatus(Enum):
    """Production order status."""

    PLANNED = "planned"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"


class InventoryClassification(Enum):
    """ABC classification for inventory."""

    A = "a"  # High value, tight control
    B = "b"  # Medium value, moderate control
    C = "c"  # Low value, loose control


class DemandPattern(Enum):
    """Demand pattern classification."""

    SMOOTH = "smooth"
    TREND = "trend"
    SEASONAL = "seasonal"
    CYCLICAL = "cyclical"
    INTERMITTENT = "intermittent"
    ERRATIC = "erratic"


@dataclass
class SKU:
    """Stock Keeping Unit (SKU) identifier."""

    code: str
    product_id: UUID
    variant_code: str | None = None
    barcode: str | None = None

    def __hash__(self) -> int:
        return hash(self.code)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SKU):
            return False
        return self.code == other.code


@dataclass
class Product:
    """Product master data."""

    id: UUID
    name: str
    sku: SKU
    unit_of_measure: str = "UNIT"
    weight: Decimal = Decimal("0")
    volume: Decimal = Decimal("0")
    value: Decimal = Decimal("0")
    supplier_id: UUID | None = None
    lead_time_days: int = 0
    is_active: bool = True
    shelf_life_days: int | None = None
    requires_cold_chain: bool = False
    hazmat_class: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Warehouse:
    """Warehouse facility."""

    id: UUID
    code: str
    name: str
    location: str
    latitude: Decimal
    longitude: Decimal
    total_capacity: Decimal
    current_utilization: Decimal = Decimal("0")
    is_active: bool = True
    region: str = ""
    warehouse_type: str = "general"  # general, cross-dock, distribution
    operating_hours_start: int = 6
    operating_hours_end: int = 22
    staff_count: int = 0


@dataclass
class Supplier:
    """Supplier master data."""

    id: UUID
    code: str
    name: str
    contact_email: str
    contact_phone: str
    address: str
    payment_terms: str = "NET_30"
    delivery_lead_time_days: int = 7
    quality_score: Decimal = Decimal("100")
    reliability_score: Decimal = Decimal("100")
    cost_score: Decimal = Decimal("100")
    is_approved: bool = True
    primary_products: list[UUID] = field(default_factory=list)
    payment_methods: list[str] = field(default_factory=lambda: ["BANK_TRANSFER"])
    currency: str = "USD"


@dataclass
class InventoryLevel:
    """Current inventory level for a product at a location."""

    sku: SKU
    warehouse_id: UUID
    quantity_on_hand: Decimal
    quantity_reserved: Decimal = Decimal("0")
    quantity_in_transit: Decimal = Decimal("0")
    quantity_damaged: Decimal = Decimal("0")
    last_counted: datetime = field(default_factory=datetime.utcnow)
    valuation_method: InventoryValuationMethod = InventoryValuationMethod.FIFO
    unit_cost: Decimal = Decimal("0")
    abc_class: InventoryClassification | None = None

    @property
    def quantity_available(self) -> Decimal:
        """Calculate available quantity for allocation."""
        return self.quantity_on_hand - self.quantity_reserved - self.quantity_damaged


@dataclass
class DemandForecast:
    """Demand forecast for a product."""

    id: UUID
    sku: SKU
    forecast_date: datetime
    forecast_periods: int
    forecasted_demand: list[Decimal]
    confidence_interval: Decimal = Decimal("95")
    forecast_method: str = "exponential_smoothing"
    accuracy_mae: Decimal | None = None
    accuracy_mape: Decimal | None = None
    accuracy_rmse: Decimal | None = None
    demand_pattern: DemandPattern | None = None
    trend_factor: Decimal = Decimal("1.0")
    seasonal_factors: list[Decimal] = field(default_factory=list)


@dataclass
class PurchaseOrder:
    """Purchase order for procurement."""

    id: UUID
    po_number: str
    supplier_id: UUID
    status: OrderStatus = OrderStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.utcnow)
    expected_delivery: datetime | None = None
    actual_delivery: datetime | None = None
    line_items: list["OrderLineItem"] = field(default_factory=list)
    total_amount: Decimal = Decimal("0")
    currency: str = "USD"
    delivery_warehouse_id: UUID | None = None
    incoterm: str = "FOB"
    notes: str = ""


@dataclass
class OrderLineItem:
    """Line item in a purchase order."""

    id: UUID
    sku: SKU
    quantity_ordered: Decimal
    unit_price: Decimal
    quantity_received: Decimal = Decimal("0")
    line_total: Decimal = field(default_factory=Decimal)
    delivery_date: datetime | None = None
    quality_status: QualityStatus = QualityStatus.PENDING

    def __post_init__(self) -> None:
        if not self.line_total:
            self.line_total = self.quantity_ordered * self.unit_price


@dataclass
class Shipment:
    """Shipment for order fulfillment."""

    id: UUID
    shipment_number: str
    status: ShipmentStatus = ShipmentStatus.CREATED
    origin_warehouse_id: UUID = field(default_factory=uuid4)
    destination_address: str = ""
    transport_mode: TransportMode = TransportMode.TRUCK
    carrier: str = ""
    tracking_number: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    ship_date: datetime | None = None
    expected_delivery: datetime | None = None
    actual_delivery: datetime | None = None
    line_items: list["ShipmentLineItem"] = field(default_factory=list)
    total_weight: Decimal = Decimal("0")
    total_volume: Decimal = Decimal("0")
    freight_cost: Decimal = Decimal("0")
    insurance_cost: Decimal = Decimal("0")
    temperature_controlled: bool = False
    temperature_min: Decimal | None = None
    temperature_max: Decimal | None = None


@dataclass
class ShipmentLineItem:
    """Line item in a shipment."""

    id: UUID
    sku: SKU
    quantity_shipped: Decimal
    quantity_delivered: Decimal = Decimal("0")
    weight: Decimal = Decimal("0")
    volume: Decimal = Decimal("0")


@dataclass
class Route:
    """Delivery route."""

    id: UUID
    route_code: str
    origin_warehouse_id: UUID
    stops: list["RouteStop"] = field(default_factory=list)
    total_distance: Decimal = Decimal("0")
    total_duration_minutes: int = 0
    vehicle_id: str = ""
    driver_id: str = ""
    route_date: datetime = field(default_factory=datetime.utcnow)
    total_cost: Decimal = Decimal("0")
    status: str = "planned"  # planned, in_progress, completed


@dataclass
class RouteStop:
    """Stop on a delivery route."""

    id: UUID
    sequence: int
    location_address: str
    latitude: Decimal
    longitude: Decimal
    shipment_id: UUID | None = None
    planned_arrival: datetime | None = None
    actual_arrival: datetime | None = None
    service_time_minutes: int = 0
    items_count: int = 0


@dataclass
class BillOfMaterials:
    """Bill of Materials (BOM) for a product."""

    id: UUID
    product_id: UUID
    version: int = 1
    components: list["BOMComponent"] = field(default_factory=list)
    effective_date: datetime = field(default_factory=datetime.utcnow)
    revision_date: datetime | None = None
    is_active: bool = True
    lead_time_days: int = 0


@dataclass
class BOMComponent:
    """Component in a BOM."""

    id: UUID
    component_sku: SKU
    quantity_per_unit: Decimal
    unit_of_measure: str = "UNIT"
    waste_percentage: Decimal = Decimal("0")
    substitutes: list[SKU] = field(default_factory=list)

    @property
    def effective_quantity(self) -> Decimal:
        """Calculate effective quantity including waste."""
        waste_factor = Decimal("1") + (self.waste_percentage / Decimal("100"))
        return self.quantity_per_unit * waste_factor


@dataclass
class ProductionOrder:
    """Production order."""

    id: UUID
    order_number: str
    product_id: UUID
    quantity: Decimal
    status: ProductionOrderStatus = ProductionOrderStatus.PLANNED
    created_at: datetime = field(default_factory=datetime.utcnow)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    bill_of_materials_id: UUID = field(default_factory=uuid4)
    required_materials: list["MaterialRequirement"] = field(default_factory=list)
    cost_estimate: Decimal = Decimal("0")
    actual_cost: Decimal = Decimal("0")
    scrap_quantity: Decimal = Decimal("0")


@dataclass
class MaterialRequirement:
    """Material required for production."""

    id: UUID
    sku: SKU
    quantity_required: Decimal
    quantity_issued: Decimal = Decimal("0")
    quantity_consumed: Decimal = Decimal("0")
    warehouse_id: UUID = field(default_factory=uuid4)


@dataclass
class QualityInspection:
    """Quality inspection record."""

    id: UUID
    inspection_date: datetime = field(default_factory=datetime.utcnow)
    sku: SKU = field(default_factory=lambda: SKU("", uuid4()))
    batch_number: str = ""
    sample_size: int = 0
    defects_found: int = 0
    status: QualityStatus = QualityStatus.PENDING
    inspector_id: str = ""
    notes: str = ""
    corrective_actions: list[str] = field(default_factory=list)

    @property
    def defect_rate(self) -> Decimal:
        """Calculate defect rate percentage."""
        if self.sample_size == 0:
            return Decimal("0")
        return (Decimal(self.defects_found) / Decimal(self.sample_size)) * Decimal("100")


@dataclass
class ReturnRequest:
    """Product return request."""

    id: UUID
    return_number: str
    shipment_id: UUID
    sku: SKU
    quantity: Decimal
    reason: ReturnReason
    status: str = "pending"  # pending, approved, received, restocked, scrapped
    requested_date: datetime = field(default_factory=datetime.utcnow)
    approved_date: datetime | None = None
    received_date: datetime | None = None
    return_reason_detail: str = ""
    refund_amount: Decimal = Decimal("0")


@dataclass
class CostBreakdown:
    """Detailed cost breakdown for logistics."""

    freight_cost: Decimal = Decimal("0")
    fuel_surcharge: Decimal = Decimal("0")
    handling_cost: Decimal = Decimal("0")
    insurance_cost: Decimal = Decimal("0")
    customs_duty: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")
    storage_cost: Decimal = Decimal("0")
    labor_cost: Decimal = Decimal("0")
    packaging_cost: Decimal = Decimal("0")
    other_costs: Decimal = Decimal("0")

    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost."""
        return (
            self.freight_cost
            + self.fuel_surcharge
            + self.handling_cost
            + self.insurance_cost
            + self.customs_duty
            + self.taxes
            + self.storage_cost
            + self.labor_cost
            + self.packaging_cost
            + self.other_costs
        )

    def to_dict(self) -> dict[str, Decimal]:
        """Convert to dictionary."""
        return {
            "freight_cost": self.freight_cost,
            "fuel_surcharge": self.fuel_surcharge,
            "handling_cost": self.handling_cost,
            "insurance_cost": self.insurance_cost,
            "customs_duty": self.customs_duty,
            "taxes": self.taxes,
            "storage_cost": self.storage_cost,
            "labor_cost": self.labor_cost,
            "packaging_cost": self.packaging_cost,
            "other_costs": self.other_costs,
            "total_cost": self.total_cost,
        }
