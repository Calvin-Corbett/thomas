"""Shipping calculation and carrier management."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from ._types import ShippingMethod


class ShippingStatus(str, Enum):
    """Shipment status enumeration."""

    PENDING = "pending"
    PICKED = "picked"
    PACKED = "packed"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class ShippingRate:
    """Shipping rate definition."""

    method: ShippingMethod
    base_rate: Decimal
    weight_rate_per_pound: Decimal = Decimal("0")
    min_rate: Decimal = Decimal("0")
    max_rate: Decimal | None = None
    estimated_days_min: int = 0
    estimated_days_max: int = 0


@dataclass
class Package:
    """Package in shipment."""

    id: str
    items: list[dict[str, Any]]
    weight_pounds: Decimal
    length_inches: Decimal
    width_inches: Decimal
    height_inches: Decimal
    tracking_number: str | None = None
    carrier: str = ""
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    status: ShippingStatus = ShippingStatus.PENDING

    def get_dimensions_cubic_inches(self) -> Decimal:
        """Calculate package dimensions in cubic inches."""
        return self.length_inches * self.width_inches * self.height_inches

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "weight_pounds": str(self.weight_pounds),
            "length_inches": str(self.length_inches),
            "width_inches": str(self.width_inches),
            "height_inches": str(self.height_inches),
            "tracking_number": self.tracking_number,
            "carrier": self.carrier,
            "shipped_at": self.shipped_at.isoformat() if self.shipped_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "status": self.status.value,
        }


class ShippingCalculator:
    """Calculate shipping costs and delivery times."""

    def __init__(self) -> None:
        """Initialize shipping calculator."""
        self.rates: dict[str, list[ShippingRate]] = {}
        self.zone_rates: dict[str, dict[str, ShippingRate]] = {}
        self.free_shipping_threshold: Decimal = Decimal("100")

    def add_rate(self, method: ShippingMethod, rate: ShippingRate) -> None:
        """Add shipping rate.

        Args:
            method: Shipping method
            rate: Shipping rate details
        """
        if method.value not in self.rates:
            self.rates[method.value] = []
        self.rates[method.value].append(rate)

    def add_zone_rate(self, zone: str, method: ShippingMethod, rate: ShippingRate) -> None:
        """Add zone-specific shipping rate.

        Args:
            zone: Shipping zone (country, state, postal code)
            method: Shipping method
            rate: Shipping rate
        """
        if zone not in self.zone_rates:
            self.zone_rates[zone] = {}
        self.zone_rates[zone][method.value] = rate

    def calculate_flat_rate(self, method: ShippingMethod) -> Decimal:
        """Get flat rate for shipping method.

        Args:
            method: Shipping method

        Returns:
            Shipping cost
        """
        rates = self.rates.get(method.value, [])
        if rates:
            return rates[0].base_rate
        return Decimal("0")

    def calculate_weight_based_rate(
        self,
        method: ShippingMethod,
        weight_pounds: Decimal,
    ) -> Decimal:
        """Calculate shipping based on weight.

        Args:
            method: Shipping method
            weight_pounds: Package weight

        Returns:
            Shipping cost
        """
        rates = self.rates.get(method.value, [])
        if not rates:
            return Decimal("0")

        rate = rates[0]
        total = rate.base_rate + (weight_pounds * rate.weight_rate_per_pound)

        # Apply min/max
        if total < rate.min_rate:
            total = rate.min_rate
        if rate.max_rate and total > rate.max_rate:
            total = rate.max_rate

        return total

    def calculate_zone_rate(
        self,
        zone: str,
        method: ShippingMethod,
        weight_pounds: Decimal | None = None,
    ) -> Decimal:
        """Calculate zone-based shipping rate.

        Args:
            zone: Shipping zone
            method: Shipping method
            weight_pounds: Optional weight for calculation

        Returns:
            Shipping cost
        """
        zone_method = self.zone_rates.get(zone, {}).get(method.value)
        if not zone_method:
            return self.calculate_weight_based_rate(method, weight_pounds or Decimal("0"))

        total = zone_method.base_rate
        if weight_pounds:
            total += weight_pounds * zone_method.weight_rate_per_pound

        if total < zone_method.min_rate:
            total = zone_method.min_rate
        if zone_method.max_rate and total > zone_method.max_rate:
            total = zone_method.max_rate

        return total

    def apply_free_shipping(self, cart_total: Decimal, shipping_cost: Decimal) -> Decimal:
        """Apply free shipping threshold.

        Args:
            cart_total: Cart total
            shipping_cost: Calculated shipping cost

        Returns:
            Final shipping cost (may be 0)
        """
        if cart_total >= self.free_shipping_threshold:
            return Decimal("0")
        return shipping_cost

    def get_estimated_delivery(
        self,
        method: ShippingMethod,
        ship_date: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        """Get estimated delivery date range.

        Args:
            method: Shipping method
            ship_date: Date package ships (defaults to today)

        Returns:
            Tuple of (min_delivery_date, max_delivery_date)
        """
        if not ship_date:
            ship_date = datetime.utcnow()

        rates = self.rates.get(method.value, [])
        if not rates:
            return (ship_date, ship_date)

        rate = rates[0]
        min_delivery = ship_date + timedelta(days=rate.estimated_days_min)
        max_delivery = ship_date + timedelta(days=rate.estimated_days_max)

        return (min_delivery, max_delivery)

    def calculate_dimensional_weight(
        self,
        length_inches: Decimal,
        width_inches: Decimal,
        height_inches: Decimal,
        divisor: int = 166,
    ) -> Decimal:
        """Calculate dimensional weight (dim weight).

        Args:
            length_inches: Length in inches
            width_inches: Width in inches
            height_inches: Height in inches
            divisor: DIM weight divisor (default 166 for standard)

        Returns:
            Dimensional weight in pounds
        """
        cubic_inches = length_inches * width_inches * height_inches
        dim_weight = cubic_inches / Decimal(divisor)
        return dim_weight.quantize(Decimal("0.1"))

    def get_billable_weight(
        self,
        actual_weight: Decimal,
        length_inches: Decimal,
        width_inches: Decimal,
        height_inches: Decimal,
    ) -> Decimal:
        """Get billable weight (actual vs dimensional).

        Args:
            actual_weight: Actual weight in pounds
            length_inches: Length in inches
            width_inches: Width in inches
            height_inches: Height in inches

        Returns:
            Billable weight (whichever is greater)
        """
        dim_weight = self.calculate_dimensional_weight(length_inches, width_inches, height_inches)
        return max(actual_weight, dim_weight)


class ShipmentTracker:
    """Track shipments and delivery status."""

    def __init__(self) -> None:
        """Initialize shipment tracker."""
        self.shipments: dict[str, Package] = {}
        self.tracking_updates: dict[str, list[dict[str, Any]]] = {}

    def create_shipment(self, package: Package) -> Package:
        """Create new shipment.

        Args:
            package: Package to ship

        Returns:
            Created package
        """
        self.shipments[package.id] = package
        self.tracking_updates[package.id] = []
        return package

    def get_shipment(self, package_id: str) -> Package | None:
        """Get shipment by ID.

        Args:
            package_id: Package ID

        Returns:
            Package or None
        """
        return self.shipments.get(package_id)

    def update_tracking(
        self,
        package_id: str,
        status: ShippingStatus,
        location: str | None = None,
        notes: str = "",
    ) -> None:
        """Update tracking status.

        Args:
            package_id: Package ID
            status: New status
            location: Current location
            notes: Additional notes
        """
        package = self.shipments.get(package_id)
        if not package:
            return

        package.status = status

        update = {
            "status": status.value,
            "location": location,
            "notes": notes,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.tracking_updates[package_id].append(update)

        # Update delivery timestamp if delivered
        if status == ShippingStatus.DELIVERED:
            package.delivered_at = datetime.utcnow()

    def mark_shipped(self, package_id: str, carrier: str, tracking_number: str) -> None:
        """Mark package as shipped.

        Args:
            package_id: Package ID
            carrier: Carrier name
            tracking_number: Tracking number
        """
        package = self.shipments.get(package_id)
        if package:
            package.carrier = carrier
            package.tracking_number = tracking_number
            package.shipped_at = datetime.utcnow()
            self.update_tracking(package_id, ShippingStatus.SHIPPED)

    def get_tracking_history(self, package_id: str) -> list[dict[str, Any]]:
        """Get tracking history for package.

        Args:
            package_id: Package ID

        Returns:
            List of tracking updates
        """
        return self.tracking_updates.get(package_id, [])

    def estimate_delivery(self, package_id: str, delivery_days: int = 5) -> datetime:
        """Estimate delivery date.

        Args:
            package_id: Package ID
            delivery_days: Days until delivery

        Returns:
            Estimated delivery datetime
        """
        package = self.shipments.get(package_id)
        if not package or not package.shipped_at:
            return datetime.utcnow() + timedelta(days=delivery_days)

        return package.shipped_at + timedelta(days=delivery_days)

    def get_delivery_status_message(self, package_id: str) -> str:
        """Get human-readable delivery status.

        Args:
            package_id: Package ID

        Returns:
            Status message
        """
        package = self.shipments.get(package_id)
        if not package:
            return "Shipment not found"

        messages = {
            ShippingStatus.PENDING: "Order received, not yet picked",
            ShippingStatus.PICKED: "Item picked from warehouse",
            ShippingStatus.PACKED: "Item packed and ready to ship",
            ShippingStatus.SHIPPED: f"Shipped via {package.carrier}",
            ShippingStatus.IN_TRANSIT: "In transit to destination",
            ShippingStatus.OUT_FOR_DELIVERY: "Out for delivery today",
            ShippingStatus.DELIVERED: "Delivered",
            ShippingStatus.FAILED: "Delivery failed",
        }

        return messages.get(package.status, "Status unknown")
