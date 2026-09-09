"""Inventory management and stock tracking."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from ._exceptions import InventoryError, OutOfStockError


class StockMovementType(str, Enum):
    """Type of inventory movement."""

    RECEIVE = "receive"
    SHIP = "ship"
    ADJUST = "adjust"
    TRANSFER = "transfer"
    RETURN = "return"
    DAMAGE = "damage"


@dataclass
class StockMovement:
    """Record of inventory movement."""

    id: str
    product_id: str
    variant_id: str | None
    movement_type: StockMovementType
    quantity: int
    reference_id: str | None
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "product_id": self.product_id,
            "variant_id": self.variant_id,
            "movement_type": self.movement_type.value,
            "quantity": self.quantity,
            "reference_id": self.reference_id,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class StockReservation:
    """Stock reservation for pending order."""

    id: str
    product_id: str
    variant_id: str | None
    quantity: int
    order_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        """Check if reservation expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at


class InventoryManager:
    """Inventory management with reservations and movements."""

    def __init__(self) -> None:
        """Initialize inventory manager."""
        self.stock_levels: dict[str, int] = {}
        self.reservations: dict[str, StockReservation] = {}
        self.movements: dict[str, StockMovement] = {}
        self.reorder_points: dict[str, int] = {}
        self.inventory_valuation: dict[str, dict[str, Any]] = {}

    def set_stock_level(self, product_id: str, quantity: int) -> None:
        """Set stock level for product.

        Args:
            product_id: Product ID
            quantity: Stock quantity
        """
        self.stock_levels[product_id] = max(0, quantity)

    def get_stock_level(self, product_id: str) -> int:
        """Get current stock level.

        Args:
            product_id: Product ID

        Returns:
            Stock quantity
        """
        return self.stock_levels.get(product_id, 0)

    def get_available_stock(self, product_id: str) -> int:
        """Get available stock (excluding reservations).

        Args:
            product_id: Product ID

        Returns:
            Available quantity
        """
        total_stock = self.get_stock_level(product_id)
        reserved = sum(
            r.quantity for r in self.reservations.values() if r.product_id == product_id and not r.is_expired()
        )
        return max(0, total_stock - reserved)

    def reserve_stock(
        self,
        product_id: str,
        variant_id: str | None,
        quantity: int,
        order_id: str,
        reservation_id: str,
        expires_in_minutes: int | None = None,
    ) -> StockReservation:
        """Reserve stock for pending order.

        Args:
            product_id: Product ID
            variant_id: Optional variant ID
            quantity: Quantity to reserve
            order_id: Order ID
            reservation_id: Unique reservation ID
            expires_in_minutes: Reservation expiry time

        Returns:
            Stock reservation

        Raises:
            OutOfStockError: If insufficient stock
        """
        available = self.get_available_stock(product_id)
        if available < quantity:
            raise OutOfStockError(product_id, quantity, available)

        expires_at = None
        if expires_in_minutes:
            from datetime import timedelta

            expires_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)

        reservation = StockReservation(
            id=reservation_id,
            product_id=product_id,
            variant_id=variant_id,
            quantity=quantity,
            order_id=order_id,
            expires_at=expires_at,
        )
        self.reservations[reservation_id] = reservation
        return reservation

    def release_reservation(self, reservation_id: str) -> None:
        """Release stock reservation.

        Args:
            reservation_id: Reservation ID
        """
        if reservation_id in self.reservations:
            del self.reservations[reservation_id]

    def confirm_reservation(self, reservation_id: str) -> None:
        """Confirm reservation and decrement stock.

        Args:
            reservation_id: Reservation ID

        Raises:
            InventoryError: If reservation not found
        """
        if reservation_id not in self.reservations:
            raise InventoryError(f"Reservation {reservation_id} not found")

        reservation = self.reservations[reservation_id]
        current_stock = self.get_stock_level(reservation.product_id)

        if current_stock < reservation.quantity:
            raise OutOfStockError(
                reservation.product_id,
                reservation.quantity,
                current_stock,
            )

        self.set_stock_level(
            reservation.product_id,
            current_stock - reservation.quantity,
        )
        del self.reservations[reservation_id]

        # Record movement
        self.record_movement(
            product_id=reservation.product_id,
            variant_id=reservation.variant_id,
            movement_type=StockMovementType.SHIP,
            quantity=-reservation.quantity,
            reference_id=reservation.order_id,
        )

    def record_movement(
        self,
        product_id: str,
        variant_id: str | None,
        movement_type: StockMovementType,
        quantity: int,
        reference_id: str | None = None,
        notes: str = "",
    ) -> StockMovement:
        """Record inventory movement.

        Args:
            product_id: Product ID
            variant_id: Optional variant ID
            movement_type: Type of movement
            quantity: Quantity moved (positive/negative)
            reference_id: Order/RMA/PO reference
            notes: Additional notes

        Returns:
            Stock movement record
        """
        movement_id = f"{product_id}_{datetime.utcnow().timestamp()}"
        movement = StockMovement(
            id=movement_id,
            product_id=product_id,
            variant_id=variant_id,
            movement_type=movement_type,
            quantity=quantity,
            reference_id=reference_id,
            notes=notes,
        )
        self.movements[movement_id] = movement

        # Update stock level for non-reservation movements
        if movement_type in [StockMovementType.RECEIVE, StockMovementType.ADJUST, StockMovementType.RETURN]:
            current = self.get_stock_level(product_id)
            self.set_stock_level(product_id, current + quantity)

        return movement

    def receive_stock(
        self,
        product_id: str,
        quantity: int,
        reference_id: str,
        notes: str = "",
    ) -> StockMovement:
        """Receive stock for product.

        Args:
            product_id: Product ID
            quantity: Quantity received
            reference_id: PO or receipt number
            notes: Additional notes

        Returns:
            Stock movement
        """
        return self.record_movement(
            product_id=product_id,
            variant_id=None,
            movement_type=StockMovementType.RECEIVE,
            quantity=quantity,
            reference_id=reference_id,
            notes=notes,
        )

    def adjust_stock(
        self,
        product_id: str,
        quantity: int,
        reason: str,
    ) -> StockMovement:
        """Adjust stock for damage, loss, etc.

        Args:
            product_id: Product ID
            quantity: Adjustment amount (positive/negative)
            reason: Reason for adjustment

        Returns:
            Stock movement
        """
        return self.record_movement(
            product_id=product_id,
            variant_id=None,
            movement_type=StockMovementType.ADJUST,
            quantity=quantity,
            notes=reason,
        )

    def set_reorder_point(self, product_id: str, threshold: int) -> None:
        """Set low stock reorder threshold.

        Args:
            product_id: Product ID
            threshold: Reorder quantity threshold
        """
        self.reorder_points[product_id] = threshold

    def get_reorder_point(self, product_id: str) -> int:
        """Get reorder threshold.

        Args:
            product_id: Product ID

        Returns:
            Reorder threshold
        """
        return self.reorder_points.get(product_id, 10)

    def needs_reorder(self, product_id: str) -> bool:
        """Check if product needs reorder.

        Args:
            product_id: Product ID

        Returns:
            True if below reorder point
        """
        stock = self.get_stock_level(product_id)
        threshold = self.get_reorder_point(product_id)
        return stock <= threshold

    def set_inventory_value(
        self,
        product_id: str,
        unit_cost: Decimal,
        valuation_method: str = "fifo",
    ) -> None:
        """Set inventory valuation for product.

        Args:
            product_id: Product ID
            unit_cost: Cost per unit
            valuation_method: "fifo", "lifo", "weighted_average"
        """
        self.inventory_valuation[product_id] = {
            "unit_cost": unit_cost,
            "method": valuation_method,
        }

    def get_inventory_value(self, product_id: str) -> Decimal:
        """Calculate inventory value for product.

        Args:
            product_id: Product ID

        Returns:
            Total inventory value
        """
        valuation = self.inventory_valuation.get(product_id)
        if not valuation:
            return Decimal("0")

        stock = self.get_stock_level(product_id)
        return Decimal(stock) * valuation["unit_cost"]

    def get_total_inventory_value(self) -> Decimal:
        """Calculate total inventory value.

        Returns:
            Total value across all products
        """
        return sum(self.get_inventory_value(pid) for pid in self.stock_levels)

    def get_movement_history(
        self,
        product_id: str | None = None,
        movement_type: StockMovementType | None = None,
        limit: int = 100,
    ) -> list[StockMovement]:
        """Get inventory movement history.

        Args:
            product_id: Optional filter by product
            movement_type: Optional filter by movement type
            limit: Maximum results

        Returns:
            List of movements
        """
        movements = list(self.movements.values())

        if product_id:
            movements = [m for m in movements if m.product_id == product_id]

        if movement_type:
            movements = [m for m in movements if m.movement_type == movement_type]

        # Sort by date descending
        movements.sort(key=lambda m: m.created_at, reverse=True)

        return movements[:limit]

    def cleanup_expired_reservations(self) -> int:
        """Remove expired reservations.

        Returns:
            Number of reservations removed
        """
        expired = [rid for rid, res in self.reservations.items() if res.is_expired()]
        for rid in expired:
            del self.reservations[rid]
        return len(expired)

    def get_stock_summary(self) -> dict[str, Any]:
        """Get overall inventory summary.

        Returns:
            Summary statistics
        """
        total_units = sum(self.stock_levels.values())
        total_value = self.get_total_inventory_value()
        reserved = sum(r.quantity for r in self.reservations.values() if not r.is_expired())

        return {
            "total_units": total_units,
            "total_value": str(total_value),
            "reserved_units": reserved,
            "products_count": len(self.stock_levels),
            "low_stock_count": sum(1 for pid in self.stock_levels if self.needs_reorder(pid)),
        }
